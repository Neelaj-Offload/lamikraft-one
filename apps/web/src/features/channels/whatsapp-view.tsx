"use client";

import { useQuery } from "@tanstack/react-query";
import { NotConnectedBadge, StatusPill, type Tone } from "@/components/ui/badge";
import { InfoIcon } from "@/components/ui/icons";
import { PageHeader } from "@/components/ui/page-header";
import { ErrorState, Loading, StateView } from "@/components/ui/states";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { channelsMessages } from "@/messages/channels";
import { settingsMessages } from "@/messages/settings";
import { SettingsAreaNav } from "@/features/settings/settings-hub";
import { AccountChecksCard, AttentionMessagesCard, TemplatesCard } from "./admin-sections";
import { fetchAccount, type Account } from "./api";
import { IdentitiesCard, LinkCard } from "./link-card";
import { Simulator } from "./simulator";

const m = channelsMessages;

const STATUS_TONE: Record<Account["status"], Tone> = {
  verified: "success",
  configured_unverified: "neutral",
  not_configured: "warning",
  error: "danger",
  disabled: "neutral",
};

/** The honest status line: "WhatsApp: Demo — not connected" until live mode passes every check. */
export function AccountStatus({ account }: { account: Account }) {
  return (
    <div className="flex flex-col gap-2">
      <p className="flex flex-wrap items-center gap-2 text-ink">
        <span className="font-semibold">{m.status.label}:</span>
        {account.mode === "demo" ? (
          <NotConnectedBadge label={account.label_text} />
        ) : (
          <StatusPill tone={STATUS_TONE[account.status]}>{account.label_text}</StatusPill>
        )}
      </p>
      {account.mode === "demo" ? <p className="text-sm text-ink-muted">{m.status.demoNote}</p> : null}
      {account.missing_settings.length > 0 ? (
        <p className="text-sm text-warning-text">
          {m.status.notConfiguredNote} <span className="font-mono">{account.missing_settings.join(", ")}</span>
        </p>
      ) : null}
    </div>
  );
}

export function WhatsAppView() {
  const { permissionKeys } = useSession();
  const account = useQuery({ queryKey: queryKeys.channels.account(), queryFn: ({ signal }) => fetchAccount(signal) });
  const canUseAssistant = permissionKeys.has("agents.assistant.use");
  const canManageAccount = permissionKeys.has("channels.account.manage");
  const canManageOutbox = permissionKeys.has("channels.outbox.manage");
  return (
    <div className="flex max-w-5xl flex-col gap-6">
      <PageHeader title={m.title} intro={m.intro} eyebrow={settingsMessages.hub.title} nav={<SettingsAreaNav currentId="settings-whatsapp" />} />
      {account.isPending ? (
        <Loading label={m.what} rows={4} />
      ) : account.isError ? (
        <ErrorState error={account.error} what={m.what} onRetry={() => void account.refetch()} />
      ) : (
        <>
          <AccountStatus account={account.data} />
          {canUseAssistant ? (
            <>
              <LinkCard account={account.data} />
              <IdentitiesCard />
              {account.data.mode === "demo" ? <Simulator /> : null}
            </>
          ) : (
            <StateView icon={<InfoIcon />} title={m.link.title} compact>
              <p>{m.intro}</p>
            </StateView>
          )}
          {canManageAccount ? <AccountChecksCard account={account.data} /> : null}
          {canManageOutbox ? <AttentionMessagesCard /> : null}
          {canManageAccount ? <TemplatesCard /> : null}
        </>
      )}
    </div>
  );
}
