"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button, unavailableWhen } from "@/components/ui/button";
import { DescriptionList } from "@/components/ui/description-list";
import { LocalDateTime } from "@/components/ui/format";
import { Link } from "@/components/ui/link";
import { ReasonDialog } from "@/components/ui/reason-dialog";
import { Conflict, EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { NavTabs } from "@/components/ui/tabs";
import { toast } from "@/components/ui/toast";
import { conflictFromError } from "@/lib/api/errors";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { fetchHistory, fetchProduct, fieldErrors, putSection, setArchived, updateProduct } from "./api";
import { FieldGrid, FieldValues } from "./field-grid";
import {
  DECOR_FIELDS,
  MASTER_FIELDS,
  PACKAGING_FIELDS,
  PROVENANCE_FIELDS,
  SPEC_FIELDS,
  masterPatch,
  masterValues,
  packagingValues,
  sectionBody,
  specValues,
  type FieldDef,
  type FormValues,
} from "./form-model";
import { MediaPanel } from "./media-panel";
import { ProductStatusPill, sizeText } from "./product-list";
import type { ProductDetail } from "./types";

export const PRODUCT_SECTIONS = ["overview", "specifications", "packaging", "pricing", "media", "history"] as const;
export type ProductSection = (typeof PRODUCT_SECTIONS)[number];

type Mode = "master" | "specification" | "packaging";

/**
 * One editable section: read view, inline form, server field errors (422) and the version-conflict view (409).
 * Saving sends only dirty master fields, or the whole section for specification/packaging (PUT).
 */
function SectionEditor({
  product,
  mode,
  groups,
  initial,
  onSaved,
}: {
  product: ProductDetail;
  mode: Mode;
  groups: readonly { title: string; fields: readonly FieldDef[] }[];
  initial: FormValues;
  onSaved: (next: ProductDetail, warnings: string[]) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [values, setValues] = useState<FormValues>(initial);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const queryClient = useQueryClient();
  const update = product.capabilities.update ?? { allowed: false, reason_code: "permission_denied" };
  const prefix = mode === "master" ? "" : `${mode}.`;
  const save = useMutation({
    mutationFn: () =>
      mode === "master"
        ? updateProduct(product.id, masterPatch(initial, values, product.version))
        : putSection(product.id, mode, product.version, sectionBody(groups.flatMap((g) => g.fields), values)),
    onSuccess: (result) => {
      setErrors({});
      setEditing(false);
      onSaved(result.product, result.warnings);
    },
    onError: (error) => setErrors(fieldErrors(error)),
  });
  const conflict = save.error ? conflictFromError(save.error) : null;
  const generalError = save.error && !conflict && !Object.keys(fieldErrors(save.error)).length ? save.error : null;

  if (!editing) {
    return (
      <div className="flex flex-col gap-6">
        <div className="flex justify-end">
          <Button
            onPress={() => {
              setValues(initial);
              setErrors({});
              save.reset();
              setEditing(true);
            }}
            {...unavailableWhen((!update.allowed) ? update.reason_code === "product_archived" ? "Restore the product to edit it" : "You cannot edit products" : null)}
          >
            Edit
          </Button>
        </div>
        {groups.map((group) => (
          <section key={group.title} aria-label={group.title} className="flex flex-col gap-3">
            <h2 className="text-base font-semibold">{group.title}</h2>
            <FieldValues fields={group.fields} values={initial} />
          </section>
        ))}
      </div>
    );
  }
  return (
    <form
      className="flex flex-col gap-6"
      aria-label={`Edit ${groups[0]?.title ?? "section"}`}
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      {conflict ? (
        <Conflict
          conflict={conflict}
          onReview={() => {
            void queryClient.invalidateQueries({ queryKey: queryKeys.catalogue.product(product.id) });
            setEditing(false);
          }}
        />
      ) : null}
      {generalError ? <ErrorState error={generalError} what="the change" compact backToToday={false} /> : null}
      {groups.map((group) => (
        <fieldset key={group.title} className="flex flex-col gap-3">
          <legend className="mb-2 text-base font-semibold">{group.title}</legend>
          <FieldGrid fields={group.fields} values={values} errors={errors} errorPrefix={prefix} onChange={(name, v) => setValues((cur) => ({ ...cur, [name]: v }))} />
        </fieldset>
      ))}
      <div className="flex flex-wrap justify-end gap-2">
        <Button onPress={() => setEditing(false)}>Cancel</Button>
        <Button type="submit" variant="primary" isPending={save.isPending} pendingLabel="Saving…">
          Save
        </Button>
      </div>
    </form>
  );
}

function Overview({ product }: { product: ProductDetail }) {
  const prices = product.prices ?? [];
  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-1 gap-6 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <DescriptionList
          items={[
            { term: "Category", description: product.subcategory ? `${product.category.name} › ${product.subcategory.name}` : product.category.name },
            { term: "Size", description: sizeText(product.size) ?? "—" },
            { term: "Thickness", description: product.specification?.thickness_mm ? `${product.specification.thickness_mm} mm` : "—" },
            { term: "Decor", description: product.decor.decor_no ? `${product.decor.decor_no}${product.decor.decor_name ? ` · ${product.decor.decor_name}` : ""}` : "—" },
            { term: "Packaging", description: product.packaging?.summary ?? "—" },
            { term: "Unit of sale", description: product.unit_of_sale ?? "—" },
            {
              term: "Completeness",
              description: `${product.completeness.score_pct}% (${product.completeness.checks_passed} of ${product.completeness.checks_evaluated} checks)`,
            },
          ]}
        />
        {product.primary_image ? (
          // eslint-disable-next-line @next/next/no-img-element -- same-origin authenticated original
          <img src={product.primary_image.url} alt={product.primary_image.alt_text ?? product.product_name} className="max-h-64 w-full rounded-md border object-contain" />
        ) : (
          <p className="rounded-md border border-dashed p-6 text-center text-sm text-ink-muted">No primary image</p>
        )}
      </div>
      {product.redacted_fields.includes("prices") ? null : prices.length ? (
        <section aria-label="Prices" className="flex flex-col gap-2">
          <h2 className="text-base font-semibold">Standard prices</h2>
          <ul className="flex flex-wrap gap-3 text-sm">
            {prices.map((p) => (
              <li key={p.currency} className="rounded-sm border px-3 py-2 tabular">
                {p.currency}: {p.unit_price?.amount ?? "—"}
              </li>
            ))}
          </ul>
        </section>
      ) : (
        <p className="text-sm text-ink-muted">No active standard price.</p>
      )}
      {product.completeness.missing.length ? (
        <section aria-label="Missing data" className="flex flex-col gap-2">
          <h2 className="text-base font-semibold">Missing data</h2>
          <ul className="list-disc ps-5 text-sm">
            {product.completeness.missing.map((m) => (
              <li key={m.code}>{m.label}</li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function History({ productId }: { productId: string }) {
  const history = useQuery({ queryKey: queryKeys.catalogue.history(productId), queryFn: ({ signal }) => fetchHistory(productId, signal) });
  if (history.isPending) return <Loading label="history" />;
  if (history.isError) return <ErrorState error={history.error} what="the history" onRetry={() => void history.refetch()} compact />;
  if (!history.data.items.length) return <EmptyState title="No recorded changes" />;
  return (
    <ol className="flex flex-col divide-y rounded-md border">
      {history.data.items.map((entry) => (
        <li key={entry.id} className="flex flex-col gap-1 px-4 py-3 text-sm">
          <span className="font-semibold">{entry.action.replace(/^catalogue\./, "").replace(/[._]/g, " ")}</span>
          <span className="text-ink-muted">
            <LocalDateTime value={entry.occurred_at} /> · {entry.actor_name ?? entry.actor_type}
            {entry.changed_fields.length ? ` · ${entry.changed_fields.join(", ")}` : ""}
            {entry.reason ? ` · ${entry.reason}` : ""}
          </span>
        </li>
      ))}
    </ol>
  );
}

/** Product detail (UI-14/38..44): deep-linked tabs, capability-driven archive/restore and inline section edits. */
export function ProductDetailView({ productId, section }: { productId: string; section: ProductSection }) {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: queryKeys.catalogue.product(productId), queryFn: ({ signal }) => fetchProduct(productId, signal) });
  const [archiveOpen, setArchiveOpen] = useState(false);
  const refresh = (next?: ProductDetail) => {
    if (next) queryClient.setQueryData(queryKeys.catalogue.product(productId), next);
    for (const key of invalidationMap["catalogue.changed"]) void queryClient.invalidateQueries({ queryKey: key });
  };
  const archive = useMutation({
    mutationFn: ({ archived, reason }: { archived: boolean; reason: string | null }) =>
      setArchived(productId, archived, query.data?.version ?? 0, reason),
    onSuccess: (next) => {
      setArchiveOpen(false);
      refresh(next);
      toast.success(next.archived_at ? "Product archived" : "Product restored");
    },
    onError: (error) => toast.error(conflictFromError(error) ? "The product changed; reload and try again" : "The change was not saved"),
  });

  if (query.isPending) return <Loading label="product" />;
  if (query.isError) return <ErrorState error={query.error} what="this product" onRetry={() => void query.refetch()} />;
  const product = query.data;
  const visible = product.sections.map((s) => s.key);
  const current = visible.includes(section) ? section : "overview";
  const onSaved = (next: ProductDetail, warnings: string[]) => {
    refresh(next);
    toast.success("Saved", warnings.length ? { description: `${warnings.length} warning(s): ${warnings.slice(0, 3).join("; ")}` } : {});
  };

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <p className="text-sm text-ink-muted">
            <Link href="/products">Products</Link> · <span className="font-mono">{product.product_key}</span>
          </p>
          <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">{product.product_name}</h1>
          <div className="flex flex-wrap items-center gap-2 text-sm text-ink-muted">
            <ProductStatusPill status={product.status} archived={Boolean(product.archived_at)} />
            <span>SKU {product.display_sku}</span>
            <span>· v{product.version}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {product.capabilities.archive?.allowed ? (
            <Button variant="danger" onPress={() => setArchiveOpen(true)}>
              Archive
            </Button>
          ) : null}
          {product.capabilities.restore?.allowed ? (
            <Button onPress={() => archive.mutate({ archived: false, reason: null })} isPending={archive.isPending}>
              Restore
            </Button>
          ) : null}
        </div>
      </header>
      <ReasonDialog
        title="Archive product"
        description={`${product.product_key} disappears from lists and pickers; quotes keep their snapshot.`}
        requireNote={false}
        noteLabel="Reason (optional)"
        confirmLabel="Archive"
        isOpen={archiveOpen}
        isPending={archive.isPending}
        onOpenChange={setArchiveOpen}
        onConfirm={(_code, note) => archive.mutate({ archived: true, reason: note.trim() || null })}
      />
      <NavTabs
        label="Product sections"
        currentId={current}
        tabs={product.sections.map((s) => ({ id: s.key, label: s.label, href: s.path, count: s.key === "media" ? product.media_count : undefined }))}
      />
      {current === "overview" ? (
        <div className="flex flex-col gap-8">
          <Overview product={product} />
          <SectionEditor
            key={`master-${product.version}`}
            product={product}
            mode="master"
            groups={[
              { title: "Master data", fields: MASTER_FIELDS },
              { title: "Decor", fields: DECOR_FIELDS },
              { title: "Source and provenance", fields: PROVENANCE_FIELDS },
            ]}
            initial={masterValues(product)}
            onSaved={onSaved}
          />
        </div>
      ) : null}
      {current === "specifications" ? (
        <SectionEditor key={`spec-${product.version}`} product={product} mode="specification" groups={[{ title: "Specifications", fields: SPEC_FIELDS }]} initial={specValues(product)} onSaved={onSaved} />
      ) : null}
      {current === "packaging" ? (
        <div className="flex flex-col gap-4">
          {product.packaging?.warnings.length ? (
            <p role="status" className="rounded-sm bg-warning-bg px-3 py-2 text-sm text-warning-text">
              Check: {product.packaging.warnings.join(", ")}
            </p>
          ) : null}
          <SectionEditor key={`pack-${product.version}`} product={product} mode="packaging" groups={[{ title: "Packaging", fields: PACKAGING_FIELDS }]} initial={packagingValues(product)} onSaved={onSaved} />
          {product.packaging?.alias_provenance ? (
            <details className="text-sm">
              <summary>Provenance of the canonical values</summary>
              <pre className="mt-2 overflow-x-auto rounded-sm bg-surface-sunken p-3 text-xs">{JSON.stringify(product.packaging.alias_provenance, null, 2)}</pre>
            </details>
          ) : null}
        </div>
      ) : null}
      {current === "pricing" ? (
        <p className="text-sm">
          Prices come from price lists. <Link href="/products/price-lists">Open the price lists</Link> to add or supersede a price.
        </p>
      ) : null}
      {current === "media" ? <MediaPanel productId={product.id} canManage={Boolean(product.capabilities.manage_media?.allowed)} /> : null}
      {current === "history" ? <History productId={product.id} /> : null}
    </div>
  );
}
