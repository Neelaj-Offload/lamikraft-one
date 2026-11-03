"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Form, Link as RacLink } from "react-aria-components";
import { Badge } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/choice";
import { DataTable, OffsetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { DescriptionList } from "@/components/ui/description-list";
import { Dialog } from "@/components/ui/dialog";
import { LocalDateTime, RelativeTime } from "@/components/ui/format";
import { LinkButton } from "@/components/ui/link";
import { SearchField } from "@/components/ui/search-field";
import { Select } from "@/components/ui/select";
import { Conflict, EmptyState } from "@/components/ui/states";
import { linkClasses } from "@/components/ui/styles";
import { TextArea, TextField } from "@/components/ui/text-field";
import { toast } from "@/components/ui/toast";
import { conflictFromError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import {
  deactivateUser,
  fetchRoles,
  fetchUser,
  fetchUsers,
  invite,
  issuePasswordReset,
  reactivateUser,
  reissueInvitation,
  resetMemberMfa,
  revokeInvitation,
  setUserRoles,
  updateUser,
  endMemberSessions,
  USERS_PAGE_SIZE,
  type UserListParams,
} from "./api";
import { OverridesPanel } from "./overrides";
import { useStepUp } from "./step-up";
import type { Delivery, UserDetail, UserListItem } from "./types";
import { fieldErrors, MemberStatus, problemText, QueryState, Section, SettingsPage } from "./ui";

export const MEMBER_STATUSES = ["active", "invited", "deactivated"] as const;

export type UserListState = UserListParams;

export function userListStateFrom(params: Record<string, string | string[] | undefined>): UserListState {
  const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? null;
  const status = one(params.status);
  const offset = Number.parseInt(one(params.offset) ?? "0", 10);
  return {
    q: one(params.q)?.trim().slice(0, 100) || null,
    status: MEMBER_STATUSES.find((s) => s === status) ?? null,
    role: one(params.role)?.match(/^[a-z][a-z0-9_]{1,40}$/) ? one(params.role) : null,
    offset: Number.isFinite(offset) && offset > 0 ? offset : 0,
  };
}

export function userListHref(state: UserListState): string {
  const q = new URLSearchParams();
  if (state.q) q.set("q", state.q);
  if (state.status) q.set("status", state.status);
  if (state.role) q.set("role", state.role);
  if (state.offset) q.set("offset", String(state.offset));
  const s = q.toString();
  return s ? `/settings/users?${s}` : "/settings/users";
}

function columns(): DataTableColumn<UserListItem>[] {
  return [
    {
      id: "name",
      header: "Name",
      isRowHeader: true,
      mobile: "title",
      mobileCell: (row) => row.display_name,
      cell: (row) => (
        <RacLink href={`/settings/users/${row.user_id}`} className={linkClasses}>
          {row.display_name}
        </RacLink>
      ),
    },
    { id: "email", header: "Email", mobile: "meta", cell: (row) => row.email ?? "—" },
    { id: "roles", header: "Roles", mobile: "key", cell: (row) => row.roles.map((r) => r.name).join(", ") || "—" },
    { id: "status", header: "Status", mobile: "status", cell: (row) => <MemberStatus status={row.status} /> },
    { id: "mfa", header: "Two-step", cell: (row) => (row.mfa_enrolled ? <Badge tone="forest">On</Badge> : <span className="text-ink-muted">Off</span>) },
    { id: "last", header: "Last sign-in", cell: (row) => (row.last_login_at ? <RelativeTime value={row.last_login_at} className="text-ink-muted" /> : <span className="text-ink-muted">Never</span>) },
  ];
}

/** Members: search, status and role filters live in the URL and apply before paging (server-side). */
export function UserListScreen({ state }: { state: UserListState }) {
  const router = useRouter();
  const query = useQuery({ queryKey: queryKeys.identity.users(state), queryFn: ({ signal }) => fetchUsers(state, signal) });
  const roles = useQuery({ queryKey: queryKeys.identity.roles(), queryFn: ({ signal }) => fetchRoles(signal) });
  const go = (next: Partial<UserListState>) => router.push(userListHref({ ...state, offset: 0, ...next }) as Parameters<typeof router.push>[0]);
  return (
    <SettingsPage
      title="Users"
      intro="Everyone with access to this company. People are never deleted: deactivated members keep their name on past work."
      actions={<LinkButton href="/settings/users/invite" variant="primary">Invite someone</LinkButton>}
    >
      <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)] md:items-end">
        <SearchField label="Search people" placeholder="Name, email or job title" defaultValue={state.q ?? ""} onSubmit={(q) => go({ q })} onClear={() => go({ q: null })} />
        <Select
          label="Status"
          options={[{ id: "", label: "Any status" }, { id: "active", label: "Active" }, { id: "invited", label: "Invited" }, { id: "deactivated", label: "Inactive" }]}
          value={state.status ?? ""}
          onChange={(value) => go({ status: MEMBER_STATUSES.find((s) => s === value) ?? null })}
        />
        <Select
          label="Role"
          options={[{ id: "", label: "Any role" }, ...(roles.data?.items ?? []).map((r) => ({ id: r.key, label: r.name }))]}
          value={state.role ?? ""}
          onChange={(value) => go({ role: value ? String(value) : null })}
        />
      </div>
      {query.isPending || query.isError ? (
        <QueryState isPending={query.isPending} error={query.error} what="the members" area="user administration" onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          caption="Members"
          hideCaption
          columns={columns()}
          rows={query.data.items}
          rowId={(row) => row.user_id}
          rowHref={(row) => `/settings/users/${row.user_id}`}
          empty={<EmptyState title="No one matches">Change the search or the filters.</EmptyState>}
          footer={
            <OffsetPagination
              label="Member pages"
              total={query.data.total}
              limit={query.data.limit || USERS_PAGE_SIZE}
              offset={query.data.offset}
              shown={query.data.items.length}
              control={(offset) => ({ href: userListHref({ ...state, offset }) })}
            />
          }
        />
      )}
    </SettingsPage>
  );
}

/** The one-time link of a demo-mode delivery ("Email delivery: Demo, not sent"). */
export function DeliveryNote({ delivery, what }: { delivery: Delivery; what: string }) {
  return (
    <div role="status" className="flex flex-col gap-2 rounded-lg border border-info/40 bg-info/5 p-3 text-sm">
      <p className="font-semibold">{delivery.label}</p>
      {delivery.manual_link ? (
        <>
          <p>Copy this {what} link now and hand it over; it is shown only once.</p>
          <TextField label={`${what[0]!.toUpperCase()}${what.slice(1)} link`} value={delivery.manual_link} isReadOnly inputClassName="font-mono text-xs" />
        </>
      ) : null}
      {delivery.outbox_file ? <p className="text-ink-muted">Written to the demo outbox as {delivery.outbox_file}.</p> : null}
    </div>
  );
}

export function InviteScreen() {
  const router = useRouter();
  const client = useQueryClient();
  const roles = useQuery({ queryKey: queryKeys.identity.roles(), queryFn: ({ signal }) => fetchRoles(signal) });
  const stepUp = useStepUp();
  const [selected, setSelected] = useState<string[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [issued, setIssued] = useState<{ delivery: Delivery; userId: string } | null>(null);
  const errors = fieldErrors(error);

  async function submit(form: FormData) {
    setBusy(true);
    setError(null);
    try {
      const result = await stepUp.run(() =>
        invite({
          email: String(form.get("email") ?? "").trim(),
          display_name: String(form.get("display_name") ?? "").trim(),
          job_title: String(form.get("job_title") ?? "").trim() || null,
          role_keys: selected,
        }),
      );
      await client.invalidateQueries({ queryKey: queryKeys.identity.all() });
      setIssued({ delivery: result.delivery, userId: result.invitation.user_id });
      toast.success("Invitation created");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const assignable = (roles.data?.items ?? []).filter((r) => r.is_assignable && !r.archived);
  return (
    <SettingsPage title="Invite someone" intro="The person gets a link valid for 7 days to choose a password. Administrators set up two-step sign-in at their first sign-in.">
      {issued ? (
        <Section title="Invitation ready">
          <DeliveryNote delivery={issued.delivery} what="invitation" />
          <div className="flex gap-2">
            <Button variant="primary" onPress={() => router.push(`/settings/users/${issued.userId}` as Parameters<typeof router.push>[0])}>
              Open their page
            </Button>
            <Button onPress={() => setIssued(null)}>Invite another person</Button>
          </div>
        </Section>
      ) : (
        <Form
          className="flex max-w-xl flex-col gap-4"
          validationErrors={errors}
          onSubmit={(event) => {
            event.preventDefault();
            void submit(new FormData(event.currentTarget));
          }}
        >
          <TextField name="email" label="Email" type="email" isRequired autoComplete="off" />
          <TextField name="display_name" label="Name" isRequired />
          <TextField name="job_title" label="Job title" />
          <fieldset className="flex flex-col gap-2">
            <legend className="font-medium">Roles</legend>
            {roles.isPending ? <p className="text-ink-muted">Loading roles…</p> : null}
            {assignable.map((role) => (
              <Checkbox
                key={role.key}
                isSelected={selected.includes(role.key)}
                onChange={(on) => setSelected(on ? [...selected, role.key] : selected.filter((k) => k !== role.key))}
              >
                {role.name}
                {role.kind === "custom" ? " (custom)" : ""}
              </Checkbox>
            ))}
            {errors.role_keys ? <p className="text-sm text-danger">{errors.role_keys}</p> : null}
          </fieldset>
          {error && !Object.keys(errors).length ? (
            <p role="alert" className="text-danger">
              {problemText(error)}
            </p>
          ) : null}
          <div>
            <Button type="submit" variant="primary" isPending={busy} pendingLabel="Inviting…" {...unavailableWhen(selected.length === 0 ? "Choose at least one role" : null)}>
              Send invitation
            </Button>
          </div>
        </Form>
      )}
      {stepUp.dialog}
    </SettingsPage>
  );
}

type Busy = null | "roles" | "deactivate" | "reactivate" | "reset" | "mfa" | "sessions" | "profile" | "invite";

export function UserDetailScreen({ userId }: { userId: string }) {
  const client = useQueryClient();
  const query = useQuery({ queryKey: queryKeys.identity.user(userId), queryFn: ({ signal }) => fetchUser(userId, signal) });
  const roles = useQuery({ queryKey: queryKeys.identity.roles(), queryFn: ({ signal }) => fetchRoles(signal) });
  const stepUp = useStepUp();
  const [busy, setBusy] = useState<Busy>(null);
  const [dialog, setDialog] = useState<null | "deactivate" | "roles" | "mfa" | "edit">(null);
  const [delivery, setDelivery] = useState<Delivery | null>(null);
  const [conflict, setConflict] = useState<unknown>(null);
  const [roleDraft, setRoleDraft] = useState<string[]>([]);
  const [formError, setFormError] = useState<unknown>(null);

  if (query.isPending || query.isError) {
    return (
      <SettingsPage title="Member">
        <QueryState isPending={query.isPending} error={query.error} what="this member" area="user administration" onRetry={() => void query.refetch()} />
      </SettingsPage>
    );
  }
  const user: UserDetail = query.data;
  const caps = user.capabilities;

  async function act<T>(kind: Busy, command: () => Promise<T>, done: string) {
    setBusy(kind);
    setFormError(null);
    try {
      const result = await stepUp.run(command);
      await client.invalidateQueries({ queryKey: queryKeys.identity.all() });
      toast.success(done);
      setDialog(null);
      return result;
    } catch (err) {
      if (conflictFromError(err)) setConflict(err);
      else setFormError(err);
      toast.error(problemText(err));
      return null;
    } finally {
      setBusy(null);
    }
  }

  const open = user.invitations.find((i) => i.status === "open" || i.status === "expired");
  return (
    <SettingsPage
      title={user.display_name}
      intro={user.email ?? undefined}
      actions={
        <>
          {caps.update.allowed ? <Button onPress={() => setDialog("edit")}>Edit details</Button> : null}
          {caps.deactivate.allowed ? (
            <Button variant="danger" onPress={() => setDialog("deactivate")}>
              Deactivate
            </Button>
          ) : null}
          {caps.reactivate.allowed ? (
            <Button isPending={busy === "reactivate"} onPress={() => void act("reactivate", () => reactivateUser(userId), "Member reactivated")}>
              Reactivate
            </Button>
          ) : null}
        </>
      }
    >
      {conflict ? (
        <Conflict
          conflict={conflictFromError(conflict)!}
          onReview={() => {
            setConflict(null);
            void query.refetch();
          }}
        />
      ) : null}
      <Section title="Profile">
        <DescriptionList
          items={[
            { term: "Status", description: <MemberStatus status={user.status} /> },
            { term: "Job title", description: user.job_title ?? "—" },
            { term: "Department", description: user.department ?? "—" },
            { term: "Manager", description: user.manager?.display_name ?? "—" },
            { term: "Branches", description: user.branches.map((b) => b.name).join(", ") || "—" },
            { term: "Teams", description: user.teams.map((t) => t.name).join(", ") || "—" },
            { term: "Last sign-in", description: user.last_login_at ? <LocalDateTime value={user.last_login_at} /> : "Never" },
            { term: "Two-step sign-in", description: user.mfa_enrolled ? "Set up" : user.mfa_required ? "Required, not set up yet" : "Not set up" },
            ...(user.deactivation_reason ? [{ term: "Deactivated because", description: user.deactivation_reason }] : []),
          ]}
        />
      </Section>
      <Section
        title="Roles"
        description="Roles decide what this person can do. Changes apply on their next request."
        actions={
          caps.assign_roles.allowed ? (
            <Button
              onPress={() => {
                setRoleDraft(user.roles.map((r) => r.key));
                setDialog("roles");
              }}
            >
              Change roles
            </Button>
          ) : null
        }
      >
        <ul className="flex flex-wrap gap-2">
          {user.roles.map((r) => (
            <li key={r.key}>
              <Badge>{r.name}</Badge>
            </li>
          ))}
        </ul>
        <p className="text-sm">
          <RacLink className={linkClasses} href={`/settings/roles/simulate?user=${userId}`}>
            See what {user.display_name} can do, and why
          </RacLink>
        </p>
      </Section>
      <OverridesPanel userId={userId} canManage={caps.manage_overrides.allowed} overrides={user.overrides} reason={caps.manage_overrides.reason_code} />
      <Section title="Access and sign-in">
        <div className="flex flex-wrap gap-2">
          {caps.reset_password.allowed ? (
            <Button
              isPending={busy === "reset"}
              onPress={() =>
                void act("reset", () => issuePasswordReset(userId), "Reset link created").then((r) => {
                  if (r) setDelivery(r.delivery);
                })
              }
            >
              Send a password reset link
            </Button>
          ) : null}
          {caps.reset_mfa.allowed && user.mfa_enrolled ? <Button onPress={() => setDialog("mfa")}>Reset two-step sign-in</Button> : null}
          {caps.end_sessions.allowed ? (
            <Button isPending={busy === "sessions"} onPress={() => void act("sessions", () => endMemberSessions(userId), "Signed out everywhere")}>
              Sign out everywhere
            </Button>
          ) : null}
          {open && caps.invite.allowed ? (
            <>
              <Button
                isPending={busy === "invite"}
                onPress={() =>
                  void act("invite", () => reissueInvitation(open.id), "New invitation link created").then((r) => {
                    if (r) setDelivery(r.delivery);
                  })
                }
              >
                Resend invitation
              </Button>
              <Button variant="danger" onPress={() => void act("invite", () => revokeInvitation(open.id), "Invitation revoked")}>
                Revoke invitation
              </Button>
            </>
          ) : null}
        </div>
        {delivery ? <DeliveryNote delivery={delivery} what={delivery.manual_link?.includes("/invite") ? "invitation" : "reset"} /> : null}
        {user.invitations.length ? (
          <ul className="text-sm text-ink-muted">
            {user.invitations.map((i) => (
              <li key={i.id}>
                Invitation {i.status}, sent {i.send_count}× (expires <LocalDateTime value={i.expires_at} />)
              </li>
            ))}
          </ul>
        ) : null}
      </Section>

      <Dialog isOpen={dialog === "roles"} onOpenChange={(o) => !o && setDialog(null)} title="Change roles" description="At least one role. You can only give access you hold yourself.">
        <div className="flex flex-col gap-2">
          {(roles.data?.items ?? [])
            .filter((r) => r.is_assignable && !r.archived)
            .map((r) => (
              <Checkbox key={r.key} isSelected={roleDraft.includes(r.key)} onChange={(on) => setRoleDraft(on ? [...roleDraft, r.key] : roleDraft.filter((k) => k !== r.key))}>
                {r.name}
              </Checkbox>
            ))}
          {formError ? <p role="alert" className="text-danger">{problemText(formError)}</p> : null}
          <div className="flex justify-end">
            <Button variant="primary" isPending={busy === "roles"} {...unavailableWhen(roleDraft.length === 0 ? "Choose at least one role" : null)} onPress={() => void act("roles", () => setUserRoles(userId, roleDraft), "Roles updated")}>
              Save roles
            </Button>
          </div>
        </div>
      </Dialog>

      <Dialog isOpen={dialog === "deactivate"} onOpenChange={(o) => !o && setDialog(null)} role="alertdialog" title={`Deactivate ${user.display_name}?`} description="They are signed out at once and their links stop working. Their name stays on past work. You can reactivate them later.">
        <Form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            const reason = String(new FormData(event.currentTarget).get("reason") ?? "").trim();
            void act("deactivate", () => deactivateUser(userId, reason, null), "Member deactivated");
          }}
        >
          <TextArea name="reason" label="Reason" isRequired />
          {formError ? <p role="alert" className="text-danger">{problemText(formError)}</p> : null}
          <div className="flex justify-end gap-2">
            <Button onPress={() => setDialog(null)}>Keep active</Button>
            <Button type="submit" variant="danger" isPending={busy === "deactivate"}>
              Deactivate
            </Button>
          </div>
        </Form>
      </Dialog>

      <Dialog isOpen={dialog === "mfa"} onOpenChange={(o) => !o && setDialog(null)} role="alertdialog" title="Reset two-step sign-in?" description="Use this when someone lost their phone. They are signed out and set up a new authenticator at their next sign-in.">
        <Form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            const reason = String(new FormData(event.currentTarget).get("reason") ?? "").trim();
            void act("mfa", () => resetMemberMfa(userId, reason), "Two-step sign-in reset");
          }}
        >
          <TextArea name="reason" label="Reason" isRequired />
          <div className="flex justify-end">
            <Button type="submit" variant="danger" isPending={busy === "mfa"}>
              Reset
            </Button>
          </div>
        </Form>
      </Dialog>

      <Dialog isOpen={dialog === "edit"} onOpenChange={(o) => !o && setDialog(null)} title="Edit details">
        <Form
          className="flex flex-col gap-3"
          validationErrors={fieldErrors(formError)}
          onSubmit={(event) => {
            event.preventDefault();
            const f = new FormData(event.currentTarget);
            void act(
              "profile",
              () =>
                updateUser(userId, {
                  expected_version: user.version,
                  display_name: String(f.get("display_name") ?? "").trim(),
                  job_title: String(f.get("job_title") ?? ""),
                  department: String(f.get("department") ?? ""),
                }),
              "Details saved",
            );
          }}
        >
          <TextField name="display_name" label="Name" defaultValue={user.display_name.replace(/ \(inactive\)$/, "")} isRequired />
          <TextField name="job_title" label="Job title" defaultValue={user.job_title ?? ""} />
          <TextField name="department" label="Department" defaultValue={user.department ?? ""} />
          <div className="flex justify-end">
            <Button type="submit" variant="primary" isPending={busy === "profile"}>
              Save
            </Button>
          </div>
        </Form>
      </Dialog>
      {stepUp.dialog}
    </SettingsPage>
  );
}
