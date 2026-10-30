"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Form } from "react-aria-components";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { LocalDateTime } from "@/components/ui/format";
import { ComboBox, Select } from "@/components/ui/select";
import { EmptyState } from "@/components/ui/states";
import { TextArea, TextField } from "@/components/ui/text-field";
import { toast } from "@/components/ui/toast";
import { queryKeys } from "@/lib/api/query-keys";
import { deleteOverride, fetchCatalogue, putOverride } from "./api";
import { useStepUp } from "./step-up";
import type { OverrideView, Scope } from "./types";
import { fieldErrors, keyLabel, problemText, SCOPE_LABEL, Section } from "./ui";

/**
 * Per-user overrides over the full catalogue (PARITY UI-22/UI-95): grant (with scope) or revoke, always with a
 * reason, optionally expiring. Revoke always wins over roles and grants.
 */
export function OverridesPanel({ userId, canManage, overrides, reason }: { userId: string; canManage: boolean; overrides: OverrideView[]; reason: string | null }) {
  const client = useQueryClient();
  const stepUp = useStepUp();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [key, setKey] = useState<string | null>(null);
  const [effect, setEffect] = useState<"grant" | "revoke">("grant");
  const [scope, setScope] = useState<Scope>("own");
  const catalogue = useQuery({ queryKey: queryKeys.identity.catalogue(), queryFn: ({ signal }) => fetchCatalogue(signal), enabled: open });
  const permission = catalogue.data?.items.find((p) => p.key === key) ?? null;

  async function save(form: FormData) {
    if (!key) return;
    setBusy(true);
    setError(null);
    try {
      const expires = String(form.get("expires_on") ?? "");
      await stepUp.run(() =>
        putOverride(userId, key, {
          effect,
          scope: effect === "grant" ? scope : null,
          reason: String(form.get("reason") ?? "").trim(),
          expires_at: expires ? new Date(`${expires}T23:59:59`).toISOString() : null,
        }),
      );
      await client.invalidateQueries({ queryKey: queryKeys.identity.all() });
      toast.success(effect === "grant" ? "Permission granted" : "Permission revoked");
      setOpen(false);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function remove(permissionKey: string) {
    try {
      await stepUp.run(() => deleteOverride(userId, permissionKey));
      await client.invalidateQueries({ queryKey: queryKeys.identity.all() });
      toast.success("Override removed; the role grants apply again");
    } catch (err) {
      toast.error(problemText(err));
    }
  }

  return (
    <Section
      title="Personal permissions"
      description="Grants and revokes for this person only, on top of their roles. A revoke always wins."
      actions={canManage ? <Button onPress={() => setOpen(true)}>Add grant or revoke</Button> : null}
    >
      {!canManage && reason === "self_access_change" ? <p className="text-sm text-ink-muted">You cannot change your own permissions.</p> : null}
      {overrides.length === 0 ? (
        <EmptyState title="No personal permissions" headingLevel={3}>
          This person has exactly what their roles give.
        </EmptyState>
      ) : (
        <ul className="divide-y">
          {overrides.map((o) => (
            <li key={o.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <div className="flex flex-col">
                <span className="font-medium">
                  <Badge tone={o.effect === "grant" ? "success" : "danger"}>{o.effect === "grant" ? "Grant" : "Revoke"}</Badge> {keyLabel(o.permission_key)}
                  {o.scope ? <span className="text-ink-muted"> · {SCOPE_LABEL[o.scope]}</span> : null}
                </span>
                <span className="text-sm text-ink-muted">
                  {o.reason}
                  {o.expires_at ? (
                    <>
                      {" "}
                      · until <LocalDateTime value={o.expires_at} />
                    </>
                  ) : null}
                  {!o.in_effect ? " · expired" : null}
                </span>
              </div>
              {canManage ? (
                <Button size="sm" variant="quiet" onPress={() => void remove(o.permission_key)}>
                  Remove
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      <Dialog isOpen={open} onOpenChange={setOpen} title="Grant or revoke a permission" description="You can only grant what you hold, at no wider scope.">
        <Form
          className="flex flex-col gap-3"
          validationErrors={fieldErrors(error)}
          onSubmit={(event) => {
            event.preventDefault();
            void save(new FormData(event.currentTarget));
          }}
        >
          <ComboBox
            label="Permission"
            options={(catalogue.data?.items ?? []).map((p) => ({ id: p.key, label: p.key }))}
            value={key}
            onChange={setKey}
            isRequired
            errorMessage={fieldErrors(error).permission_key}
          />
          <Select
            label="Effect"
            options={[
              { id: "grant", label: "Grant" },
              { id: "revoke", label: "Revoke" },
            ]}
            value={effect}
            onChange={(value) => setEffect(value === "revoke" ? "revoke" : "grant")}
          />
          {effect === "grant" ? (
            <Select
              label="Scope"
              options={(permission?.allowed_scopes ?? ["own", "team", "branch", "company"]).map((s) => ({ id: s, label: SCOPE_LABEL[s] ?? s }))}
              value={scope}
              onChange={(value) => setScope((value as Scope | null) ?? "own")}
            />
          ) : null}
          <TextArea name="reason" label="Reason" isRequired />
          <TextField name="expires_on" label="Ends on (optional)" type="date" />
          {error && !Object.keys(fieldErrors(error)).length ? (
            <p role="alert" className="text-danger">
              {problemText(error)}
            </p>
          ) : null}
          <div className="flex justify-end">
            <Button type="submit" variant="primary" isPending={busy}>
              Save
            </Button>
          </div>
        </Form>
      </Dialog>
      {stepUp.dialog}
    </Section>
  );
}
