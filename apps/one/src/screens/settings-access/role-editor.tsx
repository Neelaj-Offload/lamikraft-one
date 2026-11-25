"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useMemo, useRef, useState, type FormEvent } from "react";
import { createRole, updateRole } from "@/app/(app)/settings/_lib/api";
import type { PermissionInfo, RoleDetail, RoleEntryIn, RoleSummary } from "@/app/(app)/settings/_lib/types";
import { conflictFromError } from "@/lib/api/errors";
import { useSession } from "@/lib/session/context";
import { usePermissionCatalogue, useRefreshIdentity, useRole, useRoles } from "~/data/settings-access";
import { Page, PageHeader, type Crumb } from "~/shell/page";
import { ErrorBlock, LoadingBlock, NotPermitted } from "~/shell/states";
import { Badge, Banner, Button, ButtonLink, EmptyState, FormActions, FormSection, Select, Textarea, TextField, toast } from "~/ui";
import { fieldErrors, formFailure, keyLabel, roleHref, ROLES_CRUMB, scopeFrom, scopeOptions, SETTINGS_CRUMB } from "./labels";
import { PermissionPicker } from "./parts";
import { useStepUp } from "./step-up";

const NO_PARENT = "none";

/** Create a custom role (`roleId` null) or edit one. */
export function RoleEditor({ roleId }: { roleId: string | null }) {
  const { permissionKeys } = useSession();
  const role = useRole(roleId);
  const roles = useRoles();
  const crumbs: Crumb[] = [SETTINGS_CRUMB, ROLES_CRUMB];

  if (roleId === null) {
    if (!permissionKeys.has("identity.role.manage")) {
      return (
        <Page width="reading">
          <PageHeader breadcrumb={[...crumbs, { label: "Create role" }]} title="Create a role" />
          <NotPermitted what="Creating roles" icon="badgeCheck" />
        </Page>
      );
    }
    return <EditorForm detail={null} roles={roles.data?.items} onReload={() => undefined} />;
  }
  // The stored parent is matched against the role list, so editing waits for it: saving before it
  // loads would read as "builds on nothing" and clear the inheritance.
  if (role.isPending || roles.isPending) {
    return (
      <Page width="reading">
        <PageHeader breadcrumb={[...crumbs, { label: "Edit role" }]} title="Edit role" />
        <LoadingBlock label="Loading this role" lines={6} />
      </Page>
    );
  }
  if (role.isError || roles.isError) {
    return (
      <Page width="reading">
        <PageHeader breadcrumb={[...crumbs, { label: "Edit role" }]} title="Edit role" />
        {role.isError ? (
          <ErrorBlock error={role.error} what="This role" onRetry={() => void role.refetch()} />
        ) : (
          <ErrorBlock error={roles.error} what="The list of roles" onRetry={() => void roles.refetch()} />
        )}
      </Page>
    );
  }
  if (!role.data.capabilities.update.allowed) {
    return (
      <Page width="reading">
        <PageHeader breadcrumb={[...crumbs, { label: role.data.role.name, href: roleHref(role.data.role.id) }, { label: "Edit" }]} title={`Edit ${role.data.role.name}`} />
        <EmptyState
          icon="lock"
          title="This role cannot be edited"
          text={
            role.data.role.kind === "system_template"
              ? "Built-in roles stay as they are. Create a custom role that builds on this one, then add or deny permissions."
              : "Your role does not include changing this role."
          }
          actions={
            <ButtonLink variant="secondary" href={roleHref(role.data.role.id)}>
              Back to the role
            </ButtonLink>
          }
        />
      </Page>
    );
  }
  // Keyed by version: after a conflict reload the form starts again from the stored role.
  return <EditorForm key={role.data.role.version} detail={role.data} roles={roles.data?.items} onReload={() => void role.refetch()} />;
}

function EditorForm({ detail, roles, onReload }: { detail: RoleDetail | null; roles: readonly RoleSummary[] | undefined; onReload: () => void }) {
  const router = useRouter();
  const refresh = useRefreshIdentity();
  const stepUp = useStepUp();
  const catalogue = usePermissionCatalogue();
  const [key, setKey] = useState("");
  const [name, setName] = useState(detail?.role.name ?? "");
  const [description, setDescription] = useState(detail?.role.description ?? "");
  const [entries, setEntries] = useState<RoleEntryIn[]>(detail?.entries ?? []);
  /** `undefined` until the person picks: the stored parent then decides. */
  const [parent, setParent] = useState<string | null | undefined>(undefined);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const banner = useRef<HTMLDivElement>(null);

  const storedParentId = roles?.find((candidate) => candidate.key === detail?.role.inherits?.key)?.id ?? null;
  const parentId = parent !== undefined ? parent : storedParentId;
  const server = fieldErrors(error);
  const conflict = conflictFromError(error);
  const failure = conflict ? null : formFailure(error);
  const client: Record<string, string> = submitted
    ? {
        ...(detail || key.trim() ? {} : { key: "Give the role a key, such as senior_sales." }),
        ...(name.trim() ? {} : { name: "Give the role a name people will recognise." }),
      }
    : {};
  const errorFor = (field: string) => server[field] ?? client[field];
  const backHref = detail ? roleHref(detail.role.id) : ("/settings/roles" as Route);
  const title = detail ? `Edit ${detail.role.name}` : "Create a role";

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (busy) return;
    if (!name.trim() || (!detail && !key.trim())) return;
    setBusy(true);
    setError(null);
    try {
      const cleanDescription = description.trim() || null;
      const saved = await stepUp.run(() =>
        detail
          ? updateRole(detail.role.id, {
              expected_version: detail.role.version,
              name: name.trim(),
              description: cleanDescription ?? "",
              entries,
              ...(parentId ? { inherits_role_id: parentId } : { clear_inherits: true }),
            })
          : createRole({ key: key.trim(), name: name.trim(), description: cleanDescription, inherits_role_id: parentId, entries }),
      );
      await refresh();
      toast.success(detail ? "Role saved" : "Role created");
      router.push(roleHref(saved.role.id));
    } catch (err) {
      setError(err);
      window.requestAnimationFrame(() => banner.current?.focus());
    } finally {
      setBusy(false);
    }
  };

  const parentOptions = [
    { value: NO_PARENT, label: "Nothing", description: "Start empty and grant each permission yourself." },
    ...(roles ?? []).filter((candidate) => candidate.id !== detail?.role.id && !candidate.archived).map((candidate) => ({ value: candidate.id, label: candidate.name })),
  ];

  return (
    <Page width="reading">
      <PageHeader
        breadcrumb={[SETTINGS_CRUMB, ROLES_CRUMB, ...(detail ? [{ label: detail.role.name, href: roleHref(detail.role.id) }, { label: "Edit" }] : [{ label: "Create role" }])]}
        title={title}
        lead="Start from a role that is close, then add what is missing and deny what should not carry over. You can only grant what you hold yourself."
      />

      <form onSubmit={(event) => void submit(event)} noValidate className="stack">
        {conflict || failure ? (
          <div ref={banner} tabIndex={-1} className="outline-none">
            {conflict ? (
              <Banner
                tone="amber"
                title="This role changed while you were editing."
                action={
                  <Button
                    variant="secondary"
                    size="sm"
                    iconLeft="refresh"
                    onPress={() => {
                      setError(null);
                      onReload();
                    }}
                  >
                    Load the latest
                  </Button>
                }
              >
                {conflict.changedBy ? `${conflict.changedBy} saved a change first. ` : "Someone saved a change first. "}Loading the latest version replaces what you have typed here.
              </Banner>
            ) : (
              <Banner tone="ember" title={detail ? "The role was not saved." : "The role was not created."}>
                {failure}
              </Banner>
            )}
          </div>
        ) : null}

        <FormSection title="The role" description="The name is what admins pick from. The key is the role's permanent id.">
          <TextField label="Name" isRequired maxLength={120} value={name} onChange={setName} error={errorFor("name")} placeholder="Senior sales" />
          {detail ? (
            <TextField label="Key" value={detail.role.key} isReadOnly help="Set when the role was created. It cannot change." />
          ) : (
            <TextField
              label="Key"
              isRequired
              maxLength={60}
              value={key}
              onChange={setKey}
              placeholder="senior_sales"
              help="Lower case with underscores. It cannot change later."
              error={errorFor("key")}
            />
          )}
          <Select
            label="Builds on"
            options={parentOptions}
            value={parentId ?? NO_PARENT}
            onChange={(value) => setParent(value === NO_PARENT ? null : value)}
            help="The role starts with everything this one allows."
            error={server.inherits_role_id}
          />
          <Textarea label="Description" optional value={description} onChange={setDescription} maxLength={500} help="One line on who should hold this role." error={server.description} />
        </FormSection>

        <FormSection title="Its own rules" description="A grant adds a permission. A deny removes one the role would otherwise get from the role it builds on.">
          <EntriesEditor
            entries={entries}
            onChange={setEntries}
            catalogue={catalogue.data?.items ?? []}
            isLoading={catalogue.isPending}
            loadError={catalogue.isError ? "The permission list could not load. Reload the page to add rules." : null}
            error={server.entries}
          />
        </FormSection>

        <FormActions>
          <ButtonLink variant="ghost" href={backHref}>
            Cancel
          </ButtonLink>
          <Button type="submit" loading={busy}>
            {detail ? "Save role" : "Create role"}
          </Button>
        </FormActions>
      </form>
      {stepUp.dialog}
    </Page>
  );
}

/** The role's own grants and denies, picked from the permission catalogue. */
function EntriesEditor({
  entries,
  onChange,
  catalogue,
  isLoading,
  loadError,
  error,
}: {
  entries: RoleEntryIn[];
  onChange: (next: RoleEntryIn[]) => void;
  catalogue: readonly PermissionInfo[];
  isLoading: boolean;
  loadError: string | null;
  error?: string;
}) {
  const [key, setKey] = useState<string | null>(null);
  const [round, setRound] = useState(0);
  const byKey = useMemo(() => new Map(catalogue.map((permission) => [permission.key, permission])), [catalogue]);
  const taken = useMemo(() => new Set(entries.map((entry) => entry.key)), [entries]);
  const available = useMemo(() => catalogue.filter((permission) => !taken.has(permission.key)), [catalogue, taken]);

  const add = (effect: "grant" | "deny") => {
    if (!key || taken.has(key)) return;
    const permission = byKey.get(key);
    onChange([...entries, { key, effect, scope: effect === "grant" ? (permission?.allowed_scopes[0] ?? "company") : null }]);
    setKey(null);
    setRound((current) => current + 1);
  };

  return (
    <div className="col-span-full flex min-w-0 flex-col gap-5">
      {loadError ? <Banner tone="ember">{loadError}</Banner> : null}
      <div className="flex min-w-0 flex-wrap items-end gap-2">
        <PermissionPicker
          key={round}
          className="min-w-0 flex-1 basis-72"
          label="Add a permission"
          permissions={available}
          isLoading={isLoading}
          value={key}
          onChange={setKey}
          help={key ? byKey.get(key)?.description : "Type part of a key, then grant or deny it."}
          error={error}
        />
        <div className="flex gap-2 pb-[26px]">
          <Button variant="secondary" iconLeft="check" isDisabled={!key} onPress={() => add("grant")}>
            Grant
          </Button>
          <Button variant="secondary" iconLeft="x" isDisabled={!key} onPress={() => add("deny")}>
            Deny
          </Button>
        </div>
      </div>

      {entries.length === 0 ? (
        <p className="t-body-sm text-ink-3">No rules of its own yet. The role allows exactly what it builds on.</p>
      ) : (
        <ul className="m-0 flex list-none flex-col p-0" aria-label="Rules of this role">
          {entries.map((entry, index) => {
            const scopes = byKey.get(entry.key)?.allowed_scopes ?? (entry.scope ? [entry.scope] : ["company" as const]);
            return (
              <li key={entry.key} className="hairline-top flex min-w-0 flex-wrap items-center gap-3 py-3">
                <Badge tone={entry.effect === "grant" ? "leaf" : "ember"} icon={entry.effect === "grant" ? "check" : "x"}>
                  {entry.effect === "grant" ? "Grant" : "Deny"}
                </Badge>
                <span className="flex min-w-0 flex-1 basis-56 flex-col">
                  <span className="t-label text-ink">{keyLabel(entry.key)}</span>
                  <span className="t-code-sm lk-mono break-all text-ink-3">{entry.key}</span>
                </span>
                {entry.effect === "grant" ? (
                  <Select
                    className="w-44"
                    size="sm"
                    label={`Reach of ${keyLabel(entry.key)}`}
                    hideLabel
                    options={scopeOptions(scopes)}
                    value={entry.scope}
                    onChange={(value) => onChange(entries.map((current, i) => (i === index ? { ...current, scope: scopeFrom(value, current.scope ?? "company") } : current)))}
                  />
                ) : null}
                <Button variant="ghost" size="sm" onPress={() => onChange(entries.filter((_, i) => i !== index))}>
                  Remove
                </Button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
