"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useId, useMemo, useState, type ReactNode } from "react";
import { useCommand } from "@/features/inventory/use-command";
import {
  fetchContainerProfiles,
  fetchPackingList,
  overrideLine,
  packingListAction,
  suggestLoad,
  type LoadSuggestion,
  type PackingLine,
  type PackingListDetail,
} from "@/features/logistics/api";
import { problemDescription } from "@/features/sales/use-quote-command";
import { queryKeys } from "@/lib/api/query-keys";
import { formatCount, formatDecimal } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { asRoute, FAILED, incompleteReason } from "~/data/dispatch";
import { Steps, type StepItem } from "~/screens/sales/quotations/parts";
import { Page, RecordHeader, Split } from "~/shell/page";
import { ErrorBlock, LoadingBlock } from "~/shell/states";
import {
  Badge,
  Banner,
  Button,
  ButtonLink,
  Code,
  ConfirmDialog,
  Dash,
  DataTable,
  DateText,
  DecimalField,
  EmptyState,
  FactStrip,
  GlassPanel,
  KeyValue,
  Menu,
  Modal,
  Qty,
  Select,
  Skeleton,
  SkeletonText,
  Tabs,
  Textarea,
  TextLink,
  toast,
  type Column,
  type MenuItem,
} from "~/ui";
import { Decimal, PackingStatusBadge, stagger } from "./parts";
import { viewHref, type PackingView } from "./views";

const FINALISE_BLOCKED: Record<string, string> = {
  packing_list_stale: "Refresh the packaging before you finalise.",
  packing_list_incomplete: "Enter the missing packaging values before you finalise.",
  permission_denied: "Finalising needs dispatch rights for this order.",
};

/** A packing list: where it stands, its lines with their cartons and weights, and a container load suggestion. */
export function PackingListRecord({ packingListId, view }: { packingListId: string; view: PackingView }) {
  const query = useQuery({ queryKey: queryKeys.logistics.packingList(packingListId), queryFn: ({ signal }) => fetchPackingList(packingListId, signal) });
  if (query.isPending) {
    return (
      <Page>
        <div className="lk-glass record-head" role="status" aria-label="Loading the packing list">
          <Skeleton width="140px" height={14} />
          <Skeleton width="45%" height={32} />
          <SkeletonText lines={2} />
        </div>
        <LoadingBlock lines={6} label="Loading the packing list" />
      </Page>
    );
  }
  if (query.isError) {
    return (
      <Page>
        <ErrorBlock error={query.error} what="This packing list" onRetry={() => void query.refetch()} />
        <div>
          <ButtonLink href="/operations/dispatch/packing-lists" variant="secondary" iconLeft="arrowLeft">
            All packing lists
          </ButtonLink>
        </div>
      </Page>
    );
  }
  return <Loaded list={query.data} view={view} />;
}

function Loaded({ list, view: asked }: { list: PackingListDetail; view: PackingView }) {
  const { permissionKeys, zone } = useSession();
  const key = useMemo(() => queryKeys.logistics.packingList(list.id), [list.id]);
  const { run, pending, offline } = useCommand<PackingListDetail>(key);
  const [entering, setEntering] = useState<PackingLine | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const caps = list.capabilities;
  const path = `/operations/dispatch/packing-lists/${list.id}`;
  const canLoad = permissionKeys.has("logistics.load_plan.run") && list.status !== "cancelled";
  const view: PackingView = asked === "load" && !canLoad ? "overview" : asked;
  const canEnter = caps.override?.allowed === true;
  const incomplete = list.lines.filter((line) => line.incomplete_reasons.length > 0);

  const act = (action: "refresh" | "finalise" | "cancel", done: string) => run(action, (k) => packingListAction(list, action, k), { done, failed: FAILED, write: (x) => x });

  const refresh = caps.refresh?.allowed
    ? { label: "Refresh packaging", icon: "refresh" as const, name: "refresh", onPress: () => void act("refresh", "Packaging refreshed") }
    : null;
  const finalise = caps.finalise?.allowed
    ? { label: "Finalise packing list", icon: "badgeCheck" as const, name: "finalise", onPress: () => void act("finalise", "Packing list finalised") }
    : null;
  const [lead, second] = list.is_stale ? [refresh ?? finalise, refresh ? finalise : null] : [finalise ?? refresh, finalise ? refresh : null];

  const menu: MenuItem[] = [];
  if (caps.cancel?.allowed) menu.push({ id: "cancel", label: "Cancel packing list", icon: "xCircle", tone: "danger", isDisabled: Boolean(offline), onAction: () => setCancelling(true) });

  const blocked = list.status === "draft" && caps.finalise && !caps.finalise.allowed && caps.finalise.reason_code ? (FINALISE_BLOCKED[caps.finalise.reason_code] ?? "This packing list cannot be finalised yet.") : null;

  return (
    <Page>
      <RecordHeader
        breadcrumb={[
          { label: "Operations", href: "/operations" },
          { label: "Dispatch", href: "/operations/dispatch" },
          { label: "Packing lists", href: "/operations/dispatch/packing-lists" },
          { label: list.packing_list_number },
        ]}
        code={list.packing_list_number}
        title={list.party_name}
        status={
          <>
            <PackingStatusBadge status={list.status} />
            {list.is_stale ? (
              <Badge tone="amber" icon="refresh">
                Packaging changed
              </Badge>
            ) : null}
          </>
        }
        lead={
          <>
            For order <TextLink href={asRoute(list.order.path)}>{list.order.number}</TextLink>
            {list.challan ? (
              <>
                {", challan "}
                <TextLink href={asRoute(list.challan.path)}>{list.challan.number}</TextLink>
              </>
            ) : null}
            . Made <DateText value={list.created_at} style="date" />.
          </>
        }
        facts={
          <FactStrip
            items={[
              { label: "Cartons", icon: "box", value: <span className="lk-tnum">{formatCount(list.total_cartons, zone.locale)}</span> },
              { label: "Volume", icon: "container", value: <Decimal value={list.total_cbm} unit="m³" /> },
              { label: "Net weight", icon: "gauge", value: <Decimal value={list.total_net_kg} unit="kg" /> },
              { label: "Gross weight", icon: "gauge", value: <Decimal value={list.total_gross_kg} unit="kg" /> },
              { label: "Lines", icon: "list", value: <span className="lk-tnum">{formatCount(list.lines.length, zone.locale)}</span> },
            ]}
          />
        }
        actions={
          <>
            {lead ? (
              <Button iconLeft={lead.icon} loading={pending === lead.name} isDisabled={Boolean(offline) || (pending !== null && pending !== lead.name)} onPress={lead.onPress}>
                {lead.label}
              </Button>
            ) : null}
            {second ? (
              <Button variant="secondary" iconLeft={second.icon} loading={pending === second.name} isDisabled={Boolean(offline) || (pending !== null && pending !== second.name)} onPress={second.onPress}>
                {second.label}
              </Button>
            ) : null}
            {menu.length > 0 ? (
              <Menu
                label="More packing list actions"
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
          label="Views of this packing list"
          selectedKey={view}
          tabs={[
            { id: "overview", label: "Overview", href: asRoute(path) },
            { id: "lines", label: "Lines", count: list.lines.length, href: asRoute(viewHref(path, "lines")) },
            ...(canLoad ? [{ id: "load", label: "Container load", href: asRoute(viewHref(path, "load")) }] : []),
          ]}
        />
      </RecordHeader>

      {offline ? (
        <Banner tone="amber" title="You are offline.">
          You can read this packing list. Actions work again once the connection is back.
        </Banner>
      ) : null}
      {list.is_stale ? (
        <Banner tone="amber" icon="refresh" title="The packaging or the order changed after this list was made.">
          Refresh the packaging before you finalise{list.stale_reason ? `: ${list.stale_reason}` : "."}
        </Banner>
      ) : null}
      {list.status === "cancelled" ? (
        <Banner tone="neutral" icon="xCircle" title="Cancelled.">
          This packing list is kept for the record. Create a new one from the order if the goods still need to go.
        </Banner>
      ) : null}

      {view === "overview" ? <Overview list={list} blocked={blocked} incomplete={incomplete} canEnter={canEnter} onEnter={setEntering} /> : null}
      {view === "lines" ? <LinesView list={list} canEnter={canEnter} onEnter={setEntering} /> : null}
      {view === "load" ? <LoadView list={list} /> : null}

      {entering ? <EnterValuesModal key={entering.id} list={list} line={entering} onClose={() => setEntering(null)} /> : null}
      <ConfirmDialog
        isOpen={cancelling}
        onOpenChange={setCancelling}
        tone="danger"
        title={`Cancel ${list.packing_list_number}?`}
        description="It stays on record but can no longer be finalised or shipped against."
        confirmLabel="Cancel packing list"
        cancelLabel="Keep it"
        onConfirm={async () => {
          const result = await act("cancel", "Packing list cancelled");
          if (!result) throw new Error("not cancelled");
        }}
      />
    </Page>
  );
}

// ---------------------------------------------------------------------------------------------
// Overview

function progressOf(list: PackingListDetail, incomplete: number): StepItem[] {
  const final = list.status === "final";
  const cancelled = list.status === "cancelled";
  const complete = final || (incomplete === 0 && !list.is_stale);
  const raw: { id: string; label: string; hint: ReactNode; done: boolean }[] = [
    { id: "packed", label: "Packed", hint: <DateText value={list.created_at} style="date" />, done: true },
    { id: "complete", label: "Figures complete", hint: list.is_stale ? "Packaging changed" : incomplete > 0 ? (incomplete === 1 ? "1 line to complete" : `${incomplete} lines to complete`) : "Every line counted", done: complete },
    { id: "final", label: "Final", hint: list.finalised_at ? <DateText value={list.finalised_at} style="date" /> : "Ready to ship", done: final },
  ];
  const current = cancelled ? -1 : raw.findIndex((step) => !step.done);
  return raw.map((step, index) => ({ id: step.id, label: step.label, hint: step.hint, state: step.done && !cancelled ? "done" : index === current ? "current" : "todo" }));
}

function standingOf(list: PackingListDetail, incomplete: number, blocked: string | null): { headline: ReactNode; body: string } {
  if (list.status === "cancelled") return { headline: "Cancelled", body: "Nothing will ship against this packing list." };
  if (list.status === "final") return { headline: <>Final and ready to <em>ship</em></>, body: "Link it to the shipment so the carton and weight figures travel with the goods." };
  if (list.is_stale) return { headline: <>The packaging <em>changed</em></>, body: "The catalogue packaging or the order changed after this list was made. Refresh to recount, then finalise." };
  if (incomplete > 0) {
    return {
      headline: <>{incomplete === 1 ? "One line needs" : `${incomplete} lines need`} <em>figures</em></>,
      body: "Their packaging data is missing, so the totals are partial. Enter the measured values with a note on how they were measured.",
    };
  }
  return { headline: <>Counted and ready to <em>finalise</em></>, body: blocked ?? "Every line has cartons, volume and weights. Finalise it to fix the figures for shipping." };
}

function Overview({
  list,
  blocked,
  incomplete,
  canEnter,
  onEnter,
}: {
  list: PackingListDetail;
  blocked: string | null;
  incomplete: PackingLine[];
  canEnter: boolean;
  onEnter: (line: PackingLine) => void;
}) {
  const standing = standingOf(list, incomplete.length, blocked);
  return (
    <Split
      main={
        <>
          <GlassPanel padding="lg" className="rise flex flex-col gap-6" eyebrow="Where it stands">
            <Steps label="Progress of this packing list" steps={progressOf(list, incomplete.length)} />
            <div className="flex max-w-prose flex-col gap-2">
              <h2 className="t-display-sm text-ink">{standing.headline}</h2>
              <p className="t-body text-ink-2">{standing.body}</p>
            </div>
          </GlassPanel>

          {incomplete.length > 0 && list.status !== "cancelled" ? (
            <GlassPanel padding="md" className="rise" style={stagger(1)} eyebrow="Needs figures" title={incomplete.length === 1 ? "One line" : `${incomplete.length} lines`} titleAs="h2">
              <ul className="flex flex-col divide-y divide-line">
                {incomplete.map((line, index) => (
                  <li key={line.id} className="rise-plain flex min-w-0 flex-wrap items-center justify-between gap-3 py-3 first:pt-0 last:pb-0" style={stagger(index)}>
                    <span className="flex min-w-0 flex-col gap-1">
                      <span className="t-label text-ink">
                        {line.line_no}. {line.description}
                      </span>
                      <span className="flex flex-wrap gap-1.5">
                        {line.incomplete_reasons.map((reason) => (
                          <Badge key={reason} tone="ember" size="sm">
                            {incompleteReason(reason)}
                          </Badge>
                        ))}
                      </span>
                    </span>
                    {canEnter ? (
                      <Button variant="secondary" size="sm" iconLeft="edit" onPress={() => onEnter(line)}>
                        Enter values
                      </Button>
                    ) : null}
                  </li>
                ))}
              </ul>
            </GlassPanel>
          ) : null}

          {list.has_estimates ? (
            <Banner tone="cobalt" title="The gross weight is an estimate.">
              Part cartons have an unknown tare, so their gross weight is estimated.
            </Banner>
          ) : null}
        </>
      }
      aside={
        <>
          <GlassPanel padding="md" className="rise" title="Linked records" titleAs="h2">
            <KeyValue
              rows
              items={[
                { label: "Order", value: <TextLink href={asRoute(list.order.path)}>{list.order.number}</TextLink> },
                { label: "Challan", value: list.challan ? <TextLink href={asRoute(list.challan.path)}>{list.challan.number}</TextLink> : null },
                { label: "Made", value: <DateText value={list.created_at} style="dayTime" /> },
                { label: "Finalised", value: list.finalised_at ? <DateText value={list.finalised_at} style="dayTime" /> : null },
              ]}
            />
          </GlassPanel>
          {list.notes ? (
            <GlassPanel padding="md" className="rise" title="Notes" titleAs="h2">
              <p className="t-body-sm whitespace-pre-line text-ink-2">{list.notes}</p>
            </GlassPanel>
          ) : null}
        </>
      }
    />
  );
}

// ---------------------------------------------------------------------------------------------
// Lines

function LinesView({ list, canEnter, onEnter }: { list: PackingListDetail; canEnter: boolean; onEnter: (line: PackingLine) => void }) {
  const columns: Column<PackingLine>[] = [
    {
      key: "line",
      header: "Line",
      primary: true,
      cell: (line) => (
        <span className="flex min-w-0 items-start gap-3">
          <span className="t-caption lk-tnum mt-0.5 w-5 flex-none text-right text-ink-3">{line.line_no}</span>
          <span className="flex min-w-0 flex-col gap-0.5">
            <span className="t-label text-ink">{line.description}</span>
            <span className="t-caption text-ink-3">
              <Code>{line.product_key}</Code>
              {line.carton_dimensions_cm ? ` · carton ${line.carton_dimensions_cm} cm` : ""}
            </span>
          </span>
        </span>
      ),
    },
    { key: "quantity", header: "Quantity", numeric: true, cell: (line) => <Qty value={{ value: line.quantity, uom: line.unit }} /> },
    {
      key: "cartons",
      header: "Cartons",
      numeric: true,
      cell: (line) => (
        <span className="flex flex-col items-end gap-0.5">
          {line.cartons === null ? <Dash /> : <span className="t-label lk-tnum text-ink">{line.cartons}</span>}
          {line.inner_packs !== null ? <span className="t-caption lk-tnum text-ink-3">{line.inner_packs} inner packs</span> : null}
        </span>
      ),
    },
    { key: "cbm", header: "CBM", numeric: true, cell: (line) => <Decimal value={line.cbm} unit="m³" /> },
    {
      key: "weight",
      header: "Net / gross",
      mobileLabel: "Net and gross weight",
      numeric: true,
      cell: (line) => (
        <span className="flex flex-col items-end gap-0.5">
          <Decimal value={line.net_kg} unit="kg" />
          <Decimal value={line.gross_kg} unit="kg" className="t-caption text-ink-3" />
        </span>
      ),
    },
    {
      key: "notes",
      header: "Notes",
      cell: (line) => {
        const flags = line.is_part_carton || line.is_estimate || line.is_fragile || line.incomplete_reasons.length > 0 || line.override_reason;
        return (
          <span className="flex min-w-0 flex-col items-start gap-1.5">
            {flags ? (
              <span className="flex flex-wrap gap-1.5">
                {line.is_part_carton ? <Badge size="sm">Part carton</Badge> : null}
                {line.is_estimate ? (
                  <Badge size="sm" tone="amber">
                    Estimate
                  </Badge>
                ) : null}
                {line.is_fragile ? (
                  <Badge size="sm" tone="amber" icon="alert">
                    Fragile
                  </Badge>
                ) : null}
                {line.incomplete_reasons.map((reason) => (
                  <Badge key={reason} size="sm" tone="ember">
                    {incompleteReason(reason)}
                  </Badge>
                ))}
              </span>
            ) : (
              <span className="text-ink-3">None</span>
            )}
            {line.override_reason ? <span className="t-caption text-ink-3">Entered by hand: {line.override_reason}</span> : null}
            {canEnter && line.incomplete_reasons.length > 0 ? (
              <Button variant="secondary" size="sm" iconLeft="edit" onPress={() => onEnter(line)}>
                Enter values
              </Button>
            ) : null}
          </span>
        );
      },
    },
  ];
  return (
    <div className="stack">
      <div className="flex min-w-0 flex-col gap-1">
        <h2 className="t-h3">Lines</h2>
        <p className="t-body-sm text-ink-3">Cartons, volume and weights per line, from the catalogue packaging. Lines marked red are missing data.</p>
      </div>
      <GlassPanel padding="none" className="rise min-w-0">
        <DataTable
          label={`Lines of ${list.packing_list_number}`}
          columns={columns}
          rows={list.lines}
          rowKey={(line) => line.id}
          empty={<EmptyState compact icon="box" title="No lines to pack" text="The order had no open stock lines when this list was made." />}
        />
      </GlassPanel>
    </div>
  );
}

/** Measured packaging values for a line the catalogue could not count, with how they were measured. */
function EnterValuesModal({ list, line, onClose }: { list: PackingListDetail; line: PackingLine; onClose: () => void }) {
  const formId = useId();
  const key = useMemo(() => queryKeys.logistics.packingList(list.id), [list.id]);
  const { run, pending, offline } = useCommand<PackingListDetail>(key);
  const [cbm, setCbm] = useState(line.cbm ?? "");
  const [net, setNet] = useState(line.net_kg ?? "");
  const [gross, setGross] = useState(line.gross_kg ?? "");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | undefined>(undefined);

  const submit = async () => {
    if (!reason.trim()) {
      setError("Say how these values were measured. It is kept with the line.");
      return;
    }
    const saved = await run("override", (k) => overrideLine(list, line.id, { cbm: cbm || null, net_kg: net || null, gross_kg: gross || null, reason }, k), {
      done: "Values saved",
      failed: FAILED,
      write: (x) => x,
    });
    if (saved) onClose();
  };

  return (
    <Modal
      isOpen
      onOpenChange={(open) => (open || pending === "override" ? undefined : onClose())}
      title={`Enter values for line ${line.line_no}`}
      description={`${line.product_key} · ${line.description}`}
      actions={
        <>
          <Button variant="ghost" onPress={onClose} isDisabled={pending === "override"}>
            Cancel
          </Button>
          <Button type="submit" form={formId} variant="primary" loading={pending === "override"} isDisabled={Boolean(offline)}>
            Save values
          </Button>
        </>
      }
    >
      <form
        id={formId}
        noValidate
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <div className="flex flex-wrap gap-1.5">
          {line.incomplete_reasons.map((code) => (
            <Badge key={code} size="sm" tone="ember">
              {incompleteReason(code)}
            </Badge>
          ))}
        </div>
        <div className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-3">
          <DecimalField label="Volume" suffix="m³" optional value={cbm} onChange={setCbm} maxFractionDigits={6} />
          <DecimalField label="Net weight" suffix="kg" optional value={net} onChange={setNet} maxFractionDigits={3} />
          <DecimalField label="Gross weight" suffix="kg" optional value={gross} onChange={setGross} maxFractionDigits={3} />
        </div>
        <Textarea
          label="How these were measured"
          rows={2}
          maxLength={500}
          value={reason}
          onChange={(value) => {
            setReason(value);
            if (error && value.trim()) setError(undefined);
          }}
          isRequired
          error={error}
          help="For example: weighed one carton on the dock scale."
        />
      </form>
    </Modal>
  );
}

// ---------------------------------------------------------------------------------------------
// Container load suggestion (read-only; nothing is booked)

function LoadView({ list }: { list: PackingListDetail }) {
  const profiles = useQuery({ queryKey: queryKeys.logistics.containers(), queryFn: ({ signal }) => fetchContainerProfiles(signal) });
  const active = (profiles.data?.items ?? []).filter((profile) => profile.is_active);
  const [profile, setProfile] = useState<string | null>(null);
  const chosen = profile ?? active[0]?.id ?? null;
  const suggestion = useMutation({
    mutationFn: (containerId: string) => suggestLoad(list.id, containerId),
    onError: (error) => toast.error(FAILED, { description: problemDescription(error) }),
  });

  return (
    <Split
      main={
        <>
          <GlassPanel padding="lg" className="rise flex flex-col gap-5" eyebrow="Container load" title="How many containers?" titleAs="h2">
            <p className="t-body-sm max-w-prose text-ink-3">
              A suggestion by volume and weight, whole cartons only, worked out the same way every time. Check it before you book containers.
            </p>
            {profiles.isPending ? (
              <LoadingBlock lines={2} label="Loading container profiles" />
            ) : profiles.isError ? (
              <ErrorBlock error={profiles.error} what="Container profiles" onRetry={() => void profiles.refetch()} />
            ) : active.length === 0 ? (
              <EmptyState compact icon="container" title="No container profile is set up" text="There is nothing to plan the load against yet." />
            ) : (
              <div className="grid min-w-0 grid-cols-1 items-end gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
                <Select
                  label="Container"
                  options={active.map((option) => ({ value: option.id, label: `${option.code} · ${option.name}`, description: `${option.internal_volume_m3} m³ · ${option.max_payload_kg} kg payload` }))}
                  value={chosen}
                  onChange={setProfile}
                />
                <Button variant="inverse" iconLeft="container" loading={suggestion.isPending} isDisabled={!chosen} onPress={() => (chosen ? suggestion.mutate(chosen) : undefined)}>
                  Suggest a load
                </Button>
              </div>
            )}
          </GlassPanel>
          {suggestion.data ? <Suggestion s={suggestion.data} /> : null}
        </>
      }
      aside={
        <GlassPanel padding="md" className="rise" title="What is being loaded" titleAs="h2">
          <KeyValue
            rows
            items={[
              { label: "Cartons", value: <span className="lk-tnum">{list.total_cartons}</span> },
              { label: "Volume", value: <Decimal value={list.total_cbm} unit="m³" /> },
              { label: "Gross weight", value: <Decimal value={list.total_gross_kg} unit="kg" /> },
            ]}
          />
          {list.totals_partial ? <p className="t-caption mt-3 text-ink-3">Some lines lack packaging data, so these totals are partial.</p> : null}
        </GlassPanel>
      }
    />
  );
}

function Suggestion({ s }: { s: LoadSuggestion }) {
  const { locale } = useSession().zone;
  const pct = (value: string) => `${formatDecimal(value, { locale, maxFractionDigits: 1 }) ?? value}%`;
  return (
    <section aria-live="polite" aria-label="Suggested load" className="stack">
      <div className="lk-glass lk-glass-inverse rise flex min-w-0 flex-wrap items-end justify-between gap-4 rounded-xl p-6">
        <div className="flex flex-col gap-1">
          <span className="t-overline opacity-70">{s.label}</span>
          <span className="t-stat-xl lk-tnum">{s.container_count}</span>
          <span className="t-body-sm opacity-80">
            {s.container_count === 1 ? "container" : "containers"} of {s.container.code}, {s.container.name}
          </span>
        </div>
        {s.totals_partial ? <p className="t-body-sm max-w-xs opacity-80">Some lines lack packaging data, so this count may be low.</p> : null}
      </div>
      <ol className="grid min-w-0 grid-cols-1 gap-4 md:grid-cols-2">
        {s.loads.map((load, index) => (
          <GlassPanel key={load.index} as="li" padding="md" className="rise-plain" style={stagger(index)} eyebrow={load.binding_constraint === "weight" ? "Weight is the limit" : load.binding_constraint === "volume" ? "Volume is the limit" : load.binding_constraint} title={`Container ${load.index}`} titleAs="h3">
            <p className="t-body-sm text-ink-2">
              Volume {pct(load.volume_utilisation_pct)} full, payload {pct(load.payload_utilisation_pct)}
            </p>
            <ul className="t-body-sm mt-3 flex flex-col gap-1 text-ink-2">
              {load.allocations.map((allocation) => (
                <li key={`${load.index}-${allocation.line_no}`} className="flex justify-between gap-3">
                  <span className="min-w-0 truncate">
                    Line {allocation.line_no} · <Code>{allocation.product_key}</Code>
                  </span>
                  <span className="lk-tnum flex-none text-ink">
                    {allocation.cartons} {allocation.cartons === 1 ? "carton" : "cartons"}
                  </span>
                </li>
              ))}
            </ul>
          </GlassPanel>
        ))}
      </ol>
      {s.unplanned.length > 0 ? (
        <Banner tone="amber" title="Not planned.">
          {s.unplanned.map((line) => `Line ${line.line_no}: ${incompleteReason(line.reason).toLowerCase()}`).join(". ")}.
        </Banner>
      ) : null}
      {s.manual_review_line_nos.length > 0 ? (
        <Banner tone="neutral" icon="alert" title="Place by hand.">
          Fragile lines {s.manual_review_line_nos.join(", ")} need a person to place them in the container.
        </Banner>
      ) : null}
    </section>
  );
}
