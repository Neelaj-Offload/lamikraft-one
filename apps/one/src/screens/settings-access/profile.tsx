"use client";

import type { Route } from "next";
import { useState } from "react";
import { saveUiPreference } from "@/features/settings/api";
import type { Me } from "@/features/settings/types";
import { useSession } from "@/lib/session/context";
import type { UiPreferencesState } from "@/lib/session/types";
import type { MotionPreference } from "@/lib/ui-preferences";
import { useMe } from "~/data/settings-access";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock, LoadingBlock } from "~/shell/states";
import { Avatar, Badge, ButtonLink, DateText, GlassPanel, KeyValue, RadioGroup, Switch, ThemeToggle, toast, type KeyValueItem } from "~/ui";
import { humanise, SETTINGS_CRUMB } from "./labels";

/** Your account as the team sees it, how Lamikraft One behaves for you, and this sign-in. */
export function Profile() {
  const me = useMe();
  return (
    <Page width="reading">
      <PageHeader breadcrumb={[SETTINGS_CRUMB, { label: "Profile" }]} title="Profile" lead="Your account as the team sees it, and how Lamikraft One looks and behaves for you." />
      <div className="rise" style={{ "--i": 1 } as React.CSSProperties}>
        {me.isPending ? (
          <LoadingBlock label="Loading your profile" lines={6} />
        ) : me.isError ? (
          <ErrorBlock error={me.error} what="Your profile" onRetry={() => void me.refetch()} />
        ) : (
          <AccountPanel me={me.data} />
        )}
      </div>
      <div className="rise" style={{ "--i": 2 } as React.CSSProperties}>
        <PreferencesPanel />
      </div>
      {me.data?.session ? (
        <div className="rise" style={{ "--i": 3 } as React.CSSProperties}>
          <SessionPanel session={me.data.session} />
        </div>
      ) : null}
    </Page>
  );
}

function AccountPanel({ me }: { me: Me }) {
  const { user, membership } = me;
  const items: (KeyValueItem | null)[] = [
    user.full_name && user.full_name !== user.display_name ? { label: "Full name", value: user.full_name } : null,
    membership.job_title ? { label: "Job title", value: membership.job_title } : null,
    membership.company ? { label: "Company", value: membership.company.display_name } : null,
    membership.branches.length ? { label: "Branches", value: membership.branches.map((branch) => `${branch.name} (${branch.code})`).join(", ") } : null,
    membership.teams.length ? { label: "Teams", value: membership.teams.map((team) => team.name).join(", ") } : null,
    membership.manager ? { label: "Reports to", value: membership.manager.display_name } : null,
    membership.joined_on ? { label: "Joined", value: <DateText value={membership.joined_on} style="business" /> } : null,
    me.time_zone ? { label: "Time zone", value: me.time_zone, mono: true } : null,
    me.locale ? { label: "Language and format", value: me.locale, mono: true } : null,
    membership.status ? { label: "Membership", value: humanise(membership.status) } : null,
  ];
  return (
    <GlassPanel as="section" padding="lg" className="flex min-w-0 flex-col gap-5" aria-label="Your account">
      <div className="flex min-w-0 items-center gap-4">
        <Avatar name={user.display_name} size="lg" />
        <div className="flex min-w-0 flex-col gap-1">
          <h2 className="t-h3 truncate" title={user.display_name}>
            {user.display_name}
          </h2>
          {user.email ? <p className="t-body-sm truncate text-ink-3">{user.email}</p> : null}
        </div>
      </div>
      <div className="flex flex-wrap gap-2" aria-label="Your roles">
        {membership.roles.length > 0 ? (
          membership.roles.map((role) => (
            <Badge key={role.key} icon="badgeCheck">
              {role.name}
            </Badge>
          ))
        ) : (
          <span className="t-body-sm text-ink-3">No role yet</span>
        )}
      </div>
      <div className="hairline-top pt-5">
        <KeyValue items={items.filter((item): item is KeyValueItem => item !== null)} columns={2} />
      </div>
      <p className="t-caption text-ink-3">An admin sets these details. Ask one if something is wrong.</p>
    </GlassPanel>
  );
}

/** Mirrors the motion choice on <html data-motion>, which the motion classes and hooks read live. */
function applyMotionLocally(motion: MotionPreference): void {
  if (motion === "reduced") document.documentElement.dataset.motion = "reduced";
  else delete document.documentElement.dataset.motion;
}

/**
 * Each change applies on this device at once (where it can) and is saved to the profile through the
 * shared versioned preference save; a failed save says so.
 */
function PreferencesPanel() {
  const { bootstrap } = useSession();
  const [ui, setUi] = useState<UiPreferencesState>(bootstrap.ui);

  const save = (change: Partial<UiPreferencesState>) => {
    setUi((current) => ({ ...current, ...change }));
    saveUiPreference(change).catch(() => toast.warning("Applied here, not saved", { description: "The change could not be saved to your profile. Try again in a moment." }));
  };

  return (
    <GlassPanel as="section" title="Preferences" titleAs="h2" padding="lg" className="flex min-w-0 flex-col gap-6">
      <p className="t-body-sm text-ink-3">Saved to your profile, so they follow you to every device.</p>
      <div className="flex min-w-0 flex-col gap-2">
        {/* The toggle names itself "Theme" for assistive tech; this is the visible label. */}
        <span className="lk-field-label" aria-hidden>
          Theme
        </span>
        <ThemeToggle className="self-start" />
      </div>
      <RadioGroup
        label="Motion"
        orientation="horizontal"
        value={ui.motion}
        onChange={(value) => {
          const motion: MotionPreference = value === "reduced" ? "reduced" : "full";
          applyMotionLocally(motion);
          save({ motion });
        }}
        options={[
          { value: "full", label: "Full", description: "Panels rise in and numbers count up." },
          { value: "reduced", label: "Reduced", description: "Changes happen at once, nothing moves for show." },
        ]}
      />
      <div className="hairline-top flex min-w-0 flex-col gap-4 pt-5">
        <Switch
          label="Keyboard shortcuts"
          description="Such as / to search. Applies the next time you open Lamikraft One."
          isSelected={ui.shortcuts_enabled}
          onChange={(value) => save({ shortcuts_enabled: value })}
        />
        <Switch
          label="Start with the menu collapsed"
          description="Opens Lamikraft One with the left menu as a narrow rail."
          isSelected={ui.sidebar_collapsed}
          onChange={(value) => save({ sidebar_collapsed: value })}
        />
      </div>
    </GlassPanel>
  );
}

function SessionPanel({ session }: { session: NonNullable<Me["session"]> }) {
  return (
    <GlassPanel
      as="section"
      title="This sign-in"
      titleAs="h2"
      padding="lg"
      className="flex min-w-0 flex-col gap-5"
      action={
        <Badge tone="leaf" dot>
          Current
        </Badge>
      }
    >
      <KeyValue
        columns={2}
        items={[
          { label: "Signed in with", value: session.auth_method ? humanise(session.auth_method) : "Not recorded" },
          { label: "Signed in", value: <DateText value={session.created_at} style="dayTime" /> },
          { label: "Signs out when idle at", value: <DateText value={session.idle_expires_at} style="dayTime" /> },
          { label: "Signs out at the latest", value: <DateText value={session.absolute_expires_at} style="dayTime" /> },
        ]}
      />
      <div className="hairline-top flex flex-wrap items-center justify-between gap-3 pt-5">
        <p className="t-body-sm min-w-0 flex-1 basis-64 text-ink-2">Change your password, set up two-step sign-in or sign out other devices.</p>
        <ButtonLink variant="secondary" size="sm" href={"/settings/security" as Route} iconRight="arrowRight">
          Open security
        </ButtonLink>
      </div>
    </GlassPanel>
  );
}
