"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useId, useState, type FormEvent } from "react";
import { useProductSearch } from "@/features/sales/pickers";
import { useResourceCommand } from "@/features/sales/resource-command";
import { fieldErrorsFrom } from "@/features/parties/form-model";
import { useSession } from "@/lib/session/context";
import { useWarehouses } from "~/data/stock";
import {
  CATEGORY_INVALIDATE,
  CATEGORY_PAGE_SIZE,
  createAndSubmitOpening,
  relocateStock,
  useCategoryTotals,
  useStockByCategory,
  type CategoryRow,
  type Market,
  type StockCategory,
} from "~/data/stock-categories";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { useStepUp } from "~/screens/settings-access/step-up";
import {
  Badge,
  Banner,
  Button,
  ChipGroup,
  ChipLink,
  ComboBox,
  DataTable,
  DecimalField,
  EmptyState,
  GlassPanel,
  Modal,
  PageSummary,
  Pagination,
  SearchField,
  Select,
  StatTile,
  TableFooter,
  TextField,
  toast,
  type Column,
} from "~/ui";
import { categoryHref, type CategoryState } from "./category-state";
import { StockViews } from "./parts";

export const CATEGORY_LABEL: Record<StockCategory, string> = { inventory: "Inventory", sample: "Sample", exhibition: "Exhibition" };
const CATEGORY_CODE: Record<StockCategory, string> = { inventory: "STOCK", sample: "SAMPLE", exhibition: "EXHIB" };
const CATEGORIES: readonly StockCategory[] = ["inventory", "sample", "exhibition"];

const qtyText = (value: string, uom: string | null | undefined) => (Number(value) === 0 ? "—" : `${Number(value).toLocaleString()}${uom ? ` ${uom}` : ""}`);

/** One stock pool, split into inventory (free to sell), sample and exhibition stock, with what the factory still owes. */
export function StockByCategory({ state }: { state: CategoryState }) {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const warehouses = useWarehouses();
  const query = useStockByCategory({ q: state.q, warehouse_id: state.warehouse, market: state.market, category: state.category, offset: state.offset });
  const totals = useCategoryTotals({ warehouse_id: state.warehouse, market: state.market });
  const [moving, setMoving] = useState<{ row: CategoryRow; round: number } | null>(null);
  const [opening, setOpening] = useState(0);
  const href = (next: Partial<CategoryState>) => categoryHref({ ...state, offset: 0, ...next }) as Route;
  const canMove = permissionKeys.has("inventory.stock.post");
  const canOpen = permissionKeys.has("inventory.opening_batch.create");
  const limit = query.data?.limit || CATEGORY_PAGE_SIZE;
  const total = query.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / limit));
  const page = Math.floor((query.data?.offset ?? state.offset) / limit) + 1;

  const columns: Column<CategoryRow>[] = [
    {
      key: "product",
      header: "Product",
      primary: true,
      cell: (r) => (
        <span className="flex min-w-0 flex-col">
          <span className="t-label lk-mono truncate text-ink">{r.product_key}</span>
          <span className="t-caption truncate text-ink-3">{r.product_name}</span>
        </span>
      ),
    },
    {
      key: "warehouse",
      header: "Warehouse",
      hideOnMobile: true,
      cell: (r) => (
        <span className="flex flex-wrap items-center gap-1">
          <span>{r.warehouse_code}</span>
          {r.market ? (
            <Badge size="sm" outline>
              {r.market === "export" ? "Export" : "Domestic"}
              {r.country_code ? ` · ${r.country_code}` : ""}
            </Badge>
          ) : null}
        </span>
      ),
    },
    { key: "inventory", header: "Inventory", numeric: true, cell: (r) => <span className="lk-tnum">{qtyText(r.inventory, r.uom)}</span> },
    { key: "sample", header: "Sample", numeric: true, cell: (r) => <span className="lk-tnum">{qtyText(r.sample, r.uom)}</span> },
    { key: "exhibition", header: "Exhibition", numeric: true, cell: (r) => <span className="lk-tnum">{qtyText(r.exhibition, r.uom)}</span> },
    { key: "on_order", header: "On order", numeric: true, hideOnMobile: true, cell: (r) => <span className="lk-tnum text-ink-2">{qtyText(r.on_order, r.uom)}</span> },
    ...(canMove
      ? [
          {
            key: "move",
            header: <span className="lk-sr-only">Move</span>,
            width: "96px",
            cell: (r: CategoryRow) => (
              <Button variant="secondary" size="sm" onPress={() => setMoving((m) => ({ row: r, round: (m?.round ?? 0) + 1 }))} aria-label={`Move ${r.product_key}`}>
                Move
              </Button>
            ),
          },
        ]
      : []),
  ];

  return (
    <Page>
      <PageHeader
        eyebrow="Operations"
        title="Stock by category"
        lead="One stock pool: inventory you can sell, samples and exhibition pieces, and what the factory still has to deliver."
        actions={
          canOpen ? (
            <Button iconLeft="plus" onPress={() => setOpening((n) => n + 1)}>
              Add opening stock
            </Button>
          ) : null
        }
      />
      <StockViews current="categories" />

      <GlassPanel padding="md" className="rise" aria-label="Stock by category at a glance" role="group">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          {CATEGORIES.map((c) => (
            <StatTile
              key={c}
              label={CATEGORY_LABEL[c]}
              value={totals.data ? Number(totals.data[c]).toLocaleString() : "…"}
              foot={c === "inventory" ? "Free to sell" : c === "sample" ? "Set aside for samples" : "At or for exhibitions"}
              href={href({ category: state.category === c ? null : c })}
            />
          ))}
        </div>
      </GlassPanel>

      <div className="rise flex min-w-0 flex-col gap-3">
        <div className="flex min-w-0 flex-col gap-3 md:flex-row md:items-center">
          <SearchField
            key={state.q}
            className="min-w-0 md:max-w-xl md:flex-1"
            label="Search stock"
            placeholder="Product key, name or decor"
            defaultValue={state.q}
            onSubmit={(q) => router.push(href({ q }))}
            onChange={(q) => {
              if (q === "" && state.q) router.push(href({ q: "" }));
            }}
          />
          {warehouses.data && warehouses.data.length > 1 ? (
            <Select
              className="min-w-0 md:w-64"
              label="Warehouse"
              hideLabel
              options={[{ value: "all", label: "All warehouses" }, ...warehouses.data.map((w) => ({ value: w.id, label: w.name, description: w.code }))]}
              value={state.warehouse ?? "all"}
              onChange={(v) => router.push(href({ warehouse: v === "all" ? null : v }))}
            />
          ) : null}
        </div>
        <ChipGroup label="Category and market">
          {CATEGORIES.map((c) => (
            <ChipLink key={c} href={href({ category: state.category === c ? null : c })} selected={state.category === c}>
              {CATEGORY_LABEL[c]}
            </ChipLink>
          ))}
          <ChipLink href={href({ market: state.market === "domestic" ? null : "domestic" })} selected={state.market === "domestic"}>
            Domestic
          </ChipLink>
          <ChipLink href={href({ market: state.market === "export" ? null : "export" })} selected={state.market === "export"} icon="globe">
            Export
          </ChipLink>
        </ChipGroup>
      </div>

      {query.isError ? (
        <ErrorBlock error={query.error} what="Stock by category" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise">
          <DataTable
            label="Stock by category"
            columns={columns}
            rows={query.data?.items ?? []}
            rowKey={(r) => `${r.product_id}:${r.warehouse_id}`}
            loading={query.isPending}
            skeletonRows={8}
            empty={
              <EmptyState
                icon="warehouse"
                title="No finished stock here yet"
                text="Add opening stock for each product as you count it. It goes to a second person for approval, then shows here."
                actions={
                  canOpen ? (
                    <Button iconLeft="plus" onPress={() => setOpening((n) => n + 1)}>
                      Add opening stock
                    </Button>
                  ) : undefined
                }
              />
            }
            footer={
              query.data && total > 0 ? (
                <TableFooter
                  left={<PageSummary from={query.data.offset + 1} to={query.data.offset + query.data.items.length} total={total} noun="stock lines" />}
                  right={pages > 1 ? <Pagination label="Stock pages" page={page} pages={pages} hrefFor={(t) => href({ offset: (t - 1) * limit })} /> : null}
                />
              ) : undefined
            }
          />
        </GlassPanel>
      )}
      {moving ? <MoveStockDialog key={moving.round} row={moving.row} onClose={() => setMoving(null)} /> : null}
      {opening > 0 ? <OpeningStockDialog key={opening} onClose={() => setOpening(0)} /> : null}
    </Page>
  );
}

function useCategoryLocations() {
  const warehouses = useWarehouses();
  const find = (warehouseId: string, category: StockCategory) =>
    warehouses.data
      ?.find((w) => w.id === warehouseId)
      ?.locations.find((l) => l.stock_category === category && (category !== "inventory" || l.code === CATEGORY_CODE.inventory))?.id ?? null;
  return { warehouses, find };
}

function MoveStockDialog({ row, onClose }: { row: CategoryRow; onClose: () => void }) {
  const formId = useId();
  const commands = useResourceCommand(`move:${row.product_id}:${row.warehouse_id}`, CATEGORY_INVALIDATE);
  const { find } = useCategoryLocations();
  const [from, setFrom] = useState<StockCategory>(Number(row.inventory) > 0 ? "inventory" : Number(row.sample) > 0 ? "sample" : "exhibition");
  const [to, setTo] = useState<StockCategory>(from === "exhibition" ? "inventory" : "exhibition");
  const [quantity, setQuantity] = useState("1");
  const [error, setError] = useState<string | null>(null);
  const available = Number(row[from]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const fromId = find(row.warehouse_id, from);
    const toId = find(row.warehouse_id, to);
    if (from === to) return setError("Pick two different categories.");
    if (!fromId || !toId) return setError("This warehouse has no location for that category.");
    if (!(Number(quantity) > 0) || Number(quantity) > available) return setError(`Enter a quantity up to ${available}.`);
    const body = { product_id: row.product_id, from_location_id: fromId, to_location_id: toId, quantity, unit: row.uom ?? "pcs" };
    const result = await commands.run("move", [JSON.stringify(body)], (key) => relocateStock(body, key), { failed: "The stock was not moved" });
    if (result.ok) {
      toast.success(`${quantity} moved to ${CATEGORY_LABEL[to].toLowerCase()}`);
      onClose();
    } else if (!result.conflict) {
      setError(result.error instanceof Error ? result.error.message : "Try again.");
    }
  };

  return (
    <Modal
      isOpen
      onOpenChange={(open) => (open ? undefined : onClose())}
      size="sm"
      title={`Move ${row.product_key}`}
      description={`Within ${row.warehouse_name}. Stock leaves one category and joins another; the total stays the same.`}
      actions={
        <>
          <Button variant="ghost" onPress={onClose}>
            Cancel
          </Button>
          <Button type="submit" form={formId} loading={commands.pending === "move"}>
            Move stock
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={(event) => void submit(event)} noValidate className="flex flex-col gap-4">
        {error ? (
          <Banner tone="ember" title="Not moved.">
            {error}
          </Banner>
        ) : null}
        <div className="grid grid-cols-2 gap-4">
          <Select label="From" options={CATEGORIES.map((c) => ({ value: c, label: `${CATEGORY_LABEL[c]} (${Number(row[c])})` }))} value={from} onChange={(v) => setFrom((v as StockCategory) ?? from)} />
          <Select label="To" options={CATEGORIES.map((c) => ({ value: c, label: CATEGORY_LABEL[c] }))} value={to} onChange={(v) => setTo((v as StockCategory) ?? to)} />
        </div>
        <DecimalField label="Quantity" value={quantity} onChange={setQuantity} maxFractionDigits={0} isRequired help={`${available} in ${CATEGORY_LABEL[from].toLowerCase()}`} />
      </form>
    </Modal>
  );
}

function OpeningStockDialog({ onClose }: { onClose: () => void }) {
  const formId = useId();
  const router = useRouter();
  const stepUp = useStepUp();
  const commands = useResourceCommand("opening:new", CATEGORY_INVALIDATE);
  const { warehouses, find } = useCategoryLocations();
  const [text, setText] = useState("");
  const [productId, setProductId] = useState<string | null>(null);
  const [warehouseId, setWarehouseId] = useState<string | null>(null);
  const [category, setCategory] = useState<StockCategory>("inventory");
  const [quantity, setQuantity] = useState("");
  const [lot, setLot] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const search = useProductSearch(text);
  const options = (search.data ?? []).map((p) => ({ id: p.id, label: p.product_key, description: p.product_name }));
  const warehouse = warehouseId ?? warehouses.data?.[0]?.id ?? null;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const local: Record<string, string> = {};
    if (!productId) local.product_id = "Pick the product you counted.";
    if (!warehouse) local.warehouse_id = "Pick the warehouse.";
    if (!(Number(quantity) > 0)) local.quantity = "Enter how many you counted.";
    const location = warehouse ? find(warehouse, category) : null;
    if (warehouse && !location) local.category = "This warehouse has no location for that category.";
    if (Object.keys(local).length) return setErrors(local);
    const body = {
      warehouse_id: warehouse!,
      lines: [{ product_id: productId!, quantity, location_id: location!, lot_code: lot.trim() || null, late_opening: true }],
    };
    const result = await commands.run("opening", [JSON.stringify(body)], (key) => stepUp.run(() => createAndSubmitOpening(body, key)), {
      failed: "The opening stock was not saved",
    });
    if (result.ok) {
      toast.success("Opening stock sent for approval", { description: "A second person approves it, then it shows in the stock." });
      onClose();
      router.push(`/operations/inventory/opening/${result.value.id}` as Route);
    } else if (!result.conflict) {
      setErrors(fieldErrorsFrom(result.error));
    }
  };

  return (
    <>
      <Modal
        isOpen
        onOpenChange={(open) => (open ? undefined : onClose())}
        title="Add opening stock"
        description="Stock you already hold, counted before Lamikraft One. It goes to a second person for approval."
        actions={
          <>
            <Button variant="ghost" onPress={onClose}>
              Cancel
            </Button>
            <Button type="submit" form={formId} loading={commands.pending === "opening"}>
              Send for approval
            </Button>
          </>
        }
      >
        <form id={formId} onSubmit={(event) => void submit(event)} noValidate className="flex flex-col gap-4">
          <ComboBox
            label="Product"
            placeholder="Type a product key or name"
            emptyText={text.trim().length < 2 ? "Type at least two letters" : "No product matches. Add it under Products first."}
            items={options}
            inputValue={text}
            onInputChange={setText}
            selectedKey={productId}
            onSelectionChange={(id) => {
              setProductId(id);
              const option = options.find((o) => o.id === id);
              if (option) setText(option.label);
            }}
            isLoading={search.isFetching}
            isRequired
            error={errors.product_id}
          />
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Select
              label="Warehouse"
              options={(warehouses.data ?? []).map((w) => ({ value: w.id, label: w.name, description: w.code }))}
              value={warehouse}
              onChange={setWarehouseId}
              isRequired
              error={errors.warehouse_id}
            />
            <Select label="Category" options={CATEGORIES.map((c) => ({ value: c, label: CATEGORY_LABEL[c] }))} value={category} onChange={(v) => setCategory((v as StockCategory) ?? "inventory")} error={errors.category} />
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <DecimalField label="Quantity counted" value={quantity} onChange={setQuantity} maxFractionDigits={0} isRequired error={errors.quantity} />
            <TextField label="Lot" optional value={lot} onChange={setLot} maxLength={60} help="Only for products tracked by lot." />
          </div>
        </form>
      </Modal>
      {stepUp.dialog}
    </>
  );
}
