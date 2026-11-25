"use client";

import type { Route } from "next";
import Link from "next/link";
import type { CompletenessRuleCount, CompletenessSummary } from "@/features/products/types";
import { formatCount } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { PRODUCTS_READ, useCompleteness } from "~/data/products";
import { Page, PageHeader, PageSection } from "~/shell/page";
import { NotPermitted, QueryView } from "~/shell/states";
import { Badge, ButtonLink, CountUp, EmptyState, GlassPanel, Icon, ProgressBar, Skeleton, SkeletonRows } from "~/ui";
import { riseStyle } from "./motion";

/**
 * Completeness is a work queue. It leads with how many products cannot be sold cleanly yet, then
 * lists each gap, biggest first; a row opens the catalogue filtered to exactly those products.
 */

/** Why each gap matters, in the words of whoever has to quote, pack or invoice the product. */
const WHY: Record<string, string> = {
  no_decor: "Without a decor these cannot be told apart from their siblings on a quotation.",
  no_specification: "Nothing is recorded about size or build, so they cannot be cut or packed with confidence.",
  no_thickness: "Cutting and weight both depend on thickness.",
  no_size: "A quotation and a packing list both need a size.",
  unparsed_dimensions: "A size was typed that could not be read into millimetres. It needs correcting by hand.",
  no_packaging: "Dispatch cannot plan cartons for these.",
  no_carton_qty: "Minimum order values are worked out from the carton quantity.",
  no_unit_weight: "Freight is quoted by weight.",
  category_inactive: "Their category is switched off, so pickers hide them.",
  no_hsn_sac: "An invoice needs an HSN or SAC code.",
  shared_display_sku: "Two or more products show the same SKU to customers.",
};

/** The catalogue filtered to one gap, as a table: the layout for working down a list. */
function queueHref(rule: CompletenessRuleCount): Route | null {
  if (!rule.filter_path) return null;
  return `${rule.filter_path}${rule.filter_path.includes("?") ? "&" : "?"}view=table` as Route;
}

function Hero({ summary }: { summary: CompletenessSummary }) {
  const { zone } = useSession();
  const gaps = Math.max(0, summary.total_products - summary.complete_products);
  const share = summary.total_products > 0 ? Math.round((summary.complete_products / summary.total_products) * 100) : 100;
  const biggest = [...summary.rules].filter((rule) => rule.count > 0).sort((a, b) => b.count - a.count)[0];
  return (
    <GlassPanel variant="inverse" padding="lg" className="rise">
      <div className="grid grid-cols-1 items-end gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
        <div className="flex flex-col gap-3">
          <p className="t-overline m-0">Not ready to sell</p>
          <p className="t-stat-xl lk-tnum m-0">
            <CountUp value={gaps} />
          </p>
          <p className="t-body-lg m-0 max-w-[46ch]">
            {gaps === 0
              ? "Every product passes every check. Nothing is waiting on you here."
              : `${gaps === 1 ? "product is" : "products are"} missing something a quotation, a carton or an invoice needs${
                  biggest ? `. The most common gap: ${biggest.label.toLowerCase()}.` : "."
                }`}
          </p>
        </div>
        <div className="flex flex-col gap-3">
          <div className="flex items-baseline justify-between gap-3">
            <span className="t-label">Complete</span>
            <span className="t-label lk-tnum">
              {formatCount(summary.complete_products, zone.locale)} of {formatCount(summary.total_products, zone.locale)}
            </span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-pill" style={{ background: "color-mix(in srgb, var(--on-inverse) 18%, transparent)" }} role="img" aria-label={`${share}% of products are complete`}>
            <div className="h-full rounded-pill" style={{ width: `${share}%`, background: "var(--on-inverse)" }} />
          </div>
          <p className="t-caption m-0" style={{ opacity: 0.72 }}>
            {share}% of the catalogue passes every check.
          </p>
        </div>
      </div>
    </GlassPanel>
  );
}

function QueueRow({ rule, total, index }: { rule: CompletenessRuleCount; total: number; index: number }) {
  const { zone } = useSession();
  const href = queueHref(rule);
  const share = total > 0 ? Math.round((rule.count / total) * 100) : 0;
  const urgent = rule.severity === "warning";
  return (
    <li className="rise-plain hairline-top relative first:border-t-0" style={riseStyle(index)}>
      <div className="grid grid-cols-1 items-center gap-x-8 gap-y-3 px-5 py-5 md:grid-cols-[minmax(0,1fr)_11rem_auto] md:px-6">
        <div className="flex min-w-0 items-start gap-4">
          <span className={`mt-0.5 flex size-9 flex-none items-center justify-center rounded-pill ${urgent ? "bg-amber-soft text-amber-text" : "bg-sand-soft text-ink-2"}`} aria-hidden="true">
            <Icon name={urgent ? "alert" : "info"} size={18} />
          </span>
          <div className="flex min-w-0 flex-col gap-1">
            <h3 className="t-h4 m-0">
              {href ? (
                <Link href={href} className="stretched text-ink no-underline">
                  {rule.label}
                </Link>
              ) : (
                rule.label
              )}
            </h3>
            {WHY[rule.code] ? <p className="t-body-sm m-0 text-ink-2">{WHY[rule.code]}</p> : null}
          </div>
        </div>
        <ProgressBar value={share} label={`Share of the catalogue with this gap`} hideLabel detail={`${share}% of products`} tone={urgent ? "ember" : "ink"} />
        <div className="flex items-center justify-between gap-4 md:justify-end">
          <p className="m-0 flex items-baseline gap-2">
            <span className="t-stat-sm lk-tnum text-ink">{formatCount(rule.count, zone.locale)}</span>
            <span className="t-body-sm text-ink-3">{rule.count === 1 ? "product" : "products"}</span>
          </p>
          {href ? (
            <span className="flex items-center gap-1 text-gold-strong" aria-hidden="true">
              <span className="t-label">Fix</span>
              <Icon name="arrowRight" size={16} />
            </span>
          ) : null}
        </div>
      </div>
    </li>
  );
}

function Queue({ title, description, rules, total, offset }: { title: string; description: string; rules: CompletenessRuleCount[]; total: number; offset: number }) {
  if (rules.length === 0) return null;
  return (
    <PageSection title={title} description={description} index={offset}>
      <GlassPanel padding="none">
        <ul className="m-0 list-none p-0">
          {rules.map((rule, index) => (
            <QueueRow key={rule.code} rule={rule} total={total} index={index} />
          ))}
        </ul>
      </GlassPanel>
    </PageSection>
  );
}

function Loading() {
  return (
    <>
      <GlassPanel variant="inverse" padding="lg" className="flex flex-col gap-4" role="status" aria-label="Loading completeness">
        <Skeleton width={140} />
        <Skeleton width={160} height={56} />
        <Skeleton width="50%" />
      </GlassPanel>
      <GlassPanel padding="none">
        <SkeletonRows rows={5} columns={3} />
      </GlassPanel>
    </>
  );
}

export function Completeness() {
  const { permissionKeys } = useSession();
  const allowed = permissionKeys.has(PRODUCTS_READ);
  const query = useCompleteness(allowed);

  return (
    <Page>
      <PageHeader
        breadcrumb={[{ label: "Catalogue", href: "/products" }]}
        title="Completeness"
        lead="What is missing from the catalogue, the biggest gap first. Open a gap to see the products behind it."
      />
      {!allowed ? (
        <NotPermitted what="The catalogue" icon="clipboardCheck" />
      ) : (
        <QueryView query={query} what="Completeness" loading={<Loading />}>
          {(summary) => {
            const open = summary.rules.filter((rule) => rule.count > 0).sort((a, b) => b.count - a.count);
            const first = open.filter((rule) => rule.severity === "warning");
            const later = open.filter((rule) => rule.severity !== "warning");
            const clear = summary.rules.filter((rule) => rule.count === 0);
            return (
              <>
                <Hero summary={summary} />
                {summary.rules.length === 0 ? (
                  <GlassPanel>
                    <EmptyState
                      icon="clipboardCheck"
                      title="No checks are set up yet"
                      text="Once the catalogue has checks, the gaps they find are listed here."
                      actions={<ButtonLink href="/products" variant="secondary">Open the catalogue</ButtonLink>}
                    />
                  </GlassPanel>
                ) : null}
                <Queue title="Fix these first" description="Each of these stops a product from being quoted, packed or invoiced properly." rules={first} total={summary.total_products} offset={0} />
                <Queue title="Worth closing" description="These do not block a sale, but they cost time every time someone has to ask." rules={later} total={summary.total_products} offset={1} />
                {clear.length > 0 ? (
                  <PageSection title="All clear" description="Checks that every product passes today." index={2}>
                    <div className="flex flex-wrap gap-2">
                      {clear.map((rule) => (
                        <Badge key={rule.code} tone="leaf" icon="check">
                          {rule.label}
                        </Badge>
                      ))}
                    </div>
                  </PageSection>
                ) : null}
                {summary.not_evaluated.length > 0 ? (
                  <p className="t-caption m-0 text-ink-3">Not checked yet: {summary.not_evaluated.map((entry) => entry.reason || entry.code).join("; ")}.</p>
                ) : null}
              </>
            );
          }}
        </QueryView>
      )}
    </Page>
  );
}
