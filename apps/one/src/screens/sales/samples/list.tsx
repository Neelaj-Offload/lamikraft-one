"use client";

import { useQuery } from "@tanstack/react-query";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { fetchSamples, SAMPLES_PAGE_SIZE, type Sample } from "@/features/samples/api";
import { sampleListHref, type SampleListState } from "@/features/samples/list-state";
import { isProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { useSampleStatusCounts } from "~/data/sales-crm";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock, NotPermitted } from "~/shell/states";
import { Badge, Button, ButtonLink, ChipLink, DataTable, DateText, EmptyState, GlassPanel, PageSummary, Pagination, Qty, SearchField, TableFooter, type Column } from "~/ui";
import { humanise, stagger } from "../customers/labels";
import { SampleCreateDialog } from "./create-dialog";
import { SAMPLE_JOURNEY, SAMPLE_STATUS_LABEL, SAMPLE_STATUS_TONE, SAMPLE_STEP_ICON, type SampleStep } from "./labels";
import { PipelineStrip } from "./pipeline";

const href = (state: Partial<SampleListState>) => sampleListHref(state) as Route;

const STAGE_HINT: Record<SampleStep, string> = {
  requested: "Waiting to leave stock",
  dispatched: "On the way",
  delivered: "Awaiting their feedback",
  feedback_received: "Answered, not closed",
  closed: "Finished",
};

const COLUMNS: Column<Sample>[] = [
  {
    key: "sample",
    header: "Sample",
    primary: true,
    cell: (sample) => (
      <span className="flex min-w-0 flex-col">
        <span className="t-label truncate text-ink" title={sample.description}>
          {sample.description || "Sample"}
        </span>
        <span className="t-caption lk-mono text-ink-3">{sample.sample_number}</span>
      </span>
    ),
  },
  { key: "customer", header: "Customer", cell: (sample) => sample.party.display_name },
  {
    key: "stage",
    header: "Stage",
    cell: (sample) => (
      <Badge tone={SAMPLE_STATUS_TONE[sample.status] ?? "neutral"} dot>
        {SAMPLE_STATUS_LABEL[sample.status] ?? humanise(sample.status)}
      </Badge>
    ),
  },
  { key: "quantity", header: "Quantity", numeric: true, hideOnMobile: true, cell: (sample) => <Qty value={{ value: sample.quantity, uom: sample.unit_code }} /> },
  {
    key: "for",
    header: "Sent for",
    hideOnMobile: true,
    cell: (sample) => {
      const linked = [sample.quote_number, sample.custom_code].filter(Boolean).join(" · ");
      return linked ? <span className="lk-mono t-code-sm">{linked}</span> : <span className="text-ink-3">Not linked</span>;
    },
  },
  { key: "requested", header: "Requested", mobileLabel: "Requested", cell: (sample) => <DateText value={sample.requested_on} style="business" className="text-ink-3" /> },
];

/** Customer samples: the journey across the top as a filter, the samples at that stage below. */
export function SampleList({ state }: { state: SampleListState }) {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const canRead = permissionKeys.has("sales.sample.read");
  const canCreate = permissionKeys.has("sales.sample.create");
  const params = { q: state.q || null, status: state.status, offset: state.offset };
  const query = useQuery({ queryKey: queryKeys.sales.samples(params), queryFn: ({ signal }) => fetchSamples(params, signal), enabled: canRead });
  const counts = useSampleStatusCounts(canRead);
  const [creating, setCreating] = useState({ open: false, round: 0 });
  const go = (next: Partial<SampleListState>) => router.push(href({ ...state, offset: 0, ...next }));
  const forbidden = !canRead || (query.isError && isProblemError(query.error) && query.error.status === 403);

  const header = (
    <PageHeader
      eyebrow="Sales"
      title="Customer samples"
      lead="Every sample taken from stock for a customer, followed from the request to their feedback."
      actions={
        canCreate && !forbidden ? (
          <Button iconLeft="plus" onPress={() => setCreating((current) => ({ open: true, round: current.round + 1 }))}>
            Add sample
          </Button>
        ) : null
      }
    />
  );

  if (forbidden) {
    return (
      <Page>
        {header}
        <GlassPanel>
          <NotPermitted what="Samples" icon="packageOpen" />
        </GlassPanel>
      </Page>
    );
  }

  const limit = query.data?.limit || SAMPLES_PAGE_SIZE;
  const total = query.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / limit));
  const page = Math.floor((query.data?.offset ?? state.offset) / limit) + 1;
  const filtered = state.q !== "" || state.status !== null;
  const cancelled = counts.data?.cancelled;

  return (
    <Page>
      {header}

      <PipelineStrip
        label="Sample journey"
        selected={state.status}
        loading={counts.isPending}
        stages={SAMPLE_JOURNEY.map((step) => ({
          id: step,
          label: SAMPLE_STATUS_LABEL[step] ?? step,
          hint: STAGE_HINT[step],
          icon: SAMPLE_STEP_ICON[step],
          count: counts.data ? (counts.data[step] ?? 0) : undefined,
          href: href({ q: state.q, status: state.status === step ? null : step }),
        }))}
      />

      <div className="rise flex min-w-0 flex-wrap items-center gap-3" style={stagger(2)}>
        <SearchField
          key={state.q}
          className="min-w-0 flex-1 basis-64"
          label="Search samples"
          placeholder="Sample number, description or courier reference"
          defaultValue={state.q}
          onSubmit={(q) => go({ q })}
          onChange={(q) => {
            if (q === "" && state.q !== "") go({ q: "" });
          }}
        />
        {state.status && state.status !== "cancelled" ? (
          <ChipLink href={href({ q: state.q, status: null })} selected icon="x">
            {SAMPLE_STATUS_LABEL[state.status]} only
          </ChipLink>
        ) : null}
        {cancelled || state.status === "cancelled" ? (
          <ChipLink href={href({ q: state.q, status: state.status === "cancelled" ? null : "cancelled" })} selected={state.status === "cancelled"} count={cancelled}>
            Cancelled
          </ChipLink>
        ) : null}
      </div>

      {query.isError ? (
        <ErrorBlock error={query.error} what="Samples" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise" style={stagger(3)}>
          <DataTable
            label="Customer samples"
            columns={COLUMNS}
            rows={query.data?.items ?? []}
            rowKey={(sample) => sample.id}
            rowHref={(sample) => `/sales/samples/${encodeURIComponent(sample.id)}` as Route}
            loading={query.isPending}
            skeletonRows={8}
            empty={
              filtered ? (
                <EmptyState
                  compact
                  icon="search"
                  title={state.q ? "Nothing matches" : "No sample is at this stage"}
                  text={state.q ? "No sample fits this search. Try the sample number or the courier reference." : "Choose another stage, or see every sample."}
                  actions={
                    <ButtonLink variant="secondary" size="sm" href={href({})}>
                      Show every sample
                    </ButtonLink>
                  }
                />
              ) : (
                <EmptyState
                  icon="packageOpen"
                  title="No samples yet"
                  text="Add the first sample a customer asks for. Receiving one is what turns a lead into a customer."
                  actions={
                    canCreate ? (
                      <Button iconLeft="plus" onPress={() => setCreating((current) => ({ open: true, round: current.round + 1 }))}>
                        Add sample
                      </Button>
                    ) : undefined
                  }
                />
              )
            }
            footer={
              query.data && total > 0 ? (
                <TableFooter
                  left={<PageSummary from={query.data.offset + 1} to={query.data.offset + query.data.items.length} total={total} noun="samples" />}
                  right={pages > 1 ? <Pagination label="Sample pages" page={page} pages={pages} hrefFor={(target) => href({ ...state, offset: (target - 1) * limit })} /> : null}
                />
              ) : undefined
            }
          />
        </GlassPanel>
      )}

      {canCreate ? <SampleCreateDialog key={creating.round} isOpen={creating.open} onOpenChange={(open) => setCreating((current) => ({ ...current, open }))} /> : null}
    </Page>
  );
}
