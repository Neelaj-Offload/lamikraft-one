"use client";

import { useQuery } from "@tanstack/react-query";
import { Link as RacLink } from "react-aria-components";
import { Badge, type Tone } from "@/components/ui/badge";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { FactStrip } from "@/components/ui/fact-strip";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, Loading, PermissionDenied } from "@/components/ui/states";
import { linkClasses } from "@/components/ui/styles";
import { queryKeys } from "@/lib/api/query-keys";
import { formatCount } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { productsMessages as m } from "@/messages/products";
import { fetchCompleteness } from "./api";
import { productsAreaNav, PRODUCTS_READ } from "./product-list";
import type { CompletenessRuleCount } from "./types";

const SEVERITY_TONE: Record<string, Tone> = { warning: "warning", info: "info" };

function ruleColumns(locale: string): DataTableColumn<CompletenessRuleCount>[] {
  const c = m.completeness.columns;
  return [
    { id: "rule", header: c.rule, isRowHeader: true, mobile: "title", cell: (rule) => rule.label },
    {
      id: "severity",
      header: c.severity,
      mobile: "status",
      cell: (rule) => <Badge tone={SEVERITY_TONE[rule.severity] ?? "neutral"}>{m.detail.completeness.severity[rule.severity] ?? rule.severity}</Badge>,
    },
    {
      id: "count",
      header: c.count,
      numeric: true,
      mobile: "amount",
      mobileCell: (rule) => formatCount(rule.count, locale),
      cell: (rule) =>
        rule.filter_path && rule.count > 0 ? (
          <RacLink href={rule.filter_path} className={`${linkClasses} tabular`}>
            {formatCount(rule.count, locale)}
          </RacLink>
        ) : (
          <span className="tabular">{formatCount(rule.count, locale)}</span>
        ),
    },
  ];
}

export function CompletenessView() {
  const { permissionKeys, zone } = useSession();
  const allowed = permissionKeys.has(PRODUCTS_READ);
  const query = useQuery({ queryKey: queryKeys.catalogue.completeness(), queryFn: ({ signal }) => fetchCompleteness(signal), enabled: allowed });
  const t = m.completeness;
  if (!allowed) return <PermissionDenied area={m.list.title.toLowerCase()} />;
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={t.title} intro={t.intro} nav={productsAreaNav()} />
      {query.isPending ? (
        <Loading label={t.loading} />
      ) : query.isError ? (
        <ErrorState error={query.error} what={t.what} onRetry={() => void query.refetch()} />
      ) : (
        <>
          <FactStrip
            label={t.facts.label}
            facts={[
              { label: t.facts.total, value: formatCount(query.data.total_products, zone.locale), href: "/products" },
              { label: t.facts.complete, value: formatCount(query.data.complete_products, zone.locale) },
            ]}
          />
          <DataTable
            caption={t.caption}
            hideCaption
            columns={ruleColumns(zone.locale)}
            rows={query.data.rules}
            rowId={(rule) => rule.code}
            rowHref={(rule) => (rule.count > 0 ? rule.filter_path : null)}
            empty={<EmptyState title={t.emptyTitle}>{t.empty}</EmptyState>}
          />
          {query.data.not_evaluated.length > 0 ? (
            <section className="flex flex-col gap-1 text-sm text-ink-muted">
              <h2 className="font-semibold">{t.notEvaluated}</h2>
              <ul className="flex flex-col gap-0.5">
                {query.data.not_evaluated.map((entry) => (
                  <li key={entry.code}>
                    <span className="font-mono">{entry.code}</span>
                    {entry.reason ? ` — ${entry.reason}` : null}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </>
      )}
    </div>
  );
}
