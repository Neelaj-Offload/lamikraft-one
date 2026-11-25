"use client";

import type { Route } from "next";
import { useState } from "react";
import type { Account, Enrolment } from "@/features/channels/api";
import { useSession } from "@/lib/session/context";
import { useAttentionMessages, useWhatsAppAccount } from "~/data/settings-ai";
import { Page, PageHeader, Split } from "~/shell/page";
import { LoadingBlock, NotPermitted, QueryView } from "~/shell/states";
import { Badge, Banner, GlassPanel, Tabs, type Tone } from "~/ui";
import { AttentionView, ConnectionView, TemplatesView } from "./whatsapp-admin";
import { LinkedNumbers, LinkPanel } from "./whatsapp-phone";
import { SIMULATOR_ID, Simulator } from "./whatsapp-simulator";
import type { WhatsAppView } from "./views";

const CRUMBS = [{ label: "Settings", href: "/settings" as Route }, { label: "WhatsApp" }];

const STATUS_TONE: Record<Account["status"], Tone> = {
  verified: "leaf",
  configured_unverified: "neutral",
  not_configured: "amber",
  error: "ember",
  disabled: "neutral",
};

/** The honest status beside the title: "Demo" until live mode has passed every check. */
function AccountBadge({ account }: { account: Account }) {
  if (account.mode === "demo") return <Badge outline>Demo</Badge>;
  return (
    <Badge tone={STATUS_TONE[account.status]} dot={account.status === "verified"}>
      {account.label_text}
    </Badge>
  );
}

function AccountNotes({ account }: { account: Account }) {
  return (
    <>
      {account.mode === "demo" ? (
        <Banner tone="cobalt" title="Demo: not connected to WhatsApp.">
          Messages are simulated inside Lamikraft One. Nothing is sent to WhatsApp, and no phone is needed.
        </Banner>
      ) : null}
      {account.missing_settings.length > 0 ? (
        <Banner tone="amber" title="Live mode is on, but the server is missing some settings.">
          Set these on the server, then run the connection checks: <span className="t-code-sm lk-mono select-all">{account.missing_settings.join(", ")}</span>
        </Banner>
      ) : null}
    </>
  );
}

/** Link a phone, choose what it receives, and in demo mode try it in the simulator. */
function PhoneView({ account }: { account: Account }) {
  const [enrolment, setEnrolment] = useState<Enrolment | null>(null);
  const [draft, setDraft] = useState("");
  const demo = account.mode === "demo";

  const useInSimulator = (text: string) => {
    setDraft(text);
    document.getElementById(SIMULATOR_ID)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };

  const panels = (
    <>
      <LinkPanel account={account} enrolment={enrolment} onEnrolment={setEnrolment} onUseInSimulator={demo ? useInSimulator : undefined} />
      <LinkedNumbers />
    </>
  );

  if (!demo) return <div className="grid items-start gap-5 lg:grid-cols-2">{panels}</div>;
  return <Split wideAside main={panels} aside={<Simulator draft={draft} onDraftChange={setDraft} />} />;
}

/**
 * Settings, WhatsApp. Everyone who may use the assistant links their own phone here; people who
 * look after the company number also get its connection checks, the messages that got stuck and
 * the templates, each as its own view.
 */
export function WhatsAppScreen({ view }: { view: WhatsAppView }) {
  const { permissionKeys } = useSession();
  const account = useWhatsAppAccount();
  const canUseAssistant = permissionKeys.has("agents.assistant.use");
  const canManageAccount = permissionKeys.has("channels.account.manage");
  const canManageOutbox = permissionKeys.has("channels.outbox.manage");
  const attention = useAttentionMessages(canManageOutbox);

  const views: { id: WhatsAppView; label: string; count?: number }[] = [
    ...(canUseAssistant ? [{ id: "phone" as const, label: "Your phone" }] : []),
    ...(canManageAccount ? [{ id: "connection" as const, label: "Connection" }] : []),
    ...(canManageOutbox ? [{ id: "messages" as const, label: "Needs attention", count: attention.data?.length || undefined }] : []),
    ...(canManageAccount ? [{ id: "templates" as const, label: "Templates" }] : []),
  ];
  const fallback = views[0]?.id;
  const current = views.some((item) => item.id === view) ? view : fallback;
  const hrefFor = (id: WhatsAppView) => (id === fallback ? "/settings/whatsapp" : `/settings/whatsapp?view=${id}`) as Route;

  return (
    <Page>
      <PageHeader
        breadcrumb={CRUMBS}
        title="WhatsApp"
        lead="Use the assistant from WhatsApp with the same permissions you have here. Sensitive decisions always open on the web."
        meta={account.data ? <AccountBadge account={account.data} /> : null}
      />
      <QueryView query={account} what="WhatsApp settings" loading={<LoadingBlock lines={5} label="Loading WhatsApp settings" />}>
        {(data) => (
          <>
            <AccountNotes account={data} />
            {current === undefined ? (
              <GlassPanel padding="lg">
                <NotPermitted what="Using the assistant on WhatsApp" icon="phone" />
              </GlassPanel>
            ) : (
              <>
                {views.length > 1 ? (
                  <Tabs label="WhatsApp settings" selectedKey={current} tabs={views.map((item) => ({ id: item.id, label: item.label, count: item.count, href: hrefFor(item.id) }))} />
                ) : null}
                {current === "phone" ? <PhoneView account={data} /> : null}
                {current === "connection" ? <ConnectionView account={data} /> : null}
                {current === "messages" ? <AttentionView /> : null}
                {current === "templates" ? <TemplatesView /> : null}
              </>
            )}
          </>
        )}
      </QueryView>
    </Page>
  );
}
