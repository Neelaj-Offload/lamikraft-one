"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { fetchBoms, fetchRoutings, type MasterSummary } from "@/features/production/api";
import { queryKeys } from "@/lib/api/query-keys";
import { asRoute, versionStatus } from "~/data/production";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { ButtonLink, DataTable, DateText, EmptyState, GlassPanel, PageSummary, SearchField, type Column } from "~/ui";
import { PATHS, ProductCell, ProductionNav, stagger, StatusBadge, versionLabel } from "./parts";
import { versionListHref } from "./views";

const COPY = {
  boms: {
    title: "Bills of materials",
    lead: "What each product is made of, version by version. Someone other than the author approves a draft, and approving it retires the version before.",
    noun: "versions",
    count: "Components",
    emptyTitle: "No bill of materials yet",
    emptyText: "No product has a bill of materials in this workspace. A product needs an approved one before it can be planned.",
    icon: "layers",
  },
  routings: {
    title: "Routings",
    lead: "How each product is made: its operations, the work centre for each and the standard times. Approved by someone other than the author.",
    noun: "versions",
    count: "Operations",
    emptyTitle: "No routing yet",
    emptyText: "No product has a routing in this workspace. A product needs an approved one before it can be planned.",
    icon: "route",
  },
} as const;

/** The versions of every bill of materials, or of every routing. The search text lives in the URL. */
export function VersionList({ kind, q }: { kind: "boms" | "routings"; q: string }) {
  const router = useRouter();
  const [text, setText] = useState(q);
  const copy = COPY[kind];
  const base = kind === "boms" ? PATHS.boms : PATHS.routings;
  const query = useQuery({
    queryKey: kind === "boms" ? queryKeys.production.boms({ q }) : queryKeys.production.routings({ q }),
    queryFn: ({ signal }) => (kind === "boms" ? fetchBoms({ q }, signal) : fetchRoutings({ q }, signal)),
  });
  const shown = query.data?.items.length ?? 0;
  const total = query.data?.total ?? 0;

  const columns: Column<MasterSummary>[] = [
    { key: "product", header: "Product", primary: true, cell: (version) => <ProductCell product={version.product} /> },
    { key: "version", header: "Version", cell: (version) => <span className="t-label lk-tnum text-ink">{versionLabel(version.version_no)}</span> },
    { key: "status", header: "Status", cell: (version) => <StatusBadge look={versionStatus(version.status)} /> },
    { key: "count", header: copy.count, numeric: true, cell: (version) => version.line_count },
    {
      key: "people",
      header: "Written and approved by",
      hideOnMobile: true,
      cell: (version) => (
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="text-ink">{version.author?.display_name ?? "Unknown author"}</span>
          <span className="t-caption text-ink-3">{version.approved_by?.display_name ? `Approved by ${version.approved_by.display_name}` : "Not approved"}</span>
        </span>
      ),
    },
    { key: "updated", header: "Updated", hideOnMobile: true, cell: (version) => <DateText value={version.updated_at} style="dayTime" /> },
  ];

  return (
    <Page>
      <PageHeader eyebrow="Production" title={copy.title} lead={copy.lead} />
      <ProductionNav current={kind} />

      <div className="rise min-w-0" style={stagger(1)}>
        <SearchField
          className="min-w-0 md:max-w-xl"
          label={`Search ${copy.title.toLowerCase()} by product`}
          placeholder="Product name or key"
          value={text}
          onChange={(value) => {
            setText(value);
            if (value === "" && q) router.push(asRoute(base));
          }}
          onSubmit={(value) => router.push(asRoute(versionListHref(base, value)))}
        />
      </div>

      {query.isError ? (
        <ErrorBlock error={query.error} what={copy.title} onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise min-w-0" style={stagger(2)}>
          <DataTable
            label={copy.title}
            columns={columns}
            rows={query.data?.items ?? []}
            rowKey={(version) => version.id}
            rowHref={(version) => asRoute(`${base}/${version.id}`)}
            loading={query.isPending}
            skeletonRows={8}
            empty={
              q ? (
                <EmptyState
                  compact
                  icon="search"
                  title="No product matches"
                  text="Check the spelling, or search by the product key."
                  actions={
                    <ButtonLink href={asRoute(base)} variant="secondary" size="sm">
                      Clear search
                    </ButtonLink>
                  }
                />
              ) : (
                <EmptyState icon={copy.icon} title={copy.emptyTitle} text={copy.emptyText} />
              )
            }
          />
        </GlassPanel>
      )}

      {query.data && total > 0 ? (
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
          <PageSummary from={1} to={shown} total={total} noun={copy.noun} />
          {total > shown ? <p className="t-body-sm text-ink-3">Search by product to find the rest.</p> : null}
        </div>
      ) : null}
    </Page>
  );
}
