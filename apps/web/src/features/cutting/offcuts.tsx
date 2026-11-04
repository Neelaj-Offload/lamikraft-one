"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/choice";
import { Loading } from "@/components/ui/states";
import { toast } from "@/components/ui/toast";
import { commandSignature, createCommandKeys } from "@/lib/api/command-keys";
import { conflictFromError, ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { useOnline } from "@/lib/hooks";
import { useSession } from "@/lib/session/context";
import { fetchOffcutCandidates, saveOffcuts, type OffcutCandidate } from "./api";
import { cuttingMessages as m } from "./messages";
import { QueryFailure } from "./query-failure";
import type { PlanDetail, PlanOffcut } from "./types";

const o = m.offcuts;

function problemText(error: unknown): string | undefined {
  if (!(error instanceof ProblemError)) return undefined;
  return [error.detail ?? error.title, error.request_id ? `Reference: ${error.request_id}` : null].filter(Boolean).join(" ");
}

/** The selection after toggling one lot, keeping the order the planner chose (the optimiser fills in this order). */
export function toggledSelection(current: readonly string[], lotId: string, on: boolean): string[] {
  const without = current.filter((id) => id !== lotId);
  return on ? [...without, lotId] : without;
}

function ChosenStatus({ offcut }: { offcut: PlanOffcut }) {
  return (
    <span className="inline-flex flex-wrap gap-1.5">
      {offcut.on_hand === false ? <Badge tone="danger">{o.gone}</Badge> : null}
      {!offcut.matches_group ? <Badge tone="warning">{o.noMatch}</Badge> : null}
      <Badge tone={offcut.used ? "success" : "neutral"}>{offcut.used ? o.used : o.notUsed}</Badge>
    </span>
  );
}

/**
 * Offcut reuse on a cut plan: the lots chosen (pinned size, whether still on hand, whether the latest layout used them)
 * and, for people who may edit the plan and read stock, the measured offcut lots on hand to choose from. Saving a new
 * choice marks a calculated plan stale; the server re-checks every lot (422 when one is no longer available).
 */
export function PlanOffcuts({ plan }: { plan: PlanDetail }) {
  const headingId = useId();
  const { permissionKeys } = useSession();
  const editable = plan.capabilities.update?.allowed === true;
  const canChoose = editable && permissionKeys.has("inventory.stock.read");
  const [open, setOpen] = useState(false);
  if (!plan.offcuts.length && !canChoose) return null;
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3 rounded-lg border bg-canvas p-4 md:p-5">
      <header className="flex flex-col gap-1">
        <h2 id={headingId} className="text-lg font-[650] text-ink">
          {o.title}
        </h2>
        <p className="text-sm text-ink-muted">{o.intro}</p>
      </header>
      {plan.offcuts.length ? (
        <ul aria-label={o.title} className="flex flex-col divide-y">
          {plan.offcuts.map((x) => (
            <li key={x.lot_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span>
                <span className="font-mono">{x.lot_code}</span> <span className="tabular text-ink-muted">· {o.size(x.length_mm, x.width_mm)} · {x.thickness_mm} mm</span>
              </span>
              <ChosenStatus offcut={x} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-ink-muted">{o.none}</p>
      )}
      {!editable && plan.offcuts.length ? <p className="text-sm text-ink-muted">{o.readOnly}</p> : null}
      {canChoose ? (
        <div>
          <Button onPress={() => setOpen((v) => !v)} aria-expanded={open}>
            {open ? o.hide : o.choose}
          </Button>
        </div>
      ) : null}
      {canChoose && open ? <Candidates plan={plan} onSaved={() => setOpen(false)} /> : null}
    </section>
  );
}

function Candidates({ plan, onSaved }: { plan: PlanDetail; onSaved: () => void }) {
  const queryClient = useQueryClient();
  const online = useOnline();
  const [keys] = useState(() => createCommandKeys());
  const [pending, setPending] = useState(false);
  const [selection, setSelection] = useState<string[]>(() => plan.offcuts.map((x) => x.lot_id));
  const query = useQuery({ queryKey: queryKeys.cutting.offcutCandidates(plan.id), queryFn: ({ signal }) => fetchOffcutCandidates(plan.id, signal) });
  if (query.isPending) return <Loading label={o.loading} />;
  if (query.isError) return <QueryFailure error={query.error} what={o.loading} onRetry={() => void query.refetch()} />;
  if (!query.data.stock_visible) return <p className="text-ink-muted">{o.noStock}</p>;
  const changed = JSON.stringify(selection) !== JSON.stringify(plan.offcuts.map((x) => x.lot_id));
  const save = async () => {
    const signature = commandSignature(plan.id, "offcuts", plan.version, selection.join(","));
    const attempt = keys.attempt(signature, () => null);
    setPending(true);
    try {
      const saved = await saveOffcuts(plan, selection, attempt.key);
      keys.settle(signature);
      queryClient.setQueryData(queryKeys.cutting.plan(plan.id), saved);
      void queryClient.invalidateQueries({ queryKey: queryKeys.cutting.offcutCandidates(plan.id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.cutting.allPlans() });
      toast.success(o.saved);
      onSaved();
    } catch (error) {
      keys.settle(signature, error);
      if (conflictFromError(error)) void queryClient.invalidateQueries({ queryKey: queryKeys.cutting.plan(plan.id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.cutting.offcutCandidates(plan.id) });
      toast.error(o.failed, { description: problemText(error) });
    } finally {
      setPending(false);
    }
  };
  const items = query.data.items;
  return (
    <div className="flex flex-col gap-3">
      <h3 className="font-[650] text-ink">{o.candidatesTitle}</h3>
      {items.length === 0 ? (
        <p className="text-ink-muted">{o.emptyCandidates}</p>
      ) : (
        <ul className="flex flex-col divide-y">
          {items.map((c) => (
            <CandidateRow key={c.lot_id} candidate={c} selected={selection.includes(c.lot_id)} onToggle={(on) => setSelection((s) => toggledSelection(s, c.lot_id, on))} />
          ))}
        </ul>
      )}
      <div>
        <Button variant="primary" isPending={pending} {...unavailableWhen(!online ? o.offline : !changed ? o.unchanged : null)} onPress={() => void save()}>
          {o.save}
        </Button>
      </div>
    </div>
  );
}

function CandidateRow({ candidate: c, selected, onToggle }: { candidate: OffcutCandidate; selected: boolean; onToggle: (on: boolean) => void }) {
  return (
    <li className="flex flex-col gap-1 py-2">
      <Checkbox isSelected={selected} onChange={onToggle} aria-label={o.pick(c.lot_code)}>
        <span>
          <span className="font-mono">{c.lot_code}</span>{" "}
          <span className="tabular text-ink-muted">
            · {o.size(c.length_mm, c.width_mm)}
            {c.thickness_mm ? ` · ${c.thickness_mm} mm` : ""}
          </span>
        </span>
      </Checkbox>
      <span className="flex flex-wrap items-center gap-1.5 pl-9 text-sm text-ink-muted">
        <span>{c.product_name ?? c.product_key ?? ""}</span>
        <span>· {o.where(c.warehouse_code, c.location_code)}</span>
        <Badge tone={c.matches_group ? "success" : "warning"}>{c.matches_group ? o.match : o.noMatch}</Badge>
        {c.other_plans?.length ? <span>· {o.alsoChosen(c.other_plans.join(", "))}</span> : null}
      </span>
    </li>
  );
}
