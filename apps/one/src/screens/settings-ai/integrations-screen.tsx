"use client";

import type { CSSProperties } from "react";
import type { Integration, IntegrationState } from "@/features/settings/types";
import { useSession } from "@/lib/session/context";
import { useIntegrations } from "~/data/settings-ai";
import { riseIndex } from "~/lib/motion";
import { Page, PageHeader, PageSection } from "~/shell/page";
import { QueryView } from "~/shell/states";
import { Badge, Banner, DateText, EmptyState, GlassPanel, Icon, KeyValue, Skeleton, type IconName, type Tone } from "~/ui";
import { ModeBadge } from "./mode-badge";

const STATE: Record<IntegrationState, { label: string; tone: Tone }> = {
  connected: { label: "Connected", tone: "leaf" },
  not_connected: { label: "Not connected", tone: "neutral" },
  error: { label: "Error", tone: "ember" },
};

/** A glyph per kind of connection, from the integration's key; a plain link for anything new. */
function iconFor(key: string): IconName {
  if (key.startsWith("ai.")) return "sparkles";
  if (key.startsWith("channels.")) return "phone";
  if (key.startsWith("voice")) return "mic";
  if (key.startsWith("vision")) return "camera";
  if (key === "email") return "mail";
  if (key === "storage") return "database";
  if (key === "accounting") return "calculator";
  if (key === "e_invoice") return "receipt";
  return "link";
}

function IntegrationTile({ integration, index }: { integration: Integration; index: number }) {
  const state = STATE[integration.state];
  // In demo mode the server's own label is just "Demo"; the state word says what that means in practice.
  const stateText = integration.mode === "demo" ? state.label : integration.label_text;
  return (
    <GlassPanel as="li" padding="md" className="rise-plain flex flex-col gap-4" style={riseIndex(index) as CSSProperties}>
      <div className="flex items-start gap-3">
        <span className="grid size-10 flex-none place-items-center rounded-md bg-sand-soft text-ink" aria-hidden="true">
          <Icon name={iconFor(integration.key)} size={20} />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <h3 className="t-h4 break-words">{integration.label}</h3>
          <div className="flex flex-wrap items-center gap-2">
            <ModeBadge mode={integration.mode} size="sm" />
            <Badge size="sm" tone={state.tone} dot={integration.state !== "not_connected"}>
              {stateText}
            </Badge>
          </div>
        </div>
      </div>
      <KeyValue
        rows
        items={[
          { label: "Verified", value: integration.verified_at ? <DateText value={integration.verified_at} style="dayTime" /> : <span className="text-ink-3">Never</span> },
          { label: "Last checked", value: integration.last_checked_at ? <DateText value={integration.last_checked_at} style="dayTime" /> : <span className="text-ink-3">Never</span> },
          {
            label: "Last error",
            value: integration.last_error_code ? <span className="select-all break-all">{integration.last_error_code}</span> : <span className="text-ink-3">None</span>,
            mono: Boolean(integration.last_error_code),
          },
        ]}
      />
    </GlassPanel>
  );
}

function summaryLine(integrations: readonly Integration[]): string {
  const live = integrations.filter((integration) => integration.mode === "live").length;
  const demo = integrations.length - live;
  const failing = integrations.filter((integration) => integration.state === "error").length;
  const parts = [`${live === 0 ? "None" : live} live`, `${demo} simulated`];
  if (failing > 0) parts.push(`${failing} reporting an error`);
  return `${parts.join(", ")}.`;
}

/** With `system.integration.read`: every connection with its mode, state and verification times. */
function IntegrationTiles() {
  const query = useIntegrations(true);
  return (
    <PageSection title="Connections" description={query.data && query.data.length > 0 ? summaryLine(query.data) : undefined} index={2}>
      <QueryView
        query={query}
        what="Integrations"
        loading={
          <div className="tiles" data-min="lg" role="status" aria-label="Loading integrations">
            {[0, 1, 2].map((tile) => (
              <GlassPanel key={tile} padding="md" className="flex flex-col gap-4">
                <Skeleton width="50%" height={18} />
                <Skeleton width="35%" />
                <Skeleton />
                <Skeleton width="80%" />
              </GlassPanel>
            ))}
          </div>
        }
        isEmpty={(data) => data.length === 0}
        empty={
          <GlassPanel padding="lg">
            <EmptyState icon="link" title="No connections are registered" text="This workspace has nothing to connect to yet. Connections appear here when the server registers them." />
          </GlassPanel>
        }
      >
        {(data) => (
          <ul className="tiles m-0 list-none p-0" data-min="lg">
            {data.map((integration, index) => (
              <IntegrationTile key={integration.key} integration={integration} index={index} />
            ))}
          </ul>
        )}
      </QueryView>
    </PageSection>
  );
}

/** Without `system.integration.read`: only the modes the session reported, no verification details. */
function IntegrationSummary() {
  const { bootstrap } = useSession();
  if (bootstrap.integrations.status !== "ok") {
    return (
      <GlassPanel padding="lg">
        <EmptyState icon="link" title="Connection status is not available right now" text="The server did not report it with your session. Reload the page in a little while." />
      </GlassPanel>
    );
  }
  const integrations = bootstrap.integrations.value;
  if (integrations.length === 0) {
    return (
      <GlassPanel padding="lg">
        <EmptyState icon="link" title="No connections are registered" text="This workspace has nothing to connect to yet." />
      </GlassPanel>
    );
  }
  return (
    <PageSection title="Connections" description="How each one runs, as reported with your session. Workspace admins also see when each was last verified." index={2}>
      <GlassPanel padding="none" className="overflow-hidden">
        <ul className="m-0 list-none divide-y divide-line p-0">
          {integrations.map((integration) => (
            <li key={integration.key} className="flex min-h-14 items-center justify-between gap-4 px-5 py-3">
              <span className="flex min-w-0 items-center gap-3">
                <span className="flex-none text-ink-3" aria-hidden="true">
                  <Icon name={iconFor(integration.key)} size={18} />
                </span>
                <span className="t-label break-words text-ink">{integration.label}</span>
              </span>
              <ModeBadge mode={integration.mode} size="sm" />
            </li>
          ))}
        </ul>
      </GlassPanel>
    </PageSection>
  );
}

/** Integrations: which connections to the outside world run live, and which are simulated. Read-only. */
export function IntegrationsScreen() {
  const { permissionKeys } = useSession();
  return (
    <Page>
      <PageHeader
        breadcrumb={[{ label: "Settings", href: "/settings" }, { label: "Integrations" }]}
        title="Integrations"
        lead="Which connections to the outside world run live, and which are simulated."
      />
      <Banner tone="cobalt" title="Demo connections are simulated.">
        Messages, emails and syncs marked Demo stay inside Lamikraft One: nothing is sent out. Live credentials are set on the server, never on this
        screen, and a connection shows Live only after the server has verified it.
      </Banner>
      {permissionKeys.has("system.integration.read") ? <IntegrationTiles /> : <IntegrationSummary />}
    </Page>
  );
}
