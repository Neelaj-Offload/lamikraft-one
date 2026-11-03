"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { Link as RacLink } from "react-aria-components";
import { StatusPill, type Tone } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/choice";
import { DataTable, OffsetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { DescriptionList } from "@/components/ui/description-list";
import { Dialog, Drawer } from "@/components/ui/dialog";
import { LocalDate, LocalDateTime, Money } from "@/components/ui/format";
import { Link } from "@/components/ui/link";
import { NumberField } from "@/components/ui/number-field";
import { ReasonDialog } from "@/components/ui/reason-dialog";
import { SearchField } from "@/components/ui/search-field";
import { ComboBox, Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading, PermissionDenied } from "@/components/ui/states";
import { linkClasses } from "@/components/ui/styles";
import { TextField } from "@/components/ui/text-field";
import { useProductSearch } from "@/features/sales/pickers";
import { useResourceCommand } from "@/features/sales/resource-command";
import { isProblemError, ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { CURRENCIES } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { commercialMessages as c } from "@/messages/commercial";
import {
  addPriceItem,
  createPriceList,
  duplicatePriceList,
  fetchItemHistory,
  fetchPriceItems,
  fetchPriceList,
  fetchPriceLists,
  ITEMS_PAGE_SIZE,
  PRICE_LIST_STATUSES,
  PRICE_LISTS_PAGE_SIZE,
  priceListCommand,
  retirePriceItem,
  supersedePriceItem,
  updatePriceItem,
  type PriceItem,
  type PriceListDetail,
  type PriceListSummary,
} from "./api";

const m = c.priceLists;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export { priceListStateFrom, priceListHref, type PriceListState } from "./list-state";
import { priceListHref, type PriceListState } from "./list-state";

const TONE: Record<string, Tone> = { draft: "neutral", active: "success", retired: "neutral" };
export function PriceListStatusPill({ status }: { status: string }) {
  return <StatusPill tone={TONE[status] ?? "neutral"}>{m.status[status] ?? status}</StatusPill>;
}

function columns(): DataTableColumn<PriceListSummary>[] {
  return [
    {
      id: "code",
      header: m.columns.code,
      isRowHeader: true,
      mobile: "title",
      mobileCell: (row) => `${row.code} · ${row.name}`,
      cell: (row) => (
        <RacLink href={row.path} className={`${linkClasses} font-mono`}>
          {row.code}
        </RacLink>
      ),
    },
    { id: "name", header: m.columns.name, cell: (row) => row.name },
    { id: "scope", header: m.columns.scope, mobile: "key", cell: (row) => [m.scopes[row.scope_kind] ?? row.scope_kind, row.party?.display_name ?? row.customer_type].filter(Boolean).join(" · ") },
    { id: "type", header: m.columns.type, cell: (row) => `${m.priceTypes[row.price_type] ?? row.price_type} · ${row.currency}` },
    {
      id: "validity",
      header: m.columns.validity,
      cell: (row) => (
        <span>
          <LocalDate value={row.valid_from} /> – {row.valid_to ? <LocalDate value={row.valid_to} /> : "open"}
        </span>
      ),
    },
    { id: "items", header: m.columns.items, numeric: true, cell: (row) => row.item_count },
    { id: "status", header: m.columns.status, mobile: "status", cell: (row) => <PriceListStatusPill status={row.status} /> },
  ];
}

export function PriceLists({ state }: { state: PriceListState }) {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const canRead = permissionKeys.has("pricing.price.read");
  const params = { q: state.q || null, status: state.status, offset: state.offset };
  const query = useQuery({ queryKey: queryKeys.pricing.priceLists(params), queryFn: ({ signal }) => fetchPriceLists(params, signal), enabled: canRead });
  const [creating, setCreating] = useState(false);
  const go = (next: Partial<PriceListState>) => router.push(priceListHref({ ...state, offset: 0, ...next }) as Parameters<typeof router.push>[0]);
  if (!canRead) return <PermissionDenied area={m.title} />;
  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">{m.title}</h1>
          <p className="text-ink-muted">{m.intro}</p>
        </div>
        {permissionKeys.has("pricing.price_list.manage") ? (
          <Button variant="primary" onPress={() => setCreating(true)}>
            {m.newList}
          </Button>
        ) : null}
      </header>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] md:items-end">
        <SearchField label={c.common.search} placeholder={m.searchPlaceholder} defaultValue={state.q} onSubmit={(q) => go({ q })} onClear={() => go({ q: "" })} />
        <Select
          label={c.common.status}
          options={[{ id: "", label: c.common.anyStatus }, ...PRICE_LIST_STATUSES.map((status) => ({ id: status, label: m.status[status] ?? status }))]}
          value={state.status ?? ""}
          onChange={(value) => go({ status: value || null })}
        />
      </div>
      {query.isPending ? (
        <Loading label={m.loadingList} />
      ) : query.isError ? (
        isProblemError(query.error) && query.error.status === 403 ? (
          <PermissionDenied area={m.title} headingLevel={2} />
        ) : (
          <ErrorState error={query.error} what={`the ${m.loadingList}`} onRetry={() => void query.refetch()} />
        )
      ) : (
        <DataTable
          caption={m.caption}
          hideCaption
          columns={columns()}
          rows={query.data.items}
          rowId={(row) => row.id}
          rowHref={(row) => row.path}
          empty={<EmptyState title={m.emptyTitle}>{m.empty}</EmptyState>}
          footer={
            <OffsetPagination
              label={c.common.pages}
              total={query.data.total}
              limit={query.data.limit || PRICE_LISTS_PAGE_SIZE}
              offset={query.data.offset}
              shown={query.data.items.length}
              control={(offset) => ({ href: priceListHref({ ...state, offset }) })}
            />
          }
        />
      )}
      <CreateListDialog isOpen={creating} onOpenChange={setCreating} />
    </div>
  );
}

function CreateListDialog({ isOpen, onOpenChange }: { isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const router = useRouter();
  const commands = useResourceCommand("price_list:new", [queryKeys.pricing.all()]);
  const [form, setForm] = useState({ code: "", name: "", price_type: "export", currency: "EUR", valid_from: "", valid_to: "", priority: null as string | null });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const submit = async () => {
    const local: Record<string, string> = {};
    if (!form.code.trim()) local.code = "Give the list a code.";
    if (!form.name.trim()) local.name = "Give the list a name.";
    if (!ISO_DATE.test(form.valid_from)) local.valid_from = "Use YYYY-MM-DD.";
    if (form.valid_to && !ISO_DATE.test(form.valid_to)) local.valid_to = "Use YYYY-MM-DD.";
    if (Object.keys(local).length) return setErrors(local);
    const body = {
      code: form.code.trim(),
      name: form.name.trim(),
      price_type: form.price_type,
      currency: form.currency,
      scope_kind: "standard",
      valid_from: form.valid_from,
      ...(form.valid_to ? { valid_to: form.valid_to } : {}),
      ...(form.priority ? { priority: Number.parseInt(form.priority, 10) } : {}),
    };
    const outcome = await commands.run("create", [JSON.stringify(body)], () => createPriceList(body), { failed: c.common.failed(m.create) });
    if (outcome.ok) router.push(outcome.value.path as Parameters<typeof router.push>[0]);
    else setErrors(outcome.fieldErrors);
  };
  return (
    <Dialog
      title={m.newList}
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      footer={(close) => (
        <>
          <Button variant="quiet" onPress={close}>
            {c.common.cancel}
          </Button>
          <Button variant="primary" onPress={() => void submit()} isPending={commands.pending === "create"} {...unavailableWhen(commands.offline)}>
            {m.create}
          </Button>
        </>
      )}
    >
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <TextField label={m.fields.code!} value={form.code} onChange={(code) => setForm({ ...form, code })} maxLength={40} isRequired errorMessage={errors.code} />
        <TextField label={m.fields.name!} value={form.name} onChange={(name) => setForm({ ...form, name })} maxLength={200} isRequired errorMessage={errors.name} />
        <Select label={m.fields.price_type!} options={Object.entries(m.priceTypes).map(([id, label]) => ({ id, label }))} value={form.price_type} onChange={(value) => setForm({ ...form, price_type: value ?? "export" })} />
        <Select label={m.fields.currency!} options={CURRENCIES.map((code) => ({ id: code, label: code }))} value={form.currency} onChange={(value) => setForm({ ...form, currency: value ?? "EUR" })} />
        <TextField label={m.fields.valid_from!} placeholder="2027-01-01" value={form.valid_from} onChange={(valid_from) => setForm({ ...form, valid_from })} isRequired errorMessage={errors.valid_from} />
        <TextField label={m.fields.valid_to!} placeholder="2027-12-31" value={form.valid_to} onChange={(valid_to) => setForm({ ...form, valid_to })} errorMessage={errors.valid_to} />
        <NumberField label={m.fields.priority!} value={form.priority} onChange={(priority) => setForm({ ...form, priority })} maxFractionDigits={0} errorMessage={errors.priority} />
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------------------------
// Detail: items with draft edits, supersede from a date, retire, history; list commands

export function PriceListView({ priceListId }: { priceListId: string }) {
  const query = useQuery({ queryKey: queryKeys.pricing.priceList(priceListId), queryFn: ({ signal }) => fetchPriceList(priceListId, signal) });
  if (query.isPending) return <Loading label={m.loading} variant="detail" />;
  if (query.isError) {
    if (isProblemError(query.error) && query.error.status === 403) return <PermissionDenied area={m.title} />;
    return <ErrorState error={query.error} what={m.loading} onRetry={() => void query.refetch()} />;
  }
  return <PriceListDetailView priceList={query.data} />;
}

type ItemDialog = { kind: "add" } | { kind: "edit" | "supersede" | "retire"; item: PriceItem } | null;

function PriceListDetailView({ priceList }: { priceList: PriceListDetail }) {
  const router = useRouter();
  const [history, setHistory] = useState(false);
  const [offset, setOffset] = useState(0);
  const items = useQuery({
    queryKey: queryKeys.pricing.priceListItems(priceList.id, { offset, history }),
    queryFn: ({ signal }) => fetchPriceItems(priceList.id, { offset, history }, signal),
  });
  const keys = useMemo(() => [queryKeys.pricing.all()], []);
  const commands = useResourceCommand(`price_list:${priceList.id}`, keys);
  const [retiring, setRetiring] = useState(false);
  const [overlap, setOverlap] = useState<{ product_key: string; price_list_code: string }[] | null>(null);
  const [dialog, setDialog] = useState<ItemDialog>(null);
  const [historyOf, setHistoryOf] = useState<PriceItem | null>(null);
  const [duplicating, setDuplicating] = useState(false);
  const caps = priceList.capabilities;
  const can = (name: string) => caps[name]?.allowed === true;
  const transitions = new Set(priceList.allowed_transitions.map((t) => t.action));

  const activate = async () => {
    setOverlap(null);
    const outcome = await commands.run("activate", [priceList.version], () => priceListCommand(priceList, "activate", null), {
      done: m.activated,
      failed: c.common.failed(m.activate),
      conflictMessage: c.common.conflict,
    });
    if (!outcome.ok && outcome.error instanceof ProblemError && outcome.error.code === "price_list_overlap") {
      const conflicts = (outcome.error.problem as { conflicts?: unknown }).conflicts;
      setOverlap(Array.isArray(conflicts) ? (conflicts as { product_key: string; price_list_code: string }[]) : []);
    }
  };

  const itemColumns: DataTableColumn<PriceItem>[] = [
    { id: "product", header: m.columnsItems.product, isRowHeader: true, mobile: "title", cell: (row) => <span className="font-mono">{row.product_key}</span> },
    { id: "unit", header: m.columnsItems.unit, cell: (row) => row.unit_code },
    { id: "price", header: m.columnsItems.price, numeric: true, mobile: "amount", cell: (row) => <Money value={row.unit_price} maxFractionDigits={4} /> },
    { id: "moq", header: m.columnsItems.moq, numeric: true, cell: (row) => (row.moq ? `${row.moq.value.replace(/\.?0+$/, "")} ${row.moq.uom}` : "—") },
    { id: "from", header: m.columnsItems.from, cell: (row) => <LocalDate value={row.valid_from} /> },
    { id: "to", header: m.columnsItems.to, cell: (row) => (row.valid_to ? <LocalDate value={row.valid_to} /> : "—") },
    { id: "status", header: m.columnsItems.status, mobile: "status", cell: (row) => (row.superseded_by_item_id ? m.historyKinds.superseded : m.status[row.status] ?? row.status) },
    {
      id: "actions",
      header: c.customProducts.sections.actions,
      cell: (row) => (
        <div className="flex flex-wrap gap-1">
          <Button size="sm" variant="quiet" onPress={() => setHistoryOf(row)}>
            {m.history}
          </Button>
          {can("edit_item") && row.status === "active" ? (
            <Button size="sm" variant="quiet" onPress={() => setDialog({ kind: "edit", item: row })}>
              {m.edit}
            </Button>
          ) : null}
          {can("supersede_item") && row.status === "active" && !row.superseded_by_item_id ? (
            <Button size="sm" variant="quiet" onPress={() => setDialog({ kind: "supersede", item: row })}>
              {m.supersede}
            </Button>
          ) : null}
          {can("retire_item") && row.status === "active" && !row.superseded_by_item_id ? (
            <Button size="sm" variant="quiet" onPress={() => setDialog({ kind: "retire", item: row })}>
              {m.retireItem}
            </Button>
          ) : null}
        </div>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <Link href="/products/price-lists" className="text-sm">
          {m.back}
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-[26px] font-bold tracking-tight text-ink md:text-3xl">
            <span className="font-mono">{priceList.code}</span> · {priceList.name}
          </h1>
          <PriceListStatusPill status={priceList.status} />
        </div>
        <p role="note" className="text-sm text-ink-muted">
          {priceList.status === "draft" ? m.draftNote : priceList.status === "active" ? m.activeNote : m.retiredNote}
        </p>
      </header>
      <DescriptionList
        items={[
          { term: m.fields.scope_kind!, description: [m.scopes[priceList.scope_kind] ?? priceList.scope_kind, priceList.party?.display_name ?? priceList.customer_type].filter(Boolean).join(" · ") },
          { term: m.fields.price_type!, description: m.priceTypes[priceList.price_type] ?? priceList.price_type },
          { term: m.fields.currency!, description: priceList.currency },
          { term: m.fields.valid_from!, description: <LocalDate value={priceList.valid_from} /> },
          { term: m.fields.valid_to!, description: priceList.valid_to ? <LocalDate value={priceList.valid_to} /> : "—" },
          { term: m.fields.priority!, description: priceList.priority === null ? "—" : String(priceList.priority), numeric: true },
        ]}
      />
      <div className="flex flex-wrap gap-2" data-testid="price-list-actions">
        {transitions.has("activate") ? (
          <Button variant="primary" onPress={() => void activate()} isPending={commands.pending === "activate"} {...unavailableWhen(commands.offline)}>
            {m.activate}
          </Button>
        ) : null}
        {can("add_item") ? (
          <Button variant="secondary" onPress={() => setDialog({ kind: "add" })} {...unavailableWhen(commands.offline)}>
            {m.addItem}
          </Button>
        ) : null}
        {can("duplicate") ? (
          <Button variant="secondary" onPress={() => setDuplicating(true)} {...unavailableWhen(commands.offline)}>
            {m.duplicate}
          </Button>
        ) : null}
        {transitions.has("retire") ? (
          <Button variant="danger" onPress={() => setRetiring(true)} {...unavailableWhen(commands.offline)}>
            {m.retire}
          </Button>
        ) : null}
      </div>
      {overlap ? (
        <div role="alert" className="rounded-md border border-danger/40 bg-danger-bg px-4 py-3 text-ink">
          <p>{m.overlap}</p>
          <ul className="list-disc ps-5 text-sm">
            {overlap.map((row) => (
              <li key={`${row.product_key}-${row.price_list_code}`}>
                {row.product_key} · {row.price_list_code}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <section aria-label={m.items} className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-[650] text-ink">{m.items}</h2>
          <Checkbox isSelected={history} onChange={(next) => (setHistory(next), setOffset(0))}>
            {m.showHistory}
          </Checkbox>
        </div>
        {items.isPending ? (
          <Loading label={m.items} variant="inline" />
        ) : items.isError ? (
          <ErrorState error={items.error} what={m.items} compact headingLevel={3} backToToday={false} onRetry={() => void items.refetch()} />
        ) : (
          <DataTable
            caption={m.items}
            hideCaption
            columns={itemColumns}
            rows={items.data.items}
            rowId={(row) => row.id}
            empty={<EmptyState title={m.items}>{m.itemsEmpty}</EmptyState>}
            footer={
              <OffsetPagination
                label={c.common.pages}
                total={items.data.total}
                limit={items.data.limit || ITEMS_PAGE_SIZE}
                offset={items.data.offset}
                shown={items.data.items.length}
                control={(next) => ({ onPress: () => setOffset(next) })}
              />
            }
          />
        )}
      </section>
      <ReasonDialog
        title={m.retire}
        description={priceList.code}
        requireNote
        noteLabel={c.common.reason}
        confirmLabel={m.retire}
        isOpen={retiring}
        isPending={commands.pending === "retire"}
        disabledReason={commands.offline}
        onOpenChange={setRetiring}
        onConfirm={(_, note) =>
          void commands
            .run("retire", [priceList.version, note], () => priceListCommand(priceList, "retire", note), { done: m.retired, failed: c.common.failed(m.retire), conflictMessage: c.common.conflict })
            .then(() => setRetiring(false))
        }
      />
      <ItemDialogView priceList={priceList} dialog={dialog} onClose={() => setDialog(null)} commands={commands} />
      <DuplicateDialog priceList={priceList} isOpen={duplicating} onOpenChange={setDuplicating} onDone={(path) => router.push(path as Parameters<typeof router.push>[0])} />
      <Drawer title={historyOf ? m.historyTitle(historyOf.product_key) : ""} isOpen={historyOf !== null} onOpenChange={(open) => (open ? null : setHistoryOf(null))}>
        {historyOf ? <ItemHistory item={historyOf} currency={priceList.currency} /> : null}
      </Drawer>
    </div>
  );
}

function ItemHistory({ item, currency }: { item: PriceItem; currency: string }) {
  const query = useQuery({ queryKey: queryKeys.pricing.itemHistory(item.id), queryFn: ({ signal }) => fetchItemHistory(item.id, signal) });
  if (query.isPending) return <Loading label={m.history} variant="inline" />;
  if (query.isError) return <ErrorState error={query.error} what={m.history} compact headingLevel={3} backToToday={false} />;
  if (query.data.length === 0) return <p className="text-ink-muted">{m.noHistory}</p>;
  const price = (snap: Record<string, unknown> | null) => (snap && typeof snap.unit_price === "string" ? <Money value={{ amount: snap.unit_price, currency }} maxFractionDigits={4} /> : null);
  return (
    <ol className="flex flex-col divide-y border-y">
      {query.data.map((entry) => (
        <li key={entry.id} className="flex flex-col gap-0.5 py-2">
          <span className="font-semibold text-ink">{m.historyKinds[entry.change_kind] ?? entry.change_kind}</span>
          <span className="text-sm text-ink">
            {price(entry.before)} {entry.before && entry.after ? "→" : null} {price(entry.after)}
            {entry.after && typeof entry.after.valid_from === "string" ? ` · from ${entry.after.valid_from}` : ""}
            {entry.after && typeof entry.after.valid_to === "string" ? ` · to ${entry.after.valid_to}` : ""}
          </span>
          <span className="text-sm text-ink-muted">
            <LocalDateTime value={entry.occurred_at} />
            {entry.actor_name ? ` · ${entry.actor_name}` : ""}
            {entry.reason ? ` · ${entry.reason}` : ""}
          </span>
        </li>
      ))}
    </ol>
  );
}

function ItemDialogView({
  priceList,
  dialog,
  onClose,
  commands,
}: {
  priceList: PriceListDetail;
  dialog: ItemDialog;
  onClose: () => void;
  commands: ReturnType<typeof useResourceCommand>;
}) {
  const [productText, setProductText] = useState("");
  const [product, setProduct] = useState<string | null>(null);
  const [unit, setUnit] = useState("pcs");
  const [price, setPrice] = useState<string | null>(null);
  const [moq, setMoq] = useState<string | null>(null);
  const [from, setFrom] = useState("");
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [openedFor, setOpenedFor] = useState<ItemDialog>(null);
  if (dialog !== openedFor) {
    setOpenedFor(dialog);
    setErrors({});
    setReason("");
    setFrom("");
    setPrice(dialog && dialog.kind !== "add" ? dialog.item.unit_price.amount : null);
    setMoq(dialog && dialog.kind === "edit" ? (dialog.item.moq?.value ?? null) : null);
  }
  const products = useProductSearch(productText);
  const options = (products.data ?? []).map((p) => ({ id: p.id, label: p.product_name, detail: p.product_key }));
  if (dialog === null) return null;
  const title = dialog.kind === "add" ? m.addItem : dialog.kind === "edit" ? m.edit : dialog.kind === "supersede" ? m.supersede : m.retireItem;
  const confirm = async () => {
    let call: () => Promise<unknown>;
    if (dialog.kind === "add") {
      if (!product || !price) return setErrors({ product_id: product ? "" : "Choose the product.", unit_price: price ? "" : "Enter the price." });
      const body = { product_id: product, unit_code: unit, unit_price: price, ...(moq ? { moq } : {}) };
      call = () => addPriceItem(priceList.id, body);
    } else if (dialog.kind === "edit") {
      const changes: Record<string, unknown> = {};
      if (price && price !== dialog.item.unit_price.amount) changes.unit_price = price;
      if (moq !== (dialog.item.moq?.value ?? null)) changes.moq = moq;
      call = () => updatePriceItem(dialog.item, changes);
    } else if (dialog.kind === "supersede") {
      if (!price || !ISO_DATE.test(from)) return setErrors({ unit_price: price ? "" : "Enter the new price.", valid_from: ISO_DATE.test(from) ? "" : "Use YYYY-MM-DD." });
      call = () => supersedePriceItem(dialog.item, { unit_price: price, valid_from: from, reason: reason.trim() || null });
    } else {
      if (!reason.trim()) return setErrors({ reason: c.common.reasonRequired });
      call = () => retirePriceItem(dialog.item, { reason: reason.trim(), retire_from: ISO_DATE.test(from) ? from : null });
    }
    const outcome = await commands.run(`item:${dialog.kind}`, [dialog.kind === "add" ? product : dialog.item.id, price, from, reason], call, {
      done: dialog.kind === "add" ? m.added : dialog.kind === "supersede" ? m.superseded : dialog.kind === "retire" ? m.itemRetired : c.common.saved,
      failed: c.common.failed(title),
      conflictMessage: c.common.conflict,
    });
    if (outcome.ok) onClose();
    else setErrors(outcome.fieldErrors);
  };
  return (
    <Dialog
      title={title}
      description={dialog.kind === "add" ? priceList.code : `${priceList.code} · ${dialog.item.product_key}`}
      isOpen
      onOpenChange={(open) => (open ? null : onClose())}
      footer={(close) => (
        <>
          <Button variant="quiet" onPress={close}>
            {c.common.cancel}
          </Button>
          <Button variant={dialog.kind === "retire" ? "danger" : "primary"} onPress={() => void confirm()} isPending={commands.pending !== null} {...unavailableWhen(commands.offline)}>
            {title}
          </Button>
        </>
      )}
    >
      <div className="flex flex-col gap-4">
        {dialog.kind === "add" ? (
          <>
            <ComboBox
              label={m.fields.product_id!}
              placeholder="Type a product key or name"
              emptyText="No product matches"
              options={options}
              value={product}
              inputValue={productText}
              onInputChange={setProductText}
              onChange={(id) => {
                setProduct(id);
                const option = options.find((candidate) => candidate.id === id);
                if (option) setProductText(option.label);
              }}
              isRequired
              errorMessage={errors.product_id || undefined}
            />
            <Select label={m.fields.unit_code!} options={["pcs", "set", "sheets", "box", "sqm", "sqft"].map((u) => ({ id: u, label: u }))} value={unit} onChange={(value) => setUnit(value ?? "pcs")} />
          </>
        ) : null}
        {dialog.kind !== "retire" ? (
          <NumberField label={m.fields.unit_price!} value={price} onChange={setPrice} currency={priceList.currency} isRequired errorMessage={errors.unit_price || undefined} />
        ) : null}
        {dialog.kind === "add" || dialog.kind === "edit" ? <NumberField label={m.fields.moq!} value={moq} onChange={setMoq} errorMessage={errors.moq || undefined} /> : null}
        {dialog.kind === "supersede" || dialog.kind === "retire" ? (
          <TextField
            label={dialog.kind === "supersede" ? m.fields.valid_from! : m.fields.retire_from!}
            placeholder="2026-11-01"
            value={from}
            onChange={setFrom}
            isRequired={dialog.kind === "supersede"}
            errorMessage={errors.valid_from || errors.retire_from || undefined}
          />
        ) : null}
        {dialog.kind === "supersede" || dialog.kind === "retire" ? (
          <TextField label={m.fields.reason!} value={reason} onChange={setReason} maxLength={500} isRequired={dialog.kind === "retire"} errorMessage={errors.reason || undefined} />
        ) : null}
      </div>
    </Dialog>
  );
}

function DuplicateDialog({ priceList, isOpen, onOpenChange, onDone }: { priceList: PriceListDetail; isOpen: boolean; onOpenChange: (open: boolean) => void; onDone: (path: string) => void }) {
  const commands = useResourceCommand(`price_list_dup:${priceList.id}`, [queryKeys.pricing.all()]);
  const [form, setForm] = useState({ code: "", name: "", valid_from: "", valid_to: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const submit = async () => {
    if (!form.code.trim() || !form.name.trim() || !ISO_DATE.test(form.valid_from)) {
      return setErrors({ code: form.code.trim() ? "" : "Give the copy a code.", name: form.name.trim() ? "" : "Give the copy a name.", valid_from: ISO_DATE.test(form.valid_from) ? "" : "Use YYYY-MM-DD." });
    }
    const body = { code: form.code.trim(), name: form.name.trim(), valid_from: form.valid_from, ...(form.valid_to ? { valid_to: form.valid_to } : {}) };
    const outcome = await commands.run("duplicate", [JSON.stringify(body)], () => duplicatePriceList(priceList.id, body), { failed: c.common.failed(m.duplicate) });
    if (outcome.ok) onDone(outcome.value.path);
    else setErrors(outcome.fieldErrors);
  };
  return (
    <Dialog
      title={m.duplicate}
      description={priceList.code}
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      footer={(close) => (
        <>
          <Button variant="quiet" onPress={close}>
            {c.common.cancel}
          </Button>
          <Button variant="primary" onPress={() => void submit()} isPending={commands.pending === "duplicate"} {...unavailableWhen(commands.offline)}>
            {m.duplicate}
          </Button>
        </>
      )}
    >
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <TextField label={m.fields.code!} value={form.code} onChange={(code) => setForm({ ...form, code })} maxLength={40} isRequired errorMessage={errors.code || undefined} />
        <TextField label={m.fields.name!} value={form.name} onChange={(name) => setForm({ ...form, name })} maxLength={200} isRequired errorMessage={errors.name || undefined} />
        <TextField label={m.fields.valid_from!} placeholder="2027-01-01" value={form.valid_from} onChange={(valid_from) => setForm({ ...form, valid_from })} isRequired errorMessage={errors.valid_from || undefined} />
        <TextField label={m.fields.valid_to!} placeholder="2027-12-31" value={form.valid_to} onChange={(valid_to) => setForm({ ...form, valid_to })} />
      </div>
    </Dialog>
  );
}
