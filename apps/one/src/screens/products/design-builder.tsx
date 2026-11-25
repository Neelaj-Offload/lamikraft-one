"use client";

import type { Route } from "next";
import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { useCategories } from "~/data/products";
import { buildVariants, type DesignInput, type VariantBuildResult } from "~/data/stock-categories";
import { Page, PageHeader } from "~/shell/page";
import { NotPermitted } from "~/shell/states";
import { Badge, Banner, Button, ButtonLink, DataTable, FormActions, FormSection, GlassPanel, Select, TextField, toast, type Column } from "~/ui";

interface DecorRow {
  decor_no: string;
  decor_name: string;
}
interface SizeRow {
  code: string;
  label: string;
  length_mm: string;
  width_mm: string;
}

const EMPTY_DECOR: DecorRow = { decor_no: "", decor_name: "" };
const EMPTY_SIZE: SizeRow = { code: "", label: "", length_mm: "", width_mm: "" };
const STARTER_SIZES: SizeRow[] = [
  { code: "S", label: "Small", length_mm: "", width_mm: "" },
  { code: "M", label: "Medium", length_mm: "", width_mm: "" },
  { code: "L", label: "Large", length_mm: "", width_mm: "" },
];

/** CB07 + 892 + M → CB07-892-M (the same rule as the server's variant_key). */
export function variantKey(design: string, decor: string, size: string): string {
  return `${design}-${decor}-${size}`.toUpperCase().replace(/-{2,}/g, "-");
}

type Row = VariantBuildResult["rows"][number];
const COLUMNS: Column<Row>[] = [
  { key: "key", header: "Product key", primary: true, cell: (r) => <span className="lk-mono">{r.product_key}</span> },
  { key: "name", header: "Name", cell: (r) => r.product_name },
  { key: "state", header: "", cell: (r) => (r.exists ? <Badge size="sm">Already exists</Badge> : r.product_id ? <Badge tone="leaf" size="sm" dot>Created</Badge> : <Badge tone="cobalt" size="sm">New</Badge>) },
];

/** Add a whole design at once: one product per decor and size, keyed DESIGN-DECOR-SIZE. */
export function DesignBuilder() {
  const { permissionKeys } = useSession();
  const queryClient = useQueryClient();
  const categories = useCategories(false);
  const [designNo, setDesignNo] = useState("");
  const [designName, setDesignName] = useState("");
  const [categoryId, setCategoryId] = useState<string | null>(null);
  const [productType, setProductType] = useState("");
  const [decors, setDecors] = useState<DecorRow[]>([{ ...EMPTY_DECOR }]);
  const [sizes, setSizes] = useState<SizeRow[]>(STARTER_SIZES.map((s) => ({ ...s })));
  const [result, setResult] = useState<VariantBuildResult | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const body = (dry: boolean): DesignInput => ({
    design_no: designNo.trim(),
    design_name: designName.trim(),
    category_id: categoryId ?? "",
    product_type: productType.trim() || null,
    decors: decors.filter((d) => d.decor_no.trim()).map((d) => ({ decor_no: d.decor_no.trim(), decor_name: d.decor_name.trim() || null })),
    sizes: sizes
      .filter((s) => s.code.trim() && s.label.trim())
      .map((s) => ({ code: s.code.trim(), label: s.label.trim(), length_mm: s.length_mm.trim() || null, width_mm: s.width_mm.trim() || null })),
    dry_run: dry,
  });

  const run = useMutation({
    mutationFn: (dry: boolean) => buildVariants(body(dry)),
    onSuccess: (data, dry) => {
      setResult(data);
      setFailure(null);
      if (!dry) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.catalogue.all() });
        toast.success(`${data.created} products created`, { description: data.skipped ? `${data.skipped} already existed and were left as they are.` : undefined });
      }
    },
    onError: (error) => setFailure(error instanceof ProblemError ? (error.detail ?? error.title) : "The connection dropped. Try again."),
  });

  if (!permissionKeys.has("catalogue.product.create")) {
    return (
      <Page width="reading">
        <PageHeader breadcrumb={[{ label: "Products", href: "/products" as Route }, { label: "Add a design" }]} title="Add a design" />
        <NotPermitted what="Adding products" icon="box" />
      </Page>
    );
  }

  const ready = designNo.trim() && designName.trim() && categoryId && body(true).decors.length && body(true).sizes.length;
  const preview = ready
    ? body(true).decors.flatMap((d) => body(true).sizes.map((s) => variantKey(designNo.trim(), d.decor_no, s.code)))
    : [];
  const setDecor = (i: number, patch: Partial<DecorRow>) => setDecors((rows) => rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const setSize = (i: number, patch: Partial<SizeRow>) => setSizes((rows) => rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  return (
    <Page width="reading">
      <PageHeader
        breadcrumb={[{ label: "Products", href: "/products" as Route }, { label: "Add a design" }]}
        title="Add a design"
        lead="A design in every decor and size it comes in. Each combination becomes its own product, ready for stock and quotations."
      />
      <form
        className="flex flex-col gap-6"
        noValidate
        onSubmit={(event: FormEvent<HTMLFormElement>) => {
          event.preventDefault();
          if (ready) run.mutate(false);
        }}
      >
        {failure ? (
          <Banner tone="ember" title="Nothing was created.">
            {failure}
          </Banner>
        ) : null}
        <FormSection title="The design" description="The design number goes into every product key.">
          <TextField label="Design number" isRequired value={designNo} onChange={(v) => setDesignNo(v.toUpperCase())} maxLength={20} placeholder="CB07" />
          <TextField label="Design name" isRequired value={designName} onChange={setDesignName} maxLength={120} placeholder="Chopping board CB07" />
          <Select
            label="Category"
            isRequired
            options={(categories.data ?? []).map((c: { id: string; name: string }) => ({ value: c.id, label: c.name }))}
            value={categoryId}
            onChange={setCategoryId}
          />
          <TextField label="Product type" optional value={productType} onChange={setProductType} maxLength={120} placeholder="Chopping board" />
        </FormSection>

        <FormSection title="Decors" description="Each decor makes its own SKU, for example 892 and 959.">
          {decors.map((d, i) => (
            <div key={i} className="col-span-full grid grid-cols-[1fr_2fr_auto] items-end gap-3">
              <TextField label="Decor number" value={d.decor_no} onChange={(v) => setDecor(i, { decor_no: v.toUpperCase() })} maxLength={10} placeholder="892" />
              <TextField label="Decor name" optional value={d.decor_name} onChange={(v) => setDecor(i, { decor_name: v })} maxLength={80} placeholder="Walnut" />
              <Button variant="ghost" size="sm" iconLeft="x" isDisabled={decors.length === 1} onPress={() => setDecors((rows) => rows.filter((_, j) => j !== i))} aria-label="Remove decor" />
            </div>
          ))}
          <Button className="col-span-full justify-self-start" variant="secondary" size="sm" iconLeft="plus" onPress={() => setDecors((rows) => [...rows, { ...EMPTY_DECOR }])}>
            Add decor
          </Button>
        </FormSection>

        <FormSection title="Sizes" description="The code goes into the key (S, M, L, XL); the size in millimetres is optional.">
          {sizes.map((s, i) => (
            <div key={i} className="col-span-full grid grid-cols-[1fr_2fr_1fr_1fr_auto] items-end gap-3">
              <TextField label="Code" value={s.code} onChange={(v) => setSize(i, { code: v.toUpperCase() })} maxLength={8} />
              <TextField label="Label" value={s.label} onChange={(v) => setSize(i, { label: v })} maxLength={40} />
              <TextField label="Length (mm)" optional inputMode="decimal" value={s.length_mm} onChange={(v) => setSize(i, { length_mm: v })} maxLength={8} />
              <TextField label="Width (mm)" optional inputMode="decimal" value={s.width_mm} onChange={(v) => setSize(i, { width_mm: v })} maxLength={8} />
              <Button variant="ghost" size="sm" iconLeft="x" isDisabled={sizes.length === 1} onPress={() => setSizes((rows) => rows.filter((_, j) => j !== i))} aria-label="Remove size" />
            </div>
          ))}
          <Button className="col-span-full justify-self-start" variant="secondary" size="sm" iconLeft="plus" onPress={() => setSizes((rows) => [...rows, { ...EMPTY_SIZE }])}>
            Add size
          </Button>
        </FormSection>

        <GlassPanel padding="md" className="flex flex-col gap-3">
          <p className="t-label text-ink">{preview.length ? `${preview.length} products will be made` : "Fill in the design, a decor and a size to see the products"}</p>
          {preview.length ? <p className="t-body-sm lk-mono text-ink-2">{preview.join("  ·  ")}</p> : null}
          {ready ? (
            <Button className="self-start" variant="secondary" size="sm" loading={run.isPending && run.variables === true} onPress={() => run.mutate(true)}>
              Check against the catalogue
            </Button>
          ) : null}
        </GlassPanel>

        {result ? (
          <GlassPanel padding="none">
            <DataTable label="Products of this design" columns={COLUMNS} rows={result.rows} rowKey={(r) => r.product_key} />
          </GlassPanel>
        ) : null}

        <FormActions>
          <ButtonLink variant="ghost" href={"/products" as Route}>
            Back to the catalogue
          </ButtonLink>
          <Button type="submit" isDisabled={!ready} loading={run.isPending && run.variables === false}>
            Create {preview.length || ""} products
          </Button>
        </FormActions>
      </form>
    </Page>
  );
}
