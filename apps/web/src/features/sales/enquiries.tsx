"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Link as RacLink } from "react-aria-components";
import { StatusPill, type Tone } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { DataTable, OffsetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { DescriptionList } from "@/components/ui/description-list";
import { LocalDateTime, RelativeTime } from "@/components/ui/format";
import { Link, LinkButton } from "@/components/ui/link";
import { ReasonDialog } from "@/components/ui/reason-dialog";
import { SearchField } from "@/components/ui/search-field";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { linkClasses } from "@/components/ui/styles";
import { toast } from "@/components/ui/toast";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { createCommandKeys, commandSignature } from "@/lib/api/command-keys";
import { conflictFromError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { useOnline } from "@/lib/hooks";
import { useSession } from "@/lib/session/context";
import { briefingMessages } from "@/messages/briefing";
import { salesMessages as m } from "@/messages/sales";
import { closeEnquiry, fetchEnquiries, fetchEnquiry, QUOTES_PAGE_SIZE } from "./api";
import type { Enquiry } from "./types";
import { problemDescription } from "./use-quote-command";

export const ENQUIRY_STATUSES = ["received", "assigned", "quoted", "closed"] as const;
type EnquiryStatus = (typeof ENQUIRY_STATUSES)[number];

const TONE: Record<string, Tone> = { received: "info", assigned: "warning", quoted: "success", closed: "neutral" };

function EnquiryStatusPill({ status }: { status: string }) {
  return <StatusPill tone={TONE[status] ?? "neutral"}>{m.enquiries.status[status] ?? status}</StatusPill>;
}

export interface EnquiryListState {
  q: string;
  status: EnquiryStatus | null;
  offset: number;
}

type Search = Record<string, string | string[] | undefined>;
const first = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);

export function enquiryListStateFrom(search: Search): EnquiryListState {
  const q = (first(search.q) ?? "").slice(0, 200);
  const status = ENQUIRY_STATUSES.find((candidate) => candidate === first(search.status)) ?? null;
  const rawOffset = Number.parseInt(first(search.offset) ?? "0", 10);
  const offset = Number.isFinite(rawOffset) && rawOffset > 0 ? rawOffset - (rawOffset % QUOTES_PAGE_SIZE) : 0;
  return { q, status, offset };
}

export function enquiryListHref(state: Partial<EnquiryListState>): string {
  const query = new URLSearchParams();
  if (state.q?.trim()) query.set("q", state.q.trim());
  if (state.status) query.set("status", state.status);
  if (state.offset) query.set("offset", String(state.offset));
  const search = query.toString();
  return search ? `/sales/enquiries?${search}` : "/sales/enquiries";
}

function columns(): DataTableColumn<Enquiry>[] {
  return [
    {
      id: "number",
      header: m.enquiries.columns.number,
      isRowHeader: true,
      mobile: "title",
      mobileCell: (row) => row.enquiry_number,
      cell: (row) => (
        <RacLink href={row.path} className={`${linkClasses} font-mono`}>
          {row.enquiry_number}
        </RacLink>
      ),
    },
    { id: "party", header: m.enquiries.columns.party, mobile: "key", cell: (row) => row.party.display_name },
    { id: "subject", header: m.enquiries.columns.subject, cell: (row) => row.subject ?? <span className="text-ink-muted">{m.enquiries.noSubject}</span> },
    { id: "status", header: m.enquiries.columns.status, mobile: "status", cell: (row) => <EnquiryStatusPill status={row.status} /> },
    { id: "quote", header: m.enquiries.columns.quote, cell: (row) => (row.quote_number ? <span className="font-mono">{row.quote_number}</span> : <span className="text-ink-muted">—</span>) },
    { id: "received", header: m.enquiries.columns.received, mobile: "meta", cell: (row) => <RelativeTime value={row.received_at} className="text-ink-muted" /> },
  ];
}

export function EnquiryList({ state }: { state: EnquiryListState }) {
  const router = useRouter();
  const params = { q: state.q || null, status: state.status, offset: state.offset };
  const query = useQuery({ queryKey: queryKeys.sales.enquiries(params), queryFn: ({ signal }) => fetchEnquiries(params, signal) });
  const go = (next: Partial<EnquiryListState>) => router.push(enquiryListHref({ ...state, offset: 0, ...next }) as Parameters<typeof router.push>[0]);

  useScreenContribution(
    query.data
      ? {
          lists: [{ key: "enquiries", rows: query.data.items.map((row, index) => ({ type: "sales.enquiry", id: row.id, version: row.version, ordinal: state.offset + index + 1 })) }],
          filters: { q: state.q, status: state.status ?? "" },
        }
      : null,
  );

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">{m.enquiries.title}</h1>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] md:items-end">
        <SearchField
          label={m.enquiries.search}
          placeholder={m.enquiries.searchPlaceholder}
          defaultValue={state.q}
          onSubmit={(q) => go({ q })}
          onClear={() => go({ q: "" })}
        />
        <Select
          label={m.enquiries.statusFilter}
          options={[{ id: "", label: m.enquiries.anyStatus }, ...ENQUIRY_STATUSES.map((status) => ({ id: status, label: m.enquiries.status[status] ?? status }))]}
          value={state.status ?? ""}
          onChange={(value) => go({ status: ENQUIRY_STATUSES.find((status) => status === value) ?? null })}
        />
      </div>
      {query.isPending ? (
        <Loading label="enquiries" />
      ) : query.isError ? (
        <ErrorState error={query.error} what="the enquiries" onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          caption={m.enquiries.caption}
          hideCaption
          columns={columns()}
          rows={query.data.items}
          rowId={(row) => row.id}
          rowHref={(row) => row.path}
          empty={<EmptyState title={m.enquiries.emptyTitle}>{m.enquiries.empty}</EmptyState>}
          footer={
            <OffsetPagination
              label={m.enquiries.pages}
              total={query.data.total}
              limit={query.data.limit || QUOTES_PAGE_SIZE}
              offset={query.data.offset}
              shown={query.data.items.length}
              control={(offset) => ({ href: enquiryListHref({ ...state, offset }) })}
            />
          }
        />
      )}
    </div>
  );
}

const OUTCOMES = ["quoted", "no_response", "not_feasible", "duplicate", "other"] as const;

export function EnquiryDetail({ enquiryId }: { enquiryId: string }) {
  const { permissionKeys } = useSession();
  const online = useOnline();
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: queryKeys.sales.enquiry(enquiryId), queryFn: ({ signal }) => fetchEnquiry(enquiryId, signal) });
  const [closing, setClosing] = useState(false);
  const [pending, setPending] = useState(false);
  const [commandKeys] = useState(() => createCommandKeys());
  const offline = online ? null : briefingMessages.offlineActions;

  useScreenContribution(query.data ? { focus: { type: "sales.enquiry", id: query.data.id, version: query.data.version } } : null);

  if (query.isPending) return <Loading label={m.enquiries.detailLoading} variant="detail" />;
  if (query.isError) return <ErrorState error={query.error} what={m.enquiries.detailLoading} onRetry={() => void query.refetch()} />;
  const enquiry = query.data;
  const canClose = enquiry.allowed_transitions.some((transition) => transition.action === "close");
  const canQuote = enquiry.status !== "closed" && !enquiry.quote_id && permissionKeys.has("sales.quote.create");

  const close = async (outcome: string) => {
    if (pending || offline) return;
    const signature = commandSignature(enquiry.id, enquiry.version, "close", outcome);
    const attempt = commandKeys.attempt(signature, () => null);
    setPending(true);
    try {
      const updated = await closeEnquiry(enquiry, outcome, attempt.key);
      commandKeys.settle(signature);
      if (updated) queryClient.setQueryData(queryKeys.sales.enquiry(enquiry.id), updated);
      await queryClient.invalidateQueries({ queryKey: ["sales", "enquiries"] });
      setClosing(false);
      toast.success(m.enquiries.closed);
    } catch (error) {
      commandKeys.settle(signature, error);
      setClosing(false);
      if (conflictFromError(error)) {
        await queryClient.invalidateQueries({ queryKey: queryKeys.sales.enquiry(enquiry.id) });
        toast.warning(m.enquiries.changed);
      } else toast.error(m.enquiries.closeFailed, { description: problemDescription(error) });
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <header className="flex flex-col gap-2">
        <Link href="/sales/enquiries" className="text-sm">
          {m.enquiries.back}
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="font-mono text-[26px] leading-tight font-bold tracking-tight md:text-3xl">{enquiry.enquiry_number}</h1>
          <EnquiryStatusPill status={enquiry.status} />
        </div>
        <p className="text-ink">{enquiry.subject ?? m.enquiries.noSubject}</p>
      </header>
      <DescriptionList
        items={[
          { term: m.enquiries.columns.party, description: `${enquiry.party.display_name} · ${enquiry.party.party_number}` },
          { term: m.enquiries.channel, description: m.channels[enquiry.channel] ?? enquiry.channel },
          { term: m.enquiries.received, description: <LocalDateTime value={enquiry.received_at} /> },
          { term: m.enquiries.owner, description: enquiry.owner.display_name ?? "—" },
          ...(enquiry.quote_id
            ? [{ term: m.enquiries.quote, description: <Link href={`/sales/quotes/${encodeURIComponent(enquiry.quote_id)}`}>{enquiry.quote_number ?? m.enquiries.quote}</Link> }]
            : []),
          ...(enquiry.outcome_code ? [{ term: m.enquiries.outcome, description: m.enquiries.outcomes[enquiry.outcome_code] ?? enquiry.outcome_code }] : []),
        ]}
      />
      {enquiry.body ? (
        <section aria-labelledby="enquiry-body" className="flex flex-col gap-2">
          <h2 id="enquiry-body" className="text-lg font-[650] text-ink">
            {m.enquiries.body}
          </h2>
          <p className="text-sm text-ink-muted">{m.enquiries.untrusted}</p>
          {/* External text: rendered as plain text, never as markup or links. */}
          <p className="rounded-md border bg-surface p-4 whitespace-pre-wrap text-ink">{enquiry.body}</p>
        </section>
      ) : null}
      {canQuote || canClose ? (
        <div className="flex flex-wrap gap-2">
          {canQuote ? (
            <LinkButton href={`/sales/quotes/new?enquiry=${encodeURIComponent(enquiry.id)}`} variant="primary">
              {m.enquiries.createQuote}
            </LinkButton>
          ) : null}
          {canClose ? (
            <Button variant="secondary" onPress={() => setClosing(true)} {...unavailableWhen(offline)}>
              {m.enquiries.close}
            </Button>
          ) : null}
        </div>
      ) : null}
      <ReasonDialog
        title={m.enquiries.closeTitle}
        description={enquiry.enquiry_number}
        reasons={OUTCOMES.map((id) => ({ id, label: m.enquiries.outcomes[id] ?? id }))}
        noteLabel={m.enquiries.outcomeLabel}
        confirmLabel={m.enquiries.closeConfirm}
        isOpen={closing}
        isPending={pending}
        disabledReason={offline}
        onOpenChange={setClosing}
        onConfirm={(code) => (code ? void close(code) : undefined)}
      />
    </div>
  );
}
