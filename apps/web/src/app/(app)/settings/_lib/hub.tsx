"use client";

import { Link as RacLink } from "react-aria-components";
import { linkClasses } from "@/components/ui/styles";
import { useSession } from "@/lib/session/context";
import { SettingsPage } from "./ui";

interface Entry {
  href: string;
  title: string;
  body: string;
  /** null: every member; otherwise any of these keys */
  keys: readonly string[] | null;
}

const PERSONAL: readonly Entry[] = [
  { href: "/settings/security", title: "Security", body: "Password, two-step sign-in and where you are signed in.", keys: null },
  { href: "/settings/delegation", title: "Delegation", body: "Let a colleague work on your records while you are away.", keys: null },
  { href: "/settings/leave", title: "Leave", body: "Record time away and name who covers your work.", keys: null },
  { href: "/settings/access-requests", title: "Access requests", body: "Ask for a permission you need for a while.", keys: null },
];

const ADMIN: readonly Entry[] = [
  { href: "/settings/users", title: "Users", body: "Invite people, change roles, deactivate and reactivate.", keys: ["identity.user.read", "identity.user.manage"] },
  { href: "/settings/roles", title: "Roles", body: "System roles and custom roles with inheritance and deny.", keys: ["identity.role.read", "identity.role.manage"] },
  { href: "/settings/roles/simulate", title: "Role simulator", body: "What can someone do, and why not.", keys: ["identity.user.read", "identity.role.read", "identity.role.manage"] },
];

function Cards({ entries }: { entries: readonly Entry[] }) {
  return (
    <ul className="grid gap-3 md:grid-cols-2">
      {entries.map((e) => (
        <li key={e.href} className="rounded-xl border bg-surface p-4">
          <RacLink href={e.href} className={`${linkClasses} text-lg font-semibold`}>
            {e.title}
          </RacLink>
          <p className="text-sm text-ink-muted">{e.body}</p>
        </li>
      ))}
    </ul>
  );
}

/** Settings home: your own settings for everyone; administration only for people holding the keys. */
export function SettingsHub() {
  const { permissionKeys } = useSession();
  const admin = ADMIN.filter((e) => e.keys === null || e.keys.some((k) => permissionKeys.has(k)));
  return (
    <SettingsPage title="Settings">
      <section aria-labelledby="settings-personal" className="flex flex-col gap-3">
        <h2 id="settings-personal" className="text-lg font-semibold">
          You
        </h2>
        <Cards entries={PERSONAL} />
      </section>
      {admin.length ? (
        <section aria-labelledby="settings-admin" className="flex flex-col gap-3">
          <h2 id="settings-admin" className="text-lg font-semibold">
            Administration
          </h2>
          <Cards entries={admin} />
        </section>
      ) : null}
    </SettingsPage>
  );
}

export const HUB_ENTRIES = { PERSONAL, ADMIN };
