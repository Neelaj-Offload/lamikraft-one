"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, StatusPill, type Tone } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { DatePicker } from "@/components/ui/date-picker";
import { LocalDate } from "@/components/ui/format";
import { SectionCard } from "@/components/ui/section-card";
import { ErrorState, Loading } from "@/components/ui/states";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { productionMessages as m } from "@/messages/production";
import { fetchOrderLineFeasibility, type FeasibilityRead } from "./api";
import { qty } from "./common";
import { isPositiveDecimalStr } from "@/lib/format/decimal";

const f = m.feasibility;
const TONES: Record<string, Tone> = { feasible: "success", at_risk: "warning", not_feasible: "danger", estimate: "info" };
const EVIDENCE_TONES: Record<string, Tone> = { ok: "success", short: "danger", missing: "info", late: "warning", info: "neutral" };

export interface FeasibilityLine {
  id: string;
  line_no: number;
  description: string;
  product_key: string | null;
  qty_remaining: string;
  unit: string;
  line_kind: string;
}

/**
 * "Can we deliver this?" on the order's open stock lines: a read-only check (stock, open supply, components and
 * capacity evidence) that never reserves, posts or saves anything. Shown to actors holding `production.feasibility.run`.
 */
export function OrderFeasibilityPanel({ lines, requestedDate }: { lines: readonly FeasibilityLine[]; requestedDate: string | null }) {
  const { permissionKeys } = useSession();
  const open = lines.filter((l) => l.product_key && l.line_kind !== "charge" && isPositiveDecimalStr(l.qty_remaining));
  const [needBy, setNeedBy] = useState<string | null>(requestedDate);
  const [checking, setChecking] = useState<string | null>(null);
  if (!permissionKeys.has("production.feasibility.run") || open.length === 0) return null;
  return (
    <SectionCard title={f.title} description={f.intro}>
      <div className="flex flex-col gap-4">
        <DatePicker label={f.needBy} value={needBy} onChange={setNeedBy} description={requestedDate ? undefined : f.noDate} />
        <ul className="flex flex-col divide-y">
          {open.map((l) => (
            <li key={l.id} className="flex flex-col gap-2 py-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <span>
                  <span className="font-mono">{l.product_key}</span> · {qty(l.qty_remaining, l.unit)}
                </span>
                <Button size="sm" {...unavailableWhen((!needBy) ? m.fillIn : null)} onPress={() => setChecking(l.id)}>
                  {f.check}
                </Button>
              </div>
              {checking === l.id && needBy ? <Result lineId={l.id} needBy={needBy} /> : null}
            </li>
          ))}
        </ul>
      </div>
    </SectionCard>
  );
}

function Result({ lineId, needBy }: { lineId: string; needBy: string }) {
  const query = useQuery({ queryKey: queryKeys.production.feasibility(lineId, needBy), queryFn: ({ signal }) => fetchOrderLineFeasibility(lineId, needBy, signal) });
  if (query.isPending) return <Loading label={f.checking} />;
  if (query.isError) return <ErrorState error={query.error} what={f.failed} onRetry={() => void query.refetch()} />;
  return <Outcome result={query.data} />;
}

export function Outcome({ result }: { result: FeasibilityRead }) {
  return (
    <div className="flex flex-col gap-2 rounded-md bg-surface-sunken p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <StatusPill tone={TONES[result.outcome] ?? "neutral"}>{f.outcomes[result.outcome] ?? result.outcome}</StatusPill>
        <span>{f.fromStock(`${result.from_stock} ${result.uom_code}`)}</span>
        {isPositiveDecimalStr(result.to_make) ? <span>· {f.toMake(`${result.to_make} ${result.uom_code}`)}</span> : null}
        {result.earliest_completion ? (
          <span className="text-ink-muted">
            · {f.earliest} <LocalDate value={result.earliest_completion} />
          </span>
        ) : null}
      </div>
      <ul aria-label={f.evidence} className="flex flex-col gap-1">
        {result.evidence.map((e, i) => (
          <li key={`${e.kind}-${i}`} className="flex flex-wrap items-center gap-2">
            <Badge tone={EVIDENCE_TONES[e.status] ?? "neutral"}>{e.kind.replace("_", " ")}</Badge>
            <span>{e.label}</span>
          </li>
        ))}
      </ul>
      {result.missing_inputs.length ? (
        <p className="text-ink-muted">
          {f.missing}: {result.missing_inputs.join(", ")}
        </p>
      ) : null}
    </div>
  );
}
