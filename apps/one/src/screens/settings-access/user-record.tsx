"use client";

import { useState, type ReactNode } from "react";
import {
  deactivateUser,
  endMemberSessions,
  issuePasswordReset,
  reactivateUser,
  reissueInvitation,
  resetMemberMfa,
  revokeInvitation,
} from "@/app/(app)/settings/_lib/api";
import type { Delivery, UserDetail } from "@/app/(app)/settings/_lib/types";
import { conflictFromError } from "@/lib/api/errors";
import { useRefreshIdentity, useUser } from "~/data/settings-access";
import { Page, PageHeader, RecordHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import {
  Badge,
  Banner,
  Button,
  ButtonLink,
  ConfirmDialog,
  DateText,
  FactStrip,
  GlassPanel,
  Icon,
  IconButton,
  KeyValue,
  Menu,
  ReasonDialog,
  Skeleton,
  SkeletonText,
  Tabs,
  TextLink,
  toast,
  type IconName,
  type MenuItem,
  type TabItem,
} from "~/ui";
import { humanise, problemText, SETTINGS_CRUMB, simulateHref, userHref, USERS_CRUMB, type UserView } from "./labels";
import { DeliveryNote, MemberStatusBadge } from "./parts";
import { useStepUp } from "./step-up";
import { ChangeRolesModal, EditDetailsModal } from "./user-dialogs";
import { PersonalPermissions } from "./user-overrides";

/** One person: who they are, what they may do, and how they sign in. */
export function UserRecord({ userId, view }: { userId: string; view: UserView }) {
  const query = useUser(userId);
  if (query.isPending) {
    return (
      <Page>
        <div className="lk-glass record-head" role="status" aria-label="Loading this person">
          <Skeleton width={90} height={10} />
          <Skeleton width="40%" height={28} />
          <SkeletonText lines={2} />
        </div>
      </Page>
    );
  }
  if (query.isError) {
    return (
      <Page>
        <PageHeader breadcrumb={[SETTINGS_CRUMB, USERS_CRUMB]} title="Person" />
        <ErrorBlock error={query.error} what="This person" onRetry={() => void query.refetch()} />
      </Page>
    );
  }
  return <Loaded user={query.data} view={view} />;
}

type Confirming = null | "reactivate" | "sessions" | "revoke";
type Reasoning = null | "deactivate" | "mfa";

function twoStepText(user: UserDetail): string {
  if (user.mfa_enrolled) return "On";
  return user.mfa_required ? "Required, not set up" : "Off";
}

function Loaded({ user, view }: { user: UserDetail; view: UserView }) {
  const refresh = useRefreshIdentity();
  const stepUp = useStepUp();
  const caps = user.capabilities;
  const [editing, setEditing] = useState({ open: false, round: 0 });
  const [changingRoles, setChangingRoles] = useState({ open: false, round: 0 });
  const [confirming, setConfirming] = useState<Confirming>(null);
  const [reasoning, setReasoning] = useState<Reasoning>(null);
  const [busy, setBusy] = useState<null | "reset" | "resend">(null);
  const [issued, setIssued] = useState<{ delivery: Delivery; what: "invitation" | "reset" } | null>(null);
  const [conflict, setConflict] = useState(false);

  /** Runs one admin command with step-up, re-reads the person, and reports the result. Rejects on failure. */
  async function act<T>(command: () => Promise<T>, done: string, failed: string): Promise<T> {
    try {
      const result = await stepUp.run(command);
      await refresh();
      toast.success(done);
      return result;
    } catch (error) {
      if (conflictFromError(error)) {
        setConflict(true);
        await refresh();
      }
      toast.error(failed, { description: problemText(error) });
      throw error;
    }
  }

  const openInvitation = user.invitations.find((invitation) => invitation.status === "open" || invitation.status === "expired");
  const name = user.display_name;

  const sendReset = async () => {
    setBusy("reset");
    try {
      const result = await act(() => issuePasswordReset(user.user_id), "Reset link created", "The reset link was not created");
      setIssued({ delivery: result.delivery, what: "reset" });
    } catch {
      // Reported by `act`.
    } finally {
      setBusy(null);
    }
  };

  const resendInvitation = async () => {
    if (!openInvitation) return;
    setBusy("resend");
    try {
      const result = await act(() => reissueInvitation(openInvitation.id), "New invitation link created", "The invitation was not sent again");
      setIssued({ delivery: result.delivery, what: "invitation" });
    } catch {
      // Reported by `act`.
    } finally {
      setBusy(null);
    }
  };

  const tab = (id: UserView, label: string, count?: number): TabItem => ({ id, label, count, href: userHref(user.user_id, id) });
  const tabs: TabItem[] = [tab("overview", "Overview"), tab("access", "Roles and permissions", user.overrides.length || undefined), tab("sign-in", "Sign-in")];

  const open = (set: typeof setEditing) => () => set((state) => ({ open: true, round: state.round + 1 }));
  const close = (set: typeof setEditing) => (isOpen: boolean) => set((state) => ({ ...state, open: isOpen }));

  const menu: MenuItem[] = [
    ...(caps.assign_roles.allowed ? [{ id: "roles", label: "Change roles", icon: "userCog" as const, onAction: open(setChangingRoles) }] : []),
    ...(caps.deactivate.allowed
      ? [
          ...(caps.assign_roles.allowed ? [{ id: "sep", separator: true as const }] : []),
          { id: "deactivate", label: "Deactivate", icon: "lock" as const, tone: "danger" as const, onAction: () => setReasoning("deactivate") },
        ]
      : []),
  ];

  const changeRolesButton = caps.assign_roles.allowed ? (
    <Button variant="secondary" size="sm" iconLeft="userCog" onPress={open(setChangingRoles)}>
      Change roles
    </Button>
  ) : undefined;

  return (
    <Page>
      <RecordHeader
        breadcrumb={[SETTINGS_CRUMB, USERS_CRUMB, { label: name }]}
        title={name}
        status={
          <>
            <MemberStatusBadge status={user.status} />
            {user.is_self ? <Badge outline>You</Badge> : null}
          </>
        }
        lead={user.email ?? undefined}
        facts={
          <FactStrip
            items={[
              { label: "Job title", value: user.job_title, icon: "user" },
              { label: "Reports to", value: user.manager?.display_name, icon: "users" },
              { label: "Last sign-in", value: user.last_login_at ? <DateText value={user.last_login_at} style="relative" /> : "Never", icon: "clock" },
              { label: "Two-step sign-in", value: twoStepText(user), icon: "shield" },
            ]}
          />
        }
        actions={
          <>
            {caps.reactivate.allowed ? (
              <Button iconLeft="undo" onPress={() => setConfirming("reactivate")}>
                Reactivate
              </Button>
            ) : null}
            {caps.update.allowed ? (
              <Button variant="secondary" iconLeft="edit" onPress={open(setEditing)}>
                Edit details
              </Button>
            ) : null}
            {menu.length > 0 ? <Menu label="More actions" items={menu} placement="bottom end" trigger={<IconButton icon="more" label="More actions" />} /> : null}
          </>
        }
      >
        <Tabs label={`${name}: views`} tabs={tabs} selectedKey={view} />
      </RecordHeader>

      {conflict ? (
        <Banner tone="amber" title="This profile changed while you were working." onClose={() => setConflict(false)}>
          The latest version is showing. Check it, then try again.
        </Banner>
      ) : null}

      {view === "overview" ? <Overview user={user} changeRoles={changeRolesButton} /> : null}

      {view === "access" ? (
        <div className="grid min-w-0 grid-cols-1 items-start gap-5 lg:grid-cols-2">
          <RolesPanel user={user} changeRoles={changeRolesButton} />
          <PersonalPermissions
            userId={user.user_id}
            name={name}
            overrides={user.overrides}
            canManage={caps.manage_overrides.allowed}
            reasonCode={caps.manage_overrides.reason_code}
          />
        </div>
      ) : null}

      {view === "sign-in" ? (
        <div className="stack">
          {issued ? <DeliveryNote delivery={issued.delivery} what={issued.what} /> : null}
          <GlassPanel as="section" title="Sign-in help" titleAs="h2" padding="lg" className="flex flex-col">
            <SignInRow
              first
              icon="key"
              title="Password"
              text={`Send ${name} a one-time link to choose a new password.`}
              action={
                caps.reset_password.allowed ? (
                  <Button variant="secondary" size="sm" loading={busy === "reset"} onPress={() => void sendReset()}>
                    Send reset link
                  </Button>
                ) : null
              }
            />
            <SignInRow
              icon="shield"
              title="Two-step sign-in"
              text={
                user.mfa_enrolled
                  ? "Set up with an authenticator app. Reset it if they lost their phone."
                  : user.mfa_required
                    ? "Their role requires it. They set it up the next time they sign in."
                    : "Not set up. They can turn it on from their own security settings."
              }
              action={
                caps.reset_mfa.allowed && user.mfa_enrolled ? (
                  <Button variant="secondary" size="sm" onPress={() => setReasoning("mfa")}>
                    Reset two-step sign-in
                  </Button>
                ) : null
              }
            />
            <SignInRow
              icon="logOut"
              title="Sessions"
              text={user.last_login_at ? "End every session on every device. They sign in again to continue." : "They have not signed in yet."}
              action={
                caps.end_sessions.allowed ? (
                  <Button variant="secondary" size="sm" onPress={() => setConfirming("sessions")}>
                    Sign out everywhere
                  </Button>
                ) : null
              }
            />
          </GlassPanel>

          {user.invitations.length > 0 ? (
            <GlassPanel
              as="section"
              title="Invitation"
              titleAs="h2"
              padding="lg"
              className="flex flex-col gap-4"
              action={
                openInvitation && caps.invite.allowed ? (
                  <div className="flex flex-wrap gap-2">
                    <Button variant="secondary" size="sm" iconLeft="send" loading={busy === "resend"} onPress={() => void resendInvitation()}>
                      Send again
                    </Button>
                    <Button variant="ghost" size="sm" onPress={() => setConfirming("revoke")}>
                      Revoke
                    </Button>
                  </div>
                ) : undefined
              }
            >
              <ul className="m-0 flex list-none flex-col p-0">
                {user.invitations.map((invitation, index) => (
                  <li key={invitation.id} className={`flex flex-wrap items-center justify-between gap-3 py-3 ${index > 0 ? "hairline-top" : ""}`}>
                    <div className="flex min-w-0 flex-col gap-1">
                      <span className="t-label text-ink break-all">{invitation.email}</span>
                      <span className="t-body-sm text-ink-3">
                        Sent {invitation.send_count === 1 ? "once" : `${invitation.send_count} times`}
                        {invitation.invited_by_name ? ` by ${invitation.invited_by_name}` : ""}
                        {" · "}
                        {invitation.status === "open" ? "expires " : "expiry "}
                        <DateText value={invitation.expires_at} style="dayTime" />
                      </span>
                    </div>
                    <Badge tone={invitation.status === "open" ? "cobalt" : invitation.status === "accepted" ? "leaf" : invitation.status === "expired" ? "amber" : "neutral"} dot>
                      {humanise(invitation.status)}
                    </Badge>
                  </li>
                ))}
              </ul>
            </GlassPanel>
          ) : null}
        </div>
      ) : null}

      {caps.update.allowed ? <EditDetailsModal key={`edit-${editing.round}`} user={user} isOpen={editing.open} onOpenChange={close(setEditing)} run={stepUp.run} /> : null}
      {caps.assign_roles.allowed ? (
        <ChangeRolesModal key={`roles-${changingRoles.round}`} user={user} isOpen={changingRoles.open} onOpenChange={close(setChangingRoles)} run={stepUp.run} />
      ) : null}

      <ReasonDialog
        isOpen={reasoning === "deactivate"}
        onOpenChange={(isOpen) => {
          if (!isOpen) setReasoning(null);
        }}
        tone="danger"
        title={`Deactivate ${name}`}
        description="They are signed out at once and their links stop working. Their name stays on past work, and you can reactivate them later."
        reasonHelp="Shown on their profile for other admins."
        cancelLabel="Keep active"
        confirmLabel="Deactivate"
        onConfirm={async (reason) => {
          await act(() => deactivateUser(user.user_id, reason, null), `${name} deactivated`, "They were not deactivated");
        }}
      />
      <ReasonDialog
        isOpen={reasoning === "mfa"}
        onOpenChange={(isOpen) => {
          if (!isOpen) setReasoning(null);
        }}
        tone="danger"
        title="Reset two-step sign-in"
        description={`Use this when ${name} has lost their phone. They are signed out and set up a new authenticator app the next time they sign in.`}
        reasonHelp="Recorded with the reset."
        confirmLabel="Reset two-step sign-in"
        onConfirm={async (reason) => {
          await act(() => resetMemberMfa(user.user_id, reason), "Two-step sign-in reset", "Two-step sign-in was not reset");
        }}
      />
      <ConfirmDialog
        isOpen={confirming === "reactivate"}
        onOpenChange={(isOpen) => {
          if (!isOpen) setConfirming(null);
        }}
        title={`Reactivate ${name}`}
        description="They can sign in again with the roles they had."
        confirmLabel="Reactivate"
        onConfirm={async () => {
          await act(() => reactivateUser(user.user_id), `${name} reactivated`, "They were not reactivated");
        }}
      />
      <ConfirmDialog
        isOpen={confirming === "sessions"}
        onOpenChange={(isOpen) => {
          if (!isOpen) setConfirming(null);
        }}
        tone="danger"
        title={`Sign ${name} out everywhere`}
        description="Every session on every device ends now. Unsaved work in those sessions is lost."
        confirmLabel="Sign out everywhere"
        onConfirm={async () => {
          await act(() => endMemberSessions(user.user_id), "Signed out everywhere", "The sessions were not ended");
        }}
      />
      <ConfirmDialog
        isOpen={confirming === "revoke"}
        onOpenChange={(isOpen) => {
          if (!isOpen) setConfirming(null);
        }}
        tone="danger"
        title="Revoke this invitation"
        description="The link stops working. You can invite them again later."
        confirmLabel="Revoke invitation"
        onConfirm={async () => {
          if (!openInvitation) return;
          await act(() => revokeInvitation(openInvitation.id), "Invitation revoked", "The invitation was not revoked");
        }}
      />
      {stepUp.dialog}
    </Page>
  );
}

function Overview({ user, changeRoles }: { user: UserDetail; changeRoles: ReactNode }) {
  const pendingInvite = user.invitations.find((invitation) => invitation.status === "open" || invitation.status === "expired");
  return (
    <div className="stack">
      {user.status === "deactivated" ? (
        <Banner tone="neutral" icon="lock" title="Deactivated.">
          {user.deactivation_reason ? `Reason given: ${user.deactivation_reason}` : "They cannot sign in. Their name stays on past work."}
          {user.deactivated_at ? (
            <>
              {" · "}
              <DateText value={user.deactivated_at} style="date" />
            </>
          ) : null}
        </Banner>
      ) : null}
      {user.status === "invited" && pendingInvite ? (
        <Banner
          tone={pendingInvite.status === "expired" ? "amber" : "cobalt"}
          title={pendingInvite.status === "expired" ? "Their invitation has expired." : "Invited, not signed in yet."}
          action={
            <ButtonLink variant="secondary" size="sm" href={userHref(user.user_id, "sign-in")}>
              See invitation
            </ButtonLink>
          }
        >
          {pendingInvite.status === "expired" ? "Send it again so they can choose a password." : "The account becomes active when they open the link and choose a password."}
        </Banner>
      ) : null}
      {user.status === "active" && user.mfa_required && !user.mfa_enrolled ? (
        <Banner tone="amber" title="Two-step sign-in is required and not set up.">
          Their role needs an authenticator app. They are asked to set it up the next time they sign in.
        </Banner>
      ) : null}

      <div className="grid min-w-0 grid-cols-1 items-start gap-5 lg:grid-cols-2">
        <GlassPanel as="section" title="Where they work" titleAs="h2" padding="lg">
          <KeyValue
            items={[
              ...(user.full_name && user.full_name !== user.display_name ? [{ label: "Full name", value: user.full_name }] : []),
              { label: "Department", value: user.department },
              { label: "Branches", value: user.branches.map((branch) => branch.name).join(", ") },
              { label: "Teams", value: user.teams.map((team) => team.name).join(", ") },
              ...(user.joined_on ? [{ label: "Joined", value: <DateText value={user.joined_on} style="business" /> }] : []),
              { label: "Last sign-in", value: user.last_login_at ? <DateText value={user.last_login_at} style="dayTime" /> : "Never" },
            ]}
          />
        </GlassPanel>
        <RolesPanel user={user} changeRoles={changeRoles} />
      </div>
    </div>
  );
}

function RolesPanel({ user, changeRoles }: { user: UserDetail; changeRoles: ReactNode }) {
  return (
    <GlassPanel as="section" title="Roles" titleAs="h2" padding="lg" action={changeRoles} className="flex flex-col gap-4">
      <p className="t-body-sm text-ink-3">Roles decide what {user.display_name} can see and do. A change applies on their next request.</p>
      {user.roles.length > 0 ? (
        <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
          {user.roles.map((role) => (
            <li key={role.key}>
              <Badge icon="badgeCheck">{role.name}</Badge>
            </li>
          ))}
        </ul>
      ) : (
        <p className="t-body text-ink-2">No role yet, so they can do very little.</p>
      )}
      <div className="hairline-top pt-4">
        <TextLink href={simulateHref({ user: user.user_id })} className="t-body-sm">
          See what {user.display_name} can do, and why
        </TextLink>
      </div>
    </GlassPanel>
  );
}

function SignInRow({ icon, title, text, action, first = false }: { icon: IconName; title: string; text: string; action: ReactNode; first?: boolean }) {
  return (
    <div className={`flex flex-wrap items-center justify-between gap-4 py-4 ${first ? "" : "hairline-top"}`}>
      <div className="flex min-w-0 flex-1 basis-64 items-start gap-3">
        <span className="mt-0.5 grid size-9 flex-none place-items-center rounded-md bg-surface text-ink-2" aria-hidden>
          <Icon name={icon} size={18} />
        </span>
        <div className="flex min-w-0 flex-col gap-0.5">
          <h3 className="t-label text-ink">{title}</h3>
          <p className="t-body-sm text-ink-2">{text}</p>
        </div>
      </div>
      {action}
    </div>
  );
}
