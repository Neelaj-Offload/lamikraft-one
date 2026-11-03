"use client";

import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Form } from "react-aria-components";
import { Button, unavailableWhen } from "@/components/ui/button";
import { RadioGroup } from "@/components/ui/choice";
import { NumberField } from "@/components/ui/number-field";
import { ComboBox, Select } from "@/components/ui/select";
import { TextField } from "@/components/ui/text-field";
import { queryKeys } from "@/lib/api/query-keys";
import { challansMessages as m } from "@/messages/challans";
import { addChallanLine, fetchChallan } from "./api";
import { fieldErrorsFrom } from "./form-model";
import { useProductSearch, type ProductOption } from "./pickers";
import { LEGACY_UNITS, type ChallanDetail, type ChallanLine, type LineCreateRequest } from "./types";
import type { ChallanCommands } from "./use-challan-command";

const w = m.workspace;

interface LineForm {
  kind: "catalog" | "manual";
  product: ProductOption | null;
  item_code: string;
  item_name: string;
  hsn_sac: string;
  quantity: string | null;
  unit: string;
  remarks: string;
  original_line_id: string | null;
}

const EMPTY: LineForm = { kind: "catalog", product: null, item_code: "", item_name: "", hsn_sac: "", quantity: null, unit: "pcs", remarks: "", original_line_id: null };

/** The request for the form, or null when a required value is missing (product for a catalogue line, name, quantity). */
export function lineRequest(form: LineForm): LineCreateRequest | null {
  if (!form.quantity) return null;
  const optional = (value: string) => value.trim() || null;
  const common = { quantity: form.quantity, remarks: optional(form.remarks), ...(form.original_line_id ? { original_line_id: form.original_line_id } : {}) };
  if (form.kind === "catalog") {
    if (!form.product) return null;
    return { line_type: "catalog", product_id: form.product.id, ...common };
  }
  if (!form.item_name.trim()) return null;
  return { line_type: "manual", item_name: form.item_name.trim(), item_code: optional(form.item_code), hsn_sac: optional(form.hsn_sac), unit: form.unit, ...common };
}

/** Add a catalogue line (code, name, HSN/SAC and unit come from the product) or a manual line (legacy free text). */
export function AddLine({ challan, commands }: { challan: ChallanDetail; commands: ChallanCommands }) {
  const [form, setForm] = useState<LineForm>(EMPTY);
  const [productText, setProductText] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitted, setSubmitted] = useState(false);
  const products = useProductSearch(productText);
  const options = [...(form.product ? [form.product] : []), ...(products.data ?? []).filter((p) => p.id !== form.product?.id)];
  const set = <K extends keyof LineForm>(key: K, value: LineForm[K]) => setForm((current) => ({ ...current, [key]: value }));
  const request = lineRequest(form);
  const originals = challan.challan_type === "return" && challan.original_challan ? challan.original_challan : null;
  const original = useQuery({
    queryKey: queryKeys.challans.challan(originals?.id ?? ""),
    queryFn: ({ signal }) => fetchChallan(originals!.id, signal),
    enabled: originals !== null,
  });

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (!request) return;
    setErrors({});
    const outcome = await commands.run("add_line", [JSON.stringify(request)], (key, current) => addChallanLine(current, request, key), {
      done: w.added,
      failed: w.failed(w.add),
    });
    if (outcome.ok) {
      setForm({ ...EMPTY, kind: form.kind });
      setProductText("");
      setSubmitted(false);
    } else setErrors(fieldErrorsFrom(outcome.error));
  };

  const missing = (ok: boolean) => (submitted && !ok ? "required" : undefined);

  return (
    <Form onSubmit={submit} className="flex flex-col gap-4 rounded-lg border bg-surface p-4" validationBehavior="aria" aria-label={w.addLine}>
      <h3 className="font-[650] text-ink">{w.addLine}</h3>
      <RadioGroup
        label={w.addLine}
        orientation="horizontal"
        options={[
          { value: "catalog", label: w.addCatalog },
          { value: "manual", label: w.addManual },
        ]}
        value={form.kind}
        onChange={(kind) => set("kind", kind === "manual" ? "manual" : "catalog")}
      />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {form.kind === "catalog" ? (
          <ComboBox
            label={w.product}
            placeholder={w.productHint}
            emptyText={productText.trim().length < 2 ? w.productHint : w.noProduct}
            options={options.map((p) => ({ id: p.id, label: p.product_name, detail: p.product_key }))}
            value={form.product?.id ?? null}
            inputValue={productText}
            onInputChange={setProductText}
            onChange={(id) => {
              const product = options.find((candidate) => candidate.id === id) ?? null;
              set("product", product);
              if (product) setProductText(product.product_name);
            }}
            className="sm:col-span-2"
            errorMessage={missing(form.product !== null) ? w.productHint : errors.product_id}
          />
        ) : (
          <>
            <TextField label={w.itemName} value={form.item_name} onChange={(value) => set("item_name", value)} maxLength={500} errorMessage={missing(form.item_name.trim() !== "") ? w.itemName : errors.item_name} />
            <TextField label={w.itemCode} value={form.item_code} onChange={(value) => set("item_code", value)} maxLength={120} errorMessage={errors.item_code} />
            <TextField label={w.hsn} value={form.hsn_sac} onChange={(value) => set("hsn_sac", value)} maxLength={8} inputMode="numeric" errorMessage={errors.hsn_sac} />
            <Select label={w.unit} options={LEGACY_UNITS.map((u) => ({ id: u, label: u }))} value={form.unit} onChange={(value) => set("unit", value ?? "pcs")} errorMessage={errors.unit} />
          </>
        )}
        <NumberField
          label={w.quantity}
          value={form.quantity}
          onChange={(value) => set("quantity", value)}
          maxFractionDigits={4}
          errorMessage={missing(form.quantity !== null) ? s.invalid.required : errors.quantity}
        />
        <TextField label={w.remarks} value={form.remarks} onChange={(value) => set("remarks", value)} errorMessage={errors.remarks} />
        {originals ? (
          <Select
            label={w.fields.original}
            options={[{ id: "", label: "—" }, ...originalLineOptions(original.data?.lines ?? [])]}
            value={form.original_line_id ?? ""}
            onChange={(value) => set("original_line_id", value || null)}
            errorMessage={errors.original_line_id}
          />
        ) : null}
      </div>
      <div>
        <Button type="submit" variant="primary" isPending={commands.pending === "add_line"} pendingLabel={w.save.saving} {...unavailableWhen(commands.offline)}>
          {w.add}
        </Button>
      </div>
    </Form>
  );
}

const s = w.save;

/** Lines of the original challan a Return line can point at (the server checks what is still out). */
function originalLineOptions(lines: readonly ChallanLine[]) {
  return lines.map((line) => ({ id: line.id, label: `${line.line_no}. ${line.item_name}`, detail: `${line.outstanding_quantity} ${line.unit}` }));
}
