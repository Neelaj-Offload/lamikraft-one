"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { StatusPill } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/choice";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { LocalDate } from "@/components/ui/format";
import { NumberField } from "@/components/ui/number-field";
import { SectionCard } from "@/components/ui/section-card";
import { ComboBox, Select } from "@/components/ui/select";
import { ErrorState, Loading } from "@/components/ui/states";
import { TextField } from "@/components/ui/text-field";
import { useCommand } from "@/features/inventory/use-command";
import { useProductSearch, type ProductOption } from "@/features/sales/pickers";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { procurementMessages as m } from "@/messages/procurement";
import { fetchVendorItems, saveVendorItem, type VendorItem, type VendorItemDraft } from "./api";
import { dash, money } from "./shared";

const CURRENCIES = ["INR", "EUR", "USD", "GBP"] as const satisfies readonly VendorItemDraft["currency"][];

/**
 * Vendor items on a vendor's party record (procurement lane, appended to the party page): what the vendor sells,
 * with vendor codes, lead times and prices; a new price supersedes the old one, which stays in the history.
 * Shown only for parties with the vendor role to people who may read vendor items.
 */
export function VendorItemsSection({ vendorId, defaultCurrency }: { vendorId: string; defaultCurrency: string | null }) {
  const v = m.vendorItems;
  const { permissionKeys } = useSession();
  const [history, setHistory] = useState(false);
  const query = useQuery({ queryKey: queryKeys.procurement.vendorItems(vendorId, history), queryFn: ({ signal }) => fetchVendorItems(vendorId, history, signal) });
  const canManage = permissionKeys.has("procurement.vendor_item.manage");
  const columns: DataTableColumn<VendorItem>[] = [
    { id: "product", header: v.columns.product, isRowHeader: true, mobile: "title", cell: (x) => `${x.product.product_key} · ${x.product.name}` },
    { id: "code", header: v.columns.code, cell: (x) => x.vendor_code ?? dash },
    { id: "lead", header: v.columns.lead, numeric: true, mobile: "meta", cell: (x) => (x.lead_time_days != null ? v.days(x.lead_time_days) : dash) },
    { id: "price", header: v.columns.price, numeric: true, mobile: "amount", cell: (x) => <>{money(x.unit_price, x.currency)} / {x.price_uom}</> },
    { id: "from", header: v.columns.from, cell: (x) => <LocalDate value={x.valid_from} /> },
    { id: "to", header: v.columns.to, cell: (x) => (x.valid_to ? <LocalDate value={x.valid_to} /> : dash) },
    { id: "status", header: v.columns.status, mobile: "status", cell: (x) => <StatusPill tone={x.is_active ? "success" : "neutral"}>{x.is_active ? v.active : v.superseded}</StatusPill> },
  ];
  return (
    <SectionCard title={v.heading} description={v.intro}>
      <div className="flex flex-col gap-4">
        <Checkbox isSelected={history} onChange={setHistory}>
          {v.showHistory}
        </Checkbox>
        {query.isPending ? (
          <Loading label={v.loading} />
        ) : query.isError ? (
          <ErrorState error={query.error} what={v.loading} onRetry={() => void query.refetch()} />
        ) : query.data.items.length === 0 ? (
          <p className="text-sm text-ink-muted">{v.empty}</p>
        ) : (
          <DataTable caption={v.heading} hideCaption columns={columns} rows={query.data.items} rowId={(x) => x.id} />
        )}
        {canManage ? <VendorItemForm vendorId={vendorId} defaultCurrency={defaultCurrency} /> : null}
      </div>
    </SectionCard>
  );
}

function VendorItemForm({ vendorId, defaultCurrency }: { vendorId: string; defaultCurrency: string | null }) {
  const v = m.vendorItems;
  const key = useMemo(() => queryKeys.procurement.vendorItems(vendorId, false), [vendorId]);
  const { run, pending, offline } = useCommand<null>(key);
  const [text, setText] = useState("");
  const [product, setProduct] = useState<ProductOption | null>(null);
  const [code, setCode] = useState("");
  const [lead, setLead] = useState<string | null>(null);
  const [price, setPrice] = useState<string | null>(null);
  const [currency, setCurrency] = useState<VendorItemDraft["currency"]>(CURRENCIES.find((c) => c === defaultCurrency) ?? "INR");
  const search = useProductSearch(text);
  const options = [...(product ? [product] : []), ...(search.data ?? []).filter((p) => p.id !== product?.id)];
  const leadDays = lead != null && /^\d{1,3}$/.test(lead) ? Number.parseInt(lead, 10) : null;
  const blocked = !product ? v.productNeeded : !price ? v.priceNeeded : lead != null && leadDays === null ? v.leadWhole : null;
  const reset = () => {
    setProduct(null);
    setText("");
    setCode("");
    setLead(null);
    setPrice(null);
  };
  return (
    <div className="flex flex-col gap-3 rounded-md border p-3">
      <p className="text-sm font-[650] text-ink">{v.addHeading}</p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <ComboBox
          label={v.product}
          placeholder={m.requisitions.productHint}
          emptyText={text.trim().length < 2 ? m.requisitions.productHint : m.requisitions.noProduct}
          options={options.map((p) => ({ id: p.id, label: p.product_name, detail: p.product_key }))}
          value={product?.id ?? null}
          inputValue={text}
          onInputChange={setText}
          onChange={(id) => {
            const found = options.find((p) => p.id === id) ?? null;
            setProduct(found);
            if (found) setText(found.product_name);
          }}
        />
        <TextField label={v.code} value={code} onChange={setCode} maxLength={60} />
        <NumberField label={v.lead} value={lead} onChange={setLead} maxFractionDigits={0} />
        <NumberField label={v.price} value={price} onChange={setPrice} currency={currency} />
        <Select label={v.currency} options={CURRENCIES.map((c) => ({ id: c, label: c }))} value={currency} onChange={(c) => setCurrency(CURRENCIES.find((x) => x === c) ?? "INR")} />
      </div>
      <div>
        <Button
          variant="primary"
          isPending={pending === "save"}
          {...unavailableWhen(offline ?? blocked)}
          onPress={() =>
            product && price
              ? void run(
                  "save",
                  (k) => saveVendorItem({ vendor_party_id: vendorId, product_id: product.id, vendor_code: code, lead_time_days: leadDays, unit_price: price, currency }, k),
                  { done: v.saved, failed: m.failed },
                ).then((x) => {
                  if (x) reset();
                })
              : undefined
          }
        >
          {v.add}
        </Button>
      </div>
    </div>
  );
}
