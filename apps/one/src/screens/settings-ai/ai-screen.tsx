"use client";

import type { Route } from "next";
import type { CSSProperties, ReactNode } from "react";
import { errorRateTenths } from "@/features/ai-admin/parse";
import type { AiFailure, AiStatus, AiUsage, ModelUsage, ProviderState, WorkflowUsage } from "@/features/ai-admin/types";
import { formatCount } from "@/lib/format/money";
import { useSession, useZone } from "@/lib/session/context";
import { useAiStatus, useAiUsage, useVerifyAi } from "~/data/settings-ai";
import { riseIndex } from "~/lib/motion";
import { Page, PageHeader, PageSection } from "~/shell/page";
import { ErrorBlock, LoadingBlock, NotPermitted, QueryView } from "~/shell/states";
import {
  Aurora,
  Badge,
  Banner,
  Button,
  CountUp,
  Dash,
  DataTable,
  DateText,
  EmptyState,
  FactStrip,
  GlassPanel,
  Orb,
  SegmentedLinks,
  Skeleton,
  StatTile,
  Tabs,
  TextLink,
  type Column,
  type Tone,
} from "~/ui";
import { RoutingView } from "./ai-routing";
import { costText, latencyText, percentText, workflowLabel } from "./format";
import { aiHref, traceHref, USAGE_WINDOWS, type AiView } from "./views";

const PROVIDER_STATE: Record<ProviderState, { label: string; tone: Tone }> = {
  demo: { label: "Demo", tone: "neutral" },
  verified: { label: "Verified", tone: "leaf" },
  failing: { label: "Failing", tone: "ember" },
  not_verified: { label: "Not verified", tone: "amber" },
  misconfigured: { label: "Not configured", tone: "ember" },
};

const PAUSE_STATE: Record<string, string> = {
  closed: "Not paused",
  open: "Paused after repeated failures",
  half_open: "Testing again",
};

function ProviderBadge({ state }: { state: ProviderState }) {
  const look = PROVIDER_STATE[state];
  // Demo keeps the same quiet outline it has everywhere else in the product.
  return state === "demo" ? <Badge outline>{look.label}</Badge> : <Badge tone={look.tone}>{look.label}</Badge>;
}

const windowLabel = (days: number) => (days === 1 ? "Today" : `Last ${days} days`);

/**
 * Settings, AI: is the assistant healthy, what does it cost to run, and which models does it
 * use. Three views of one subject, each its own URL (`?view=`), so the screen never stacks
 * provider health, three usage tables and the routing editor on top of each other.
 */
export function AiScreen({ view, days }: { view: AiView; days: number }) {
  const { permissionKeys } = useSession();
  const allowed = permissionKeys.has("agents.ai_usage.read");
  const status = useAiStatus(allowed);

  return (
    <Page>
      <PageHeader
        breadcrumb={[{ label: "Settings", href: "/settings" }, { label: "AI" }]}
        title="AI"
        lead="Whether the assistant is healthy, what it costs to run and which models answer."
        meta={status.data ? <ProviderBadge state={status.data.provider.state} /> : null}
      />
      {allowed ? (
        <>
          <Tabs
            label="AI settings"
            selectedKey={view}
            tabs={[
              { id: "overview", label: "Overview", href: aiHref("overview", days) as Route },
              { id: "usage", label: "Usage", href: aiHref("usage", days) as Route },
              { id: "routing", label: "Routing", href: aiHref("routing", days) as Route },
            ]}
          />
          {view === "usage" ? (
            <UsageView days={days} />
          ) : (
            <QueryView query={status} what="The AI status" loading={<LoadingBlock lines={6} label="Loading the AI status" />}>
              {(data) => (view === "routing" ? <RoutingView status={data} /> : <OverviewView status={data} days={days} />)}
            </QueryView>
          )}
        </>
      ) : (
        <NotPermitted what="AI status and usage" />
      )}
    </Page>
  );
}

// ---- overview ----

function OverviewView({ status, days }: { status: AiStatus; days: number }) {
  return (
    <>
      <ProviderPanel status={status} />
      <UsageGlance days={days} />
      <PageSection
        title="Data protection (DPDP)"
        description="Live AI sends business data to Anthropic and Google only after the owner's approval is on record."
        index={3}
      >
        <GlassPanel variant="outline" padding="md">
          {status.dpdp_text ? <p className="t-body text-ink">{status.dpdp_text}</p> : <p className="t-body text-ink-3">The server sent no statement.</p>}
        </GlassPanel>
      </PageSection>
    </>
  );
}

function ProviderPanel({ status }: { status: AiStatus }) {
  const { permissionKeys } = useSession();
  const verify = useVerifyAi();
  const provider = status.provider;
  const canVerify = permissionKeys.has("system.integration.manage");
  const pause = PAUSE_STATE[provider.circuit.state] ?? provider.circuit.state;
  const failures = provider.circuit.recent_failures;

  return (
    <GlassPanel as="section" padding="lg" className="rise overflow-hidden" style={riseIndex(1) as CSSProperties} aria-label="Provider">
      <Aurora quiet />
      <div className="relative flex flex-col gap-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 items-center gap-4">
            <span aria-hidden="true" className="flex-none">
              <Orb size="md" />
            </span>
            <div className="flex min-w-0 flex-col gap-1">
              <p className="t-overline text-ink-3">Provider</p>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="t-h2 min-w-0 break-words">{provider.label}</h2>
                <ProviderBadge state={provider.state} />
              </div>
            </div>
          </div>
          {canVerify ? (
            <Button variant="inverse" iconLeft="refresh" loading={verify.isPending} onPress={() => verify.mutate()}>
              Verify connection
            </Button>
          ) : null}
        </div>

        {provider.state === "demo" ? (
          <p className="t-body text-ink-2">
            The assistant answers from a built-in demo engine. Nothing is sent to Anthropic or Google, and no keys are needed.
          </p>
        ) : null}
        {provider.state === "misconfigured" ? (
          <Banner tone="ember" title="Live mode is on, but the server has no ANTHROPIC_API_KEY.">
            The assistant shows an error instead of answering. Set the key on the server, then verify the connection.
          </Banner>
        ) : null}
        {verify.isError ? <ErrorBlock error={verify.error} what="The connection check" onRetry={() => verify.mutate()} /> : null}

        <FactStrip
          items={[
            { label: "Mode", value: provider.mode === "live" ? "Live" : "Demo" },
            { label: "Verified", value: provider.verified_at ? <DateText value={provider.verified_at} style="dayTime" /> : "Never" },
            { label: "Last checked", value: provider.last_checked_at ? <DateText value={provider.last_checked_at} style="dayTime" /> : "Never" },
            { label: "Last error", value: provider.last_error_code ? <span className="t-code-sm lk-mono select-all">{provider.last_error_code}</span> : "None" },
            {
              label: "Automatic pause",
              value: (
                <span className="flex flex-col">
                  <span>{pause}</span>
                  {failures > 0 ? (
                    <span className="t-caption text-ink-3">
                      {formatCount(failures)} {failures === 1 ? "failure" : "failures"} in the last 2 minutes
                    </span>
                  ) : null}
                </span>
              ),
            },
          ]}
        />
      </div>
    </GlassPanel>
  );
}

function Figure({ children, ready }: { children: ReactNode; ready: boolean }) {
  return ready ? <>{children}</> : <Skeleton width={56} height={32} />;
}

/** The four numbers that say how the period went; each opens the full usage view. */
function UsageGlance({ days }: { days: number }) {
  const { locale } = useZone();
  const usage = useAiUsage(days);
  const href = aiHref("usage", days) as Route;
  const totals = usage.data?.totals;
  const ready = totals !== undefined;
  const problems = totals ? totals.errors + totals.refusals : 0;
  const rate = totals ? errorRateTenths(problems, totals.calls) : null;

  return (
    <PageSection title={windowLabel(days)} description="From the AI call log. Open any figure for the breakdown by workflow and model." index={2}>
      {usage.isError ? (
        <ErrorBlock error={usage.error} what="AI usage" onRetry={() => void usage.refetch()} />
      ) : (
        <div className="tiles" role="group" aria-label={`AI usage, ${windowLabel(days).toLowerCase()}`}>
          <GlassPanel interactive>
            <StatTile
              label="Provider calls"
              value={<Figure ready={ready}>{totals ? <CountUp value={totals.calls} /> : null}</Figure>}
              foot={totals ? `${formatCount(totals.runs, locale)} assistant ${totals.runs === 1 ? "run" : "runs"}` : undefined}
              href={href}
            />
          </GlassPanel>
          <GlassPanel interactive>
            <StatTile
              label="Errors and declines"
              value={<Figure ready={ready}>{totals ? <CountUp value={problems} /> : null}</Figure>}
              foot={totals ? (rate === null ? "No calls yet" : `${percentText(rate)} of calls`) : undefined}
              dot={problems > 0 ? "var(--ember)" : false}
              href={href}
            />
          </GlassPanel>
          <GlassPanel interactive>
            <StatTile
              label="Response time, p95"
              value={<Figure ready={ready}>{totals ? (latencyText(totals.p95_latency_ms, locale) ?? <Dash />) : null}</Figure>}
              foot="95 in 100 calls answer faster"
              href={href}
            />
          </GlassPanel>
          <GlassPanel interactive>
            <StatTile
              label="Estimated cost"
              value={<Figure ready={ready}>{usage.data && totals ? costText(totals.estimated_cost, usage.data.price_currency, locale) : null}</Figure>}
              foot="Worked out now from the price table"
              href={href}
            />
          </GlassPanel>
        </div>
      )}
    </PageSection>
  );
}

// ---- usage ----

function Mono({ children }: { children: ReactNode }) {
  return <span className="t-code-sm lk-mono select-all break-all">{children}</span>;
}

function Stacked({ top, bottom }: { top: ReactNode; bottom?: ReactNode }) {
  return (
    <span className="flex flex-col">
      <span>{top}</span>
      {bottom ? <span className="t-caption text-ink-3">{bottom}</span> : null}
    </span>
  );
}

function workflowColumns(currency: string, locale: string): Column<WorkflowUsage>[] {
  const count = (value: number) => formatCount(value, locale);
  return [
    { key: "workflow", header: "Workflow", primary: true, cell: (row) => <span className="t-label text-ink">{workflowLabel(row.workflow)}</span> },
    {
      key: "calls",
      header: "Calls",
      numeric: true,
      cell: (row) => <Stacked top={count(row.calls)} bottom={`${count(row.runs)} ${row.runs === 1 ? "run" : "runs"}`} />,
    },
    {
      key: "errors",
      header: "Error rate",
      numeric: true,
      cell: (row) => {
        const problems = row.errors + row.refusals;
        const tenths = errorRateTenths(problems, row.calls);
        return tenths === null ? <Dash /> : <Stacked top={percentText(tenths)} bottom={`${count(problems)} of ${count(row.calls)}`} />;
      },
    },
    {
      key: "latency",
      header: "Response time",
      numeric: true,
      cell: (row) => {
        const median = latencyText(row.p50_latency_ms, locale);
        const slow = latencyText(row.p95_latency_ms, locale);
        return median === null && slow === null ? <Dash /> : <Stacked top={median ?? <Dash />} bottom={slow ? `p95 ${slow}` : undefined} />;
      },
    },
    {
      key: "tokens",
      header: "Tokens in / out",
      numeric: true,
      cell: (row) => (
        <Stacked
          top={`${count(row.input_tokens)} / ${count(row.output_tokens)}`}
          bottom={`Cache ${count(row.cache_read_tokens)} read, ${count(row.cache_write_tokens)} written`}
        />
      ),
    },
    { key: "cost", header: "Est. cost", numeric: true, cell: (row) => costText(row.estimated_cost, currency, locale) },
  ];
}

function modelColumns(currency: string, locale: string): Column<ModelUsage>[] {
  const count = (value: number) => formatCount(value, locale);
  return [
    { key: "model", header: "Model", primary: true, cell: (row) => <Mono>{row.model}</Mono> },
    { key: "provider", header: "Provider", cell: (row) => (row.provider === "demo" ? <Badge size="sm" outline>Demo</Badge> : row.provider) },
    { key: "calls", header: "Calls", numeric: true, cell: (row) => count(row.calls) },
    { key: "tokens", header: "Tokens in / out", numeric: true, cell: (row) => `${count(row.input_tokens)} / ${count(row.output_tokens)}` },
    { key: "cache", header: "Cache read", numeric: true, cell: (row) => count(row.cache_read_tokens) },
    { key: "cost", header: "Est. cost", numeric: true, cell: (row) => costText(row.estimated_cost, currency, locale, row.provider) },
  ];
}

const OUTCOME: Record<string, { label: string; tone: Tone }> = {
  error: { label: "Error", tone: "ember" },
  refusal: { label: "Declined", tone: "amber" },
};

function failureColumns(): Column<AiFailure>[] {
  return [
    {
      key: "workflow",
      header: "Workflow",
      primary: true,
      cell: (row) => <Stacked top={<span className="t-label text-ink">{workflowLabel(row.workflow)}</span>} bottom={row.model ? <Mono>{row.model}</Mono> : undefined} />,
    },
    { key: "at", header: "When", cell: (row) => <DateText value={row.at} style="dayTime" /> },
    {
      key: "outcome",
      header: "Outcome",
      cell: (row) => {
        const look = OUTCOME[row.outcome] ?? { label: row.outcome, tone: "ember" as const };
        return (
          <Badge size="sm" tone={look.tone}>
            {look.label}
          </Badge>
        );
      },
    },
    { key: "error", header: "Error", cell: (row) => (row.error_type ? <Mono>{row.error_type}</Mono> : <Dash />) },
    { key: "request", header: "Request id", cell: (row) => (row.request_id ? <Mono>{row.request_id}</Mono> : <Dash />) },
    {
      key: "trace",
      header: "Trace",
      cell: (row) => (row.correlation_id ? <TextLink href={traceHref(row.correlation_id) as Route}>Open trace</TextLink> : <Dash />),
    },
  ];
}

function UsageBody({ usage }: { usage: AiUsage }) {
  const { locale } = useZone();
  const totals = usage.totals;
  const problems = totals.errors + totals.refusals;
  const rate = errorRateTenths(problems, totals.calls);

  return (
    <>
      <GlassPanel padding="md" className="rise" style={riseIndex(1) as CSSProperties}>
        <FactStrip
          items={[
            { label: "Provider calls", value: formatCount(totals.calls, locale) },
            { label: "Assistant runs", value: formatCount(totals.runs, locale) },
            { label: "Errors and declines", value: rate === null ? formatCount(problems, locale) : `${formatCount(problems, locale)} (${percentText(rate)})` },
            { label: "Response time, p95", value: latencyText(totals.p95_latency_ms, locale) },
            { label: "Estimated cost", value: costText(totals.estimated_cost, usage.price_currency, locale) },
          ]}
        />
      </GlassPanel>

      <PageSection title="By workflow" description="What the assistant was doing when it called a model." index={2}>
        <GlassPanel padding="none">
          <DataTable label="Usage by workflow" columns={workflowColumns(usage.price_currency, locale)} rows={usage.by_workflow} rowKey={(row) => row.workflow} />
        </GlassPanel>
      </PageSection>

      <PageSection title="By model" description="Which models answered, and what each one cost." index={3}>
        <GlassPanel padding="none">
          <DataTable label="Usage by model" columns={modelColumns(usage.price_currency, locale)} rows={usage.by_model} rowKey={(row) => `${row.provider}:${row.model}`} />
        </GlassPanel>
      </PageSection>

      <PageSection title="Recent failures" description="Calls that errored or were declined. Open a trace to see what the request did around it." index={4}>
        <GlassPanel padding="none">
          <DataTable
            label="Recent failures"
            columns={failureColumns()}
            rows={usage.failures}
            rowKey={(row) => `${row.at}:${row.request_id ?? row.run_id ?? row.workflow}`}
            empty={<EmptyState compact icon="checkCircle" title="No failures in this period" text="Every call the assistant made came back with an answer." />}
          />
        </GlassPanel>
      </PageSection>
    </>
  );
}

function UsageView({ days }: { days: number }) {
  const usage = useAiUsage(days);
  return (
    <>
      <div className="rise flex flex-wrap items-center justify-between gap-3">
        <p className="t-body-sm text-ink-3">From the AI call log. Cost is worked out now from the price table; it is never stored as money.</p>
        <SegmentedLinks
          label="Period"
          size="sm"
          value={String(days)}
          options={USAGE_WINDOWS.map((window) => ({ value: String(window.days), label: window.label, href: aiHref("usage", window.days) as Route }))}
        />
      </div>
      <QueryView
        query={usage}
        what="AI usage"
        loading={<LoadingBlock lines={6} label="Loading AI usage" />}
        isEmpty={(data) => data.totals.calls === 0}
        empty={
          <GlassPanel padding="lg">
            <EmptyState
              icon="sparkles"
              title={days === 1 ? "No assistant calls today" : `No assistant calls in the last ${days} days`}
              text="Ask Lamikraft something and its calls appear here, with their cost and response time."
            />
          </GlassPanel>
        }
      >
        {(data) => <UsageBody usage={data} />}
      </QueryView>
    </>
  );
}
