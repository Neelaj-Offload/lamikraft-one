"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { StatusPill, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { FactStrip } from "@/components/ui/fact-strip";
import { LocalDateTime } from "@/components/ui/format";
import { KeyValueGrid, type KeyValue } from "@/components/ui/key-value-grid";
import { Link } from "@/components/ui/link";
import { PageHeader } from "@/components/ui/page-header";
import { SectionCard } from "@/components/ui/section-card";
import { EmptyState, ErrorState, Loading, PermissionDenied } from "@/components/ui/states";
import { ProblemError } from "@/lib/api/errors";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { formatCount, formatDecimal } from "@/lib/format/money";
import { useSession, useZone } from "@/lib/session/context";
import { aiMessages } from "@/messages/ai";
import { settingsMessages } from "@/messages/settings";
import { fetchSetting } from "@/features/settings/api";
import { SettingCard } from "@/features/settings/setting-card";
import { SettingsAreaNav } from "@/features/settings/settings-hub";
import { AI_ROUTING_SETTING, fetchAiStatus, fetchAiUsage, verifyAi } from "./api";
import { errorRateTenths } from "./parse";
import type { AiFailure, AiStatus, AiUsage, ModelUsage, ProviderState, WorkflowUsage } from "./types";

const m = aiMessages.settings;
const PROVIDER_TONE: Record<ProviderState, Tone> = { demo: "info", verified: "success", failing: "danger", not_verified: "warning", misconfigured: "danger" };
export const TRACE_PATH = (correlationId: string) => `/settings/ai/traces/${encodeURIComponent(correlationId)}`;

const muted = (text: string) => <span className="text-ink-muted">{text}</span>;
const mono = (text: string) => <span className="font-mono text-xs select-all">{text}</span>;

/** "≈ USD 0.0123" from the server's estimate string; demo calls cost nothing; a missing price is said, not guessed. */
export function costText(cost: string | null, currency: string, locale: string, provider?: string): string {
  if (provider === "demo") return m.usage.demoCost;
  if (cost === null) return m.usage.noPrice;
  return m.usage.estimate(formatDecimal(cost, { locale, maxFractionDigits: 4 }) ?? cost, currency);
}

export function latencyText(value: number | null, locale: string): string {
  return value === null ? m.usage.noValue : m.usage.ms(formatCount(value, locale));
}

export function providerItems(status: AiStatus): KeyValue[] {
  const p = status.provider;
  const c = m.provider;
  return [
    { term: c.mode, description: c.modes[p.mode] ?? p.mode },
    { term: c.verifiedAt, description: p.verified_at ? <LocalDateTime value={p.verified_at} /> : muted(c.never) },
    { term: c.lastChecked, description: p.last_checked_at ? <LocalDateTime value={p.last_checked_at} /> : muted(c.never) },
    { term: c.lastError, description: p.last_error_code ? mono(p.last_error_code) : muted(c.none) },
    {
      term: c.circuit,
      description: (
        <span className="flex flex-col">
          <span>{c.circuitStates[p.circuit.state] ?? p.circuit.state}</span>
          {p.circuit.recent_failures > 0 ? <span className="text-xs text-ink-muted">{c.recentFailures(p.circuit.recent_failures)}</span> : null}
        </span>
      ),
    },
  ];
}

function ProviderSection({ status }: { status: AiStatus }) {
  const { permissionKeys } = useSession();
  const client = useQueryClient();
  const verify = useMutation({
    mutationFn: () => verifyAi(),
    onSettled: () => {
      for (const key of invalidationMap["agents.ai_verified"]) void client.invalidateQueries({ queryKey: key });
    },
  });
  const p = status.provider;
  const canVerify = permissionKeys.has("system.integration.manage");
  return (
    <SectionCard
      title={m.provider.title}
      description={
        <span className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-ink">{p.label}</span>
          <StatusPill tone={PROVIDER_TONE[p.state]}>{m.provider.states[p.state] ?? p.state}</StatusPill>
        </span>
      }
      actions={
        canVerify ? (
          <Button size="sm" onPress={() => verify.mutate()} isPending={verify.isPending} pendingLabel={m.provider.verifying}>
            {m.provider.verify}
          </Button>
        ) : null
      }
    >
      {p.state === "demo" ? <p className="text-sm text-ink-muted">{m.provider.demoBody}</p> : null}
      {p.state === "misconfigured" ? <p className="text-sm text-danger">{m.provider.misconfiguredBody}</p> : null}
      <KeyValueGrid items={providerItems(status)} />
      {verify.isSuccess ? <p role="status" className="text-sm text-ink-muted">{m.provider.verifyDone}</p> : null}
      {verify.isError ? (
        <p role="alert" className="text-sm text-danger">
          {verify.error instanceof ProblemError ? (verify.error.detail ?? m.provider.lastError) : m.provider.lastError}
        </p>
      ) : null}
    </SectionCard>
  );
}

// ---- usage ----------------------------------------------------------------------------------------------------------
export function workflowColumns(currency: string, locale: string): DataTableColumn<WorkflowUsage>[] {
  const c = m.usage.columns;
  const count = (value: number) => formatCount(value, locale);
  return [
    { id: "workflow", header: c.workflow, isRowHeader: true, mobile: "title", cell: (row) => m.usage.workflows[row.workflow] ?? row.workflow },
    { id: "calls", header: c.calls, numeric: true, mobile: "key", cell: (row) => count(row.calls) },
    { id: "runs", header: c.runs, numeric: true, cell: (row) => count(row.runs) },
    {
      id: "errors",
      header: c.errorRate,
      numeric: true,
      mobile: "status",
      cell: (row) => {
        const tenths = errorRateTenths(row.errors + row.refusals, row.calls);
        return tenths === null ? m.usage.noValue : `${m.usage.percent(tenths)} (${count(row.errors + row.refusals)})`;
      },
    },
    { id: "p50", header: c.p50, numeric: true, cell: (row) => latencyText(row.p50_latency_ms, locale) },
    { id: "p95", header: c.p95, numeric: true, mobile: "meta", cell: (row) => latencyText(row.p95_latency_ms, locale) },
    { id: "in", header: c.tokensIn, numeric: true, cell: (row) => count(row.input_tokens) },
    { id: "out", header: c.tokensOut, numeric: true, cell: (row) => count(row.output_tokens) },
    { id: "cache-read", header: c.cacheRead, numeric: true, cell: (row) => count(row.cache_read_tokens) },
    { id: "cache-write", header: c.cacheWrite, numeric: true, cell: (row) => count(row.cache_write_tokens) },
    { id: "cost", header: c.cost, numeric: true, mobile: "amount", cell: (row) => costText(row.estimated_cost, currency, locale) },
  ];
}

export function modelColumns(currency: string, locale: string): DataTableColumn<ModelUsage>[] {
  const c = m.usage.columns;
  const count = (value: number) => formatCount(value, locale);
  return [
    { id: "model", header: c.model, isRowHeader: true, mobile: "title", cell: (row) => mono(row.model) },
    { id: "provider", header: c.provider, mobile: "meta", cell: (row) => row.provider },
    { id: "calls", header: c.calls, numeric: true, mobile: "key", cell: (row) => count(row.calls) },
    { id: "in", header: c.tokensIn, numeric: true, cell: (row) => count(row.input_tokens) },
    { id: "out", header: c.tokensOut, numeric: true, cell: (row) => count(row.output_tokens) },
    { id: "cache-read", header: c.cacheRead, numeric: true, cell: (row) => count(row.cache_read_tokens) },
    { id: "cost", header: c.cost, numeric: true, mobile: "amount", cell: (row) => costText(row.estimated_cost, currency, locale, row.provider) },
  ];
}

export function failureColumns(): DataTableColumn<AiFailure>[] {
  const c = m.failures.columns;
  return [
    { id: "at", header: c.at, mobile: "meta", cell: (row) => <LocalDateTime value={row.at} /> },
    { id: "workflow", header: c.workflow, isRowHeader: true, mobile: "title", cell: (row) => m.usage.workflows[row.workflow] ?? row.workflow },
    { id: "model", header: c.model, cell: (row) => mono(row.model) },
    {
      id: "outcome",
      header: c.outcome,
      mobile: "status",
      cell: (row) => <StatusPill tone={row.outcome === "refusal" ? "warning" : "danger"}>{m.failures.outcomes[row.outcome] ?? row.outcome}</StatusPill>,
    },
    { id: "error", header: c.error, cell: (row) => (row.error_type ? mono(row.error_type) : muted(m.provider.none)) },
    { id: "request", header: c.requestId, mobile: "key", cell: (row) => (row.request_id ? mono(row.request_id) : muted(m.provider.none)) },
    {
      id: "trace",
      header: c.trace,
      cell: (row) => (row.correlation_id ? <Link href={TRACE_PATH(row.correlation_id)}>{m.failures.openTrace}</Link> : muted(m.provider.none)),
    },
  ];
}

export function usageFacts(usage: AiUsage, locale: string) {
  const f = m.usage.facts;
  const t = usage.totals;
  return [
    { label: f.calls, value: formatCount(t.calls, locale) },
    { label: f.runs, value: formatCount(t.runs, locale) },
    { label: f.errors, value: formatCount(t.errors + t.refusals, locale) },
    { label: f.p95, value: latencyText(t.p95_latency_ms, locale) },
    { label: f.cost, value: costText(t.estimated_cost, usage.price_currency, locale) },
  ];
}

function UsageSection({ days }: { days: number }) {
  const { locale } = useZone();
  const query = useQuery({ queryKey: queryKeys.agents.aiUsage(days), queryFn: ({ signal }) => fetchAiUsage(days, signal) });
  const windows = (
    <nav aria-label={m.usage.window} className="flex flex-wrap gap-3 text-sm">
      {m.usage.windows.map((w) =>
        w.days === days ? (
          <span key={w.days} aria-current="page" className="font-semibold text-ink">
            {w.label}
          </span>
        ) : (
          <Link key={w.days} href={`/settings/ai?days=${w.days}`}>
            {w.label}
          </Link>
        ),
      )}
    </nav>
  );
  let body: React.ReactNode;
  if (query.isPending) body = <Loading label={m.usageWhat} rows={4} />;
  else if (query.isError) body = <ErrorState error={query.error} what={m.usageWhat} onRetry={() => void query.refetch()} />;
  else if (query.data.totals.calls === 0) body = <EmptyState title={m.usage.empty}>{m.usage.emptyHint}</EmptyState>;
  else {
    const usage = query.data;
    body = (
      <div className="flex flex-col gap-6">
        <FactStrip label={m.usage.title} facts={usageFacts(usage, locale)} />
        <DataTable caption={m.usage.byWorkflow} columns={workflowColumns(usage.price_currency, locale)} rows={usage.by_workflow} rowId={(row) => row.workflow} />
        <DataTable caption={m.usage.byModel} columns={modelColumns(usage.price_currency, locale)} rows={usage.by_model} rowId={(row) => `${row.provider}:${row.model}`} />
        <DataTable
          caption={m.failures.title}
          columns={failureColumns()}
          rows={usage.failures}
          rowId={(row) => `${row.at}:${row.request_id ?? row.run_id ?? row.workflow}`}
          empty={<EmptyState title={m.failures.empty} />}
        />
      </div>
    );
  }
  return (
    <SectionCard title={m.usage.title} description={m.usage.intro(days)} actions={windows}>
      {body}
    </SectionCard>
  );
}

// ---- routing --------------------------------------------------------------------------------------------------------
export function routingItems(status: AiStatus, locale: string): KeyValue[] {
  const r = m.routing;
  const items: KeyValue[] = Object.entries(status.models).map(([role, model]) => ({ term: r.modelRoles[role] ?? role, description: model, mono: true }));
  for (const [task, effort] of Object.entries(status.effort)) items.push({ term: `${r.effort}: ${m.usage.workflows[task] ?? task}`, description: effort });
  for (const [task, b] of Object.entries(status.budgets)) {
    items.push({ term: `${r.budgets}: ${task}`, description: r.budget(b.steps, b.seconds, formatCount(b.input_tokens, locale), formatCount(b.max_tokens, locale)) });
  }
  for (const [name, limit] of Object.entries(status.quotas)) items.push({ term: r.quotaNames[name] ?? name, description: formatCount(limit, locale), numeric: true });
  return items;
}

function RoutingEditor() {
  const query = useQuery({ queryKey: queryKeys.org.setting(AI_ROUTING_SETTING), queryFn: ({ signal }) => fetchSetting(AI_ROUTING_SETTING, signal) });
  if (query.isPending) return <Loading label={m.routing.editor} rows={2} />;
  if (query.isError) return <ErrorState error={query.error} what={m.routing.editor} onRetry={() => void query.refetch()} />;
  return <SettingCard setting={query.data} />;
}

function RoutingSection({ status }: { status: AiStatus }) {
  const { locale } = useZone();
  const c = m.routing.priceColumns;
  const priceColumns: DataTableColumn<AiStatus["prices"][number]>[] = [
    { id: "model", header: c.model, isRowHeader: true, mobile: "title", cell: (row) => mono(row.model) },
    { id: "input", header: c.input, numeric: true, mobile: "key", cell: (row) => row.input },
    { id: "output", header: c.output, numeric: true, cell: (row) => row.output },
    { id: "cache-read", header: c.cacheRead, numeric: true, cell: (row) => row.cache_read },
    { id: "cache-write", header: c.cacheWrite, numeric: true, cell: (row) => row.cache_write },
  ];
  return (
    <SectionCard title={m.routing.title} description={m.routing.intro}>
      <KeyValueGrid items={routingItems(status, locale)} columns={2} />
      <DataTable caption={m.routing.prices} columns={priceColumns} rows={status.prices} rowId={(row) => row.model} />
      {status.can_manage_routing ? (
        <div className="flex flex-col gap-2">
          <p className="text-sm text-ink-muted">{m.routing.editorIntro}</p>
          <RoutingEditor />
        </div>
      ) : null}
    </SectionCard>
  );
}

// ---- page -----------------------------------------------------------------------------------------------------------
export function AiSettingsView({ days }: { days: number }) {
  const { permissionKeys } = useSession();
  const allowed = permissionKeys.has("agents.ai_usage.read");
  const status = useQuery({ queryKey: queryKeys.agents.aiStatus(), queryFn: ({ signal }) => fetchAiStatus(signal), enabled: allowed });
  let body: React.ReactNode;
  if (!allowed) body = <PermissionDenied area={m.what} headingLevel={2} />;
  else if (status.isPending) body = <Loading label={m.what} rows={4} />;
  else if (status.isError) body = <ErrorState error={status.error} what={m.what} onRetry={() => void status.refetch()} />;
  else {
    body = (
      <>
        <ProviderSection status={status.data} />
        <SectionCard title={m.dpdp.title} description={m.dpdp.intro}>
          <p className="text-sm text-ink">{status.data.dpdp_text}</p>
        </SectionCard>
        <UsageSection days={days} />
        <RoutingSection status={status.data} />
      </>
    );
  }
  return (
    <div className="flex max-w-6xl flex-col gap-6">
      <PageHeader title={m.title} intro={m.intro} eyebrow={settingsMessages.hub.title} nav={<SettingsAreaNav currentId="settings-ai" />} />
      {body}
    </div>
  );
}
