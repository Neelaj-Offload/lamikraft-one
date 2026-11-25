"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { endMyOtherSessions, endMySession } from "@/app/(app)/settings/_lib/api";
import type { SessionListItem } from "@/app/(app)/settings/_lib/types";
import { changePassword } from "@/features/settings/api";
import { createIdempotencyKey } from "@/lib/api/client";
import { isProblemError } from "@/lib/api/errors";
import { invalidationMap } from "@/lib/api/query-keys";
import { useOnline } from "@/lib/hooks";
import { useMfaStatus, useMySessions, useRefreshIdentity } from "~/data/settings-access";
import { PasswordField } from "~/screens/auth/parts";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock, LoadingBlock } from "~/shell/states";
import { Badge, Banner, Button, ConfirmDialog, DateText, EmptyState, GlassPanel, Icon, SkeletonRows, toast } from "~/ui";
import { humanise, problemText, SETTINGS_CRUMB } from "./labels";
import { TwoStepPanel } from "./two-step-panel";

/** Your own sign-in: two-step, password, and every place you are signed in. */
export function Security() {
  const mfa = useMfaStatus();
  return (
    <Page width="reading">
      <PageHeader
        breadcrumb={[SETTINGS_CRUMB, { label: "Security" }]}
        title="Security"
        lead="How you sign in to Lamikraft One, and every place you are signed in now."
      />
      <div className="rise" style={{ "--i": 1 } as React.CSSProperties}>
        {mfa.isPending ? (
          <LoadingBlock label="Loading your two-step sign-in" lines={3} />
        ) : mfa.isError ? (
          <ErrorBlock error={mfa.error} what="Your two-step sign-in" onRetry={() => void mfa.refetch()} />
        ) : (
          <TwoStepPanel status={mfa.data} />
        )}
      </div>
      <div className="rise" style={{ "--i": 2 } as React.CSSProperties}>
        <PasswordPanel />
      </div>
      <div className="rise" style={{ "--i": 3 } as React.CSSProperties}>
        <SessionsPanel />
      </div>
    </Page>
  );
}

// ---- password ------------------------------------------------------------------------------------

interface PasswordForm {
  current: string;
  next: string;
  confirm: string;
}

const EMPTY: PasswordForm = { current: "", next: "", confirm: "" };

/** Field errors from a 422 (`current_password`, `new_password`), else one sentence for the banner. */
function passwordProblem(error: unknown): { fields: Record<string, string>; alert: string | null } {
  if (!isProblemError(error)) return { fields: {}, alert: problemText(error) };
  if (error.code === "reauth_required") return { fields: {}, alert: "Your sign-in is older than a password change allows. Sign out, sign in again, then change it." };
  if (error.status === 429) return { fields: {}, alert: error.detail || "Too many attempts. Wait a moment, then try again." };
  const fields: Record<string, string> = {};
  for (const issue of error.validationIssues) {
    const field = String(issue.loc[issue.loc.length - 1] ?? "");
    if (field === "current_password" || field === "new_password") fields[field] = issue.msg;
  }
  if (Object.keys(fields).length > 0) return { fields, alert: null };
  return { fields: {}, alert: error.detail || error.title };
}

function PasswordPanel() {
  const client = useQueryClient();
  const refresh = useRefreshIdentity();
  const online = useOnline();
  const [form, setForm] = useState<PasswordForm>(EMPTY);
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<{ fields: Record<string, string>; alert: string | null }>({ fields: {}, alert: null });

  const set = (key: keyof PasswordForm) => (value: string) => setForm((current) => ({ ...current, [key]: value }));
  const local = submitted
    ? {
        current: form.current ? undefined : "Enter the password you use now.",
        next: form.next ? undefined : "Choose a new password.",
        confirm: !form.confirm ? "Type the new password again." : form.confirm !== form.next ? "The two new passwords do not match." : undefined,
      }
    : { current: undefined, next: undefined, confirm: undefined };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (busy || !online || !form.current || !form.next || form.next !== form.confirm) return;
    setBusy(true);
    setProblem({ fields: {}, alert: null });
    try {
      await changePassword({ current_password: form.current, new_password: form.next }, createIdempotencyKey());
      await Promise.all([
        ...invalidationMap["identity.password_changed"].map((queryKey) => client.invalidateQueries({ queryKey })),
        refresh(),
      ]);
      toast.success("Password changed", { description: "Your other devices were signed out. This one stays signed in." });
      setForm(EMPTY);
      setSubmitted(false);
    } catch (error) {
      setProblem(passwordProblem(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <GlassPanel as="section" title="Password" titleAs="h2" padding="lg" className="flex min-w-0 flex-col gap-5">
      <p className="t-body-sm text-ink-3">Changing it signs you out on every other device. This one stays signed in.</p>
      <form onSubmit={(event) => void submit(event)} noValidate className="flex min-w-0 flex-col gap-4" aria-label="Change your password">
        {problem.alert ? (
          <Banner tone="ember" title="Your password was not changed.">
            {problem.alert}
          </Banner>
        ) : null}
        {!online ? (
          <Banner tone="amber" title="You are offline.">
            Your password can change once the connection is back.
          </Banner>
        ) : null}
        <PasswordField
          label="Current password"
          autoComplete="current-password"
          isRequired
          value={form.current}
          onChange={set("current")}
          error={problem.fields.current_password ?? local.current}
        />
        <div className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2">
          <PasswordField
            label="New password"
            autoComplete="new-password"
            isRequired
            maxLength={256}
            value={form.next}
            onChange={set("next")}
            help="At least 12 characters. Not a common password, and not your name or email."
            error={problem.fields.new_password ?? local.next}
          />
          <PasswordField label="New password again" autoComplete="new-password" isRequired maxLength={256} value={form.confirm} onChange={set("confirm")} error={local.confirm} />
        </div>
        <div>
          <Button type="submit" variant="secondary" iconLeft="key" loading={busy} isDisabled={!online}>
            Change password
          </Button>
        </div>
      </form>
    </GlassPanel>
  );
}

// ---- sessions ------------------------------------------------------------------------------------

function SessionsPanel() {
  const sessions = useMySessions();
  const refresh = useRefreshIdentity();
  const [ending, setEnding] = useState<string | null>(null);
  const [confirmAll, setConfirmAll] = useState(false);
  const others = (sessions.data?.items ?? []).filter((session) => !session.current);

  const endOne = async (session: SessionListItem) => {
    setEnding(session.id);
    try {
      await endMySession(session.id);
      toast.success("Signed out of that session");
      await refresh();
    } catch (error) {
      toast.error("That session was not ended", { description: problemText(error) });
    } finally {
      setEnding(null);
    }
  };

  const endOthers = async () => {
    try {
      const result = await endMyOtherSessions();
      toast.success(result.revoked === 1 ? "Signed out of 1 other session" : `Signed out of ${result.revoked} other sessions`);
      await refresh();
    } catch (error) {
      toast.error("The other sessions were not ended", { description: problemText(error) });
      throw error;
    }
  };

  return (
    <GlassPanel
      as="section"
      title="Where you are signed in"
      titleAs="h2"
      padding="lg"
      className="flex min-w-0 flex-col gap-4"
      action={
        others.length > 0 ? (
          <Button variant="secondary" size="sm" iconLeft="logOut" onPress={() => setConfirmAll(true)}>
            Sign out everywhere else
          </Button>
        ) : undefined
      }
    >
      {sessions.isPending ? (
        <SkeletonRows rows={3} />
      ) : sessions.isError ? (
        <ErrorBlock error={sessions.error} what="Your sessions" onRetry={() => void sessions.refetch()} />
      ) : sessions.data.items.length === 0 ? (
        <EmptyState compact icon="monitor" title="No sessions to show" text="Sessions appear here each time you sign in on a device." />
      ) : (
        <ul className="m-0 flex list-none flex-col p-0">
          {sessions.data.items.map((session, index) => (
            <li key={session.id} className={`flex min-w-0 flex-wrap items-center justify-between gap-3 py-3 ${index > 0 ? "hairline-top" : ""}`}>
              <div className="flex min-w-0 flex-1 basis-64 items-start gap-3">
                <span className="mt-0.5 grid size-9 flex-none place-items-center rounded-md bg-surface text-ink-2" aria-hidden>
                  <Icon name="monitor" size={18} />
                </span>
                <div className="flex min-w-0 flex-col gap-0.5">
                  <p className="t-label flex flex-wrap items-center gap-2 text-ink">
                    Signed in <DateText value={session.created_at} style="dayTime" />
                    {session.current ? (
                      <Badge tone="leaf" size="sm">
                        This browser
                      </Badge>
                    ) : null}
                  </p>
                  <p className="t-body-sm text-ink-3">
                    Last active <DateText value={session.last_seen_at} style="relative" /> · {session.mfa_verified ? "Two-step verified" : humanise(session.auth_method)}
                  </p>
                </div>
              </div>
              {session.current ? null : (
                <Button variant="ghost" size="sm" loading={ending === session.id} onPress={() => void endOne(session)}>
                  Sign out
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      <ConfirmDialog
        isOpen={confirmAll}
        onOpenChange={setConfirmAll}
        tone="danger"
        title="Sign out everywhere else"
        description={`Every other session ends now (${others.length}). This browser stays signed in.`}
        confirmLabel="Sign out everywhere else"
        onConfirm={endOthers}
      />
    </GlassPanel>
  );
}
