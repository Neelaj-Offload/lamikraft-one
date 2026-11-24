"use client";

import type { FeasibilityRead } from "@/features/production/api";
import { isPositiveDecimalStr } from "@/lib/format/decimal";
import { EVIDENCE_KIND, EVIDENCE_TONE, FEASIBILITY_OUTCOME, humanise } from "~/data/production";
import { Badge, DateText, Qty } from "~/ui";
import { StatusBadge } from "./parts";

/** One feasibility answer: the verdict, how much comes from stock and how much must be made, and the evidence behind it. */
export function Outcome({ result }: { result: FeasibilityRead }) {
  const look = FEASIBILITY_OUTCOME[result.outcome] ?? { label: humanise(result.outcome), tone: "neutral" as const };
  const quantity = (value: string) => <Qty value={{ value, uom: result.uom_code }} className="t-label text-ink" />;
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
        <StatusBadge look={look} />
        {result.earliest_completion ? (
          <span className="t-body-sm text-ink-2">
            Earliest finish <DateText value={result.earliest_completion} style="business" className="t-label text-ink" />
          </span>
        ) : null}
      </div>
      <p className="t-body-sm text-ink-2">
        {quantity(result.from_stock)} from stock
        {isPositiveDecimalStr(result.to_make) ? <>, {quantity(result.to_make)} to make</> : null}
        {result.warehouse ? <> in {result.warehouse.name}</> : null}.
      </p>
      {result.evidence.length > 0 ? (
        <ul aria-label="Why" className="flex flex-col gap-2">
          {result.evidence.map((item, index) => (
            <li key={`${item.kind}-${index}`} className="t-body-sm flex min-w-0 items-start gap-2 text-ink-2">
              <Badge tone={EVIDENCE_TONE[item.status] ?? "neutral"} size="sm" className="flex-none">
                {EVIDENCE_KIND[item.kind] ?? humanise(item.kind)}
              </Badge>
              <span className="min-w-0">{item.label}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {result.missing_inputs.length > 0 ? <p className="t-caption text-ink-3">Not known yet: {result.missing_inputs.join(", ")}.</p> : null}
    </div>
  );
}
