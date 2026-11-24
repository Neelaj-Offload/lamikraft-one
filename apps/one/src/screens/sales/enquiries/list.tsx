"use client";

import { useQuery } from "@tanstack/react-query";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { fetchEnquiries, QUOTES_PAGE_SIZE } from "@/features/sales/api";
import { enquiryListHref, type EnquiryListState } from "@/features/sales/list-state";
import type { Enquiry } from "@/features/sales/types";
import { queryKeys } from "@/lib/api/query-keys";
import { useEnquiryCount } from "~/data/sales-crm";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { Badge, ButtonLink, ChipLink, Code, DataTable, DateText, EmptyState, GlassPanel, Icon, PageSummary, Pagination, SearchField, TableFooter, type Column } from "~/ui";
import { stagger } from "../customers/labels";
import { PipelineStrip } from "../samples/pipeline";
import { CHANNEL_ICON, channelLabel, ENQUIRY_PIPELINE, ENQUIRY_STAGE_HINT, ENQUIRY_STAGE_ICON, ENQUIRY_STAGE_LABEL, ENQUIRY_STAGE_TONE } from "./labels";

const href = (state: Partial<EnquiryListState>) => enquiryListHref(state) as Route;

const COLUMNS: Column<Enquiry>[] = [
  {
    key: "enquiry",
    header: "Enquiry",
    primary: true,
    cell: (enquiry) => (
      <span className="flex min-w-0 flex-col">
        <span className="t-label truncate text-ink" title={enquiry.subject ?? undefined}>
          {enquiry.subject ?? "No subject"}
        </span>
        <span className="t-caption lk-mono text-ink-3">{enquiry.enquiry_number}</span>
      </span>
    ),
  },
  { key: "customer", header: "From", cell: (enquiry) => enquiry.party.display_name },
  {
    key: "channel",
    header: "Came by",
    hideOnMobile: true,
    cell: (enquiry) => (
      <span className="inline-flex items-center gap-2 text-ink-2">
        <Icon name={CHANNEL_ICON[enquiry.channel] ?? "message"} size={14} />
        {channelLabel(enquiry.channel)}
      </span>
    ),
  },
  {
    key: "stage",
    header: "Stage",
    cell: (enquiry) => (
      <Badge tone={ENQUIRY_STAGE_TONE[enquiry.status]} dot>
        {ENQUIRY_STAGE_LABEL[enquiry.status]}
      </Badge>
    ),
  },
  { key: "quotation", header: "Quotation", hideOnMobile: true, cell: (enquiry) => (enquiry.quote_number ? <Code>{enquiry.quote_number}</Code> : <span className="text-ink-3">Not quoted</span>) },
  { key: "received", header: "Received", mobileLabel: "Received", cell: (enquiry) => <DateText value={enquiry.received_at} style="relative" className="text-ink-3" /> },
];

/** Enquiries as a pipeline: four stages across the top, the list for the chosen stage below. */
export function EnquiryList({ state }: { state: EnquiryListState }) {
  const router = useRouter();
  const params = { q: state.q || null, status: state.status, offset: state.offset };
  const query = useQuery({ queryKey: queryKeys.sales.enquiries(params), queryFn: ({ signal }) => fetchEnquiries(params, signal) });
  const received = useEnquiryCount("received");
  const assigned = useEnquiryCount("assigned");
  const quoted = useEnquiryCount("quoted");
  const closed = useEnquiryCount("closed");
  const counts = { received, assigned, quoted, closed };
  const go = (next: Partial<EnquiryListState>) => router.push(href({ ...state, offset: 0, ...next }));

  useScreenContribution(
    query.data
      ? {
          lists: [{ key: "enquiries", rows: query.data.items.map((row, index) => ({ type: "sales.enquiry", id: row.id, version: row.version, ordinal: state.offset + index + 1 })) }],
          filters: { q: state.q, status: state.status ?? "" },
        }
      : null,
  );

  const limit = query.data?.limit || QUOTES_PAGE_SIZE;
  const total = query.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / limit));
  const page = Math.floor((query.data?.offset ?? state.offset) / limit) + 1;
  const filtered = state.q !== "" || state.status !== null;

  return (
    <Page>
      <PageHeader eyebrow="Sales" title="Enquiries" lead="Every request from a lead or a customer, from the day it arrives to the day it is quoted or closed." />

      <PipelineStrip
        label="Enquiry pipeline"
        selected={state.status}
        loading={received.isPending}
        stages={ENQUIRY_PIPELINE.map((stage) => ({
          id: stage,
          label: ENQUIRY_STAGE_LABEL[stage],
          hint: ENQUIRY_STAGE_HINT[stage],
          icon: ENQUIRY_STAGE_ICON[stage],
          count: counts[stage].data,
          href: href({ q: state.q, status: state.status === stage ? null : stage }),
        }))}
      />

      <div className="rise flex min-w-0 flex-wrap items-center gap-3" style={stagger(2)}>
        <SearchField
          key={state.q}
          className="min-w-0 flex-1 basis-64"
          label="Search enquiries"
          placeholder="Number, customer or subject"
          defaultValue={state.q}
          onSubmit={(q) => go({ q })}
          onChange={(q) => {
            if (q === "" && state.q !== "") go({ q: "" });
          }}
        />
        {state.status ? (
          <ChipLink href={href({ q: state.q, status: null })} selected icon="x">
            {ENQUIRY_STAGE_LABEL[state.status]} only
          </ChipLink>
        ) : null}
      </div>

      {query.isError ? (
        <ErrorBlock error={query.error} what="Enquiries" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise" style={stagger(3)}>
          <DataTable
            label="Enquiries"
            columns={COLUMNS}
            rows={query.data?.items ?? []}
            rowKey={(enquiry) => enquiry.id}
            rowHref={(enquiry) => enquiry.path as Route}
            loading={query.isPending}
            skeletonRows={8}
            empty={
              filtered ? (
                <EmptyState
                  compact
                  icon="search"
                  title={state.q ? "Nothing matches" : `Nothing is ${state.status ? ENQUIRY_STAGE_LABEL[state.status].toLowerCase() : "here"}`}
                  text={state.q ? "No enquiry fits this search. Try the customer's name or the enquiry number." : "No enquiry is at this stage right now."}
                  actions={
                    <ButtonLink variant="secondary" size="sm" href={href({})}>
                      Show every enquiry
                    </ButtonLink>
                  }
                />
              ) : (
                <EmptyState
                  icon="inbox"
                  title="No enquiries yet"
                  text="When a lead or customer asks for a price by email, WhatsApp or the website, their request lands here."
                  actions={
                    <ButtonLink variant="secondary" href={"/sales/customer-messages" as Route}>
                      Open messages
                    </ButtonLink>
                  }
                />
              )
            }
            footer={
              query.data && total > 0 ? (
                <TableFooter
                  left={<PageSummary from={query.data.offset + 1} to={query.data.offset + query.data.items.length} total={total} noun="enquiries" />}
                  right={pages > 1 ? <Pagination label="Enquiry pages" page={page} pages={pages} hrefFor={(target) => href({ ...state, offset: (target - 1) * limit })} /> : null}
                />
              ) : undefined
            }
          />
        </GlassPanel>
      )}
    </Page>
  );
}
