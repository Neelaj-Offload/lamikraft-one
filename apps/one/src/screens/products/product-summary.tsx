"use client";

import type { Route } from "next";
import type { ProductDetail } from "@/features/products/types";
import { useZone } from "@/lib/session/context";
import type { LoadedProduct } from "~/data/products";
import { Split } from "~/shell/page";
import { ButtonLink, DateText, GlassPanel, Icon, KeyValue, ProgressRing, TextLink } from "~/ui";
import { PRODUCT_STATUS_LABEL, StandardPrice } from "./format";
import { issueFixHref, productViewHref } from "./links";
import { glanceItems } from "./product-views";
import { decorSwatch } from "./swatch";

/** The summary answers one question: is this product ready to sell, and if not, what is missing? */

interface Gap {
  key: string;
  text: string;
  /** Where the gap is closed; absent when nothing on this record can close it. */
  href?: Route;
  fix?: string;
}

const FIX_LABEL: Record<string, string> = {
  no_decor: "Add it in Details",
  no_hsn_sac: "Add it in Details",
  shared_display_sku: "Change it in Details",
  no_specification: "Add it in Specification",
  no_thickness: "Add it in Specification",
  no_size: "Add it in Specification",
  unparsed_dimensions: "Correct it in Specification",
  no_packaging: "Add it in Packaging",
  no_carton_qty: "Add it in Packaging",
  no_unit_weight: "Add it in Packaging",
  category_inactive: "Open Taxonomy",
};

function gapsOf(product: ProductDetail): { blocking: Gap[]; tidy: Gap[] } {
  const blocking: Gap[] = [];
  const tidy: Gap[] = [];
  if (product.archived_at) blocking.push({ key: "archived", text: "It is archived, so it is hidden from lists and pickers." });
  else if (product.status !== "active") {
    blocking.push({ key: "status", text: `Its status is “${PRODUCT_STATUS_LABEL[product.status] ?? product.status}”, so it is not offered for sale yet.` });
  }
  for (const issue of product.completeness.missing) {
    const gap: Gap = { key: issue.code, text: issue.label, href: issueFixHref(product.id, issue.code), fix: FIX_LABEL[issue.code] ?? "Fix it in Details" };
    (issue.severity === "warning" ? blocking : tidy).push(gap);
  }
  if (product.prices !== null && !product.prices.some((column) => column.status === "found" && column.unit_price)) {
    blocking.push({ key: "price", text: "No standard price in any currency.", href: productViewHref(product.id, "pricing"), fix: "See its prices" });
  }
  return { blocking, tidy };
}

function GapRow({ gap, tone }: { gap: Gap; tone: "amber" | "ink" }) {
  return (
    <li className="hairline-top flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-3 first:border-t-0 first:pt-0 last:pb-0">
      <span className="flex min-w-0 items-start gap-3">
        <span className={tone === "amber" ? "mt-0.5 flex-none text-amber-text" : "mt-0.5 flex-none text-ink-3"}>
          <Icon name={tone === "amber" ? "alert" : "info"} size={16} />
        </span>
        <span className="t-body text-ink">{gap.text}</span>
      </span>
      {gap.href && gap.fix ? (
        <TextLink href={gap.href} className="t-label flex-none whitespace-nowrap">
          {gap.fix}
        </TextLink>
      ) : null}
    </li>
  );
}

export function ProductSummary({ raw, product }: LoadedProduct) {
  const { locale } = useZone();
  const { blocking, tidy } = gapsOf(product);
  const ready = blocking.length === 0;
  const { completeness } = product;
  const ownImage = raw.primary_image?.url?.startsWith("/api/") ? raw.primary_image : null;
  const swatch = ownImage ? null : decorSwatch(product.decor.decor_no, product.decor.decor_name, product.product_name, product.specification?.material_type);
  const hasMedia = product.sections.some((section) => section.key === "media");

  return (
    <Split
      main={
        <>
          <GlassPanel padding="lg" className="rise flex flex-col gap-6">
            <div className="flex flex-wrap items-center gap-5">
              <ProgressRing
                value={completeness.score_pct}
                label={`${completeness.checks_passed} of ${completeness.checks_evaluated} checks passed`}
                tone={ready ? "leaf" : "ink"}
                size={88}
                stroke={7}
              />
              <div className="flex min-w-0 flex-1 flex-col gap-1">
                <p className="t-overline m-0 text-ink-3">Ready to sell?</p>
                <h2 className="t-h2 m-0">
                  {ready ? "Yes. Nothing is holding this product back." : blocking.length === 1 ? "Not yet. One thing to fix first." : `Not yet. ${blocking.length} things to fix first.`}
                </h2>
                <p className="t-body-sm m-0 text-ink-2">
                  {completeness.checks_passed} of {completeness.checks_evaluated} checks passed
                  {tidy.length > 0 ? `, and ${tidy.length} smaller ${tidy.length === 1 ? "gap" : "gaps"} worth closing` : ""}.
                </p>
              </div>
            </div>
            {blocking.length > 0 ? (
              <ul className="m-0 flex list-none flex-col p-0" aria-label="What to fix first">
                {blocking.map((gap) => (
                  <GapRow key={gap.key} gap={gap} tone="amber" />
                ))}
              </ul>
            ) : null}
          </GlassPanel>

          {tidy.length > 0 ? (
            <GlassPanel variant="outline" padding="lg" title="Worth closing when you can" titleAs="h3">
              <ul className="m-0 flex list-none flex-col p-0">
                {tidy.map((gap) => (
                  <GapRow key={gap.key} gap={gap} tone="ink" />
                ))}
              </ul>
            </GlassPanel>
          ) : null}

          {product.prices !== null ? (
            <GlassPanel
              padding="lg"
              title="Standard prices"
              titleAs="h3"
              action={
                <ButtonLink href={productViewHref(product.id, "pricing")} variant="ghost" size="sm" iconRight="arrowRight">
                  Every price
                </ButtonLink>
              }
            >
              {product.prices.length === 0 ? (
                <p className="t-body-sm m-0 text-ink-3">No price list covers this product yet.</p>
              ) : (
                <KeyValue
                  rows
                  items={product.prices.map((column) => ({
                    label: (
                      <span className="flex flex-wrap items-baseline gap-x-2">
                        <span className="lk-mono">{column.currency}</span>
                        {column.status === "found" && column.price_list_code ? <span className="t-caption text-ink-3">from {column.price_list_code}</span> : null}
                      </span>
                    ),
                    value: <StandardPrice column={column} />,
                  }))}
                />
              )}
            </GlassPanel>
          ) : null}

          {completeness.not_evaluated.length > 0 ? (
            <p className="t-caption m-0 text-ink-3">
              Not checked for this product: {completeness.not_evaluated.map((entry) => entry.reason || entry.code).join("; ")}.
            </p>
          ) : null}
        </>
      }
      aside={
        <>
          <GlassPanel padding="none" className="rise overflow-hidden">
            <div className="relative aspect-[4/3] w-full bg-sand-soft">
              {ownImage || swatch ? (
                // A product photo from the API or a decor swatch built into the app; neither needs the image optimiser.
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={ownImage ? ownImage.url : swatch!.albedo}
                  alt={ownImage ? (ownImage.alt_text ?? product.product_name) : ""}
                  className={`h-full w-full ${ownImage ? "object-contain" : "object-cover"}`}
                />
              ) : (
                <div className="flex h-full w-full flex-col items-center justify-center gap-2 text-ink-3">
                  <Icon name="image" size={28} />
                  <span className="t-caption">No photo yet</span>
                </div>
              )}
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-4">
              <p className="t-caption m-0 text-ink-3">{ownImage ? "Main photo" : swatch ? "Decor swatch, not a product photo" : "Add a photo so the catalogue shows it."}</p>
              {ownImage || !swatch ? (
                hasMedia ? (
                  <TextLink href={productViewHref(product.id, "media")} className="t-label">
                    {ownImage ? "All media" : "Add a photo"}
                  </TextLink>
                ) : null
              ) : (
                <TextLink href={productViewHref(product.id, "material")} className="t-label">
                  See it in 3D
                </TextLink>
              )}
            </div>
          </GlassPanel>
          <GlassPanel padding="lg" title="At a glance" titleAs="h3">
            <KeyValue rows items={[...glanceItems(product, locale), { label: "Last changed", value: <DateText value={product.updated_at} style="relative" /> }]} />
          </GlassPanel>
        </>
      }
    />
  );
}
