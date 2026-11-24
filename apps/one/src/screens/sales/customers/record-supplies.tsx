"use client";

import { useQuery } from "@tanstack/react-query";
import { useId, useMemo, useState, type FormEvent } from "react";
import { useCommand } from "@/features/inventory/use-command";
import { fetchVendorItems, saveVendorItem, type VendorItem, type VendorItemDraft } from "@/features/procurement/api";
import { useProductSearch, type ProductOption } from "@/features/sales/pickers";
import { queryKeys } from "@/lib/api/query-keys";
import { CURRENCIES } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { ErrorBlock } from "~/shell/states";
import { Badge, Button, ComboBox, DataTable, DateText, DecimalField, EmptyState, GlassPanel, Modal, Money, Select, Switch, TextField, type Column } from "~/ui";

const COLUMNS: Column<VendorItem>[] = [
  {
    key: "product",
    header: "Product",
    primary: true,
    cell: (item) => (
      <span className="flex min-w-0 flex-col">
        <span className="t-label truncate text-ink">{item.product.name}</span>
        <span className="t-caption lk-mono text-ink-3">{item.product.product_key}</span>
      </span>
    ),
  },
  { key: "code", header: "Their code", cell: (item) => item.vendor_code ?? "" },
  { key: "lead", header: "Lead time", numeric: true, cell: (item) => (item.lead_time_days === null ? "" : `${item.lead_time_days} ${item.lead_time_days === 1 ? "day" : "days"}`) },
  {
    key: "price",
    header: "Price",
    numeric: true,
    cell: (item) => (
      <span className="whitespace-nowrap">
        <Money value={{ amount: item.unit_price, currency: item.currency }} /> <span className="text-ink-3">per {item.price_uom}</span>
      </span>
    ),
  },
  { key: "from", header: "From", hideOnMobile: true, cell: (item) => <DateText value={item.valid_from} style="business" /> },
  {
    key: "status",
    header: "Status",
    cell: (item) => (
      <Badge tone={item.is_active ? "leaf" : "neutral"} dot>
        {item.is_active ? "Current" : "Replaced"}
      </Badge>
    ),
  },
];

/**
 * What a vendor sells you: their codes, lead times and prices. A new price replaces the old one,
 * which stays in the history. Shown on records with the vendor role, to people who may read it.
 */
export function SuppliesView({ vendorId, vendorName, defaultCurrency }: { vendorId: string; vendorName: string; defaultCurrency: string | null }) {
  const { permissionKeys } = useSession();
  const [history, setHistory] = useState(false);
  const [adding, setAdding] = useState(0);
  const [open, setOpen] = useState(false);
  const query = useQuery({ queryKey: queryKeys.procurement.vendorItems(vendorId, history), queryFn: ({ signal }) => fetchVendorItems(vendorId, history, signal) });
  const canManage = permissionKeys.has("procurement.vendor_item.manage");
  const addButton = canManage ? (
    <Button
      variant="secondary"
      size="sm"
      iconLeft="plus"
      onPress={() => {
        setAdding((count) => count + 1);
        setOpen(true);
      }}
    >
      Add a price
    </Button>
  ) : undefined;

  return (
    <div className="stack">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Switch label="Show replaced prices" isSelected={history} onChange={setHistory} />
        {addButton}
      </div>
      {query.isError ? (
        <ErrorBlock error={query.error} what="Their price list" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise">
          <DataTable
            label={`What ${vendorName} supplies`}
            columns={COLUMNS}
            rows={query.data?.items ?? []}
            rowKey={(item) => item.id}
            loading={query.isPending}
            skeletonRows={4}
            empty={<EmptyState icon="tag" title="No prices from this vendor yet" text="Add what they sell you, with their code, lead time and price, so purchase orders can pick it up." actions={addButton} />}
          />
        </GlassPanel>
      )}
      {canManage ? <AddPriceModal key={adding} vendorId={vendorId} defaultCurrency={defaultCurrency} isOpen={open} onOpenChange={setOpen} /> : null}
    </div>
  );
}

function AddPriceModal({ vendorId, defaultCurrency, isOpen, onOpenChange }: { vendorId: string; defaultCurrency: string | null; isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const formId = useId();
  const key = useMemo(() => queryKeys.procurement.vendorItems(vendorId, false), [vendorId]);
  const { run, pending, offline } = useCommand<null>(key);
  const [text, setText] = useState("");
  const [product, setProduct] = useState<ProductOption | null>(null);
  const [code, setCode] = useState("");
  const [lead, setLead] = useState("");
  const [price, setPrice] = useState("");
  const [currency, setCurrency] = useState<VendorItemDraft["currency"]>(CURRENCIES.find((candidate) => candidate === defaultCurrency) ?? "INR");
  const [submitted, setSubmitted] = useState(false);
  const search = useProductSearch(text);
  const options = [...(product ? [product] : []), ...(search.data ?? []).filter((candidate) => candidate.id !== product?.id)];
  const leadDays = /^\d{1,3}$/.test(lead) ? Number.parseInt(lead, 10) : null;
  const errors = {
    product: !product ? "Choose the product this price is for." : undefined,
    price: !price ? "Enter the price they charge." : undefined,
    lead: lead !== "" && leadDays === null ? "Enter whole days, up to 999." : undefined,
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (!product || !price || errors.lead || pending) return;
    const saved = await run(
      "save",
      (idempotencyKey) => saveVendorItem({ vendor_party_id: vendorId, product_id: product.id, vendor_code: code, lead_time_days: leadDays, unit_price: price, currency }, idempotencyKey),
      { done: "Price saved", failed: "The price was not saved" },
    );
    if (saved) onOpenChange(false);
  };

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      title="Add a price"
      description="If this vendor already has a price for the product, the new one replaces it and the old one moves to the history."
      actions={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" form={formId} loading={pending === "save"} isDisabled={Boolean(offline)}>
            Save price
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={(event) => void submit(event)} noValidate className="flex flex-col gap-4">
        <ComboBox
          label="Product"
          placeholder="Type a name or code"
          emptyText={text.trim().length < 2 ? "Type at least two letters" : "No product matches"}
          items={options.map((option) => ({ id: option.id, label: option.product_name, description: option.product_key }))}
          inputValue={text}
          onInputChange={setText}
          selectedKey={product?.id ?? null}
          onSelectionChange={(id) => {
            const found = options.find((option) => option.id === id) ?? null;
            setProduct(found);
            if (found) setText(found.product_name);
          }}
          isLoading={search.isFetching}
          isRequired
          error={submitted ? errors.product : undefined}
        />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <TextField label="Their code" optional value={code} onChange={setCode} maxLength={60} />
          <DecimalField label="Lead time" optional value={lead} onChange={setLead} maxFractionDigits={0} suffix="days" error={errors.lead} />
          <DecimalField label="Price" value={price} onChange={setPrice} maxFractionDigits={4} prefix={currency} isRequired error={submitted ? errors.price : undefined} />
          <Select label="Currency" options={CURRENCIES.map((option) => ({ value: option, label: option }))} value={currency} onChange={(value) => setCurrency(CURRENCIES.find((candidate) => candidate === value) ?? "INR")} />
        </div>
      </form>
    </Modal>
  );
}
