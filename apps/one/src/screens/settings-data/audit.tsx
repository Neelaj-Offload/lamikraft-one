"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { fetchAuditEntries } from "@/features/settings/api";
import { auditListHref, auditQueryFrom, type AuditListState } from "@/features/settings/list-state";
import { AUDIT_OUTCOMES, type AuditEntry, type AuditOutcome } from "@/features/settings/types";
import { useSession } from "@/lib/session/context";
import { AUDIT_READ, useAuditEntries } from "~/data/settings-data";
import { Page, PageHeader } from "~/shell/page";
import { NotPermitted } from "~/shell/states";
import { Button, ButtonLink, DataTable, DatePicker, DateText, EmptyState, GlassPanel, Select, TextField, type Column } from "~/ui";
import { asRoute, Mono, Quiet, SETTINGS_CRUMBS, StatusBadge, type StatusLook } from "./shared";
import { ProtectedReadProblem } from "./step-up";

/**
 * Every recorded action in the company, newest first. Filters are edited in place and written to
 * the URL on "Show entries"; pages follow the server's keyset cursor (newer pages are reached from
 * the first page, as the cursor only runs one way).
 */

const OUTCOME: Record<string, StatusLook> = {
  success: { label: "Done", tone: "leaf" },
  denied: { label: "Refused", tone: "amber" },
  failed: { label: "Failed", tone: "ember" },
};
const ANY = "any";
const CLEARED: AuditListState = { action_prefix: "", outcome: null, occurred_from: null, occurred_to: null, cursor: null };

function actorLabel(entry: Pick<AuditEntry, "actor_name" | "actor_user_id" | "actor_type">): string {
  return entry.actor_name ?? entry.actor_user_id ?? (entry.actor_type && entry.actor_type !== "system" ? entry.actor_type : "Lamikraft One");
}

const columns: Column<AuditEntry>[] = [
  { key: "when", header: "When", primary: true, width: "15%", cell: (row) => <DateText value={row.occurred_at} style="dayTime" /> },
  { key: "who", header: "Who", mobileLabel: "Who", cell: (row) => <span className="[overflow-wrap:anywhere]">{actorLabel(row)}</span> },
  { key: "action", header: "Action", mobileLabel: "Action", cell: (row) => <Mono>{row.action}</Mono> },
  {
    key: "record",
    header: "Record",
    mobileLabel: "Record",
    cell: (row) =>
      row.resource_type || row.resource_id ? (
        <span className="flex min-w-0 flex-col gap-0.5">
          {row.resource_type ? <span>{row.resource_label ?? row.resource_type}</span> : null}
          {row.resource_id ? <Mono className="select-all text-ink-3">{row.resource_id}</Mono> : null}
        </span>
      ) : (
        <Quiet>None</Quiet>
      ),
  },
  {
    key: "outcome",
    header: "Outcome",
    mobileLabel: "Outcome",
    cell: (row) => (
      <span className="flex min-w-0 flex-col gap-1">
        <StatusBadge look={OUTCOME[row.outcome] ?? { label: row.outcome, tone: "neutral" }} size="sm" />
        {row.reason ? <span className="t-caption text-ink-3 [overflow-wrap:anywhere]">{row.reason}</span> : null}
      </span>
    ),
  },
  { key: "request", header: "Request", mobileLabel: "Request", hideOnMobile: true, cell: (row) => (row.request_id ? <Mono className="select-all">{row.request_id}</Mono> : <Quiet>None</Quiet>) },
];

function Filters({ state, onApply }: { state: AuditListState; onApply: (next: AuditListState) => void }) {
  const [draft, setDraft] = useState<AuditListState>(state);
  const filtered = Boolean(state.action_prefix || state.outcome || state.occurred_from || state.occurred_to);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onApply({ ...draft, cursor: null });
  };
  return (
    <form onSubmit={submit} noValidate className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_auto] xl:items-end">
      <TextField
        className="sm:col-span-2 xl:col-span-1"
        label="Action starts with"
        placeholder="sales.quote."
        value={draft.action_prefix}
        onChange={(action_prefix) => setDraft((current) => ({ ...current, action_prefix }))}
        maxLength={120}
      />
      <Select
        label="Outcome"
        options={[{ value: ANY, label: "Any outcome" }, ...AUDIT_OUTCOMES.map((outcome) => ({ value: outcome, label: OUTCOME[outcome]?.label ?? outcome }))]}
        value={draft.outcome ?? ANY}
        onChange={(value) => setDraft((current) => ({ ...current, outcome: (AUDIT_OUTCOMES.find((outcome) => outcome === value) ?? null) as AuditOutcome | null }))}
      />
      <DatePicker label="From" value={draft.occurred_from} onChange={(occurred_from) => setDraft((current) => ({ ...current, occurred_from }))} />
      <DatePicker label="To" value={draft.occurred_to} onChange={(occurred_to) => setDraft((current) => ({ ...current, occurred_to }))} />
      <div className="flex gap-2 sm:col-span-2 xl:col-span-1">
        <Button type="submit" variant="inverse" iconLeft="filter">
          Show entries
        </Button>
        {filtered ? (
          <Button
            variant="ghost"
            onPress={() => {
              setDraft(CLEARED);
              onApply(CLEARED);
            }}
          >
            Clear
          </Button>
        ) : null}
      </div>
    </form>
  );
}

export function AuditLog({ state }: { state: AuditListState }) {
  const router = useRouter();
  const { permissionKeys, zone } = useSession();
  const allowed = permissionKeys.has(AUDIT_READ);
  const query = useAuditEntries(state, zone.timeZone, allowed);
  const go = (next: AuditListState) => router.push(asRoute(auditListHref(next)));
  const filtered = Boolean(state.action_prefix || state.outcome || state.occurred_from || state.occurred_to);

  const header = (
    <PageHeader breadcrumb={SETTINGS_CRUMBS} title="Audit log" lead="Every action recorded in your company, newest first: who did it, to which record, and whether it went through." />
  );

  if (!allowed) {
    return (
      <Page>
        {header}
        <NotPermitted what="The audit log" icon="history" />
      </Page>
    );
  }

  const data = query.data;
  return (
    <Page>
      {header}
      <Filters key={auditListHref({ ...state, cursor: null })} state={state} onApply={go} />
      {query.isError && !data ? (
        <ProtectedReadProblem error={query.error} what="The audit log" reason="The audit log records everything people do here. Confirm with your authenticator to see it." retry={() => fetchAuditEntries(auditQueryFrom(state, zone.timeZone)).then(() => query.refetch())} />
      ) : (
        <GlassPanel padding="none">
          <DataTable
            label="Audit entries"
            columns={columns}
            rows={data?.items ?? []}
            rowKey={(row) => row.id}
            loading={query.isPending}
            skeletonRows={10}
            empty={
              filtered ? (
                <EmptyState
                  compact
                  icon="search"
                  title="Nothing was recorded for these filters"
                  text="Widen the dates or clear the action to see more."
                  actions={
                    <ButtonLink href="/settings/audit" variant="secondary" size="sm">
                      Clear the filters
                    </ButtonLink>
                  }
                />
              ) : (
                <EmptyState icon="history" title="Nothing recorded yet" text="Actions appear here as people sign in, change settings and work on records." />
              )
            }
          />
        </GlassPanel>
      )}
      {data && (state.cursor || data.next_cursor) ? (
        <nav aria-label="Audit log pages" className="flex min-w-0 flex-wrap items-center justify-between gap-3">
          <span className="t-body-sm text-ink-3">{state.cursor ? "Showing older entries." : "Showing the newest entries."}</span>
          <div className="flex gap-2">
            {state.cursor ? (
              <ButtonLink href={asRoute(auditListHref({ ...state, cursor: null }))} variant="secondary" size="sm" iconLeft="chevronLeft">
                Newest
              </ButtonLink>
            ) : null}
            {data.next_cursor ? (
              <ButtonLink href={asRoute(auditListHref({ ...state, cursor: data.next_cursor }))} variant="secondary" size="sm" iconRight="chevronRight">
                Older entries
              </ButtonLink>
            ) : null}
          </div>
        </nav>
      ) : null}
    </Page>
  );
}
