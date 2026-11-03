"use client";

import { useState, type FormEvent } from "react";
import { Form } from "react-aria-components";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Switch } from "@/components/ui/choice";
import { NumberField } from "@/components/ui/number-field";
import { ComboBox, Select } from "@/components/ui/select";
import { TextArea, TextField } from "@/components/ui/text-field";
import { usePartySearch, useProductSearch, type PartyOption, type ProductOption } from "@/features/sales/pickers";
import { CURRENCIES } from "@/lib/format/money";
import { commercialMessages as c } from "@/messages/commercial";
import { CUSTOM_TYPES, type CustomProductDetail } from "./api";

const m = c.customProducts;

/** Every editable legacy field as form text (decimals stay strings; empty means "not set"). */
export interface CustomForm {
  custom_type: string;
  party: { id: string; label: string } | null;
  base_product: { id: string; label: string } | null;
  customer_specific_flag: boolean;
  legacy_customer_name: string;
  inquiry_reference: string;
  product_name: string;
  description: string;
  dimensions_text: string;
  length_mm: string | null;
  width_mm: string | null;
  height_mm: string | null;
  thickness_mm: string | null;
  thickness_text: string;
  decor_no: string;
  decor_name: string;
  finish: string;
  shape: string;
  groove_count: string | null;
  bowl_count: string | null;
  handle_type: string;
  packaging_notes: string;
  carton_qty: string | null;
  inner_qty: string | null;
  packing_type: string;
  unit_weight_g: string | null;
  cbm: string | null;
  quoted_price: string | null;
  quoted_currency: string | null;
  unit_code: string;
  remarks: string;
}

export const EMPTY_CUSTOM: CustomForm = {
  custom_type: "fully_new",
  party: null,
  base_product: null,
  customer_specific_flag: false,
  legacy_customer_name: "",
  inquiry_reference: "",
  product_name: "",
  description: "",
  dimensions_text: "",
  length_mm: null,
  width_mm: null,
  height_mm: null,
  thickness_mm: null,
  thickness_text: "",
  decor_no: "",
  decor_name: "",
  finish: "",
  shape: "",
  groove_count: null,
  bowl_count: null,
  handle_type: "",
  packaging_notes: "",
  carton_qty: null,
  inner_qty: null,
  packing_type: "",
  unit_weight_g: null,
  cbm: null,
  quoted_price: null,
  quoted_currency: null,
  unit_code: "pcs",
  remarks: "",
};

const text = (value: string | null | undefined) => value ?? "";

export function customFormOf(p: CustomProductDetail): CustomForm {
  const pack = p.packaging ?? {};
  return {
    custom_type: p.custom_type,
    party: p.party ? { id: p.party.id, label: p.party.display_name } : null,
    base_product: p.base_product_id ? { id: p.base_product_id, label: p.base_product_key ?? p.base_product_id } : null,
    customer_specific_flag: p.customer_specific_flag,
    legacy_customer_name: text(p.legacy_customer_name),
    inquiry_reference: text(p.inquiry_reference),
    product_name: p.product_name,
    description: text(p.description),
    dimensions_text: text(p.dimensions_text),
    length_mm: p.length_mm,
    width_mm: p.width_mm,
    height_mm: p.height_mm,
    thickness_mm: p.thickness_mm,
    thickness_text: text(p.thickness_text),
    decor_no: text(p.decor_no),
    decor_name: text(p.decor_name),
    finish: text(p.finish),
    shape: text(p.shape),
    groove_count: p.groove_count === null ? null : String(p.groove_count),
    bowl_count: p.bowl_count === null ? null : String(p.bowl_count),
    handle_type: text(p.handle_type),
    packaging_notes: text(p.packaging_notes),
    carton_qty: pack.carton_qty == null ? null : String(pack.carton_qty),
    inner_qty: pack.inner_qty == null ? null : String(pack.inner_qty),
    packing_type: text(pack.packing_type),
    unit_weight_g: pack.unit_weight_g ?? null,
    cbm: pack.cbm ?? null,
    quoted_price: p.quoted_price?.amount ?? null,
    quoted_currency: p.quoted_price?.currency ?? null,
    unit_code: p.unit_code,
    remarks: text(p.remarks),
  };
}

const TEXT_FIELDS = [
  "legacy_customer_name",
  "inquiry_reference",
  "product_name",
  "description",
  "dimensions_text",
  "thickness_text",
  "decor_no",
  "decor_name",
  "finish",
  "shape",
  "handle_type",
  "packaging_notes",
  "remarks",
] as const;
const DECIMAL_FIELDS = ["length_mm", "width_mm", "height_mm", "thickness_mm", "quoted_price"] as const;
const COUNT_FIELDS = ["groove_count", "bowl_count"] as const;

function packagingOf(form: CustomForm): Record<string, unknown> | null {
  const out: Record<string, unknown> = {};
  if (form.carton_qty) out.carton_qty = Number.parseInt(form.carton_qty, 10);
  if (form.inner_qty) out.inner_qty = Number.parseInt(form.inner_qty, 10);
  if (form.packing_type.trim()) out.packing_type = form.packing_type.trim();
  if (form.unit_weight_g) out.unit_weight_g = form.unit_weight_g;
  if (form.cbm) out.cbm = form.cbm;
  return Object.keys(out).length ? out : null;
}

/** The request body: on create every filled field, on update only what changed relative to `base` (nulls clear). */
export function customBody(form: CustomForm, base: CustomForm | null): Record<string, unknown> {
  const all: Record<string, unknown> = {
    custom_type: form.custom_type,
    party_id: form.party?.id ?? null,
    base_product_id: form.base_product?.id ?? null,
    customer_specific_flag: form.customer_specific_flag,
    unit_code: form.unit_code || "pcs",
    quoted_currency: form.quoted_price ? form.quoted_currency : null,
    packaging: packagingOf(form),
  };
  for (const field of TEXT_FIELDS) all[field] = form[field].trim() || null;
  for (const field of DECIMAL_FIELDS) all[field] = form[field] || null;
  for (const field of COUNT_FIELDS) all[field] = form[field] ? Number.parseInt(form[field]!, 10) : null;
  if (base === null) return Object.fromEntries(Object.entries(all).filter(([, value]) => value !== null && value !== ""));
  const before = customBody(base, null);
  const changed: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(all)) {
    if (JSON.stringify(value ?? null) !== JSON.stringify(before[key] ?? null)) changed[key] = value;
  }
  if ("quoted_price" in changed || "quoted_currency" in changed) {
    changed.quoted_price = all.quoted_price;
    changed.quoted_currency = all.quoted_currency;
  }
  return changed;
}

export function CustomProductFields({
  form,
  set,
  errors,
  disabled = false,
}: {
  form: CustomForm;
  set: <K extends keyof CustomForm>(field: K, value: CustomForm[K]) => void;
  errors: Record<string, string>;
  disabled?: boolean;
}) {
  const [partyText, setPartyText] = useState(form.party?.label ?? "");
  const [productText, setProductText] = useState(form.base_product?.label ?? "");
  const parties = usePartySearch(partyText);
  const products = useProductSearch(productText);
  const partyOptions: { id: string; label: string; detail?: string }[] = [
    ...(form.party ? [form.party] : []),
    ...(parties.data ?? []).filter((p: PartyOption) => p.id !== form.party?.id).map((p) => ({ id: p.id, label: p.display_name, detail: p.party_number })),
  ];
  const productOptions: { id: string; label: string; detail?: string }[] = [
    ...(form.base_product ? [form.base_product] : []),
    ...(products.data ?? []).filter((p: ProductOption) => p.id !== form.base_product?.id).map((p) => ({ id: p.id, label: p.product_name, detail: p.product_key })),
  ];
  const f = (field: string) => m.fields[field] ?? field;
  const tf = (field: (typeof TEXT_FIELDS)[number], maxLength = 120) => (
    <TextField label={f(field)} value={form[field]} onChange={(value) => set(field, value)} maxLength={maxLength} errorMessage={errors[field]} isDisabled={disabled} />
  );
  const nf = (field: keyof CustomForm, digits = 3) => (
    <NumberField label={f(field)} value={form[field] as string | null} onChange={(value) => set(field, value as never)} maxFractionDigits={digits} errorMessage={errors[field]} isDisabled={disabled} />
  );
  return (
    <div className="flex flex-col gap-6">
      <fieldset className="flex flex-col gap-4">
        <legend className="mb-2 text-lg font-[650] text-ink">{m.sections.identity}</legend>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <TextField label={f("product_name")} value={form.product_name} onChange={(value) => set("product_name", value)} maxLength={300} isRequired errorMessage={errors.product_name} isDisabled={disabled} />
          <Select
            label={f("custom_type")}
            options={CUSTOM_TYPES.map((type) => ({ id: type, label: m.types[type] ?? type }))}
            value={form.custom_type}
            onChange={(value) => set("custom_type", value ?? "fully_new")}
            errorMessage={errors.custom_type}
            isDisabled={disabled}
          />
          <ComboBox
            label={f("base_product_id")}
            placeholder="Type a product key or name"
            emptyText="No product matches"
            options={productOptions}
            value={form.base_product?.id ?? null}
            inputValue={productText}
            onInputChange={setProductText}
            onChange={(id) => {
              const option = productOptions.find((candidate) => candidate.id === id) ?? null;
              set("base_product", option ? { id: option.id, label: option.detail ?? option.label } : null);
              if (option) setProductText(option.label);
            }}
            errorMessage={errors.base_product_id}
            isDisabled={disabled}
          />
          <ComboBox
            label={f("party_id")}
            placeholder="Type a name or P-number"
            emptyText="No customer matches"
            options={partyOptions}
            value={form.party?.id ?? null}
            inputValue={partyText}
            onInputChange={setPartyText}
            onChange={(id) => {
              const option = partyOptions.find((candidate) => candidate.id === id) ?? null;
              set("party", option ? { id: option.id, label: option.label } : null);
              if (option) setPartyText(option.label);
            }}
            errorMessage={errors.party_id}
            isDisabled={disabled}
          />
          {tf("legacy_customer_name", 200)}
          {tf("inquiry_reference")}
        </div>
        <Switch isSelected={form.customer_specific_flag} onChange={(value) => set("customer_specific_flag", value)} isDisabled={disabled}>
          {f("customer_specific_flag")}
        </Switch>
        <TextArea label={f("description")} value={form.description} onChange={(value) => set("description", value)} errorMessage={errors.description} isDisabled={disabled} />
      </fieldset>
      <fieldset className="flex flex-col gap-4">
        <legend className="mb-2 text-lg font-[650] text-ink">{m.sections.specification}</legend>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {tf("dimensions_text", 200)}
          {nf("length_mm")}
          {nf("width_mm")}
          {nf("height_mm")}
          {nf("thickness_mm")}
          {tf("thickness_text", 40)}
          {tf("decor_no", 40)}
          {tf("decor_name")}
          {tf("finish")}
          {tf("shape")}
          {nf("groove_count", 0)}
          {nf("bowl_count", 0)}
          {tf("handle_type")}
        </div>
      </fieldset>
      <fieldset className="flex flex-col gap-4">
        <legend className="mb-2 text-lg font-[650] text-ink">{m.sections.packaging}</legend>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {nf("carton_qty", 0)}
          {nf("inner_qty", 0)}
          <TextField label={f("packing_type")} value={form.packing_type} onChange={(value) => set("packing_type", value)} maxLength={120} isDisabled={disabled} />
          {nf("unit_weight_g")}
          {nf("cbm", 6)}
        </div>
        <TextArea label={f("packaging_notes")} value={form.packaging_notes} onChange={(value) => set("packaging_notes", value)} isDisabled={disabled} />
      </fieldset>
      <fieldset className="flex flex-col gap-4">
        <legend className="mb-2 text-lg font-[650] text-ink">{m.sections.commercial}</legend>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <NumberField label={f("quoted_price")} value={form.quoted_price} onChange={(value) => set("quoted_price", value)} currency={form.quoted_currency ?? undefined} errorMessage={errors.quoted_price} isDisabled={disabled} />
          <Select
            label={f("quoted_currency")}
            options={[{ id: "", label: "—" }, ...CURRENCIES.map((code) => ({ id: code, label: code }))]}
            value={form.quoted_currency ?? ""}
            onChange={(value) => set("quoted_currency", value || null)}
            errorMessage={errors.quoted_currency}
            isDisabled={disabled}
          />
          <Select
            label={f("unit_code")}
            options={["pcs", "set", "sheets", "box", "carton", "sqm"].map((unit) => ({ id: unit, label: unit }))}
            value={form.unit_code}
            onChange={(value) => set("unit_code", value ?? "pcs")}
            isDisabled={disabled}
          />
        </div>
        <TextArea label={f("remarks")} value={form.remarks} onChange={(value) => set("remarks", value)} isDisabled={disabled} />
      </fieldset>
    </div>
  );
}

/** The create page: every field, validated on the server (422 mapped onto the fields). */
export function CustomProductCreate({
  onSubmit,
  pending,
  offline,
}: {
  onSubmit: (body: Record<string, unknown>) => Promise<Record<string, string>>;
  pending: boolean;
  offline: string | null;
}) {
  const [form, setForm] = useState<CustomForm>(EMPTY_CUSTOM);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const set = <K extends keyof CustomForm>(field: K, value: CustomForm[K]) => setForm((current) => ({ ...current, [field]: value }));
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!form.product_name.trim()) {
      setErrors({ product_name: "Give the product a name." });
      return;
    }
    if (form.quoted_price && !form.quoted_currency) {
      setErrors({ quoted_currency: "Choose the currency of the quoted price." });
      return;
    }
    setErrors(await onSubmit(customBody(form, null)));
  };
  return (
    <Form onSubmit={(event) => void submit(event)} className="flex flex-col gap-6" validationBehavior="aria">
      <CustomProductFields form={form} set={set} errors={errors} />
      <div>
        <Button type="submit" variant="primary" isPending={pending} pendingLabel={m.creating} {...unavailableWhen(offline)}>
          {m.create}
        </Button>
      </div>
    </Form>
  );
}
