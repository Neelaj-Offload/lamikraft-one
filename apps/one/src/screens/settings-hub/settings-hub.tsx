"use client";

import type { Route } from "next";
import Link from "next/link";
import { useId, type CSSProperties } from "react";
import { canAccessRoute, contextRoutesFor, type RouteDefinition } from "@/lib/routes";
import { useSession } from "@/lib/session/context";
import type { IntegrationMode, SessionBootstrap } from "@/lib/session/types";
import { riseIndex } from "~/lib/motion";
import { Page, PageHeader } from "~/shell/page";
import { Badge, GlassPanel, Icon, type IconName } from "~/ui";
import { ModeBadge } from "../settings-ai/mode-badge";

type GroupId = "you" | "people" | "company" | "ai" | "other";

interface Tile {
  group: GroupId;
  label: string;
  icon: IconName;
  line: string;
}

const GROUPS: readonly { id: GroupId; title: string }[] = [
  { id: "you", title: "You" },
  { id: "people", title: "People and access" },
  { id: "company", title: "Company and data" },
  { id: "ai", title: "AI and integrations" },
  { id: "other", title: "More" },
];

/** Words and a place for every settings screen in the route manifest, by route id. */
const TILES: Record<string, Tile> = {
  "settings-profile": { group: "you", label: "Your profile", icon: "user", line: "Your account details, and how Lamikraft One looks and behaves for you." },
  "settings-security": { group: "you", label: "Sign-in and security", icon: "shield", line: "Your password, two-step sign-in and the places you are signed in." },
  "settings-delegation": { group: "you", label: "Delegation", icon: "share", line: "Let a colleague work on your records while you are away." },
  "settings-leave": { group: "you", label: "Leave", icon: "calendar", line: "Record time away and name who covers your work." },
  "settings-access-requests": { group: "you", label: "Access requests", icon: "key", line: "Ask for a permission you need for a while." },

  "settings-users": { group: "people", label: "Users", icon: "userCog", line: "Invite people, change their roles, and switch access off or back on." },
  "settings-roles": { group: "people", label: "Roles", icon: "badgeCheck", line: "What each role may see and do, including roles you define yourself." },
  "settings-audit": { group: "people", label: "Audit log", icon: "history", line: "Who did what, when, and whether it was allowed." },

  "settings-company": { group: "company", label: "Company", icon: "building", line: "The name, bank accounts, terms and brands printed on your documents." },
  "settings-quotes": { group: "company", label: "Quotation settings", icon: "fileText", line: "Defaults for new quotations: validity, revisions and who owns a duplicate." },
  "settings-fx-rates": { group: "company", label: "Exchange rates", icon: "banknote", line: "Dated rates, approved by a second person, and how amounts convert." },
  "settings-customer-types": { group: "company", label: "Customer types and lead sources", icon: "tag", line: "The kinds of customer you sell to, and the trade shows and channels your leads come from." },
  "settings-reference": { group: "company", label: "Reference data", icon: "globe", line: "Currencies, units of measure and your work calendar." },
  "settings-lookups": { group: "company", label: "Lookup reference", icon: "list", line: "Reference lists carried over from the old portal, to browse and export." },
  "settings-imports": { group: "company", label: "Imports", icon: "upload", line: "Bring in products, prices, packaging and media from spreadsheets, reviewed before anything is saved." },
  "settings-migration": { group: "company", label: "Migration", icon: "database", line: "Dry runs over the old portal's export: what reconciles, what is held back, and likely customer matches." },
  "settings-backups": { group: "company", label: "Backups", icon: "archive", line: "When the database was last backed up, and whether its restore rehearsal passed." },

  "settings-ai": { group: "ai", label: "AI", icon: "sparkles", line: "Whether the assistant is healthy, what it costs to run and which models it uses." },
  "settings-integrations": { group: "ai", label: "Integrations", icon: "link", line: "Which connections run live and which are simulated." },
  "settings-whatsapp": { group: "ai", label: "WhatsApp", icon: "phone", line: "Link your phone to use the assistant on WhatsApp, and choose which messages you get." },
};

/** A settings screen added to the manifest later still shows, under "More", with its manifest label. */
function tileFor(route: RouteDefinition): Tile {
  return TILES[route.id] ?? { group: "other", label: route.label, icon: "settings", line: "" };
}

/** The modes for the workspace line: the typed `integration_modes`, else the session's `integrations` section. */
function workspaceModes(bootstrap: SessionBootstrap): { key: string; label: string; mode: IntegrationMode }[] {
  const modes = bootstrap.integration_modes;
  if (modes) {
    return [
      { key: "ai", label: "Assistant", mode: modes.ai },
      { key: "whatsapp", label: "WhatsApp", mode: modes.whatsapp },
      { key: "email", label: "Email", mode: modes.email === "smtp" ? "live" : "demo" },
    ];
  }
  return bootstrap.integrations.status === "ok" ? bootstrap.integrations.value : [];
}

/**
 * Settings: every settings screen this person may open, as one flat set of tiles under plain
 * headings. The same permission check as the menu (`canAccessRoute` over the route manifest), so
 * nothing here leads to a refusal.
 */
export function SettingsHub() {
  const { bootstrap, permissionKeys } = useSession();
  const routes = contextRoutesFor("settings").filter((route) => canAccessRoute(route, permissionKeys));
  const modes = workspaceModes(bootstrap);
  const groups = GROUPS.map((group) => ({ ...group, routes: routes.filter((route) => tileFor(route).group === group.id) })).filter(
    (group) => group.routes.length > 0,
  );

  return (
    <Page>
      <PageHeader
        display
        eyebrow="Settings"
        title={
          <>
            How Lamikraft One works for <em>you</em>
          </>
        }
        lead="Your own account first, then the people, company details and connections you look after."
      />

      <GlassPanel as="section" padding="md" className="rise flex flex-col gap-4 md:flex-row md:items-center md:justify-between" style={riseIndex(1) as CSSProperties} aria-label="Workspace">
        <div className="flex min-w-0 items-center gap-4">
          <span className="grid size-10 flex-none place-items-center rounded-md bg-sand-soft text-ink" aria-hidden="true">
            <Icon name="building" size={20} />
          </span>
          <div className="flex min-w-0 flex-col gap-0.5">
            <p className="t-caption text-ink-3">Workspace</p>
            <div className="flex flex-wrap items-center gap-2">
              <p className="t-h4 min-w-0 break-words text-ink">{bootstrap.company.display_name}</p>
              {bootstrap.company.is_demo ? (
                <Badge tone="gold" dot size="sm">
                  Demo
                </Badge>
              ) : null}
            </div>
          </div>
        </div>
        {modes.length > 0 ? (
          <ul className="m-0 flex list-none flex-wrap gap-x-6 gap-y-2 p-0" aria-label="How each connection runs">
            {modes.map((entry) => (
              <li key={entry.key} className="flex items-center gap-2">
                <span className="t-body-sm text-ink-2">{entry.label}</span>
                <ModeBadge mode={entry.mode} size="sm" />
              </li>
            ))}
          </ul>
        ) : null}
      </GlassPanel>

      {groups.map((group, index) => (
        <TileGroup key={group.id} title={group.title} routes={group.routes} index={index + 2} />
      ))}
    </Page>
  );
}

function TileGroup({ title, routes, index }: { title: string; routes: readonly RouteDefinition[]; index: number }) {
  const headingId = useId();
  return (
    <section className="rise flex flex-col gap-3" style={riseIndex(index) as CSSProperties} aria-labelledby={headingId}>
      <h2 id={headingId} className="t-h3">
        {title}
      </h2>
      <ul className="tiles m-0 list-none p-0" data-min="lg">
        {routes.map((route) => {
          const tile = tileFor(route);
          return (
            <GlassPanel as="li" key={route.id} variant="outline" interactive className="relative flex items-start gap-4">
              <span className="mt-0.5 flex-none text-ink-3" aria-hidden="true">
                <Icon name={tile.icon} size={20} />
              </span>
              <span className="flex min-w-0 flex-col gap-1">
                <Link href={route.path as Route} className="stretched t-h4 text-ink no-underline">
                  {tile.label}
                </Link>
                {tile.line ? <span className="t-body-sm text-ink-3">{tile.line}</span> : null}
              </span>
            </GlassPanel>
          );
        })}
      </ul>
    </section>
  );
}
