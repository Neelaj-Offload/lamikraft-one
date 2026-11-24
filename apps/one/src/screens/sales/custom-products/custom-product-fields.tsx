"use client";

import { useState } from "react";
import { CUSTOM_TYPES } from "@/features/custom-products/api";
import { usePartySearch, useProductSearch } from "@/features/sales/pickers";
import { CURRENCIES } from "@/lib/format/money";
import { CUSTOM_TYPE_LABEL, type CustomForm } from "~/data/sales-deals";
import { ComboBox, DecimalField, IntegerField, RadioCards, Select, Switch, Textarea, TextField, type RadioCardOption } from "~/ui";

/**
 * The fields of a custom product, grouped by topic. Each group renders bare fields for a
 * `FormSection` grid, so the create steps and the record's edit form share them.
 */

export interface FieldGroupProps {
  form: CustomForm;
  set: <K extends keyof CustomForm>(field: K, value: CustomForm[K]) => void;
  errors: Record<string, string>;
}

type CountField = "groove_count" | "bowl_count" | "carton_qty" | "inner_qty";
type DecimalName = "length_mm" | "width_mm" | "height_mm" | "thickness_mm" | "unit_weight_g" | "cbm";

const TYPE_HINT: Record<string, string> = {
  modified_catalog: "A catalogue product with something changed: a colour, a size, a handle.",
  fully_new: "Designed from nothing for this customer.",
  quote_only: "Priced for a quotation, with no development planned.",
};
const TYPE_OPTIONS: RadioCardOption[] = CUSTOM_TYPES.map((type) => ({
  value: type,
  label: CUSTOM_TYPE_LABEL[type] ?? type,
  description: TYPE_HINT[type],
  icon: type === "modified_catalog" ? "swatch" : type === "fully_new" ? "sparkles" : "fileText",
}));
const UNITS = ["pcs", "set", "sheets", "box", "carton", "sqm"];
const NO_CURRENCY = "none";

/** Which create step holds each field, so a server error can take the person to it. */
export const FIELD_STEP: Record<string, 0 | 1 | 2> = {
  product_name: 0,
  custom_type: 0,
  base_product_id: 0,
  party_id: 0,
  legacy_customer_name: 0,
  inquiry_reference: 0,
  customer_specific_flag: 0,
  description: 0,
  quoted_price: 2,
  quoted_currency: 2,
  unit_code: 2,
  remarks: 2,
  packaging: 2,
  packaging_notes: 2,
};

function count(form: CustomForm, set: FieldGroupProps["set"], errors: Record<string, string>, field: CountField, label: string, help?: string) {
  const value = form[field] && /^\d+$/.test(form[field]) ? Number.parseInt(form[field], 10) : null;
  return <IntegerField label={label} optional value={value} onChange={(next) => set(field, next === null ? "" : String(next))} minValue={0} help={help} error={errors[field] || undefined} />;
}

function decimal(form: CustomForm, set: FieldGroupProps["set"], errors: Record<string, string>, field: DecimalName, label: string, suffix: string, digits = 3) {
  return <DecimalField label={label} optional value={form[field]} onChange={(next) => set(field, next)} suffix={suffix} maxFractionDigits={digits} error={errors[field] || undefined} />;
}

export function IdentityFields({ form, set, errors }: FieldGroupProps) {
  const [partyText, setPartyText] = useState(form.party?.label ?? "");
  const [productText, setProductText] = useState(form.base_product?.label ?? "");
  const parties = usePartySearch(partyText);
  const products = useProductSearch(productText);
  const partyOptions = [
    ...(form.party ? [{ id: form.party.id, label: form.party.label }] : []),
    ...(parties.data ?? []).filter((p) => p.id !== form.party?.id).map((p) => ({ id: p.id, label: p.display_name, description: p.party_number })),
  ];
  const productOptions: { id: string; label: string; description?: string }[] = [
    ...(form.base_product ? [{ id: form.base_product.id, label: form.base_product.label }] : []),
    ...(products.data ?? []).filter((p) => p.id !== form.base_product?.id).map((p) => ({ id: p.id, label: p.product_name, description: p.product_key })),
  ];
  return (
    <>
      <TextField
        className="col-span-full"
        label="Product name"
        placeholder="What the team will call it"
        value={form.product_name}
        onChange={(value) => set("product_name", value)}
        maxLength={300}
        isRequired
        error={errors.product_name || undefined}
      />
      <RadioCards className="col-span-full" label="Kind of custom product" value={form.custom_type} onChange={(value) => set("custom_type", value)} options={TYPE_OPTIONS} error={errors.custom_type || undefined} />
      <ComboBox
        label="Based on"
        optional
        placeholder="A catalogue product, by key or name"
        items={productOptions}
        inputValue={productText}
        onInputChange={(text) => {
          setProductText(text);
          if (text === "" && form.base_product) set("base_product", null);
        }}
        selectedKey={form.base_product?.id ?? null}
        onSelectionChange={(id) => {
          const option = productOptions.find((candidate) => candidate.id === id) ?? null;
          set("base_product", option ? { id: option.id, label: option.description || option.label } : null);
          if (option) setProductText(option.label);
        }}
        isLoading={products.isFetching}
        emptyText={productText.trim().length < 2 ? "Type at least two letters" : "No product matches"}
        help="The catalogue product this one changes, if any."
        error={errors.base_product_id || undefined}
      />
      <ComboBox
        label="Customer"
        optional
        placeholder="Name or customer number"
        items={partyOptions}
        inputValue={partyText}
        onInputChange={(text) => {
          setPartyText(text);
          if (text === "" && form.party) set("party", null);
        }}
        selectedKey={form.party?.id ?? null}
        onSelectionChange={(id) => {
          const option = partyOptions.find((candidate) => candidate.id === id) ?? null;
          set("party", option ? { id: option.id, label: option.label } : null);
          if (option) setPartyText(option.label);
        }}
        isLoading={parties.isFetching}
        emptyText={partyText.trim().length < 2 ? "Type at least two letters" : "No customer matches"}
        help="Who asked for it."
        error={errors.party_id || undefined}
      />
      <TextField
        label="Customer name, as written"
        optional
        value={form.legacy_customer_name}
        onChange={(value) => set("legacy_customer_name", value)}
        maxLength={200}
        help="For an older record whose customer is not in Lamikraft One."
        error={errors.legacy_customer_name || undefined}
      />
      <TextField label="Enquiry reference" optional value={form.inquiry_reference} onChange={(value) => set("inquiry_reference", value)} maxLength={120} error={errors.inquiry_reference || undefined} />
      <Switch
        className="col-span-full"
        label="Only for this customer"
        description="It is never offered to anyone else."
        isSelected={form.customer_specific_flag}
        onChange={(value) => set("customer_specific_flag", value)}
      />
      <Textarea className="col-span-full" label="Description" optional rows={3} value={form.description} onChange={(value) => set("description", value)} error={errors.description || undefined} />
    </>
  );
}

export function SpecificationFields({ form, set, errors }: FieldGroupProps) {
  const text = (field: "dimensions_text" | "thickness_text" | "decor_no" | "decor_name" | "finish" | "shape" | "handle_type", label: string, maxLength = 120, help?: string) => (
    <TextField label={label} optional value={form[field]} onChange={(value) => set(field, value)} maxLength={maxLength} help={help} error={errors[field] || undefined} />
  );
  return (
    <>
      {text("dimensions_text", "Dimensions, as written", 200, "The way the customer states them, for example 300 x 200 x 12 mm.")}
      {text("shape", "Shape")}
      {decimal(form, set, errors, "length_mm", "Length", "mm")}
      {decimal(form, set, errors, "width_mm", "Width", "mm")}
      {decimal(form, set, errors, "height_mm", "Height", "mm")}
      {decimal(form, set, errors, "thickness_mm", "Thickness", "mm")}
      {text("thickness_text", "Thickness, as written", 40)}
      {text("finish", "Finish")}
      {text("decor_no", "Decor number", 40)}
      {text("decor_name", "Decor name")}
      {count(form, set, errors, "groove_count", "Grooves")}
      {count(form, set, errors, "bowl_count", "Bowls")}
      {text("handle_type", "Handle")}
    </>
  );
}

export function PackagingFields({ form, set, errors }: FieldGroupProps) {
  return (
    <>
      {count(form, set, errors, "carton_qty", "Units per carton")}
      {count(form, set, errors, "inner_qty", "Units per inner pack")}
      <TextField label="Packing type" optional value={form.packing_type} onChange={(value) => set("packing_type", value)} maxLength={120} />
      {decimal(form, set, errors, "unit_weight_g", "Unit weight", "g")}
      {decimal(form, set, errors, "cbm", "Carton volume", "CBM", 6)}
      <Textarea className="col-span-full" label="Packaging notes" optional rows={2} value={form.packaging_notes} onChange={(value) => set("packaging_notes", value)} />
    </>
  );
}

export function CommercialFields({ form, set, errors }: FieldGroupProps) {
  return (
    <>
      <DecimalField
        label="Quoted price"
        optional
        value={form.quoted_price}
        onChange={(value) => set("quoted_price", value)}
        prefix={form.quoted_currency ?? undefined}
        maxFractionDigits={4}
        help="Per unit. Quotation lines take this price unless one is entered on the line."
        error={errors.quoted_price || undefined}
      />
      <Select
        label="Currency of the price"
        options={[{ value: NO_CURRENCY, label: "Not set" }, ...CURRENCIES.map((code) => ({ value: code, label: code }))]}
        value={form.quoted_currency ?? NO_CURRENCY}
        onChange={(value) => set("quoted_currency", value === NO_CURRENCY ? null : value)}
        error={errors.quoted_currency || undefined}
      />
      <Select label="Sold by" options={UNITS.map((unit) => ({ value: unit, label: unit }))} value={form.unit_code} onChange={(value) => set("unit_code", value)} error={errors.unit_code || undefined} />
      <Textarea className="col-span-full" label="Remarks" optional rows={2} value={form.remarks} onChange={(value) => set("remarks", value)} error={errors.remarks || undefined} />
    </>
  );
}

/** What the screen itself can tell before the server is asked. */
export function validateCustom(form: CustomForm): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!form.product_name.trim()) errors.product_name = "Give the product a name the team will recognise.";
  if (form.quoted_price && !form.quoted_currency) errors.quoted_currency = "Choose the currency of the quoted price.";
  return errors;
}
