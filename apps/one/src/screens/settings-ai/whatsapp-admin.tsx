"use client";

import { useState } from "react";
import type { Account, Message, Template, VerifyResult } from "@/features/channels/api";
import { useAttentionMessages, useResolveOutbox, useSyncTemplates, useTemplates, useVerifyWhatsApp } from "~/data/settings-ai";
import { PageSection } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { Badge, Button, ConfirmDialog, Dash, DataTable, DateText, EmptyState, GlassPanel, Icon, KeyValue, type Column, type Tone } from "~/ui";

// ---- connection ----

type CheckName = VerifyResult["checks"][number]["name"];

const CHECKS: readonly { name: CheckName; label: string; line: string; at: (account: Account) => string | null | undefined }[] = [
  { name: "graph_api", label: "Graph API", line: "WhatsApp's API accepts the account's credentials.", at: (account) => account.checks.graph_ok_at },
  { name: "handshake", label: "Webhook handshake", line: "WhatsApp reached our webhook and it answered correctly.", at: (account) => account.checks.handshake_ok_at },
  { name: "signed_event", label: "Signed event", line: "A real event arrived with a valid signature.", at: (account) => account.checks.signed_event_ok_at },
];

/**
 * The account behind the company number and the three checks it must pass. WhatsApp reads as
 * connected only after all three have passed; running them again records the latest result.
 */
export function ConnectionView({ account }: { account: Account }) {
  const verify = useVerifyWhatsApp();
  const results = verify.data?.checks;
  const canVerify = account.capabilities.verify?.allowed === true;

  return (
    <PageSection
      title="Connection checks"
      description="WhatsApp shows as connected only after the Graph API check, the webhook handshake and a signed event have all passed."
      action={
        canVerify ? (
          <Button variant="inverse" iconLeft="refresh" loading={verify.isPending} onPress={() => verify.mutate()}>
            Run checks
          </Button>
        ) : null
      }
      index={1}
    >
      {verify.isError ? <ErrorBlock error={verify.error} what="The connection checks" onRetry={() => verify.mutate()} /> : null}
      <GlassPanel padding="none" className="overflow-hidden">
        <ul className="m-0 list-none divide-y divide-line p-0">
          {CHECKS.map((check) => {
            const passedAt = check.at(account);
            const detail = results?.find((result) => result.name === check.name)?.detail;
            return (
              <li key={check.name} className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2 px-5 py-4">
                <span className="flex min-w-0 items-start gap-3">
                  <span className={passedAt ? "mt-0.5 flex-none text-leaf-text" : "mt-0.5 flex-none text-ink-3"} aria-hidden="true">
                    <Icon name={passedAt ? "checkCircle" : "circleDot"} size={18} />
                  </span>
                  <span className="flex min-w-0 flex-col gap-0.5">
                    <span className="t-label text-ink">{check.label}</span>
                    <span className="t-body-sm text-ink-3">{detail ?? check.line}</span>
                  </span>
                </span>
                {passedAt ? (
                  <Badge size="sm" tone="leaf">
                    Passed <DateText value={passedAt} style="dayTime" />
                  </Badge>
                ) : (
                  <Badge size="sm">Not yet</Badge>
                )}
              </li>
            );
          })}
        </ul>
      </GlassPanel>
      <GlassPanel variant="outline" padding="md">
        <KeyValue
          rows
          items={[
            { label: "Graph API version", value: account.api_version, mono: true },
            { label: "Display number", value: account.display_phone ?? <Dash />, mono: account.display_phone !== null },
            { label: "Live sending", value: account.live_outbound ? "On: replies go to real phones" : "Off: nothing is sent to real phones" },
            ...(account.verified_at ? [{ label: "Verified", value: <DateText value={account.verified_at} style="dayTime" /> }] : []),
            ...(account.last_error ? [{ label: "Last error", value: <span className="select-all break-all">{account.last_error}</span>, mono: true }] : []),
          ]}
        />
      </GlassPanel>
    </PageSection>
  );
}

// ---- messages needing attention ----

const OUTBOX_STATE: Record<string, { label: string; tone: Tone }> = {
  pending: { label: "Waiting", tone: "neutral" },
  sending: { label: "Sending", tone: "neutral" },
  accepted: { label: "Accepted", tone: "leaf" },
  unknown: { label: "Outcome unknown", tone: "amber" },
  failed: { label: "Failed", tone: "ember" },
  blocked: { label: "Blocked", tone: "neutral" },
  cancelled: { label: "Closed", tone: "neutral" },
  escalated: { label: "Escalated", tone: "amber" },
};

function ResolveActions({ message }: { message: Message }) {
  const resolve = useResolveOutbox();
  const [confirming, setConfirming] = useState(false);
  const outboxId = message.outbox_id;
  if (!outboxId) return <Dash />;
  const canResend = message.capabilities?.resend?.allowed === true;
  const canClose = message.capabilities?.cancel?.allowed === true;
  if (!canResend && !canClose) return <Dash />;

  return (
    <div className="flex flex-wrap gap-2">
      {canResend ? (
        <Button size="sm" variant="secondary" isDisabled={resolve.isPending} onPress={() => setConfirming(true)}>
          Resend as new
        </Button>
      ) : null}
      {canClose ? (
        <Button
          size="sm"
          variant="ghost"
          loading={resolve.isPending && resolve.variables?.action === "cancel"}
          isDisabled={resolve.isPending}
          onPress={() => resolve.mutate({ outboxId, action: "cancel" })}
        >
          Close
        </Button>
      ) : null}
      <ConfirmDialog
        isOpen={confirming}
        onOpenChange={setConfirming}
        title="Send this as a new message?"
        description="The first one may already have arrived. A new message goes out with its own idempotency key, and the old one is closed."
        confirmLabel="Resend as new message"
        cancelLabel="Keep waiting"
        onConfirm={async () => {
          await resolve.mutateAsync({ outboxId, action: "resend" });
        }}
      />
    </div>
  );
}

const messageColumns: Column<Message>[] = [
  {
    key: "message",
    header: "Message",
    primary: true,
    cell: (row) => <span className="line-clamp-2 break-words text-ink">{row.body ?? <span className="text-ink-3">[{row.type}]</span>}</span>,
  },
  { key: "created", header: "Created", cell: (row) => <DateText value={row.created_at} style="dayTime" /> },
  {
    key: "state",
    header: "State",
    cell: (row) => {
      const look = OUTBOX_STATE[row.outbox_state ?? ""] ?? { label: row.outbox_state ?? row.status, tone: "neutral" as const };
      return (
        <Badge size="sm" tone={look.tone}>
          {look.label}
        </Badge>
      );
    },
  },
  {
    key: "reason",
    header: "Reason",
    cell: (row) => {
      const reason = row.blocked_reason ?? row.last_error;
      return reason ? <span className="t-code-sm lk-mono break-all">{reason}</span> : <Dash />;
    },
  },
  { key: "actions", header: "Actions", mobileLabel: "Actions", cell: (row) => <ResolveActions message={row} /> },
];

/** Unknown, failed, blocked and escalated messages. An unknown outcome is never resent on its own. */
export function AttentionView() {
  const query = useAttentionMessages(true);
  return (
    <PageSection
      title="Messages needing attention"
      description="Unknown, failed, blocked and escalated messages. A message whose outcome is unknown is never resent automatically."
      index={1}
    >
      {query.isError ? (
        <ErrorBlock error={query.error} what="Messages needing attention" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none">
          <DataTable
            label="Messages needing attention"
            columns={messageColumns}
            rows={query.data ?? []}
            rowKey={(row) => row.id}
            loading={query.isPending}
            skeletonRows={3}
            empty={<EmptyState compact icon="checkCircle" title="Nothing needs attention" text="Every message reached WhatsApp or was closed. Stuck ones appear here." />}
          />
        </GlassPanel>
      )}
    </PageSection>
  );
}

// ---- templates ----

const TEMPLATE_STATE: Record<Template["status"], { label: string; tone: Tone }> = {
  approved: { label: "Approved", tone: "leaf" },
  pending: { label: "In review", tone: "cobalt" },
  rejected: { label: "Rejected", tone: "ember" },
  paused: { label: "Paused", tone: "amber" },
  disabled: { label: "Disabled", tone: "ember" },
  unknown: { label: "Unknown", tone: "neutral" },
};

const templateColumns: Column<Template>[] = [
  { key: "name", header: "Name", primary: true, cell: (row) => <span className="t-code-sm lk-mono break-all text-ink">{row.name}</span> },
  { key: "language", header: "Language", cell: (row) => <span className="lk-mono">{row.language}</span> },
  { key: "category", header: "Category", cell: (row) => row.category },
  {
    key: "status",
    header: "Status",
    cell: (row) => (
      <Badge size="sm" tone={TEMPLATE_STATE[row.status].tone}>
        {TEMPLATE_STATE[row.status].label}
      </Badge>
    ),
  },
  { key: "synced", header: "Synced", cell: (row) => (row.synced_at ? <DateText value={row.synced_at} style="dayTime" /> : <Dash />) },
];

/** The message templates WhatsApp holds for the company number, synced on request. */
export function TemplatesView() {
  const query = useTemplates(true);
  const sync = useSyncTemplates();
  return (
    <PageSection
      title="Templates"
      description="Outside WhatsApp's 24-hour reply window, only approved templates can be sent."
      action={
        <Button variant="inverse" iconLeft="refresh" loading={sync.isPending} onPress={() => sync.mutate()}>
          Sync templates
        </Button>
      }
      index={1}
    >
      {query.isError ? (
        <ErrorBlock error={query.error} what="Templates" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none">
          <DataTable
            label="Templates"
            columns={templateColumns}
            rows={query.data ?? []}
            rowKey={(row) => row.id}
            loading={query.isPending}
            skeletonRows={3}
            empty={<EmptyState compact icon="fileText" title="No templates synced yet" text="Sync templates to fetch the list WhatsApp holds for the company number." />}
          />
        </GlassPanel>
      )}
    </PageSection>
  );
}
