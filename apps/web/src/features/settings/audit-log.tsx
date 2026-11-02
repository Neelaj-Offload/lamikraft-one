"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Form } from "react-aria-components";
import { StatusPill, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable, KeysetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { DatePicker } from "@/components/ui/date-picker";
import { LocalDateTime } from "@/components/ui/format";
import { PageHeader } from "@/components/ui/page-header";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading, PermissionDenied } from "@/components/ui/states";
import { TextField } from "@/components/ui/text-field";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { settingsMessages } from "@/messages/settings";
import { auditSearch, fetchAuditEntries } from "./api";
import { auditListHref, auditQueryFrom, type AuditListState } from "./list-state";
import { SettingsAreaNav } from "./settings-hub";
import { AUDIT_OUTCOMES, type AuditEntry, type AuditOutcome } from "./types";

const m = settingsMessages.audit;

export const OUTCOME_TONE: Record<string, Tone> = { success: "success", denied: "warning", failed: "danger" };

export function OutcomePill({ outcome }: { outcome: string }) {
  return <StatusPill tone={OUTCOME_TONE[outcome] ?? "neutral"}>{m.outcomes[outcome] ?? outcome}</StatusPill>;
}

export function actorLabel(entry: Pick<AuditEntry, "actor_name" | "actor_user_id" | "actor_type">): string {
  return entry.actor_name ?? entry.actor_user_id ?? (entry.actor_type === "system" ? m.system : entry.actor_type || m.system);
}

export function auditColumns(): DataTableColumn<AuditEntry>[] {
  const c = m.columns;
  return [
    { id: "occurred", header: c.occurredAt, isRowHeader: true, mobile: "title", cell: (row) => <LocalDateTime value={row.occurred_at} /> },
    { id: "actor", header: c.actor, mobile: "meta", cell: (row) => actorLabel(row) },
    { id: "action", header: c.action, mobile: "key", cell: (row) => <span className="font-mono text-xs [overflow-wrap:anywhere]">{row.action}</span> },
    {
      id: "resource",
      header: c.resource,
      cell: (row) =>
        row.resource_type || row.resource_id ? (
          <span className="flex flex-col gap-0.5">
            {row.resource_type ? <span>{row.resource_label ?? row.resource_type}</span> : null}
            {row.resource_id ? <span className="font-mono text-xs text-ink-muted select-all">{row.resource_id}</span> : null}
          </span>
        ) : (
          <span className="text-ink-muted">{m.noResource}</span>
        ),
    },
    { id: "outcome", header: c.outcome, mobile: "status", cell: (row) => <OutcomePill outcome={row.outcome} /> },
    {
      id: "request",
      header: c.requestId,
      cell: (row) => (row.request_id ? <span className="font-mono text-xs select-all">{row.request_id}</span> : <span className="text-ink-muted">{m.noResource}</span>),
    },
  ];
}

/** The filter row: edits are local until Apply, which writes them to the URL and clears the cursor. */
function AuditFilters({ state, onApply }: { state: AuditListState; onApply: (next: AuditListState) => void }) {
  const f = m.filters;
  const [draft, setDraft] = useState<AuditListState>(state);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onApply({ ...draft, cursor: null });
  };
  return (
    <Form onSubmit={submit} className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end">
      <TextField
        label={f.actionPrefix}
        placeholder={f.actionPlaceholder}
        value={draft.action_prefix}
        onChange={(action_prefix) => setDraft((current) => ({ ...current, action_prefix }))}
        inputClassName="font-mono"
        spellCheck="false"
        maxLength={120}
      />
      <Select
        label={f.outcome}
        placeholder={f.anyOutcome}
        options={[{ id: "", label: f.anyOutcome }, ...AUDIT_OUTCOMES.map((outcome) => ({ id: outcome, label: m.outcomes[outcome] ?? outcome }))]}
        value={draft.outcome ?? ""}
        onChange={(value) => setDraft((current) => ({ ...current, outcome: (AUDIT_OUTCOMES.find((outcome) => outcome === value) ?? null) as AuditOutcome | null }))}
      />
      <DatePicker label={f.from} value={draft.occurred_from} onChange={(occurred_from) => setDraft((current) => ({ ...current, occurred_from }))} />
      <DatePicker label={f.to} value={draft.occurred_to} onChange={(occurred_to) => setDraft((current) => ({ ...current, occurred_to }))} />
      <div className="flex gap-2">
        <Button type="submit" variant="primary">
          {f.apply}
        </Button>
        <Button
          onPress={() => {
            const cleared: AuditListState = { action_prefix: "", outcome: null, occurred_from: null, occurred_to: null, cursor: null };
            setDraft(cleared);
            onApply(cleared);
          }}
        >
          {f.clear}
        </Button>
      </div>
    </Form>
  );
}

export function auditQueryKey(state: AuditListState, timeZone: string) {
  return queryKeys.audit.entries(Object.fromEntries(auditSearch(auditQueryFrom(state, timeZone)).entries()));
}

export function AuditLog({ state }: { state: AuditListState }) {
  const router = useRouter();
  const { permissionKeys, zone } = useSession();
  const allowed = permissionKeys.has("audit.log.read");
  const params = auditQueryFrom(state, zone.timeZone);
  const query = useQuery({
    queryKey: auditQueryKey(state, zone.timeZone),
    queryFn: ({ signal }) => fetchAuditEntries(params, signal),
    enabled: allowed,
  });
  const go = (next: AuditListState) => router.push(auditListHref(next) as Parameters<typeof router.push>[0]);

  if (!allowed) return <PermissionDenied area={m.area} />;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={m.title} intro={m.intro} eyebrow={settingsMessages.hub.title} nav={<SettingsAreaNav />} />
      <AuditFilters key={auditListHref({ ...state, cursor: null })} state={state} onApply={go} />
      {query.isPending ? (
        <Loading label={m.what} />
      ) : query.isError ? (
        <ErrorState error={query.error} what={m.what} onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          caption={m.caption}
          hideCaption
          columns={auditColumns()}
          rows={query.data.items}
          rowId={(row) => row.id}
          empty={<EmptyState title={m.emptyTitle}>{m.empty}</EmptyState>}
          footer={
            <KeysetPagination
              label={m.pages}
              next={query.data.next_cursor ? { href: auditListHref({ ...state, cursor: query.data.next_cursor }) } : null}
              first={state.cursor ? { href: auditListHref({ ...state, cursor: null }) } : null}
            />
          }
        />
      )}
    </div>
  );
}
