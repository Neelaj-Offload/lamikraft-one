"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent, type ReactNode } from "react";
import type { PlanDetail } from "@/features/cutting/types";
import { formatCount } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { asRoute, isCalculating, MODE_LABEL, usePlan, usePlanCommands, usePlanEditor } from "~/data/cutting";
import { Steps, type StepItem } from "~/screens/sales/quotations/parts";
import { Page, RecordHeader, Split } from "~/shell/page";
import { ErrorBlock, LoadingBlock } from "~/shell/states";
import {
  Banner,
  Button,
  ButtonLink,
  ConfirmDialog,
  DateText,
  DecimalField,
  ExternalLink,
  FactStrip,
  GlassPanel,
  Icon,
  KeyValue,
  Menu,
  Skeleton,
  SkeletonText,
  Tabs,
  Textarea,
  type MenuItem,
} from "~/ui";
import { LayoutView } from "./layout-view";
import { OffcutsView } from "./offcuts-view";
import { Measure, mm, Pct, PlanFlags, PlanStatusBadge, Size, stagger } from "./parts";
import { ConflictBanner } from "./plan-form";
import { PiecesView } from "./pieces-view";
import { planViewHref, type PlanView } from "./views";

/** A saved cut plan: where it stands, its cut list and board, the offcuts it may use and the calculated layout. */
export function PlanRecord({ planId, view }: { planId: string; view: PlanView }) {
  const query = usePlan(planId);
  if (query.isPending) {
    return (
      <Page>
        <div className="lk-glass record-head" role="status" aria-label="Loading the cut plan">
          <Skeleton width="120px" height={14} />
          <Skeleton width="45%" height={32} />
          <SkeletonText lines={2} />
        </div>
        <LoadingBlock lines={6} label="Loading the cut plan" />
      </Page>
    );
  }
  if (query.isError) {
    return (
      <Page>
        <ErrorBlock error={query.error} what="This cut plan" onRetry={() => void query.refetch()} />
        <div>
          <ButtonLink href="/operations/cutting" variant="secondary" iconLeft="arrowLeft">
            All cut plans
          </ButtonLink>
        </div>
      </Page>
    );
  }
  return <Loaded key={query.data.id} plan={query.data} view={view} />;
}

const pieceTotal = (plan: PlanDetail) => plan.items.reduce((sum, item) => sum + item.quantity, 0);

function Loaded({ plan, view: asked }: { plan: PlanDetail; view: PlanView }) {
  const router = useRouter();
  const { permissionKeys, zone } = useSession();
  const editor = usePlanEditor(plan);
  const commands = usePlanCommands(plan);
  const [archiving, setArchiving] = useState(false);

  const editable = plan.capabilities.update?.allowed === true;
  const canCalculate = editable && plan.capabilities.calculate?.allowed === true;
  const canDuplicate = plan.capabilities.duplicate?.allowed === true;
  const canArchive = plan.allowed_transitions.some((transition) => transition.action === "archive");
  const showOffcuts = plan.offcuts.length > 0 || (editable && permissionKeys.has("inventory.stock.read"));
  const view: PlanView = asked === "offcuts" && !showOffcuts ? "overview" : asked;
  const busy = isCalculating(plan);
  const offline = editor.offline || commands.offline;
  const path = `/operations/cutting/${plan.id}`;
  const totals = plan.latest_calculation?.totals ?? null;
  const pieces = pieceTotal(plan);

  const menu: MenuItem[] = [];
  if (canDuplicate) {
    menu.push({
      id: "duplicate",
      label: "Duplicate as a new draft",
      icon: "copy",
      description: "Same pieces and board, a new plan number",
      isDisabled: offline || commands.pending !== null,
      onAction: () =>
        void commands.duplicate().then((copy) => {
          if (copy) router.push(asRoute(copy.path));
        }),
    });
  }
  if (canArchive) {
    if (menu.length > 0) menu.push({ id: "sep", separator: true });
    menu.push({ id: "archive", label: "Archive plan", icon: "archive", tone: "danger", isDisabled: offline, onAction: () => setArchiving(true) });
  }

  return (
    <Page>
      <RecordHeader
        breadcrumb={[{ label: "Operations", href: "/operations" }, { label: "Cut plans", href: "/operations/cutting" }, { label: plan.plan_number }]}
        code={plan.plan_number}
        title={plan.name}
        status={
          <>
            <PlanStatusBadge status={plan.status} />
            <PlanFlags
              plan={{ calc_status: plan.calculation.status, stale: plan.stale, requires_physical_verification: plan.verification.required, verified: plan.verification.verified }}
            />
          </>
        }
        lead={[plan.owner.display_name ? `Planned by ${plan.owner.display_name}` : null, plan.duplicated_from ? `copied from ${plan.duplicated_from}` : null].filter(Boolean).join(", ") || undefined}
        facts={
          <FactStrip
            items={[
              { label: "Pieces", icon: "shapes", value: <span className="lk-tnum">{formatCount(pieces, zone.locale)}</span> },
              { label: "Boards", icon: "layers", value: totals ? <span className="lk-tnum">{formatCount(totals.boards, zone.locale)}</span> : null },
              { label: "Board used", icon: "percent", value: totals ? <Pct value={totals.efficiency_usable_pct} /> : null },
              { label: "Layout", icon: "grid", value: MODE_LABEL[plan.settings.mode]?.split(",")[0] ?? plan.settings.mode },
              { label: "Updated", icon: "clock", value: <DateText value={plan.updated_at} style="relative" /> },
            ]}
          />
        }
        actions={
          <>
            {canCalculate ? (
              <Button
                variant={editor.dirty ? "secondary" : "primary"}
                iconLeft="calculator"
                loading={editor.pending === "calculate" || busy}
                isDisabled={offline || editor.dirty || editor.pending !== null}
                onPress={() => void editor.calculate()}
              >
                {busy ? "Calculating" : plan.latest_calculation ? "Calculate again" : "Calculate layout"}
              </Button>
            ) : null}
            {menu.length > 0 ? (
              <Menu
                label="More plan actions"
                items={menu}
                placement="bottom end"
                trigger={
                  <Button variant="secondary" iconRight="chevronDown" loading={commands.pending === "duplicate"}>
                    More
                  </Button>
                }
              />
            ) : null}
          </>
        }
      >
        <Tabs
          label="Views of this cut plan"
          selectedKey={view}
          tabs={[
            { id: "overview", label: "Overview", href: asRoute(path) },
            { id: "pieces", label: "Pieces and board", count: plan.items.length, href: asRoute(planViewHref(path, "pieces")) },
            ...(showOffcuts ? [{ id: "offcuts", label: "Offcuts", count: plan.offcuts.length, href: asRoute(planViewHref(path, "offcuts")) }] : []),
            { id: "layout", label: "Layout", count: totals?.boards, href: asRoute(planViewHref(path, "layout")) },
          ]}
        />
      </RecordHeader>

      {offline ? (
        <Banner tone="amber" title="You are offline.">
          You can read this plan. Saving and calculating work again once the connection is back.
        </Banner>
      ) : null}
      <ConflictBanner editor={editor} />
      <CalculationBanner plan={plan} />
      {editor.dirty && view !== "pieces" && editable ? (
        <Banner
          tone="amber"
          title="You have unsaved changes to the pieces or the board."
          action={
            <ButtonLink href={asRoute(planViewHref(path, "pieces"))} variant="secondary" size="sm">
              Review changes
            </ButtonLink>
          }
        >
          Save them before you calculate.
        </Banner>
      ) : null}

      {view === "overview" ? <Overview plan={plan} canCalculate={canCalculate} /> : null}
      {view === "pieces" ? <PiecesView plan={plan} editor={editor} editable={editable} /> : null}
      {view === "offcuts" ? <OffcutsView plan={plan} editable={editable} /> : null}
      {view === "layout" ? <LayoutView plan={plan} canCalculate={canCalculate} editor={editor} /> : null}

      <ConfirmDialog
        isOpen={archiving}
        onOpenChange={setArchiving}
        tone="danger"
        title={`Archive ${plan.plan_number}?`}
        description="It stays readable and exportable, but it can no longer be changed or calculated."
        confirmLabel="Archive plan"
        cancelLabel="Keep it open"
        onConfirm={async () => {
          const saved = await commands.archive();
          if (!saved) throw new Error("not archived");
        }}
      />
    </Page>
  );
}

/** A calculation in flight, or one that failed. */
function CalculationBanner({ plan }: { plan: PlanDetail }) {
  const calc = plan.calculation;
  if (calc.status === "queued" || calc.status === "running") {
    return (
      <Banner tone="cobalt" icon="timer" title={`Laying out ${calc.pieces === 1 ? "1 piece" : `${calc.pieces} pieces`} in the background.`}>
        This page updates by itself when the layout is ready.
      </Banner>
    );
  }
  if (calc.status === "failed") {
    return (
      <Banner tone="ember" title="The last calculation failed.">
        {calc.error?.detail ?? "The server could not lay the pieces out."} Check the pieces and the board, then calculate again.
      </Banner>
    );
  }
  return null;
}

// ---------------------------------------------------------------------------------------------
// Overview: where the plan stands and what comes next

function progressOf(plan: PlanDetail): StepItem[] {
  const calc = plan.latest_calculation;
  const archived = plan.status === "archived";
  const released = plan.status === "released";
  const rows = plan.items.length;
  const raw: { id: string; label: string; hint: ReactNode; done: boolean }[] = [
    { id: "pieces", label: "Cut list", hint: rows === 0 ? "What to cut" : rows === 1 ? "1 row" : `${rows} rows`, done: rows > 0 },
    {
      id: "layout",
      label: "Layout",
      hint: isCalculating(plan) ? "Calculating" : calc ? (plan.stale ? "Inputs changed" : `Calculation ${calc.calc_no ?? ""}`.trim()) : "Pieces on boards",
      done: Boolean(calc) && !plan.stale,
    },
    ...(plan.verification.required
      ? [{ id: "verify", label: "Boards measured", hint: plan.verification.verified ? "Verified" : "Before release", done: plan.verification.verified }]
      : []),
    { id: "released", label: "Released", hint: "For a work order", done: released },
  ];
  const current = archived ? -1 : raw.findIndex((step) => !step.done);
  return raw.map((step, index) => ({ id: step.id, label: step.label, hint: step.hint, state: step.done ? "done" : index === current ? "current" : "todo" }));
}

function standingOf(plan: PlanDetail, canCalculate: boolean): { headline: ReactNode; body: string } {
  const calc = plan.latest_calculation;
  const v = plan.verification;
  if (plan.status === "archived") return { headline: "Archived", body: "It stays readable and exportable, but it can no longer be changed or calculated." };
  if (isCalculating(plan)) {
    return { headline: <>Laying out the <em>pieces</em></>, body: "The calculation runs in the background on large plans. This page updates when it is ready." };
  }
  if (plan.calculation.status === "failed") return { headline: <>The calculation <em>failed</em></>, body: "Check the pieces and the board, then calculate again." };
  if (plan.items.length === 0) return { headline: <>Start with the <em>pieces</em></>, body: "List what needs cutting under Pieces and board, then calculate the layout." };
  if (!calc) {
    return {
      headline: <>Ready to <em>calculate</em></>,
      body: canCalculate ? "The cut list and the board are saved. Calculate to lay the pieces out on boards." : "No layout has been calculated for this plan.",
    };
  }
  if (plan.stale) return { headline: <>The layout is <em>out of date</em></>, body: "The pieces, the board or the offcut choice changed after this layout was calculated. Calculate again to update it." };
  if (v.required && !v.verified) {
    return {
      headline: <>Measure the <em>boards</em></>,
      body: `This layout counts on boards of ${mm(v.assumed_length_mm ?? "0")} × ${mm(v.assumed_width_mm ?? "0")} mm. Measure them before the plan is released.`,
    };
  }
  if (plan.status === "released") return { headline: <>Released for <em>cutting</em></>, body: "The layout is fixed. Export it for the saw or the CNC." };
  const boards = calc.totals.boards;
  return {
    headline: (
      <>
        Laid out on {boards} <em>{boards === 1 ? "board" : "boards"}</em>
      </>
    ),
    body: "Export the plan for the saw, or open Layout to check every board.",
  };
}

function Overview({ plan, canCalculate }: { plan: PlanDetail; canCalculate: boolean }) {
  const standing = standingOf(plan, canCalculate);
  const calc = plan.latest_calculation;
  const s = plan.settings;
  const exports = plan.exports;
  return (
    <Split
      main={
        <>
          <GlassPanel padding="lg" className="rise flex flex-col gap-6" eyebrow="Where it stands">
            <Steps label="Progress of this cut plan" steps={progressOf(plan)} />
            <div className="flex max-w-prose flex-col gap-2">
              <h2 className="t-display-sm text-ink">{standing.headline}</h2>
              <p className="t-body text-ink-2">{standing.body}</p>
            </div>
          </GlassPanel>

          <Verification plan={plan} />

          {calc ? (
            <section aria-label="The latest layout" className="lk-glass lk-glass-inverse rise flex min-w-0 flex-col gap-5 rounded-xl p-6" style={stagger(1)}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="t-overline opacity-70">The latest layout</h2>
                <span className="t-caption opacity-70">
                  {calc.calc_no ? `Calculation ${calc.calc_no}` : "Calculated"}
                  {calc.created_at ? (
                    <>
                      {" · "}
                      <DateText value={calc.created_at} style="dayTime" />
                    </>
                  ) : null}
                </span>
              </div>
              <div className="flex flex-wrap items-end gap-x-10 gap-y-4">
                <div className="flex flex-col gap-1">
                  <span className="t-stat-xl lk-tnum">{calc.totals.boards}</span>
                  <span className="t-body-sm opacity-80">
                    {calc.totals.boards === 1 ? "board" : "boards"}, at least {calc.totals.lower_bound_boards} by area
                    {calc.totals.offcut_boards > 0 ? ` · ${calc.totals.offcut_boards} from offcuts` : ""}
                  </span>
                </div>
                <dl className="grid min-w-0 flex-1 grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
                  <InverseFigure label="Board used" value={<Pct value={calc.totals.efficiency_usable_pct} />} />
                  <InverseFigure label="Scrap" value={<Pct value={calc.totals.scrap_pct} />} />
                  <InverseFigure label="Pieces placed" value={`${calc.totals.placed_required} of ${calc.totals.required}`} />
                  <InverseFigure label="Did not fit" value={String(calc.totals.unfit)} />
                </dl>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-on-inverse/20 pt-4">
                <p className="t-body-sm opacity-80">A heuristic layout: good, not guaranteed to be the best possible.</p>
                <ButtonLink href={asRoute(planViewHref(`/operations/cutting/${plan.id}`, "layout"))} variant="secondary" size="sm" iconRight="arrowRight">
                  See every board
                </ButtonLink>
              </div>
            </section>
          ) : null}
        </>
      }
      aside={
        <>
          <GlassPanel padding="md" className="rise" title="Board and machine" titleAs="h2">
            <KeyValue
              rows
              items={[
                { label: "Board", value: <Size length={s.board_length_mm} width={s.board_width_mm} /> },
                { label: "Usable area", value: <Size length={s.usable_length_mm} width={s.usable_width_mm} /> },
                { label: "Edge margin", value: <Measure value={s.margin_mm} unit="mm" digits={1} /> },
                { label: "Cutting gap", value: <Measure value={s.gap_mm} unit="mm" digits={1} /> },
                { label: "Layout", value: MODE_LABEL[s.mode] ?? s.mode },
                { label: "Oversize boards", value: s.oversize_enabled ? `Yes, ${mm(s.oversize_mm)} mm each side` : "No" },
                { label: "Extra pieces", value: s.overproduction_enabled ? `Up to ${s.max_extra_qty} a row, ${mm(s.max_extra_pct)}% of required` : "No" },
              ]}
            />
          </GlassPanel>
          {exports.csv || exports.summary_csv || exports.pdf ? (
            <GlassPanel padding="md" className="rise" title="Take it to the saw" titleAs="h2">
              <ul className="flex flex-col gap-3">
                {exports.pdf ? (
                  <li>
                    <ExternalLink href={exports.pdf} className="t-body-sm">
                      Plan with board drawings, PDF
                    </ExternalLink>
                  </li>
                ) : null}
                {exports.csv ? <DownloadLink href={exports.csv}>Placements, CSV</DownloadLink> : null}
                {exports.summary_csv ? <DownloadLink href={exports.summary_csv}>Summary, CSV</DownloadLink> : null}
              </ul>
            </GlassPanel>
          ) : null}
          {plan.warnings.length > 0 ? (
            <Banner tone="amber" title="Worth knowing">
              {plan.warnings.join(" ")}
            </Banner>
          ) : null}
        </>
      }
    />
  );
}

function InverseFigure({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <dt className="t-caption opacity-70">{label}</dt>
      <dd className="t-stat-sm lk-tnum">{value}</dd>
    </div>
  );
}

/** A file the browser downloads with the session cookie (CSV exports). */
function DownloadLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <li>
      <a href={href} className="lk-link t-body-sm inline-flex items-center gap-1.5">
        <Icon name="download" size={14} />
        {children}
      </a>
    </li>
  );
}

// ---------------------------------------------------------------------------------------------
// Board verification: a layout that counts on oversize boards needs them measured before release

function Verification({ plan }: { plan: PlanDetail }) {
  const commands = usePlanCommands(plan);
  const [length, setLength] = useState("");
  const [width, setWidth] = useState("");
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<{ length?: string; width?: string }>({});
  const v = plan.verification;
  if (!v.required) return null;

  if (v.verified) {
    return (
      <Banner tone="leaf" icon="badgeCheck" title="Boards measured.">
        Verified by {v.verified_by?.display_name ?? "someone on the team"}
        {v.verified_at ? (
          <>
            {" "}
            <DateText value={v.verified_at} style="dayTime" />
          </>
        ) : null}
        .
      </Banner>
    );
  }

  const canVerify = plan.capabilities.verify?.allowed === true;
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const next = { length: length ? undefined : "Enter the length you measured.", width: width ? undefined : "Enter the width you measured." };
    setErrors(next);
    if (next.length || next.width) return;
    const saved = await commands.verify({ length_mm: length, width_mm: width, note });
    if (saved) {
      setLength("");
      setWidth("");
      setNote("");
    }
  };

  return (
    <GlassPanel
      as="section"
      padding="lg"
      className="rise flex flex-col gap-4"
      style={stagger(1)}
      eyebrow="Before release"
      title="Measure the boards"
      titleAs="h2"
    >
      <p className="t-body text-ink-2">
        This layout counts on boards of{" "}
        <Size length={v.assumed_length_mm ?? "0"} width={v.assumed_width_mm ?? "0"} className="t-label text-ink" />. Measure a board and record what you find.
      </p>
      {v.outcome === "smaller_than_assumed" ? (
        <Banner tone="ember" title="The boards measured smaller than assumed.">
          Turn oversize off, or enter the measured size as the board, then calculate again.
        </Banner>
      ) : null}
      {canVerify ? (
        <form onSubmit={(event) => void submit(event)} noValidate className="grid min-w-0 grid-cols-1 items-start gap-4 sm:grid-cols-2">
          <DecimalField label="Measured length" suffix="mm" value={length} onChange={setLength} maxFractionDigits={1} isRequired error={errors.length} />
          <DecimalField label="Measured width" suffix="mm" value={width} onChange={setWidth} maxFractionDigits={1} isRequired error={errors.width} />
          <Textarea className="sm:col-span-2" label="Note" optional rows={2} maxLength={500} value={note} onChange={setNote} />
          <div className="sm:col-span-2">
            <Button type="submit" variant="inverse" iconLeft="ruler" loading={commands.pending === "verify"} isDisabled={commands.offline}>
              Record measurement
            </Button>
          </div>
        </form>
      ) : (
        <p className="t-body-sm text-ink-3">Someone with the right to verify boards records the measurement.</p>
      )}
    </GlassPanel>
  );
}
