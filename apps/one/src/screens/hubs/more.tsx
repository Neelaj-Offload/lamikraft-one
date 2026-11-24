"use client";

import type { Route } from "next";
import Link from "next/link";
import { useId, type CSSProperties, type ReactNode } from "react";
import { canAccessRoute, matchRoute } from "@/lib/routes";
import { useSession } from "@/lib/session/context";
import { riseIndex } from "~/lib/motion";
import { Page } from "~/shell/page";
import { Avatar, Badge, GlassPanel, Icon, ThemeToggle, type IconName } from "~/ui";

interface Row {
  label: string;
  hint: string;
  icon: IconName;
  href: Route;
}

const YOU: readonly Row[] = [
  { label: "Your profile", hint: "Your account details, and how Lamikraft One looks and behaves for you.", icon: "user", href: "/settings/profile" },
  { label: "Sign-in and security", hint: "Your password, two-step sign-in and the places you are signed in.", icon: "shield", href: "/settings/security" },
];

const WORKSPACE: readonly Row[] = [
  { label: "Workspace settings", hint: "Your team, the company and how the workspace behaves.", icon: "settings", href: "/settings" },
  { label: "Activity", hint: "What changed on the records you can open, newest first.", icon: "activity", href: "/activity" },
];

/**
 * More: who you are, then the handful of things that are about you rather than about the work.
 * The phone's fourth tab; on a larger screen it is the same short list in a reading column.
 */
export function MoreScreen() {
  const { bootstrap, permissionKeys } = useSession();
  const { user, company, membership } = bootstrap;
  const roleLine = membership.role_names.join(", ") || "Member";
  const canOpen = (row: Row) => {
    const route = matchRoute(String(row.href));
    return route !== null && canAccessRoute(route, permissionKeys);
  };
  const you = YOU.filter(canOpen);
  const workspace = WORKSPACE.filter(canOpen);

  return (
    <Page width="narrow">
      <header className="page-head rise">
        <div className="flex items-center gap-5">
          <Avatar name={user.display_name} size="xl" className="flex-none" />
          <div className="flex min-w-0 flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <p className="t-overline page-eyebrow min-w-0 truncate">{company.display_name}</p>
              {company.is_demo ? (
                <Badge tone="gold" dot size="sm">
                  Demo
                </Badge>
              ) : null}
            </div>
            <h1 className="t-display-md break-words">{user.display_name}</h1>
            <p className="t-body page-lead break-words">{roleLine}</p>
            {user.email ? <p className="t-body-sm break-all text-ink-3">{user.email}</p> : null}
          </div>
        </div>
      </header>

      {you.length > 0 ? <Group title="You" rows={you} index={1} /> : null}
      {workspace.length > 0 ? <Group title="Workspace" rows={workspace} index={2} /> : null}

      <Group title="This device" index={3}>
        <li className="flex flex-col gap-4 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
          <RowText icon="palette" label="Theme" hint="Light, dark, or whatever this device is set to." />
          <ThemeToggle className="self-start sm:self-auto" />
        </li>
        <RowLink row={{ label: "Sign out", hint: "Ends your session on this device only.", icon: "logOut", href: "/sign-out" }} />
      </Group>
    </Page>
  );
}

function Group({ title, rows, index, children }: { title: string; rows?: readonly Row[]; index: number; children?: ReactNode }) {
  const headingId = useId();
  return (
    <section className="rise flex flex-col gap-3" style={riseIndex(index) as CSSProperties} aria-labelledby={headingId}>
      <h2 id={headingId} className="t-overline px-1 text-ink-3">
        {title}
      </h2>
      <GlassPanel padding="none" className="overflow-hidden">
        <ul className="m-0 list-none divide-y divide-line p-0">
          {rows?.map((row) => <RowLink key={row.label} row={row} />)}
          {children}
        </ul>
      </GlassPanel>
    </section>
  );
}

function RowText({ icon, label, hint }: { icon: IconName; label: string; hint: string }) {
  return (
    <span className="flex min-w-0 items-center gap-4 sm:flex-1">
      <span className="grid size-10 flex-none place-items-center rounded-md bg-sand-soft text-ink" aria-hidden>
        <Icon name={icon} size={20} />
      </span>
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="t-h4 text-ink">{label}</span>
        <span className="t-body-sm text-ink-3">{hint}</span>
      </span>
    </span>
  );
}

function RowLink({ row }: { row: Row }) {
  return (
    <li>
      <Link href={row.href} className="flex min-h-16 items-center gap-4 px-5 py-4 no-underline transition-colors hover:bg-sand-soft">
        <RowText icon={row.icon} label={row.label} hint={row.hint} />
        <Icon name="chevronRight" size={18} className="flex-none text-ink-4" />
      </Link>
    </li>
  );
}
