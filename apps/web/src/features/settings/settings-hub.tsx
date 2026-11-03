"use client";

import { Link as RacLink } from "react-aria-components";
import { AreaNav } from "@/components/shell/area-nav";
import { DemoBadge } from "@/components/ui/badge";
import { ChevronRightIcon } from "@/components/ui/icons";
import { PageHeader } from "@/components/ui/page-header";
import { sectionLabelClasses } from "@/components/ui/styles";
import { canAccessRoute, contextRoutesFor } from "@/lib/routes";
import { useSession } from "@/lib/session/context";
import type { IntegrationMode, SessionBootstrap } from "@/lib/session/types";
import { settingsMessages as m } from "@/messages/settings";
import { ModeBadge } from "./mode-badge";

const HINTS: Record<string, string> = {
  "settings-profile": m.hub.profileHint,
  "settings-company": m.hub.companyHint,
  "settings-reference": m.hub.referenceHint,
  "settings-integrations": m.hub.integrationsHint,
  "settings-audit": m.hub.auditHint,
  "settings-whatsapp": m.hub.whatsappHint,
};

export const SETTINGS_NAV_LEADING = [{ id: "settings", label: "Overview", href: "/settings" }] as const;

export function SettingsAreaNav({ currentId }: { currentId?: string }) {
  return <AreaNav area="settings" label={m.hub.title} leading={SETTINGS_NAV_LEADING} currentId={currentId} />;
}

/** The modes to show on the workspace line: the typed `integration_modes`, else the `integrations` section. */
export function workspaceModes(bootstrap: SessionBootstrap): { key: string; label: string; mode: IntegrationMode }[] {
  const modes = bootstrap.integration_modes;
  if (modes) {
    return [
      { key: "ai", label: m.hub.modes.ai, mode: modes.ai },
      { key: "whatsapp", label: m.hub.modes.whatsapp, mode: modes.whatsapp },
      { key: "email", label: m.hub.modes.email, mode: modes.email === "smtp" ? "live" : "demo" },
    ];
  }
  return bootstrap.integrations.status === "ok" ? bootstrap.integrations.value : [];
}

const rowClasses = "flex min-h-14 items-center gap-3 border-b px-1 py-3 text-ink last:border-b-0 hover:bg-surface-sunken";

export function SettingsHub() {
  const { bootstrap, permissionKeys } = useSession();
  const sections = contextRoutesFor("settings").filter((route) => canAccessRoute(route, permissionKeys));
  const modes = workspaceModes(bootstrap);

  return (
    <div className="flex max-w-3xl flex-col gap-8">
      <PageHeader title={m.hub.title} intro={m.hub.intro} nav={<SettingsAreaNav />} />

      <section aria-labelledby="settings-workspace" className="flex flex-col gap-2">
        <h2 id="settings-workspace" className={sectionLabelClasses}>
          {m.hub.workspace}
        </h2>
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="font-semibold text-ink">{bootstrap.company.display_name}</span>
          {bootstrap.company.is_demo ? <DemoBadge /> : null}
        </p>
        {modes.length > 0 ? (
          <ul className="flex flex-wrap gap-x-5 gap-y-2 text-sm text-ink-muted">
            {modes.map((entry) => (
              <li key={entry.key} className="flex items-center gap-2">
                <span>{entry.label}</span>
                <ModeBadge mode={entry.mode} />
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <section aria-labelledby="settings-sections" className="flex flex-col gap-2">
        <h2 id="settings-sections" className={sectionLabelClasses}>
          {m.hub.sections}
        </h2>
        <ul className="rounded-lg border bg-surface px-3">
          {sections.map((route) => (
            <li key={route.id}>
              <RacLink href={route.path} className={rowClasses}>
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="font-semibold">{route.label}</span>
                  {HINTS[route.id] ? <span className="text-sm text-ink-muted">{HINTS[route.id]}</span> : null}
                </span>
                <ChevronRightIcon size={18} className="shrink-0 text-ink-muted" />
              </RacLink>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
