"use client";

import type { Route } from "next";
import type { Trace, TraceEntry } from "@/features/ai-admin/types";
import { ProblemError } from "@/lib/api/errors";
import { formatCount } from "@/lib/format/money";
import { useZone } from "@/lib/session/context";
import { useTrace } from "~/data/settings-ai";
import { Page, PageHeader, RecordHeader, Split, type Crumb } from "~/shell/page";
import { ErrorBlock, LoadingBlock } from "~/shell/states";
import { Badge, ButtonLink, DateText, EmptyState, FactStrip, GlassPanel, KeyValue, Timeline, type IconName, type TimelineItem, type Tone } from "~/ui";
import { humanise } from "./format";
import { aiHref } from "./views";

const CRUMBS: readonly Crumb[] = [{ label: "Settings", href: "/settings" }, { label: "AI", href: "/settings/ai" }, { label: "Trace" }];

const KIND: Record<string, { label: string; icon: IconName }> = {
  turn: { label: "Turn", icon: "message" },
  run: { label: "Run", icon: "play" },
  step: { label: "Step", icon: "route" },
  ai_call: { label: "AI call", icon: "sparkles" },
  receipt: { label: "Receipt", icon: "receipt" },
  event: { label: "Event", icon: "zap" },
  audit: { label: "Audit", icon: "shield" },
};

const ACCESS: Record<string, string> = { participant: "Your request", auditor: "Viewed as an auditor" };

const OK = new Set(["ok", "succeeded", "success", "dispatched", "active", "undone"]);
const BAD = new Set(["error", "failed", "refusal", "denied", "budget_exceeded"]);

function statusTone(status: string | null): Tone {
  if (status === null) return "neutral";
  if (OK.has(status)) return "leaf";
  if (BAD.has(status)) return "ember";
  return "neutral";
}

/** Redacted detail as `key: value` pairs (scalars and lists only; the server never sends text or payloads here). */
function detailPairs(detail: Record<string, unknown>): { key: string; value: string }[] {
  return Object.entries(detail)
    .filter(([, value]) => value !== null && value !== undefined && value !== "" && (typeof value !== "object" || Array.isArray(value)))
    .map(([key, value]) => ({ key, value: Array.isArray(value) ? value.join(", ") : String(value) }));
}

/** A trace happens inside a few seconds, so each step shows the clock to the second and how far in it was. */
function useStepClock(startedAt: string | undefined) {
  const { locale, timeZone } = useZone();
  const start = startedAt ? Date.parse(startedAt) : Number.NaN;
  const clock = new Intl.DateTimeFormat(locale, { timeZone, hour: "2-digit", minute: "2-digit", second: "2-digit" });
  return (at: string) => {
    const instant = Date.parse(at);
    if (Number.isNaN(instant)) return { time: at, offset: null };
    const elapsed = Number.isNaN(start) ? null : Math.max(0, instant - start);
    return { time: clock.format(instant), offset: elapsed === null ? null : `+${(elapsed / 1000).toFixed(1)} s` };
  };
}

function entryItem(entry: TraceEntry, index: number, clock: ReturnType<typeof useStepClock>): TimelineItem {
  const kind = KIND[entry.kind] ?? { label: humanise(entry.kind), icon: "circleDot" as const };
  const { time, offset } = clock(entry.at);
  const pairs = detailPairs(entry.detail);
  return {
    id: `${index}:${entry.kind}:${entry.ref_id ?? ""}:${entry.name}:${entry.at}`,
    icon: kind.icon,
    tone: statusTone(entry.status),
    title: (
      <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="t-label text-ink">{kind.label}</span>
        <span className="t-code-sm lk-mono break-all text-ink-2">{entry.name}</span>
        {entry.status ? (
          <Badge size="sm" tone={statusTone(entry.status)}>
            {humanise(entry.status)}
          </Badge>
        ) : null}
      </span>
    ),
    meta: (
      <time dateTime={entry.at} className="lk-tnum whitespace-nowrap">
        {time}
        {offset ? <span className="text-ink-3"> · {offset}</span> : null}
      </time>
    ),
    body:
      entry.ref_id || pairs.length > 0 ? (
        <span className="flex flex-col gap-1">
          {pairs.length > 0 ? (
            <span className="t-body-sm text-ink-2">
              {pairs.map((pair, pairIndex) => (
                <span key={pair.key}>
                  {pairIndex > 0 ? " · " : null}
                  <span className="text-ink-3">{humanise(pair.key)}</span> {pair.value}
                </span>
              ))}
            </span>
          ) : null}
          {entry.ref_id ? (
            <span className="t-code-sm lk-mono select-all break-all text-ink-3">
              {entry.ref_type ? `${entry.ref_type} ` : ""}
              {entry.ref_id}
            </span>
          ) : null}
        </span>
      ) : undefined,
  };
}

function TraceBody({ trace }: { trace: Trace }) {
  const first = trace.entries[0];
  const clock = useStepClock(first?.at);
  const failed = trace.entries.filter((entry) => entry.status !== null && BAD.has(entry.status)).length;

  return (
    <>
      <RecordHeader
        breadcrumb={CRUMBS}
        code={trace.correlation_id}
        title="Assistant request"
        status={
          <Badge tone="cobalt" icon={trace.access === "auditor" ? "shield" : "user"}>
            {ACCESS[trace.access] ?? humanise(trace.access)}
          </Badge>
        }
        lead="Everything this one request did, in order. Message text, tool inputs and tool outputs are redacted."
        facts={
          <FactStrip
            items={[
              { label: "Started", value: first ? <DateText value={first.at} style="dayTime" /> : null, icon: "clock" },
              { label: "Entries", value: formatCount(trace.entries.length) },
              { label: "Runs", value: formatCount(trace.run_ids.length) },
              { label: "Failed or declined", value: failed > 0 ? formatCount(failed) : "None" },
            ]}
          />
        }
        actions={
          <ButtonLink href={aiHref("usage") as Route} variant="secondary" iconLeft="arrowLeft">
            Back to usage
          </ButtonLink>
        }
      />
      <Split
        main={
          <GlassPanel as="section" padding="lg" title="What happened" titleAs="h2" className="rise">
            {trace.entries.length === 0 ? (
              <EmptyState compact icon="clock" title="Nothing recorded yet" text="The request has started but has not logged a step. Reload in a moment." />
            ) : (
              <Timeline label="Trace entries, oldest first" items={trace.entries.map((entry, index) => entryItem(entry, index, clock))} />
            )}
          </GlassPanel>
        }
        aside={
          <GlassPanel as="section" variant="outline" padding="md" title="Identifiers" titleAs="h2" className="rise">
            <KeyValue
              rows
              items={[
                { label: "Correlation id", value: <span className="select-all break-all">{trace.correlation_id}</span>, mono: true },
                ...trace.run_ids.map((id, index) => ({
                  label: trace.run_ids.length === 1 ? "Run" : `Run ${index + 1}`,
                  value: <span className="select-all break-all">{id}</span>,
                  mono: true,
                })),
              ]}
            />
            <p className="t-caption mt-4 text-ink-3">Quote the correlation id when you ask for help with this request.</p>
          </GlassPanel>
        }
      />
    </>
  );
}

/**
 * One assistant request, step by step: turns, runs, tool steps, model calls, receipts, events and
 * audit entries on a single timeline. An unknown id and a trace this person may not see look the
 * same on purpose.
 */
export function TraceScreen({ correlationId }: { correlationId: string | null }) {
  const query = useTrace(correlationId);
  const missing = correlationId === null || (query.isError && query.error instanceof ProblemError && query.error.status === 404);

  if (!missing && query.data) {
    return (
      <Page>
        <TraceBody trace={query.data} />
      </Page>
    );
  }

  return (
    <Page>
      <PageHeader breadcrumb={CRUMBS} title="Trace" lead="Everything one assistant request did, in order." />
      {missing ? (
        <GlassPanel padding="lg">
          <EmptyState
            icon="search"
            title="No trace to show for this id"
            text="Either it does not exist or it is not visible to you. Traces open for the person who made the request, and for auditors."
            actions={
              <ButtonLink href={aiHref("usage") as Route} variant="secondary" iconLeft="arrowLeft">
                Back to usage
              </ButtonLink>
            }
          />
        </GlassPanel>
      ) : query.isError ? (
        <ErrorBlock error={query.error} what="This trace" onRetry={() => void query.refetch()} />
      ) : (
        <LoadingBlock lines={8} label="Loading the trace" />
      )}
    </Page>
  );
}
