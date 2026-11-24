"use client";

import type { Budget, AiStatus, PriceRow } from "@/features/ai-admin/types";
import { formatCount, formatDecimal } from "@/lib/format/money";
import { useZone } from "@/lib/session/context";
import { PageSection } from "~/shell/page";
import { DataTable, GlassPanel, KeyValue, type Column } from "~/ui";
import { humanise, workflowLabel } from "./format";
import { SavedRouting } from "./routing-setting";

const MODEL_ROLE: Record<string, string> = {
  phrasing: "Routing and phrasing",
  orchestrator: "Assistant",
  escalation: "Escalation",
  vision: "Vision",
};

const BUDGET_TASK: Record<string, string> = {
  orchestration: "Assistant runs",
  escalation: "Escalation",
  routing: "Request routing",
  phrasing: "Phrasing",
};

const QUOTA_NAME: Record<string, string> = {
  orchestrator_runs_per_user: "Assistant runs per person",
  escalations_per_user: "Escalations per person",
  vision_calls_per_user: "Vision calls per person",
  company_escalations: "Escalations for the company",
};

interface BudgetRow extends Budget {
  task: string;
}

/**
 * Routing: what the assistant uses right now (models, effort, limits, prices), then, for people
 * who may change it, the saved setting behind those values with its history and editor.
 */
export function RoutingView({ status }: { status: AiStatus }) {
  const { locale } = useZone();
  const count = (value: number) => formatCount(value, locale);
  const price = (value: string) => formatDecimal(value, { locale, maxFractionDigits: 4 }) ?? value;

  const budgets: BudgetRow[] = Object.entries(status.budgets).map(([task, budget]) => ({ task, ...budget }));
  const budgetColumns: Column<BudgetRow>[] = [
    { key: "task", header: "Task", primary: true, cell: (row) => <span className="t-label text-ink">{BUDGET_TASK[row.task] ?? humanise(row.task)}</span> },
    { key: "steps", header: "Steps", numeric: true, cell: (row) => count(row.steps) },
    { key: "seconds", header: "Time limit", numeric: true, cell: (row) => `${count(row.seconds)} s` },
    { key: "input", header: "Input tokens", numeric: true, cell: (row) => count(row.input_tokens) },
    { key: "max", header: "Tokens per call", numeric: true, cell: (row) => count(row.max_tokens) },
  ];
  const priceColumns: Column<PriceRow>[] = [
    { key: "model", header: "Model", primary: true, cell: (row) => <span className="t-code-sm lk-mono select-all break-all">{row.model}</span> },
    { key: "input", header: "Input", numeric: true, cell: (row) => price(row.input) },
    { key: "output", header: "Output", numeric: true, cell: (row) => price(row.output) },
    { key: "cache-read", header: "Cache read", numeric: true, cell: (row) => price(row.cache_read) },
    { key: "cache-write", header: "Cache write", numeric: true, cell: (row) => price(row.cache_write) },
  ];

  const models = Object.entries(status.models);
  const effort = Object.entries(status.effort);
  const quotas = Object.entries(status.quotas);

  return (
    <>
      <PageSection
        title="In use now"
        description="The models, effort and limits every assistant request runs under. Changing them needs a recent sign-in with two-step verification."
        index={1}
      >
        <div className="tiles" data-min="lg">
          <GlassPanel title="Models" padding="md">
            {models.length > 0 ? (
              <KeyValue rows items={models.map(([role, model]) => ({ label: MODEL_ROLE[role] ?? humanise(role), value: model, mono: true }))} />
            ) : (
              <p className="t-body-sm text-ink-3">The server reported no models.</p>
            )}
          </GlassPanel>
          <GlassPanel title="Effort and daily quotas" padding="md">
            <KeyValue
              rows
              items={[
                ...effort.map(([task, level]) => ({ label: `Effort, ${workflowLabel(task).toLowerCase()}`, value: humanise(level) })),
                ...quotas.map(([name, limit]) => ({ label: QUOTA_NAME[name] ?? humanise(name), value: <span className="lk-tnum">{count(limit)}</span> })),
              ]}
            />
          </GlassPanel>
        </div>
      </PageSection>

      <PageSection title="Run budgets" description="Where a single request stops: steps, seconds and tokens, per kind of task." index={2}>
        <GlassPanel padding="none">
          <DataTable label="Run budgets" columns={budgetColumns} rows={budgets} rowKey={(row) => row.task} />
        </GlassPanel>
      </PageSection>

      <PageSection title="Price table" description={`${status.price_currency} per million tokens. Used only to estimate cost on the usage view.`} index={3}>
        <GlassPanel padding="none">
          <DataTable label="Price table" columns={priceColumns} rows={status.prices} rowKey={(row) => row.model} />
        </GlassPanel>
      </PageSection>

      {status.can_manage_routing ? <SavedRouting /> : null}
    </>
  );
}
