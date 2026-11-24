"use client";

import { useQuery } from "@tanstack/react-query";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { fetchParties, PARTIES_PAGE_SIZE } from "@/features/parties/api";
import { partyListHref, partyListParams, partyListQueryKey, type PartyListState } from "@/features/parties/list-state";
import { CUSTOMER_TYPES, PARTY_ROLES, type PartyStatus, type PartySummary } from "@/features/parties/types";
import { useSession } from "@/lib/session/context";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import {
  Avatar,
  Badge,
  Button,
  ButtonLink,
  ChipGroup,
  ChipLink,
  DataTable,
  DateText,
  EmptyState,
  GlassPanel,
  Menu,
  PageSummary,
  Pagination,
  SearchField,
  SegmentedLinks,
  TableFooter,
  type Column,
  type MenuItem,
} from "~/ui";
import { countryName, listViewOf, ROLE_LABEL, STAGE_LABEL, STAGE_TONE, TYPE_LABEL, type CustomerListView } from "./labels";

const VIEW_COPY: Record<CustomerListView, { title: string; lead: string; action: string; noun: string }> = {
  leads: {
    title: "Leads",
    lead: "People who have asked about your products but have not bought or received a sample yet.",
    action: "Add lead",
    noun: "leads",
  },
  customers: {
    title: "Customers",
    lead: "Everyone who has bought from you or has been sent a sample.",
    action: "Add customer",
    noun: "customers",
  },
  all: {
    title: "Leads and customers",
    lead: "Everyone you sell to, from first conversation to repeat order.",
    action: "Add customer",
    noun: "leads and customers",
  },
};

const OTHER_STATUS_COPY: Partial<Record<PartyStatus, { title: string; lead: string }>> = {
  inactive: { title: "Inactive customers", lead: "Customers you no longer trade with. Their history stays here." },
  blocked: { title: "Blocked customers", lead: "Customers on hold. Do not quote or ship until the block is cleared." },
};

const href = (state: Partial<PartyListState>) => partyListHref(state) as Route;

function columns(showStage: boolean): Column<PartySummary>[] {
  const cols: Column<PartySummary>[] = [
    {
      key: "name",
      header: "Name",
      primary: true,
      cell: (party) => (
        <span className="flex min-w-0 items-center gap-3">
          <Avatar name={party.display_name} size="sm" />
          <span className="flex min-w-0 flex-col">
            <span className="t-label truncate text-ink" title={party.display_name}>
              {party.display_name}
            </span>
            <span className="t-caption truncate text-ink-3">
              <span className="lk-mono">{party.party_number}</span>
              {party.customer_type ? ` · ${TYPE_LABEL[party.customer_type] ?? party.customer_type}` : ""}
            </span>
          </span>
        </span>
      ),
    },
  ];
  if (showStage) {
    cols.push({
      key: "stage",
      header: "Stage",
      cell: (party) => (
        <span className="flex flex-wrap items-center gap-1">
          <Badge tone={STAGE_TONE[party.status]} dot>
            {STAGE_LABEL[party.status]}
          </Badge>
          {party.roles
            .filter((role) => role !== "customer")
            .map((role) => (
              <Badge key={role} outline size="sm">
                {ROLE_LABEL[role]}
              </Badge>
            ))}
        </span>
      ),
    });
  }
  cols.push(
    { key: "contact", header: "Main contact", cell: (party) => party.primary_contact ?? <span className="text-ink-3">Not added</span> },
    { key: "country", header: "Country", hideOnMobile: true, cell: (party) => countryName(party.country_code) ?? "" },
    { key: "owner", header: "Looked after by", hideOnMobile: true, cell: (party) => party.owner.display_name ?? "" },
    { key: "updated", header: "Last change", mobileLabel: "Last change", cell: (party) => <DateText value={party.updated_at} style="relative" className="text-ink-3" /> },
  );
  return cols;
}

/** Leads and customers: one list, three views bound to `?status=`. */
export function CustomerList({ state }: { state: PartyListState }) {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const query = useQuery({ queryKey: partyListQueryKey(state), queryFn: ({ signal }) => fetchParties(partyListParams(state), signal) });
  const canCreate = permissionKeys.has("parties.party.create");
  const view = listViewOf(state.status);
  const other = state.status ? OTHER_STATUS_COPY[state.status] : undefined;
  const copy = { ...VIEW_COPY[view], ...other };
  const go = (next: Partial<PartyListState>) => router.push(href({ ...state, offset: 0, ...next }));
  const extraFilters = Boolean(state.role || state.customer_type || state.include_archived || other);
  const filtered = extraFilters || state.q !== "";
  const newHref = (view === "leads" ? "/sales/parties/new?status=prospect" : "/sales/parties/new") as Route;

  useScreenContribution(
    query.data
      ? {
          lists: [{ key: "parties", rows: query.data.items.map((party, index) => ({ type: "parties.party", id: party.id, version: null, ordinal: state.offset + index + 1 })) }],
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

  const tick = (on: boolean) => (on ? ("check" as const) : undefined);
  const filterMenu: MenuItem[] = [
    {
      id: "role",
      section: "Role",
      items: [
        { id: "role-any", label: "Any role", icon: tick(!state.role), href: href({ ...state, role: null, offset: 0 }) },
        ...PARTY_ROLES.map((role) => ({ id: `role-${role}`, label: ROLE_LABEL[role], icon: tick(state.role === role), href: href({ ...state, role, offset: 0 }) })),
      ],
    },
    { id: "sep-type", separator: true },
    {
      id: "type",
      section: "Customer type",
      items: [
        { id: "type-any", label: "Any type", icon: tick(!state.customer_type), href: href({ ...state, customer_type: null, offset: 0 }) },
        ...CUSTOMER_TYPES.map((type) => ({ id: `type-${type}`, label: TYPE_LABEL[type] ?? type, icon: tick(state.customer_type === type), href: href({ ...state, customer_type: type, offset: 0 }) })),
      ],
    },
    { id: "sep-status", separator: true },
    {
      id: "status",
      section: "No longer active",
      items: [
        { id: "status-inactive", label: "Inactive", icon: tick(state.status === "inactive"), href: href({ ...state, status: state.status === "inactive" ? null : "inactive", offset: 0 }) },
        { id: "status-blocked", label: "Blocked", icon: tick(state.status === "blocked"), href: href({ ...state, status: state.status === "blocked" ? null : "blocked", offset: 0 }) },
        {
          id: "archived",
          label: "Include archived",
          description: "Records the team has put away",
          icon: tick(state.include_archived),
          href: href({ ...state, include_archived: !state.include_archived, offset: 0 }),
        },
      ],
    },
  ];

  const limit = query.data?.limit || PARTIES_PAGE_SIZE;
  const total = query.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / limit));
  const page = Math.floor((query.data?.offset ?? state.offset) / limit) + 1;

  return (
    <Page>
      <PageHeader
        eyebrow="Sales"
        title={copy.title}
        lead={copy.lead}
        actions={
          canCreate ? (
            <ButtonLink href={newHref} iconLeft="plus">
              {copy.action}
            </ButtonLink>
          ) : null
        }
      />

      <div className="rise flex min-w-0 flex-col gap-3" style={{ "--i": 1 } as React.CSSProperties}>
        <div className="flex min-w-0 flex-wrap items-center gap-3">
          <SegmentedLinks
            label="Show"
            glass
            value={other ? "" : view}
            options={[
              { value: "leads", label: "Leads", href: href({ ...state, status: "prospect", offset: 0 }) },
              { value: "customers", label: "Customers", href: href({ ...state, status: "active", offset: 0 }) },
              { value: "all", label: "All", href: href({ ...state, status: null, offset: 0 }) },
            ]}
          />
          <SearchField
            key={state.q}
            className="min-w-0 flex-1 basis-64"
            label={`Search ${copy.noun}`}
            placeholder="Name, number or contact"
            defaultValue={state.q}
            onSubmit={(q) => go({ q })}
            onChange={(q) => {
              if (q === "" && state.q !== "") go({ q: "" });
            }}
          />
          <Menu
            label="More filters"
            items={filterMenu}
            placement="bottom end"
            trigger={
              <Button variant="secondary" iconLeft="filter">
                Filters
              </Button>
            }
          />
        </div>
        {extraFilters ? (
          <ChipGroup label="Filters in use">
            {other && state.status ? (
              <ChipLink href={href({ ...state, status: null, offset: 0 })} selected icon="x">
                {STAGE_LABEL[state.status]}
              </ChipLink>
            ) : null}
            {state.role ? (
              <ChipLink href={href({ ...state, role: null, offset: 0 })} selected icon="x">
                {ROLE_LABEL[state.role]}
              </ChipLink>
            ) : null}
            {state.customer_type ? (
              <ChipLink href={href({ ...state, customer_type: null, offset: 0 })} selected icon="x">
                {TYPE_LABEL[state.customer_type] ?? state.customer_type}
              </ChipLink>
            ) : null}
            {state.include_archived ? (
              <ChipLink href={href({ ...state, include_archived: false, offset: 0 })} selected icon="x">
                Archived included
              </ChipLink>
            ) : null}
          </ChipGroup>
        ) : null}
      </div>

      {query.isError ? (
        <ErrorBlock error={query.error} what={copy.title} onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise" style={{ "--i": 2 } as React.CSSProperties}>
          <DataTable
            label={copy.title}
            columns={columns(view === "all")}
            rows={query.data?.items ?? []}
            rowKey={(party) => party.id}
            rowHref={(party) => party.path as Route}
            loading={query.isPending}
            skeletonRows={8}
            empty={
              filtered ? (
                <EmptyState
                  compact
                  icon="search"
                  title="Nothing matches"
                  text="No one fits this search and these filters. Clear them to see the whole list."
                  actions={
                    <ButtonLink variant="secondary" size="sm" href={href({ status: other ? null : state.status })}>
                      Clear search and filters
                    </ButtonLink>
                  }
                />
              ) : view === "leads" ? (
                <EmptyState
                  icon="userPlus"
                  title="No leads yet"
                  text="Add the first person who has asked about your products. They become a customer when they buy or receive a sample."
                  actions={
                    canCreate ? (
                      <ButtonLink href={newHref} iconLeft="plus">
                        Add lead
                      </ButtonLink>
                    ) : undefined
                  }
                />
              ) : (
                <EmptyState
                  icon="users"
                  title="No customers yet"
                  text="Add your first customer, then attach their quotations, samples and orders to one profile."
                  actions={
                    canCreate ? (
                      <ButtonLink href={newHref} iconLeft="plus">
                        Add customer
                      </ButtonLink>
                    ) : undefined
                  }
                />
              )
            }
            footer={
              query.data && total > 0 ? (
                <TableFooter
                  left={<PageSummary from={query.data.offset + 1} to={query.data.offset + query.data.items.length} total={total} noun={copy.noun} />}
                  right={pages > 1 ? <Pagination label={`${copy.title} pages`} page={page} pages={pages} hrefFor={(target) => href({ ...state, offset: (target - 1) * limit })} /> : null}
                />
              ) : undefined
            }
          />
        </GlassPanel>
      )}
    </Page>
  );
}
