"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState, type ReactNode } from "react";
import {
  completeOperation,
  fetchWorkOrder,
  recheckWorkOrder,
  transitionWorkOrder,
  type MaterialRead,
  type OperationRead,
  type WorkOrderRead,
} from "@/features/production/api";
import { cx } from "@/lib/cx";
import { queryKeys } from "@/lib/api/query-keys";
import { isPositiveDecimalStr } from "@/lib/format/decimal";
import { asRoute, CANCEL_REASONS, humanise, POSTING_KIND, useProductionCommand, workOrderStatus } from "~/data/production";
import { Page, RecordHeader, Split } from "~/shell/page";
import {
  Badge,
  Banner,
  Button,
  Code,
  DataTable,
  DateText,
  EmptyState,
  FactStrip,
  GlassPanel,
  Icon,
  KeyValue,
  Menu,
  ProgressBar,
  Qty,
  Tabs,
  TextLink,
  Timeline,
  type Column,
  type IconName,
  type MenuItem,
  type TimelineItem,
} from "~/ui";
import { Steps, type StepItem } from "../sales/quotations/parts";
import { BlockedBadge, Minutes, OPERATIONS_CRUMB, PATHS, RecordFailed, RecordLoading, stagger, StatusBadge, useCanOpen, versionLabel, ViewHeading } from "./parts";
import { viewHref, type WorkOrderView } from "./views";
import { CancelDialog, IssueDialog, OffcutDialog, OutputDialog, PlanDialog, remainingToMake, WipDialog } from "./work-order-dialogs";

const FAILED = "That did not go through";

/** A work order: where it stands, its materials, its operations and what it has posted to stock. */
export function WorkOrderRecord({ workOrderId, view }: { workOrderId: string; view: WorkOrderView }) {
  const query = useQuery({ queryKey: queryKeys.production.workOrder(workOrderId), queryFn: ({ signal }) => fetchWorkOrder(workOrderId, signal) });
  if (query.isPending) return <RecordLoading label="Loading the work order" />;
  if (query.isError) return <RecordFailed error={query.error} what="This work order" onRetry={() => void query.refetch()} backHref={PATHS.workOrders} backLabel="All work orders" />;
  return <Loaded wo={query.data} view={view} />;
}

type DialogKind = "issue" | "consume" | "return" | "output" | "cancel" | "offcut" | "plan" | null;
type Step = { id: string; label: string; icon: IconName; ready: boolean; pendingName?: string; run: () => void };

function Loaded({ wo, view }: { wo: WorkOrderRead; view: WorkOrderView }) {
  const canOpen = useCanOpen();
  const key = useMemo(() => queryKeys.production.workOrder(wo.id), [wo.id]);
  const { run, pending, offline } = useProductionCommand<WorkOrderRead>(key);
  const [open, setOpen] = useState<DialogKind>(null);
  const [planOperation, setPlanOperation] = useState<OperationRead | null>(null);
  const can = (name: string) => Boolean(wo.capabilities[name]?.allowed);
  const write = (record: WorkOrderRead) => record;
  const path = `${PATHS.workOrders}/${wo.id}`;
  const act = (action: "release" | "complete" | "close", done: string) => void run(action, (k) => transitionWorkOrder(wo, action, k), { done, failed: FAILED, write });

  const left = remainingToMake(wo);
  const stillToMake = isPositiveDecimalStr(left);
  const toIssue = wo.materials.some((material) => isPositiveDecimalStr(material.qty_to_issue));
  const inWip = wo.materials.some((material) => isPositiveDecimalStr(material.qty_in_wip));

  // The forward steps in the order the floor takes them. The first one that has work waiting leads.
  const steps: Step[] = [];
  if (can("release")) steps.push({ id: "release", label: "Release to the floor", icon: "play", ready: true, pendingName: "release", run: () => act("release", "Released. Its materials are reserved") });
  if (can("issue")) steps.push({ id: "issue", label: "Issue material", icon: "packageOpen", ready: toIssue, run: () => setOpen("issue") });
  if (can("consume")) steps.push({ id: "consume", label: "Consume material", icon: "hammer", ready: inWip, run: () => setOpen("consume") });
  if (can("output")) steps.push({ id: "output", label: "Report output", icon: "boxes", ready: stillToMake, run: () => setOpen("output") });
  if (can("complete")) steps.push({ id: "complete", label: "Complete work order", icon: "check", ready: !stillToMake, pendingName: "complete", run: () => act("complete", "Work order completed") });
  if (can("close")) steps.push({ id: "close", label: "Close work order", icon: "archive", ready: true, pendingName: "close", run: () => act("close", "Work order closed") });
  const lead = steps.find((step) => step.ready) ?? steps[0];
  const rest = steps.filter((step) => step !== lead);
  const [second, ...others] = rest;

  const menu: MenuItem[] = others.map((step) => ({ id: step.id, label: step.label, icon: step.icon, isDisabled: Boolean(offline), onAction: step.run }));
  if (can("return")) {
    menu.push({ id: "return", label: "Return material to stock", icon: "undo", description: "Sends unused material back from the floor", isDisabled: Boolean(offline), onAction: () => setOpen("return") });
  }
  if (can("cancel")) {
    if (menu.length > 0) menu.push({ id: "sep", separator: true });
    menu.push({ id: "cancel", label: "Cancel work order", icon: "xCircle", tone: "danger", isDisabled: Boolean(offline), onAction: () => setOpen("cancel") });
  }

  const dialog = { wo, run, pending, onClose: () => setOpen(null) };
  const cancelReason = CANCEL_REASONS.find((reason) => reason.id === wo.cancel_reason_code)?.label ?? (wo.cancel_reason_code ? humanise(wo.cancel_reason_code) : null);

  return (
    <Page>
      <RecordHeader
        breadcrumb={[OPERATIONS_CRUMB, { label: "Work orders", href: PATHS.workOrders }, { label: wo.wo_number }]}
        code={wo.wo_number}
        title={wo.product.name}
        status={
          <>
            <StatusBadge look={workOrderStatus(wo.status)} />
            {wo.is_blocked ? <BlockedBadge /> : null}
          </>
        }
        lead={
          <>
            <Code>{wo.product.product_key}</Code>
            {wo.sales_order ? (
              <>
                {" · for order "}
                {canOpen(wo.sales_order.path) ? <TextLink href={asRoute(wo.sales_order.path)}>{wo.sales_order.order_number}</TextLink> : wo.sales_order.order_number}
                {wo.sales_order.line_no ? `, line ${wo.sales_order.line_no}` : ""}
              </>
            ) : (
              " · made for stock"
            )}
          </>
        }
        facts={
          <FactStrip
            items={[
              { label: "To make", icon: "boxes", value: <Qty value={{ value: wo.qty_planned, uom: wo.uom_code }} className="t-stat-sm" /> },
              { label: "Made so far", icon: "check", value: <Qty value={{ value: wo.qty_good, uom: wo.uom_code }} /> },
              { label: "Due", icon: "clock", value: wo.due_date ? <DateText value={wo.due_date} style="business" /> : null },
              { label: "Planned start", icon: "calendar", value: wo.planned_start_date ? <DateText value={wo.planned_start_date} style="business" /> : null },
              { label: "Warehouse", icon: "warehouse", value: wo.warehouse.name },
            ]}
          />
        }
        actions={
          <>
            {lead ? (
              <Button iconLeft={lead.icon} loading={lead.pendingName !== undefined && pending === lead.pendingName} isDisabled={Boolean(offline)} onPress={lead.run}>
                {lead.label}
              </Button>
            ) : null}
            {second ? (
              <Button variant="secondary" iconLeft={second.icon} loading={second.pendingName !== undefined && pending === second.pendingName} isDisabled={Boolean(offline)} onPress={second.run}>
                {second.label}
              </Button>
            ) : null}
            {menu.length > 0 ? (
              <Menu
                label="More work order actions"
                items={menu}
                placement="bottom end"
                trigger={
                  <Button variant="secondary" iconRight="chevronDown">
                    More
                  </Button>
                }
              />
            ) : null}
          </>
        }
      >
        <Tabs
          label="Views of this work order"
          selectedKey={view}
          tabs={[
            { id: "overview", label: "Overview", href: asRoute(path) },
            { id: "materials", label: "Materials", count: wo.materials.length, href: asRoute(viewHref(path, "materials", "overview")) },
            { id: "operations", label: "Operations", count: wo.operations.length, href: asRoute(viewHref(path, "operations", "overview")) },
            { id: "postings", label: "Stock postings", count: wo.transactions.length || undefined, href: asRoute(viewHref(path, "postings", "overview")) },
          ]}
        />
      </RecordHeader>

      {offline ? (
        <Banner tone="amber" title="You are offline.">
          You can read this work order. Actions work again once the connection is back.
        </Banner>
      ) : null}
      {wo.is_blocked ? (
        <Banner
          tone="amber"
          title="Waiting for material."
          action={
            can("recheck") ? (
              <Button
                variant="secondary"
                size="sm"
                iconLeft="refresh"
                loading={pending === "recheck"}
                isDisabled={Boolean(offline)}
                onPress={() => void run("recheck", (k) => recheckWorkOrder(wo, k), { done: "Materials checked again", failed: FAILED, write })}
              >
                Check materials again
              </Button>
            ) : undefined
          }
        >
          Some of what it needs could not be reserved
          {wo.blocked_since ? (
            <>
              {", so it has waited since "}
              <DateText value={wo.blocked_since} style="date" />
            </>
          ) : null}
          . It unblocks by itself when stock arrives or is freed.
          {wo.blocked_causes.length > 0 ? (
            <>
              {" Held up by: "}
              {wo.blocked_causes.map((cause, index) => (
                <span key={cause.id}>
                  {index > 0 ? ", " : ""}
                  {cause.path && canOpen(cause.path) ? <TextLink href={asRoute(cause.path)}>{cause.label ?? humanise(cause.type)}</TextLink> : (cause.label ?? humanise(cause.type))}
                </span>
              ))}
              .
            </>
          ) : null}
        </Banner>
      ) : null}
      {wo.status === "cancelled" ? (
        <Banner tone="neutral" icon="xCircle" title={`Cancelled${cancelReason ? `: ${cancelReason.toLowerCase()}` : ""}.`}>
          {wo.cancel_reason ?? "Its reservations were released."}
        </Banner>
      ) : null}

      {view === "overview" ? <Overview wo={wo} path={path} nextLabel={lead?.label ?? null} stillToMake={left} /> : null}
      {view === "materials" ? <MaterialsView wo={wo} /> : null}
      {view === "operations" ? (
        <OperationsView
          wo={wo}
          pending={pending}
          offline={Boolean(offline)}
          onComplete={(operation) =>
            void run(`op-${operation.id}`, (k) => completeOperation(wo, operation.id, k), { done: `Operation ${operation.seq} completed`, failed: FAILED, write })
          }
          onLinkPlan={(operation) => {
            setPlanOperation(operation);
            setOpen("plan");
          }}
          onOffcut={() => setOpen("offcut")}
        />
      ) : null}
      {view === "postings" ? <PostingsView wo={wo} /> : null}

      {open === "issue" ? <IssueDialog {...dialog} /> : null}
      {open === "consume" || open === "return" ? <WipDialog kind={open} {...dialog} /> : null}
      {open === "output" ? <OutputDialog {...dialog} /> : null}
      {open === "offcut" ? <OffcutDialog {...dialog} /> : null}
      {open === "plan" && planOperation ? <PlanDialog operation={planOperation} {...dialog} /> : null}
      {open === "cancel" ? <CancelDialog {...dialog} /> : null}
    </Page>
  );
}

// ---------------------------------------------------------------------------------------------
// Overview: where it stands and what is next

const ORDER = ["draft", "released", "in_progress", "completed", "closed"];

function progressOf(wo: WorkOrderRead): StepItem[] {
  const cancelled = wo.status === "cancelled";
  const reached = ORDER.indexOf(wo.status);
  const started = reached >= 2 || wo.transactions.length > 0;
  const raw: { id: string; label: string; hint: ReactNode; done: boolean }[] = [
    { id: "planned", label: "Planned", hint: wo.planned_start_date ? <DateText value={wo.planned_start_date} style="business" /> : "Start not set", done: true },
    { id: "released", label: "Released", hint: wo.released_at ? <DateText value={wo.released_at} style="date" /> : "Reserves its materials", done: reached >= 1 },
    { id: "started", label: "Started", hint: started ? "Material on the floor" : "First material issued", done: started && reached >= 1 },
    { id: "completed", label: "Completed", hint: wo.completed_at ? <DateText value={wo.completed_at} style="date" /> : "Output is in stock", done: reached >= 3 },
    { id: "closed", label: "Closed", hint: wo.closed_at ? <DateText value={wo.closed_at} style="date" /> : "Nothing more to post", done: reached >= 4 },
  ];
  const current = cancelled ? -1 : raw.findIndex((step) => !step.done);
  return raw.map((step, index) => ({ id: step.id, label: step.label, hint: step.hint, state: step.done && !cancelled ? "done" : index === current ? "current" : "todo" }));
}

function standingOf(wo: WorkOrderRead, nextLabel: string | null): { headline: ReactNode; body: string } {
  const next = nextLabel ? ` Next: ${nextLabel.toLowerCase()}.` : "";
  if (wo.status === "cancelled") return { headline: "Cancelled", body: "Nothing more will be made or posted on this work order." };
  if (wo.status === "closed") return { headline: <>Finished and <em>closed</em></>, body: "Its output is in stock and its postings stay on record." };
  if (wo.status === "completed") return { headline: <>Production is <em>complete</em></>, body: `The output is in stock.${next || " Close the order once nothing more needs posting."}` };
  if (wo.is_blocked) return { headline: <>Waiting for <em>material</em></>, body: "Some of what it needs could not be reserved. The Materials view shows which components are short." };
  if (wo.status === "draft") return { headline: <>Planned, not yet <em>released</em></>, body: "Releasing reserves its materials and puts the order in front of the floor." };
  if (wo.status === "released") return { headline: <>Released to the <em>floor</em></>, body: `Its materials are reserved.${next}` };
  return { headline: <>On the <em>floor</em></>, body: `Material is moving and output is being reported.${next}` };
}

function Figure({ label, children, quiet = false }: { label: string; children: ReactNode; quiet?: boolean }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span className="t-overline text-ink-3">{label}</span>
      <span className={cx("t-stat", quiet ? "text-ink-2" : "text-ink")}>{children}</span>
    </div>
  );
}

function Overview({ wo, path, nextLabel, stillToMake }: { wo: WorkOrderRead; path: string; nextLabel: string | null; stillToMake: string }) {
  const canOpen = useCanOpen();
  const standing = standingOf(wo, nextLabel);
  const done = wo.operations.filter((operation) => operation.status === "done").length;
  const nextOperation = wo.operations.find((operation) => operation.status === "pending") ?? null;
  const short = wo.materials.filter((material) => material.short).length;
  const quantity = (value: string) => <Qty value={{ value, uom: wo.uom_code }} />;
  return (
    <Split
      main={
        <>
          <GlassPanel padding="lg" className="rise flex flex-col gap-6" eyebrow="Where it stands">
            <Steps label="Progress of this work order" steps={progressOf(wo)} />
            <div className="flex max-w-prose flex-col gap-2">
              <h2 className="t-display-sm text-ink">{standing.headline}</h2>
              <p className="t-body text-ink-2">{standing.body}</p>
            </div>
          </GlassPanel>

          <GlassPanel padding="lg" className="rise flex flex-col gap-5" style={stagger(1)} title="Output" titleAs="h2">
            <div className="grid grid-cols-2 gap-x-6 gap-y-5 md:grid-cols-4">
              <Figure label="To make">{quantity(wo.qty_planned)}</Figure>
              <Figure label="Good">{quantity(wo.qty_good)}</Figure>
              <Figure label="Scrap" quiet>
                {quantity(wo.qty_scrap)}
              </Figure>
              <Figure label="Still to make" quiet={!isPositiveDecimalStr(stillToMake)}>
                {quantity(stillToMake)}
              </Figure>
            </div>
          </GlassPanel>

          <GlassPanel
            padding="lg"
            className="rise flex flex-col gap-4"
            style={stagger(2)}
            title="Operations"
            titleAs="h2"
            action={<TextLink href={asRoute(viewHref(path, "operations", "overview"))}>See operations</TextLink>}
          >
            {wo.operations.length === 0 ? (
              <p className="t-body text-ink-2">This work order has no operations.</p>
            ) : (
              <>
                <ProgressBar
                  label="Operations done"
                  value={(done / wo.operations.length) * 100}
                  detail={`${done} of ${wo.operations.length}`}
                  segments={wo.operations.length <= 12 ? wo.operations.length : undefined}
                  tone={done === wo.operations.length ? "leaf" : "ink"}
                />
                <p className="t-body-sm text-ink-2">
                  {nextOperation ? (
                    <>
                      Next: operation {nextOperation.seq}, {nextOperation.name}, at {nextOperation.work_center.name}
                      {nextOperation.planned_date ? (
                        <>
                          {" on "}
                          <DateText value={nextOperation.planned_date} style="business" />
                        </>
                      ) : null}
                      .
                    </>
                  ) : (
                    "Every operation is done."
                  )}
                </p>
              </>
            )}
          </GlassPanel>
        </>
      }
      aside={
        <>
          <GlassPanel padding="md" className="rise" title="Materials" titleAs="h2" action={<TextLink href={asRoute(viewHref(path, "materials", "overview"))}>See materials</TextLink>}>
            <KeyValue
              rows
              items={[
                { label: "Components", value: String(wo.materials.length) },
                {
                  label: "Short",
                  value:
                    short > 0 ? (
                      <Badge tone="amber" icon="alert" size="sm">
                        {short === 1 ? "1 component" : `${short} components`}
                      </Badge>
                    ) : (
                      "None"
                    ),
                },
              ]}
            />
          </GlassPanel>
          <GlassPanel padding="md" className="rise" title="Made to" titleAs="h2">
            <KeyValue
              rows
              items={[
                {
                  label: "Bill of materials",
                  value: canOpen(`${PATHS.boms}/${wo.bom.id}`) ? <TextLink href={asRoute(`${PATHS.boms}/${wo.bom.id}`)}>{versionLabel(wo.bom.version_no)}</TextLink> : versionLabel(wo.bom.version_no),
                },
                {
                  label: "Routing",
                  value: canOpen(`${PATHS.routings}/${wo.routing.id}`) ? (
                    <TextLink href={asRoute(`${PATHS.routings}/${wo.routing.id}`)}>{versionLabel(wo.routing.version_no)}</TextLink>
                  ) : (
                    versionLabel(wo.routing.version_no)
                  ),
                },
                ...(wo.sales_order
                  ? [
                      {
                        label: "Sales order",
                        value: canOpen(wo.sales_order.path) ? (
                          <TextLink href={asRoute(wo.sales_order.path)}>
                            <Code>{wo.sales_order.order_number}</Code>
                          </TextLink>
                        ) : (
                          <Code>{wo.sales_order.order_number}</Code>
                        ),
                      },
                    ]
                  : []),
                { label: "Warehouse", value: `${wo.warehouse.code} · ${wo.warehouse.name}` },
                { label: "Planned by", value: wo.owner?.display_name ?? null },
              ]}
            />
          </GlassPanel>
          {wo.notes ? (
            <GlassPanel padding="md" className="rise" title="Notes" titleAs="h2">
              <p className="t-body whitespace-pre-line text-ink-2">{wo.notes}</p>
            </GlassPanel>
          ) : null}
        </>
      }
    />
  );
}

// ---------------------------------------------------------------------------------------------
// Materials

function MaterialsView({ wo }: { wo: WorkOrderRead }) {
  const qty = (value: string, material: MaterialRead) => <Qty value={{ value, uom: material.uom_code }} />;
  const columns: Column<MaterialRead>[] = [
    {
      key: "component",
      header: "Component",
      primary: true,
      cell: (material) => (
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="t-label text-ink">{material.component.name}</span>
            {material.requirement_source === "cut_plan" ? (
              <Badge tone="cobalt" size="sm" icon="scissors">
                From the cut plan
              </Badge>
            ) : null}
          </span>
          <span className="t-caption text-ink-3">
            {material.component.product_key}
            {material.alternates.length > 0 ? ` · can be replaced by ${material.alternates.map((alternate) => alternate.product_key).join(", ")}` : ""}
          </span>
        </span>
      ),
    },
    { key: "required", header: "Required", numeric: true, cell: (material) => <span className="t-label text-ink">{qty(material.qty_required, material)}</span> },
    {
      key: "reserved",
      header: "Reserved",
      numeric: true,
      cell: (material) =>
        material.short ? (
          <span className="inline-flex flex-wrap items-center justify-end gap-1.5">
            <Badge tone="amber" size="sm" icon="alert">
              Short
            </Badge>
            {qty(material.qty_reserved, material)}
          </span>
        ) : (
          qty(material.qty_reserved, material)
        ),
    },
    { key: "issued", header: "Issued", numeric: true, cell: (material) => qty(material.qty_issued, material) },
    { key: "wip", header: "On the floor", numeric: true, cell: (material) => qty(material.qty_in_wip, material) },
    { key: "consumed", header: "Consumed", numeric: true, cell: (material) => qty(material.qty_consumed, material) },
    { key: "free", header: "Free in stock", numeric: true, cell: (material) => <span className="text-ink-3">{qty(material.qty_free, material)}</span> },
  ];
  return (
    <div className="stack">
      <ViewHeading title="Materials" text="What this order needs and where each quantity stands: reserved, issued to the floor, consumed." />
      <GlassPanel padding="none" className="rise min-w-0">
        <DataTable
          label={`Materials of ${wo.wo_number}`}
          columns={columns}
          rows={wo.materials}
          rowKey={(material) => material.id}
          empty={<EmptyState compact icon="layers" title="This work order needs no materials" text="Its bill of materials has no components." />}
        />
      </GlassPanel>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Operations

function OperationsView({
  wo,
  pending,
  offline,
  onComplete,
  onLinkPlan,
  onOffcut,
}: {
  wo: WorkOrderRead;
  pending: string | null;
  offline: boolean;
  onComplete: (operation: OperationRead) => void;
  onLinkPlan: (operation: OperationRead) => void;
  onOffcut: () => void;
}) {
  const canOpen = useCanOpen();
  const can = (name: string) => Boolean(wo.capabilities[name]?.allowed);
  return (
    <div className="stack">
      <ViewHeading title="Operations" text="The steps of the routing, in the order the floor takes them." />
      {wo.operations.length === 0 ? (
        <GlassPanel padding="md" className="rise">
          <EmptyState compact icon="route" title="This work order has no operations" text="Its routing version lists none." />
        </GlassPanel>
      ) : (
        <GlassPanel padding="none" className="rise min-w-0">
          <ol aria-label={`Operations of ${wo.wo_number}`} className="flex flex-col">
            {wo.operations.map((operation, index) => {
              const isDone = operation.status === "done";
              const linkPlan = operation.is_board_cutting && !isDone && can("link_cut_plan");
              const offcut = operation.is_board_cutting && can("record_offcut");
              const complete = !isDone && can("complete_operation") && wo.status !== "draft";
              const centrePath = `${PATHS.workCentres}/${operation.work_center.id}`;
              return (
                <li key={operation.id} className={cx("rise-plain flex min-w-0 flex-col gap-4 p-5 md:flex-row md:items-start", index > 0 && "border-t border-line")} style={stagger(index)}>
                  <div className="flex min-w-0 flex-1 items-start gap-4">
                    <span
                      className={cx(
                        "t-label lk-tnum flex h-8 w-8 flex-none items-center justify-center rounded-pill border",
                        isDone ? "border-inverse bg-inverse text-on-inverse" : "border-line-strong text-ink-2",
                      )}
                    >
                      {isDone ? <Icon name="check" size={14} /> : operation.seq}
                    </span>
                    <div className="flex min-w-0 flex-col gap-1.5">
                      <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <h3 className="t-h4 text-ink">
                          <span className="sr-only">Operation {operation.seq}: </span>
                          {operation.name}
                        </h3>
                        {isDone ? (
                          <Badge tone="leaf" size="sm" icon="check">
                            Done
                          </Badge>
                        ) : (
                          <Badge size="sm" outline>
                            To do
                          </Badge>
                        )}
                      </div>
                      <p className="t-body-sm text-ink-2">
                        {canOpen(centrePath) ? <TextLink href={asRoute(centrePath)}>{operation.work_center.name}</TextLink> : operation.work_center.name}
                        {" · "}
                        <Minutes value={operation.planned_minutes} /> planned
                        {operation.planned_date ? (
                          <>
                            {" · "}
                            <DateText value={operation.planned_date} style="business" />
                          </>
                        ) : null}
                        {isDone && operation.completed_at ? (
                          <>
                            {" · done "}
                            <DateText value={operation.completed_at} style="dayTime" />
                          </>
                        ) : null}
                      </p>
                      {operation.cut_plan ? (
                        <p className="t-body-sm flex min-w-0 flex-wrap items-center gap-2 text-ink-2">
                          <Icon name="scissors" size={14} />
                          {canOpen(operation.cut_plan.path) ? (
                            <TextLink href={asRoute(operation.cut_plan.path)}>
                              <Code>{operation.cut_plan.plan_number}</Code>
                            </TextLink>
                          ) : (
                            <Code>{operation.cut_plan.plan_number}</Code>
                          )}
                          {operation.cut_plan.boards != null ? <span>{operation.cut_plan.boards === 1 ? "1 board" : `${operation.cut_plan.boards} boards`}</span> : null}
                          {operation.cut_plan.ready ? (
                            <Badge tone="leaf" size="sm">
                              Ready
                            </Badge>
                          ) : (
                            <Badge tone="amber" size="sm" icon="alert">
                              Not ready{operation.cut_plan.reason_code ? `: ${humanise(operation.cut_plan.reason_code).toLowerCase()}` : ""}
                            </Badge>
                          )}
                        </p>
                      ) : operation.is_board_cutting ? (
                        <p className="t-body-sm flex items-center gap-2 text-ink-3">
                          <Icon name="scissors" size={14} />
                          Board cutting. No cut plan linked yet.
                        </p>
                      ) : null}
                    </div>
                  </div>
                  {linkPlan || offcut || complete ? (
                    <div className="flex flex-wrap items-center gap-2 pl-12 md:flex-none md:justify-end md:pl-0">
                      {linkPlan ? (
                        <Button variant="secondary" size="sm" iconLeft="link" isDisabled={offline} onPress={() => onLinkPlan(operation)}>
                          {operation.cut_plan ? "Change cut plan" : "Link cut plan"}
                        </Button>
                      ) : null}
                      {offcut ? (
                        <Button variant="secondary" size="sm" iconLeft="ruler" isDisabled={offline} onPress={onOffcut}>
                          Record offcut
                        </Button>
                      ) : null}
                      {complete ? (
                        <Button
                          variant="inverse"
                          size="sm"
                          iconLeft="check"
                          aria-label={`Complete operation ${operation.seq}`}
                          loading={pending === `op-${operation.id}`}
                          isDisabled={offline}
                          onPress={() => onComplete(operation)}
                        >
                          Complete
                        </Button>
                      ) : null}
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ol>
        </GlassPanel>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Stock postings

const POSTING_ICON: Record<string, IconName> = { issue: "packageOpen", consume: "hammer", return: "undo", output: "boxes", offcut: "ruler" };

/** Where a posting line moved: both ends when known, otherwise the end the server named. */
function movedText(from: string | null, to: string | null): string {
  if (from && to) return `from ${from} to ${to}`;
  if (to) return `into ${to}`;
  if (from) return `out of ${from}`;
  return "";
}

function PostingsView({ wo }: { wo: WorkOrderRead }) {
  const canOpen = useCanOpen();
  const movements = "/operations/inventory/movements";
  const items: TimelineItem[] = wo.transactions.map((posting) => ({
    id: posting.id,
    title: POSTING_KIND[posting.kind] ?? humanise(posting.kind),
    meta: (
      <>
        {posting.created_by?.display_name ? `${posting.created_by.display_name} · ` : ""}
        <DateText value={posting.created_at} style="dayTime" />
      </>
    ),
    icon: POSTING_ICON[posting.kind],
    tone: posting.kind === "output" ? "leaf" : undefined,
    body: (
      <ul className="flex flex-col gap-1">
        {posting.lines.map((line, index) => (
          <li key={`${posting.id}-${index}`} className="t-body-sm flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5 text-ink-2">
            <Qty value={{ value: line.quantity, uom: line.uom_code }} className="t-label text-ink" />
            <span>{line.product.name}</span>
            <Code className="t-code-sm">{line.product.product_key}</Code>
            {line.lot_code ? <span className="text-ink-3">lot {line.lot_code}</span> : null}
            <span className="text-ink-3">{movedText(line.from_location, line.to_location)}</span>
          </li>
        ))}
        {posting.reason ? <li className="t-body-sm text-ink-3">{posting.reason}</li> : null}
      </ul>
    ),
  }));
  return (
    <GlassPanel
      padding="lg"
      className="rise"
      title="Stock postings"
      titleAs="h2"
      action={wo.transactions.length > 0 && canOpen(movements) ? <TextLink href={asRoute(movements)}>See all stock movements</TextLink> : undefined}
    >
      {items.length === 0 ? (
        <EmptyState compact icon="history" title="Nothing has been posted yet" text="Issues, consumption, returns, output and offcuts are listed here as they happen." />
      ) : (
        <Timeline label={`Stock postings of ${wo.wo_number}`} items={items} />
      )}
    </GlassPanel>
  );
}
