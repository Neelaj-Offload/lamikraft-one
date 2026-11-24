"use client";

import { useId, useState, type FormEvent } from "react";
import { deleteOverride, putOverride } from "@/app/(app)/settings/_lib/api";
import type { OverrideView, Scope } from "@/app/(app)/settings/_lib/types";
import { usePermissionCatalogue, useRefreshIdentity } from "~/data/settings-access";
import { Badge, Banner, Button, ConfirmDialog, DatePicker, DateText, EmptyState, GlassPanel, Modal, SegmentedControl, Select, Textarea, toast } from "~/ui";
import { dayToInstant, fieldErrors, formFailure, keyLabel, problemText, SCOPE_LABEL, scopeFrom, scopeOptions, SCOPES } from "./labels";
import { PermissionPicker } from "./parts";
import { useStepUp } from "./step-up";

/**
 * Grants and revokes for one person, on top of their roles. Every change needs a reason and may
 * carry an end date; a revoke always wins over roles and grants.
 */
export function PersonalPermissions({
  userId,
  name,
  overrides,
  canManage,
  reasonCode,
}: {
  userId: string;
  name: string;
  overrides: OverrideView[];
  canManage: boolean;
  /** Why managing is refused, when it is (`self_access_change` for your own profile). */
  reasonCode: string | null;
}) {
  const refresh = useRefreshIdentity();
  const stepUp = useStepUp();
  const [adding, setAdding] = useState({ open: false, round: 0 });
  const [removing, setRemoving] = useState<OverrideView | null>(null);

  const remove = async (override: OverrideView) => {
    try {
      await stepUp.run(() => deleteOverride(userId, override.permission_key));
      await refresh();
      toast.success("Personal permission removed", { description: "Their roles decide this permission again." });
    } catch (error) {
      toast.error("The permission was not removed", { description: problemText(error) });
      throw error;
    }
  };

  return (
    <GlassPanel
      as="section"
      title="Personal permissions"
      titleAs="h2"
      padding="lg"
      action={
        canManage ? (
          <Button variant="secondary" size="sm" iconLeft="plus" onPress={() => setAdding((state) => ({ open: true, round: state.round + 1 }))}>
            Add grant or revoke
          </Button>
        ) : undefined
      }
      className="flex flex-col gap-4"
    >
      <p className="t-body-sm text-ink-3">Exceptions for {name} only, on top of their roles. A revoke always wins.</p>
      {!canManage && reasonCode === "self_access_change" ? <Banner tone="neutral">You cannot change your own permissions. Ask another admin.</Banner> : null}
      {overrides.length === 0 ? (
        <EmptyState compact icon="key" title="No exceptions" text={`${name} has exactly what their roles give.`} />
      ) : (
        <ul className="m-0 flex list-none flex-col p-0">
          {overrides.map((override, index) => (
            <li key={override.id} className={`flex flex-wrap items-start justify-between gap-3 py-3 ${index > 0 ? "hairline-top" : ""}`}>
              <div className="flex min-w-0 flex-col gap-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={override.effect === "grant" ? "leaf" : "ember"} icon={override.effect === "grant" ? "check" : "x"}>
                    {override.effect === "grant" ? "Grant" : "Revoke"}
                  </Badge>
                  <span className="t-label text-ink" title={override.permission_key}>
                    {keyLabel(override.permission_key)}
                  </span>
                  {override.scope ? <span className="t-body-sm text-ink-3">{SCOPE_LABEL[override.scope]}</span> : null}
                  {!override.in_effect ? (
                    <Badge size="sm" outline>
                      Expired
                    </Badge>
                  ) : null}
                </div>
                <p className="t-body-sm text-ink-2">
                  {override.reason}
                  {override.expires_at ? (
                    <>
                      {" · until "}
                      <DateText value={override.expires_at} style="dayTime" />
                    </>
                  ) : null}
                </p>
              </div>
              {canManage ? (
                <Button variant="ghost" size="sm" onPress={() => setRemoving(override)}>
                  Remove
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      {canManage ? (
        <AddOverrideModal
          key={adding.round}
          userId={userId}
          name={name}
          isOpen={adding.open}
          onOpenChange={(open) => setAdding((state) => ({ ...state, open }))}
          run={stepUp.run}
        />
      ) : null}
      <ConfirmDialog
        isOpen={removing !== null}
        onOpenChange={(open) => {
          if (!open) setRemoving(null);
        }}
        title="Remove this personal permission"
        description={removing ? `${keyLabel(removing.permission_key)} goes back to what ${name}'s roles give.` : undefined}
        confirmLabel="Remove permission"
        tone="danger"
        onConfirm={() => (removing ? remove(removing) : undefined)}
      />
      {stepUp.dialog}
    </GlassPanel>
  );
}

function AddOverrideModal({
  userId,
  name,
  isOpen,
  onOpenChange,
  run,
}: {
  userId: string;
  name: string;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  run: <T>(command: () => Promise<T>) => Promise<T>;
}) {
  const formId = useId();
  const refresh = useRefreshIdentity();
  const catalogue = usePermissionCatalogue({ enabled: isOpen });
  const [key, setKey] = useState<string | null>(null);
  const [effect, setEffect] = useState<"grant" | "revoke">("grant");
  const [scope, setScope] = useState<Scope>("own");
  const [reason, setReason] = useState("");
  const [expires, setExpires] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const permission = catalogue.data?.items.find((item) => item.key === key) ?? null;
  const allowedScopes = permission?.allowed_scopes ?? SCOPES;
  const chosenScope = allowedScopes.includes(scope) ? scope : (allowedScopes[0] ?? "own");
  const server = fieldErrors(error);
  const failure = formFailure(error);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (busy || !key || !reason.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await run(() =>
        putOverride(userId, key, {
          effect,
          scope: effect === "grant" ? chosenScope : null,
          reason: reason.trim(),
          expires_at: dayToInstant(expires, "end"),
        }),
      );
      await refresh();
      toast.success(effect === "grant" ? "Permission granted" : "Permission revoked");
      onOpenChange(false);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      title="Grant or revoke a permission"
      description={`For ${name} only. You can grant what you hold yourself, at no wider scope.`}
      actions={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" form={formId} loading={busy}>
            {effect === "grant" ? "Grant permission" : "Revoke permission"}
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={(event) => void submit(event)} noValidate className="flex flex-col gap-4">
        {failure ? <Banner tone="ember" title="Not saved.">{failure}</Banner> : null}
        {catalogue.isError ? <Banner tone="ember" title="The permission list could not load.">{problemText(catalogue.error)}</Banner> : null}
        <SegmentedControl
          label="Effect"
          value={effect}
          onChange={(value) => setEffect(value === "revoke" ? "revoke" : "grant")}
          options={[
            { value: "grant", label: "Grant" },
            { value: "revoke", label: "Revoke" },
          ]}
        />
        <PermissionPicker
          permissions={catalogue.data?.items ?? []}
          isLoading={catalogue.isPending && isOpen}
          value={key}
          onChange={setKey}
          isRequired
          help={permission?.description}
          error={server.permission_key ?? (submitted && !key ? "Choose the permission this is about." : undefined)}
        />
        {effect === "grant" ? (
          <Select
            label="Scope"
            options={scopeOptions(allowedScopes)}
            value={chosenScope}
            onChange={(value) => setScope(scopeFrom(value, chosenScope))}
            help="How far the grant reaches."
            error={server.scope}
          />
        ) : null}
        <Textarea
          label="Reason"
          isRequired
          value={reason}
          onChange={setReason}
          help="Kept with the change, so the next admin knows why."
          error={server.reason ?? (submitted && !reason.trim() ? "Say why, in a sentence." : undefined)}
        />
        <DatePicker label="Ends on" optional value={expires} onChange={setExpires} help="Leave empty to keep it until someone removes it." error={server.expires_at} />
      </form>
    </Modal>
  );
}
