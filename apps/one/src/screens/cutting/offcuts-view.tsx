"use client";

import { useState } from "react";
import type { OffcutCandidate } from "@/features/cutting/api";
import type { PlanDetail, PlanOffcut } from "@/features/cutting/types";
import { useSession } from "@/lib/session/context";
import { toggledSelection, useOffcutCandidates, usePlanCommands } from "~/data/cutting";
import { ErrorBlock, LoadingBlock } from "~/shell/states";
import { Badge, Button, Checkbox, Code, EmptyState, GlassPanel } from "~/ui";
import { mm, Size, stagger } from "./parts";

/**
 * Offcut reuse. The lots the plan has chosen (size pinned when chosen, whether still on hand, whether
 * the latest layout used them) and, for people who may change the plan and read stock, the measured
 * lots on hand to choose from. Chosen lots are filled in the order picked, before any standard sheet.
 */
export function OffcutsView({ plan, editable }: { plan: PlanDetail; editable: boolean }) {
  const { permissionKeys } = useSession();
  const canChoose = editable && permissionKeys.has("inventory.stock.read");
  return (
    <div className="stack">
      <div className="flex min-w-0 flex-col gap-1">
        <h2 className="t-h3">Offcuts to use first</h2>
        <p className="t-body-sm max-w-prose text-ink-3">
          Measured offcut lots are filled before any standard sheet is opened. Each lot is checked again when the plan is released for a work order.
        </p>
      </div>
      <Chosen plan={plan} editable={editable} canChoose={canChoose} />
      {canChoose ? <Candidates key={plan.version} plan={plan} /> : null}
    </div>
  );
}

function ChosenBadges({ offcut }: { offcut: PlanOffcut }) {
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      {offcut.on_hand === false ? (
        <Badge tone="ember" size="sm" icon="alert">
          No longer on hand
        </Badge>
      ) : null}
      {!offcut.matches_group ? (
        <Badge tone="amber" size="sm">
          No piece matches its decor and thickness
        </Badge>
      ) : null}
      <Badge tone={offcut.used ? "leaf" : "neutral"} size="sm" icon={offcut.used ? "check" : undefined} outline={!offcut.used}>
        {offcut.used ? "Used in the layout" : "Not used in the layout"}
      </Badge>
    </span>
  );
}

function Chosen({ plan, editable, canChoose }: { plan: PlanDetail; editable: boolean; canChoose: boolean }) {
  if (plan.offcuts.length === 0 && canChoose) {
    return <p className="t-body-sm text-ink-2">No offcut is chosen yet, so this plan cuts from standard sheets only.</p>;
  }
  if (plan.offcuts.length === 0) {
    return (
      <GlassPanel padding="md" className="rise">
        <EmptyState compact icon="layers" title="No offcut chosen" text="This plan cuts from standard sheets only." />
      </GlassPanel>
    );
  }
  return (
    <GlassPanel padding="md" className="rise" title="Chosen for this plan" titleAs="h3">
      <ol className="flex flex-col divide-y divide-line">
        {plan.offcuts.map((offcut, index) => (
          <li key={offcut.lot_id} className="rise-plain flex min-w-0 flex-wrap items-center justify-between gap-3 py-3 first:pt-0 last:pb-0" style={stagger(index)}>
            <span className="flex min-w-0 items-baseline gap-3">
              <span className="t-caption lk-tnum w-5 flex-none text-right text-ink-3">{index + 1}</span>
              <span className="flex min-w-0 flex-col gap-0.5">
                <Code>{offcut.lot_code}</Code>
                <span className="t-caption text-ink-3">
                  <Size length={offcut.length_mm} width={offcut.width_mm} /> · {mm(offcut.thickness_mm)} mm thick{offcut.decor_key ? ` · decor ${offcut.decor_key}` : ""}
                </span>
              </span>
            </span>
            <ChosenBadges offcut={offcut} />
          </li>
        ))}
      </ol>
      {!editable ? <p className="t-caption mt-4 text-ink-3">This plan can no longer be changed, so its offcut choice is fixed.</p> : null}
    </GlassPanel>
  );
}

function Candidates({ plan }: { plan: PlanDetail }) {
  const query = useOffcutCandidates(plan.id, true);
  const commands = usePlanCommands(plan);
  const [selection, setSelection] = useState<string[]>(() => plan.offcuts.map((offcut) => offcut.lot_id));
  const saved = plan.offcuts.map((offcut) => offcut.lot_id);
  const changed = JSON.stringify(selection) !== JSON.stringify(saved);

  if (query.isPending) return <LoadingBlock lines={4} label="Loading offcut lots on hand" />;
  if (query.isError) return <ErrorBlock error={query.error} what="Offcut lots on hand" onRetry={() => void query.refetch()} />;
  if (!query.data.stock_visible) {
    return (
      <GlassPanel padding="md" className="rise">
        <EmptyState compact icon="lock" title="Stock is not visible to you" text="Offcut lots are listed for people who can read stock." />
      </GlassPanel>
    );
  }

  const items = query.data.items;
  return (
    <GlassPanel
      padding="md"
      className="rise"
      style={stagger(1)}
      title="Offcut lots on hand"
      titleAs="h3"
      action={
        items.length > 0 ? (
          <Button
            variant={changed ? "inverse" : "secondary"}
            size="sm"
            iconLeft="save"
            loading={commands.pending === "offcuts"}
            isDisabled={commands.offline || !changed}
            onPress={() => void commands.chooseOffcuts(selection)}
          >
            Save offcut choice
          </Button>
        ) : undefined
      }
    >
      {items.length === 0 ? (
        <EmptyState compact icon="warehouse" title="No measured offcut on hand" text="None of the warehouses you can see holds a measured offcut lot right now." />
      ) : (
        <>
          <p className="t-body-sm mb-4 text-ink-3">
            Tick the lots to use, in the order they should be filled. Saving a new choice marks a calculated layout out of date.
          </p>
          <ul className="flex flex-col divide-y divide-line">
            {items.map((candidate, index) => (
              <CandidateRow
                key={candidate.lot_id}
                index={index}
                candidate={candidate}
                order={selection.indexOf(candidate.lot_id)}
                onToggle={(on) => setSelection((current) => toggledSelection(current, candidate.lot_id, on))}
              />
            ))}
          </ul>
        </>
      )}
    </GlassPanel>
  );
}

function CandidateRow({ candidate: c, index, order, onToggle }: { candidate: OffcutCandidate; index: number; order: number; onToggle: (on: boolean) => void }) {
  const selected = order >= 0;
  return (
    <li className="rise-plain flex min-w-0 flex-wrap items-start justify-between gap-3 py-3 first:pt-0 last:pb-0" style={stagger(index)}>
      <Checkbox
        isSelected={selected}
        onChange={onToggle}
        label={
          <span className="flex min-w-0 flex-col gap-0.5">
            <span className="lk-mono t-label text-ink">{c.lot_code}</span>
            <span className="t-caption text-ink-3">
              <Size length={c.length_mm} width={c.width_mm} />
              {c.thickness_mm ? ` · ${mm(c.thickness_mm)} mm thick` : ""}
            </span>
          </span>
        }
        description={[c.product_name ?? c.product_key, `${c.warehouse_code} · ${c.location_code}`, c.other_plans?.length ? `also chosen for ${c.other_plans.join(", ")}` : null]
          .filter(Boolean)
          .join(" · ")}
      />
      <span className="flex flex-wrap items-center gap-1.5">
        {selected ? (
          <Badge tone="inverse" size="sm">
            {order === 0 ? "Filled first" : `Filled ${order + 1}${ordinal(order + 1)}`}
          </Badge>
        ) : null}
        <Badge tone={c.matches_group ? "leaf" : "amber"} size="sm" icon={c.matches_group ? "check" : undefined}>
          {c.matches_group ? "Matches a piece group" : "No piece matches"}
        </Badge>
      </span>
    </li>
  );
}

function ordinal(n: number): string {
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) return "th";
  return n % 10 === 1 ? "st" : n % 10 === 2 ? "nd" : n % 10 === 3 ? "rd" : "th";
}
