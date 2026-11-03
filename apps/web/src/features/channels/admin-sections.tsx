"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { StatusPill, type Tone } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { Dialog } from "@/components/ui/dialog";
import { LocalDateTime } from "@/components/ui/format";
import { KeyValueGrid } from "@/components/ui/key-value-grid";
import { SectionCard } from "@/components/ui/section-card";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { toast } from "@/components/ui/toast";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { channelsMessages } from "@/messages/channels";
import { fetchAttentionMessages, fetchTemplates, resolveOutbox, syncTemplates, verifyAccount, type Account, type Message, type Template } from "./api";

const m = channelsMessages.admin;

const STATE_TONE: Record<string, Tone> = { unknown: "warning", escalated: "warning", failed: "danger", blocked: "neutral" };
const TEMPLATE_TONE: Record<Template["status"], Tone> = { approved: "success", pending: "info", rejected: "danger", paused: "warning", disabled: "danger", unknown: "neutral" };

function useInvalidate() {
  const client = useQueryClient();
  return () => Promise.all(invalidationMap["channels.changed"].map((queryKey) => client.invalidateQueries({ queryKey })));
}

/** Status, the three checks and Run checks (``channels.account.manage``). */
export function AccountChecksCard({ account }: { account: Account }) {
  const invalidate = useInvalidate();
  const verify = useMutation({
    mutationFn: () => verifyAccount(),
    onSuccess: (result) => {
      toast.success(m.verified, { description: result.account.label_text });
      void invalidate();
    },
  });
  const checks = verify.data?.checks;
  const at = { graph_api: account.checks.graph_ok_at, handshake: account.checks.handshake_ok_at, signed_event: account.checks.signed_event_ok_at };
  const canVerify = account.capabilities.verify?.allowed ?? false;
  return (
    <SectionCard
      title={m.accountTitle}
      description={m.accountDescription}
      actions={
        <Button variant="secondary" size="sm" onPress={() => verify.mutate()} isPending={verify.isPending} pendingLabel={m.verifying}
          {...unavailableWhen(canVerify ? null : (account.capabilities.verify?.reason_code ?? "permission_denied"))}>
          {m.verify}
        </Button>
      }
    >
      <ul className="flex flex-col divide-y rounded-lg border px-3">
        {(Object.keys(at) as (keyof typeof at)[]).map((name) => {
          const detail = checks?.find((c) => c.name === name)?.detail;
          return (
            <li key={name} className="flex min-h-12 flex-wrap items-center justify-between gap-2 py-2">
              <span className="font-semibold text-ink">{m.checks[name]}</span>
              <span className="flex flex-col items-end text-sm">
                {at[name] ? (
                  <StatusPill tone="success">
                    {m.passed} <LocalDateTime value={at[name]} />
                  </StatusPill>
                ) : (
                  <StatusPill tone="neutral">{m.notYet}</StatusPill>
                )}
                {detail ? <span className="text-ink-muted">{detail}</span> : null}
              </span>
            </li>
          );
        })}
      </ul>
      <KeyValueGrid
        items={[
          { term: m.apiVersion, description: account.api_version, mono: true },
          { term: m.phone, description: account.display_phone ?? "—", mono: true },
          { term: m.liveOutbound, description: account.live_outbound ? m.liveOutboundOn : m.liveOutboundOff },
        ]}
      />
      {verify.isError ? <ErrorState error={verify.error} what={m.accountTitle.toLowerCase()} compact backToToday={false} /> : null}
    </SectionCard>
  );
}

function ResolveActions({ message }: { message: Message }) {
  const invalidate = useInvalidate();
  const [open, setOpen] = useState(false);
  const resolve = useMutation({
    mutationFn: (action: "resend" | "cancel") => resolveOutbox(message.outbox_id as string, action),
    onSuccess: (_result, action) => {
      setOpen(false);
      toast.success(action === "resend" ? m.resent : m.cancelled);
      void invalidate();
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : m.messagesTitle),
  });
  const resend = message.capabilities?.resend;
  const cancel = message.capabilities?.cancel;
  return (
    <div className="flex flex-wrap gap-2">
      <Button size="sm" variant="secondary" onPress={() => setOpen(true)} {...unavailableWhen(resend?.allowed ? null : (resend?.reason_code ?? "not_resendable"))}>
        {m.resend}
      </Button>
      <Button size="sm" variant="quiet" onPress={() => resolve.mutate("cancel")} isPending={resolve.isPending && resolve.variables === "cancel"}
        {...unavailableWhen(cancel?.allowed ? null : (cancel?.reason_code ?? "not_cancellable"))}>
        {m.cancel}
      </Button>
      <Dialog
        role="alertdialog"
        size="sm"
        title={m.resendTitle}
        isOpen={open}
        onOpenChange={setOpen}
        footer={(close) => (
          <>
            <Button variant="secondary" onPress={close}>
              {m.cancel}
            </Button>
            <Button variant="primary" onPress={() => resolve.mutate("resend")} isPending={resolve.isPending && resolve.variables === "resend"}>
              {m.resend}
            </Button>
          </>
        )}
      >
        <p className="text-ink">{m.resendBody}</p>
      </Dialog>
    </div>
  );
}

/** Unknown, failed, blocked and escalated messages with Resend (confirmed, a new message) and Close. */
export function AttentionMessagesCard() {
  const query = useQuery({ queryKey: queryKeys.channels.messages(), queryFn: ({ signal }) => fetchAttentionMessages(signal) });
  const c = m.columns;
  const columns: DataTableColumn<Message>[] = [
    { id: "created", header: c.created, mobile: "meta", cell: (row) => <LocalDateTime value={row.created_at} /> },
    { id: "message", header: c.message, isRowHeader: true, mobile: "title", cell: (row) => <span className="line-clamp-2">{row.body ?? `[${row.type}]`}</span> },
    { id: "state", header: c.state, mobile: "status", cell: (row) => <StatusPill tone={STATE_TONE[row.outbox_state ?? ""] ?? "neutral"}>{row.outbox_state ?? row.status}</StatusPill> },
    { id: "reason", header: c.reason, cell: (row) => <span className="font-mono text-xs">{row.blocked_reason ?? row.last_error ?? "—"}</span> },
    { id: "actions", header: c.actions, cell: (row) => (row.outbox_id ? <ResolveActions message={row} /> : null) },
  ];
  return (
    <SectionCard title={m.messagesTitle} description={m.messagesDescription}>
      {query.isPending ? (
        <Loading label={m.messagesWhat} rows={3} />
      ) : query.isError ? (
        <ErrorState error={query.error} what={m.messagesWhat} onRetry={() => void query.refetch()} compact />
      ) : (
        <DataTable caption={m.messagesTitle} hideCaption columns={columns} rows={query.data} rowId={(row) => row.id} empty={<EmptyState title={m.messagesEmpty} />} />
      )}
    </SectionCard>
  );
}

export function TemplatesCard() {
  const invalidate = useInvalidate();
  const query = useQuery({ queryKey: queryKeys.channels.templates(), queryFn: ({ signal }) => fetchTemplates(signal) });
  const sync = useMutation({
    mutationFn: () => syncTemplates(),
    onSuccess: () => {
      toast.success(m.synced);
      void invalidate();
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : m.templatesTitle),
  });
  const c = m.templateColumns;
  const columns: DataTableColumn<Template>[] = [
    { id: "name", header: c.name, isRowHeader: true, mobile: "title", cell: (row) => <span className="font-mono text-sm">{row.name}</span> },
    { id: "language", header: c.language, mobile: "key", cell: (row) => row.language },
    { id: "category", header: c.category, cell: (row) => row.category },
    { id: "status", header: c.status, mobile: "status", cell: (row) => <StatusPill tone={TEMPLATE_TONE[row.status]}>{row.status}</StatusPill> },
    { id: "synced", header: c.synced, mobile: "meta", cell: (row) => <LocalDateTime value={row.synced_at} /> },
  ];
  return (
    <SectionCard
      title={m.templatesTitle}
      description={m.templatesDescription}
      actions={
        <Button variant="secondary" size="sm" onPress={() => sync.mutate()} isPending={sync.isPending} pendingLabel={m.syncing}>
          {m.sync}
        </Button>
      }
    >
      {query.isPending ? (
        <Loading label={m.templatesWhat} rows={3} />
      ) : query.isError ? (
        <ErrorState error={query.error} what={m.templatesWhat} onRetry={() => void query.refetch()} compact />
      ) : (
        <DataTable caption={m.templatesTitle} hideCaption columns={columns} rows={query.data} rowId={(row) => row.id} empty={<EmptyState title={m.templatesEmpty} />} />
      )}
    </SectionCard>
  );
}
