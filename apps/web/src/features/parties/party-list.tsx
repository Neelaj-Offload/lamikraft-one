"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Link as RacLink } from "react-aria-components";
import { AreaNav } from "@/components/shell/area-nav";
import { Badge, StatusPill, type Tone } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/choice";
import { DataTable, OffsetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { RelativeTime } from "@/components/ui/format";
import { LinkButton } from "@/components/ui/link";
import { PageHeader } from "@/components/ui/page-header";
import { SearchField } from "@/components/ui/search-field";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { linkClasses } from "@/components/ui/styles";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { useSession } from "@/lib/session/context";
import { partiesMessages as m } from "@/messages/parties";
import { fetchParties, PARTIES_PAGE_SIZE } from "./api";
import { partyListHref, partyListParams, partyListQueryKey, type PartyListState } from "./list-state";
import { CUSTOMER_TYPES, PARTY_ROLES, PARTY_STATUSES, type PartySummary } from "./types";

export const PARTY_STATUS_TONE: Record<string, Tone> = { prospect: "info", active: "success", inactive: "neutral", blocked: "danger" };

export function PartyStatusPill({ status }: { status: string }) {
  return <StatusPill tone={PARTY_STATUS_TONE[status] ?? "neutral"}>{m.status[status] ?? status}</StatusPill>;
}

export function RoleBadges({ roles }: { roles: readonly string[] }) {
  if (roles.length === 0) return <span className="text-ink-muted">—</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {roles.map((role) => (
        <Badge key={role}>{m.roles[role] ?? role}</Badge>
      ))}
    </span>
  );
}

export const SALES_NAV_LEADING = [{ id: "sales", label: m.overview, href: "/sales" }] as const;

export { partyListHref, partyListParams, partyListQueryKey, partyListStateFrom, type PartyListState } from "./list-state";

const dash = <span className="text-ink-muted">—</span>;

export function partyColumns(): DataTableColumn<PartySummary>[] {
  return [
    {
      id: "number",
      header: m.list.columns.number,
      isRowHeader: true,
      mobile: "title",
      mobileCell: (party) => `${party.party_number} · ${party.display_name}`,
      cell: (party) => (
        <RacLink href={party.path} className={`${linkClasses} font-mono`}>
          {party.party_number}
        </RacLink>
      ),
    },
    {
      id: "name",
      header: m.list.columns.name,
      mobile: "key",
      mobileCell: (party) => party.country_code,
      cell: (party) => (
        <span className="flex flex-col">
          <span>{party.display_name}</span>
          {party.legal_name !== party.display_name ? <span className="text-xs text-ink-muted">{party.legal_name}</span> : null}
        </span>
      ),
    },
    { id: "roles", header: m.list.columns.roles, cell: (party) => <RoleBadges roles={party.roles} /> },
    { id: "type", header: m.list.columns.customerType, cell: (party) => (party.customer_type ? m.customerTypes[party.customer_type] ?? party.customer_type : dash) },
    { id: "country", header: m.list.columns.country, cell: (party) => party.country_code || dash },
    { id: "currency", header: m.list.columns.currency, cell: (party) => party.default_currency || dash },
    { id: "status", header: m.list.columns.status, mobile: "status", cell: (party) => <PartyStatusPill status={party.status} /> },
    { id: "owner", header: m.list.columns.owner, cell: (party) => party.owner.display_name ?? dash },
    { id: "contact", header: m.list.columns.primaryContact, cell: (party) => party.primary_contact ?? dash },
    { id: "updated", header: m.list.columns.updated, mobile: "meta", cell: (party) => <RelativeTime value={party.updated_at} className="text-ink-muted" /> },
  ];
}

export function PartyList({ state }: { state: PartyListState }) {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const params = partyListParams(state);
  const query = useQuery({ queryKey: partyListQueryKey(state), queryFn: ({ signal }) => fetchParties(params, signal) });
  const go = (next: Partial<PartyListState>) => router.push(partyListHref({ ...state, offset: 0, ...next }) as Parameters<typeof router.push>[0]);
  const canCreate = permissionKeys.has("parties.party.create");

  useScreenContribution(
    query.data
      ? {
          lists: [
            {
              key: "parties",
              rows: query.data.items.map((party, index) => ({ type: "parties.party", id: party.id, version: null, ordinal: state.offset + index + 1 })),
            },
          ],
          filters: {
            q: state.q,
            role: state.role ?? "",
            status: state.status ?? "",
            country_code: state.country_code ?? "",
            customer_type: state.customer_type ?? "",
            include_archived: state.include_archived,
          },
        }
      : null,
  );

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={m.list.title}
        intro={m.list.intro}
        nav={<AreaNav area="sales" label={m.area} leading={SALES_NAV_LEADING} />}
        actions={
          canCreate ? (
            <LinkButton href="/sales/parties/new" variant="primary">
              {m.list.newCustomer}
            </LinkButton>
          ) : null
        }
      />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,2fr)_repeat(3,minmax(0,1fr))_auto] md:items-end">
        <SearchField label={m.list.search} placeholder={m.list.searchPlaceholder} defaultValue={state.q} onSubmit={(q) => go({ q })} onClear={() => go({ q: "" })} />
        <Select
          label={m.list.role}
          options={[{ id: "", label: m.list.anyRole }, ...PARTY_ROLES.map((role) => ({ id: role, label: m.roles[role] ?? role }))]}
          value={state.role ?? ""}
          onChange={(value) => go({ role: PARTY_ROLES.find((role) => role === value) ?? null })}
        />
        <Select
          label={m.list.status}
          options={[{ id: "", label: m.list.anyStatus }, ...PARTY_STATUSES.map((status) => ({ id: status, label: m.status[status] ?? status }))]}
          value={state.status ?? ""}
          onChange={(value) => go({ status: PARTY_STATUSES.find((status) => status === value) ?? null })}
        />
        <Select
          label={m.list.customerType}
          options={[{ id: "", label: m.list.anyType }, ...CUSTOMER_TYPES.map((type) => ({ id: type, label: m.customerTypes[type] ?? type }))]}
          value={state.customer_type ?? ""}
          onChange={(value) => go({ customer_type: CUSTOMER_TYPES.find((type) => type === value) ?? null })}
        />
        <Checkbox isSelected={state.include_archived} onChange={(include_archived) => go({ include_archived })} className="md:mb-1.5">
          {m.list.includeArchived}
        </Checkbox>
      </div>
      {query.isPending ? (
        <Loading label={m.list.loading} />
      ) : query.isError ? (
        <ErrorState error={query.error} what={m.list.loading} onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          caption={m.list.caption}
          hideCaption
          columns={partyColumns()}
          rows={query.data.items}
          rowId={(party) => party.id}
          rowHref={(party) => party.path}
          empty={<EmptyState title={m.list.emptyTitle}>{m.list.empty}</EmptyState>}
          footer={
            <OffsetPagination
              label={m.list.pages}
              total={query.data.total}
              limit={query.data.limit || PARTIES_PAGE_SIZE}
              offset={query.data.offset}
              shown={query.data.items.length}
              control={(offset) => ({ href: partyListHref({ ...state, offset }) })}
            />
          }
        />
      )}
    </div>
  );
}
