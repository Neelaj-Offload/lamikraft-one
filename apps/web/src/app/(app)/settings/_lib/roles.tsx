"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { Form, Link as RacLink } from "react-aria-components";
import { Badge } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { LinkButton } from "@/components/ui/link";
import { SearchField } from "@/components/ui/search-field";
import { ComboBox, Select } from "@/components/ui/select";
import { Conflict, EmptyState } from "@/components/ui/states";
import { linkClasses } from "@/components/ui/styles";
import { TextArea, TextField } from "@/components/ui/text-field";
import { toast } from "@/components/ui/toast";
import { conflictFromError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { archiveRole, createRole, fetchAccessCheck, fetchCatalogue, fetchEffective, fetchRole, fetchRoles, fetchUsers, updateRole } from "./api";
import { useStepUp } from "./step-up";
import type { EffectiveKey, PermissionInfo, RoleDetail, RoleEntryIn, RoleSummary, Scope } from "./types";
import { fieldErrors, keyLabel, problemText, QueryState, SCOPE_LABEL, Section, SettingsPage, useHasAny } from "./ui";

function roleColumns(): DataTableColumn<RoleSummary>[] {
  return [
    {
      id: "name",
      header: "Role",
      isRowHeader: true,
      mobile: "title",
      mobileCell: (row) => row.name,
      cell: (row) => (
        <RacLink href={`/settings/roles/${row.id}`} className={linkClasses}>
          {row.name}
        </RacLink>
      ),
    },
    { id: "kind", header: "Kind", mobile: "status", cell: (row) => (row.kind === "custom" ? <Badge tone="info">Custom</Badge> : <Badge>System</Badge>) },
    { id: "inherits", header: "Inherits", cell: (row) => row.inherits?.name ?? "—" },
    { id: "members", header: "Members", mobile: "meta", cell: (row) => String(row.member_count) },
    { id: "entries", header: "Own entries", cell: (row) => `${row.grant_count} grants${row.deny_count ? `, ${row.deny_count} denies` : ""}` },
  ];
}

export function RoleListScreen() {
  const query = useQuery({ queryKey: queryKeys.identity.roles(), queryFn: ({ signal }) => fetchRoles(signal) });
  const canManage = useHasAny("identity.role.manage");
  return (
    <SettingsPage
      title="Roles"
      intro="System roles mirror the standard jobs and cannot be edited. Make a custom role that inherits one and add or deny permissions."
      actions={
        <>
          <LinkButton href="/settings/roles/simulate">Role simulator</LinkButton>
          {canManage ? (
            <LinkButton href="/settings/roles/new" variant="primary">
              New custom role
            </LinkButton>
          ) : null}
        </>
      }
    >
      {query.isPending || query.isError ? (
        <QueryState isPending={query.isPending} error={query.error} what="the roles" area="role administration" onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          caption="Roles"
          hideCaption
          columns={roleColumns()}
          rows={query.data.items}
          rowId={(row) => row.id}
          rowHref={(row) => `/settings/roles/${row.id}`}
          empty={<EmptyState title="No roles">The system roles appear once the company is set up.</EmptyState>}
        />
      )}
    </SettingsPage>
  );
}

/** Grant and deny entries editor over the permission catalogue. */
function EntriesEditor({ entries, onChange, catalogue }: { entries: RoleEntryIn[]; onChange: (next: RoleEntryIn[]) => void; catalogue: PermissionInfo[] }) {
  const [key, setKey] = useState<string | null>(null);
  const byKey = useMemo(() => new Map(catalogue.map((p) => [p.key, p])), [catalogue]);
  const add = (effect: "grant" | "deny") => {
    if (!key || entries.some((e) => e.key === key)) return;
    const perm = byKey.get(key);
    onChange([...entries, { key, effect, scope: effect === "grant" ? (perm?.allowed_scopes[0] ?? "company") : null }]);
    setKey(null);
  };
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-2">
        <ComboBox className="min-w-72 flex-1" label="Permission" options={catalogue.map((p) => ({ id: p.key, label: p.key }))} value={key} onChange={setKey} />
        <Button onPress={() => add("grant")} {...unavailableWhen(!key ? "Choose a permission first" : null)}>
          Grant
        </Button>
        <Button onPress={() => add("deny")} {...unavailableWhen(!key ? "Choose a permission first" : null)}>
          Deny
        </Button>
      </div>
      {entries.length === 0 ? (
        <p className="text-sm text-ink-muted">No own entries: the role has exactly what it inherits.</p>
      ) : (
        <ul className="divide-y rounded-lg border">
          {entries.map((entry, index) => (
            <li key={entry.key} className="flex flex-wrap items-center gap-2 px-3 py-2">
              <Badge tone={entry.effect === "grant" ? "success" : "danger"}>{entry.effect === "grant" ? "Grant" : "Deny"}</Badge>
              <span className="flex-1 font-mono text-sm">{entry.key}</span>
              {entry.effect === "grant" ? (
                <Select
                  label={`Scope for ${entry.key}`}
                  className="w-44"
                  options={(byKey.get(entry.key)?.allowed_scopes ?? ["company"]).map((s) => ({ id: s, label: SCOPE_LABEL[s] ?? s }))}
                  value={entry.scope}
                  onChange={(value) => onChange(entries.map((e, i) => (i === index ? { ...e, scope: (value as Scope | null) ?? e.scope } : e)))}
                />
              ) : null}
              <Button size="sm" variant="quiet" onPress={() => onChange(entries.filter((_, i) => i !== index))}>
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function RoleEditorScreen({ roleId }: { roleId: string | null }) {
  const router = useRouter();
  const client = useQueryClient();
  const stepUp = useStepUp();
  const roles = useQuery({ queryKey: queryKeys.identity.roles(), queryFn: ({ signal }) => fetchRoles(signal) });
  const catalogue = useQuery({ queryKey: queryKeys.identity.catalogue(), queryFn: ({ signal }) => fetchCatalogue(signal) });
  const role = useQuery({ queryKey: queryKeys.identity.role(roleId ?? "new"), queryFn: ({ signal }) => fetchRole(roleId!, signal), enabled: roleId !== null });
  const [entries, setEntries] = useState<RoleEntryIn[] | null>(null);
  const [parent, setParent] = useState<string | null | undefined>(undefined);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  if (roleId !== null && (role.isPending || role.isError)) {
    return (
      <SettingsPage title="Role">
        <QueryState isPending={role.isPending} error={role.error} what="this role" area="role administration" onRetry={() => void role.refetch()} />
      </SettingsPage>
    );
  }
  const detail = role.data ?? null;
  const currentEntries = entries ?? detail?.entries ?? [];
  const parentId = parent !== undefined ? parent : (roles.data?.items.find((r) => r.key === detail?.role.inherits?.key)?.id ?? null);
  const errors = fieldErrors(error);
  const conflict = conflictFromError(error);

  async function save(form: FormData) {
    setBusy(true);
    setError(null);
    try {
      const name = String(form.get("name") ?? "").trim();
      const description = String(form.get("description") ?? "").trim() || null;
      const saved = await stepUp.run(() =>
        detail
          ? updateRole(detail.role.id, {
              expected_version: detail.role.version,
              name,
              description: description ?? "",
              entries: currentEntries,
              ...(parentId ? { inherits_role_id: parentId } : { clear_inherits: true }),
            })
          : createRole({ key: String(form.get("key") ?? "").trim(), name, description, inherits_role_id: parentId, entries: currentEntries }),
      );
      await client.invalidateQueries({ queryKey: queryKeys.identity.all() });
      toast.success(detail ? "Role saved" : "Role created");
      router.push(`/settings/roles/${saved.role.id}` as Parameters<typeof router.push>[0]);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <SettingsPage title={detail ? `Edit ${detail.role.name}` : "New custom role"} intro="A deny removes a permission the role would otherwise inherit. You can only grant what you hold yourself.">
      {conflict ? (
        <Conflict
          conflict={conflict}
          onReview={() => {
            setError(null);
            setEntries(null);
            void role.refetch();
          }}
        />
      ) : null}
      <Form
        className="flex flex-col gap-5"
        validationErrors={errors}
        onSubmit={(event) => {
          event.preventDefault();
          void save(new FormData(event.currentTarget));
        }}
      >
        <div className="grid gap-4 md:grid-cols-2">
          {detail ? null : <TextField name="key" label="Key" description="Lower case, e.g. senior_sales" isRequired />}
          <TextField name="name" label="Name" defaultValue={detail?.role.name} isRequired />
          <Select
            label="Inherits from"
            options={[{ id: "", label: "Nothing (start empty)" }, ...(roles.data?.items ?? []).filter((r) => r.id !== detail?.role.id && !r.archived).map((r) => ({ id: r.id, label: r.name }))]}
            value={parentId ?? ""}
            onChange={(value) => setParent(value || null)}
            errorMessage={errors.inherits_role_id}
            isInvalid={!!errors.inherits_role_id}
          />
          <TextArea name="description" label="Description" defaultValue={detail?.role.description ?? ""} />
        </div>
        <Section title="Own entries">
          <EntriesEditor entries={currentEntries} onChange={setEntries} catalogue={catalogue.data?.items ?? []} />
          {errors.entries ? <p className="text-sm text-danger">{errors.entries}</p> : null}
        </Section>
        {error && !conflict && !Object.keys(errors).length ? (
          <p role="alert" className="text-danger">
            {problemText(error)}
          </p>
        ) : null}
        <div className="flex gap-2">
          <Button type="submit" variant="primary" isPending={busy} pendingLabel="Saving…">
            {detail ? "Save role" : "Create role"}
          </Button>
        </div>
      </Form>
      {stepUp.dialog}
    </SettingsPage>
  );
}

function EffectiveTable({ rows, caption }: { rows: EffectiveKey[]; caption: string }) {
  const [filter, setFilter] = useState("");
  const shown = rows.filter((r) => r.key.includes(filter.trim().toLowerCase()));
  return (
    <div className="flex flex-col gap-2">
      <SearchField label={`Filter ${caption.toLowerCase()}`} hideLabel placeholder="Filter by key, e.g. sales.quote" onChange={setFilter} />
      <DataTable
        caption={caption}
        hideCaption
        columns={[
          { id: "key", header: "Permission", isRowHeader: true, mobile: "title", mobileCell: (r) => r.key, cell: (r) => <span className="font-mono text-sm">{r.key}</span> },
          { id: "scope", header: "Scope", mobile: "status", cell: (r) => (r.scope ? SCOPE_LABEL[r.scope] : "Not in effect") },
          { id: "why", header: "Why", mobile: "meta", cell: (r) => r.sources.map((s) => s.label).join("; ") || "—" },
        ]}
        rows={shown}
        rowId={(r) => r.key}
        empty={<EmptyState title="Nothing here">No permission matches.</EmptyState>}
      />
    </div>
  );
}

export function RoleDetailScreen({ roleId }: { roleId: string }) {
  const client = useQueryClient();
  const stepUp = useStepUp();
  const query = useQuery({ queryKey: queryKeys.identity.role(roleId), queryFn: ({ signal }) => fetchRole(roleId, signal) });
  const [busy, setBusy] = useState(false);
  if (query.isPending || query.isError) {
    return (
      <SettingsPage title="Role">
        <QueryState isPending={query.isPending} error={query.error} what="this role" area="role administration" onRetry={() => void query.refetch()} />
      </SettingsPage>
    );
  }
  const detail: RoleDetail = query.data;
  const caps = detail.capabilities;
  async function archive() {
    setBusy(true);
    try {
      await stepUp.run(() => archiveRole(roleId));
      await client.invalidateQueries({ queryKey: queryKeys.identity.all() });
      toast.success("Role archived");
    } catch (err) {
      toast.error(problemText(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <SettingsPage
      title={detail.role.name}
      intro={detail.role.description ?? (detail.role.kind === "system_template" ? "System role (read-only)." : undefined)}
      actions={
        <>
          <LinkButton href={`/settings/roles/simulate?role=${roleId}`}>Simulate</LinkButton>
          {caps.update.allowed ? <LinkButton href={`/settings/roles/${roleId}/edit`}>Edit</LinkButton> : null}
          {detail.role.kind === "custom" && !detail.role.archived ? (
            <Button variant="danger" isPending={busy} onPress={() => void archive()} {...unavailableWhen(caps.archive.allowed ? null : caps.archive.reason_code === "role_in_use" ? "Unassign it first (and change roles that inherit it)" : "You cannot archive this role")}>
              Archive
            </Button>
          ) : null}
        </>
      }
    >
      <Section title="Inheritance" description="Root first; each role adds or denies on top of its parent.">
        <ol className="flex flex-wrap items-center gap-2 text-sm">
          {detail.chain.map((r, i) => (
            <li key={r.key} className="flex items-center gap-2">
              {i > 0 ? <span aria-hidden="true">→</span> : null}
              <Badge tone={i === detail.chain.length - 1 ? "forest" : "neutral"}>{r.name}</Badge>
            </li>
          ))}
        </ol>
        {detail.entries.some((e) => e.effect === "deny") ? (
          <p className="text-sm">Denies: {detail.entries.filter((e) => e.effect === "deny").map((e) => keyLabel(e.key)).join(", ")}</p>
        ) : null}
      </Section>
      <Section title={`What this role grants (${detail.effective.length})`}>
        <EffectiveTable rows={detail.effective} caption="Effective permissions" />
      </Section>
      {stepUp.dialog}
    </SettingsPage>
  );
}

/** "What can X do, and why not?" over a member or a role (PARITY LM-09 / UI-21 / UI-94). */
export function SimulatorScreen({ userId, roleId }: { userId: string | null; roleId: string | null }) {
  const router = useRouter();
  const users = useQuery({ queryKey: queryKeys.identity.users({}), queryFn: ({ signal }) => fetchUsers({ q: null, status: "active", role: null, offset: 0 }, signal) });
  const roles = useQuery({ queryKey: queryKeys.identity.roles(), queryFn: ({ signal }) => fetchRoles(signal) });
  const subject = { userId, roleId: userId ? null : roleId };
  const query = useQuery({
    queryKey: queryKeys.identity.effective(subject),
    queryFn: ({ signal }) => fetchEffective(subject, signal),
    enabled: !!(subject.userId || subject.roleId),
  });
  const [checkKey, setCheckKey] = useState<string | null>(null);
  const [checkScope, setCheckScope] = useState<Scope>("own");
  const check = useQuery({
    queryKey: queryKeys.identity.check({ userId: userId ?? "", key: checkKey ?? "", scope: checkScope }),
    queryFn: ({ signal }) => fetchAccessCheck(userId!, checkKey!, checkScope, signal),
    enabled: !!userId && !!checkKey,
  });
  const go = (next: { user?: string | null; role?: string | null }) => {
    const p = new URLSearchParams();
    if (next.user) p.set("user", next.user);
    if (next.role) p.set("role", next.role);
    router.push(`/settings/roles/simulate${p.toString() ? `?${p}` : ""}` as Parameters<typeof router.push>[0]);
  };
  return (
    <SettingsPage title="Role simulator" intro="Pick a person to see every permission they have, where it comes from, and what was taken away.">
      <div className="grid gap-4 md:grid-cols-2">
        <ComboBox label="Person" options={(users.data?.items ?? []).map((u) => ({ id: u.user_id, label: u.display_name, detail: u.roles.map((r) => r.name).join(", ") }))} value={userId} onChange={(v) => go({ user: v })} />
        <Select label="Or a role on its own" options={[{ id: "", label: "—" }, ...(roles.data?.items ?? []).map((r) => ({ id: r.id, label: r.name }))]} value={userId ? "" : (roleId ?? "")} onChange={(v) => go({ role: v || null })} />
      </div>
      {!subject.userId && !subject.roleId ? (
        <EmptyState title="Choose someone">The simulator explains access; it never changes it.</EmptyState>
      ) : query.isPending || query.isError ? (
        <QueryState isPending={query.isPending} error={query.error} what="the effective permissions" area="the role simulator" onRetry={() => void query.refetch()} />
      ) : (
        <>
          <p className="text-sm text-ink-muted">
            {query.data.display_name} · roles: {query.data.role_keys.join(", ") || "none"}
            {query.data.membership_status && query.data.membership_status !== "active" ? ` · ${query.data.membership_status}: no permissions apply` : ""}
          </p>
          {userId ? (
            <Section title="Why or why not?" description="Check one permission at a scope.">
              <div className="grid gap-3 md:grid-cols-[2fr_1fr]">
                <ComboBox label="Permission" options={[...query.data.granted, ...query.data.removed].map((r) => ({ id: r.key, label: r.key }))} value={checkKey} onChange={setCheckKey} />
                <Select label="Scope needed" options={(["own", "team", "branch", "company"] as const).map((s) => ({ id: s, label: SCOPE_LABEL[s]! }))} value={checkScope} onChange={(v) => setCheckScope((v as Scope | null) ?? "own")} />
              </div>
              {check.data ? (
                <div role="status" className="rounded-lg border p-3">
                  <p className="font-semibold">{check.data.allowed ? "Yes, allowed." : "No, not allowed."}</p>
                  <ul className="list-disc ps-5 text-sm">
                    {check.data.reasons.map((r) => (
                      <li key={r}>{r}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </Section>
          ) : null}
          <Section title={`Granted (${query.data.granted.length})`}>
            <EffectiveTable rows={query.data.granted} caption="Granted permissions" />
          </Section>
          {query.data.removed.length ? (
            <Section title={`Taken away (${query.data.removed.length})`} description="A role deny or a personal revoke removed these.">
              <EffectiveTable rows={query.data.removed} caption="Removed permissions" />
            </Section>
          ) : null}
          {query.data.delegated.length ? (
            <Section title="Delegated reach" description="Delegation reaches other people's records; it never adds permissions.">
              <EffectiveTable rows={query.data.delegated} caption="Delegated permissions" />
            </Section>
          ) : null}
        </>
      )}
    </SettingsPage>
  );
}
