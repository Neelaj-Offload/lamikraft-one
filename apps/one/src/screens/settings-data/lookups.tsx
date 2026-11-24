"use client";

import { useRouter } from "next/navigation";
import { lookupExportHref } from "@/features/catalogue/api";
import { lookupHref, type LookupListState } from "@/features/catalogue/lookup-state";
import type { LookupRead } from "@/features/catalogue/types";
import { formatCount } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { IMPORTS_RUN, LOOKUPS_READ, useLookups, useLookupTypes } from "~/data/settings-data";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock, NotPermitted } from "~/shell/states";
import { ButtonLink, DataTable, EmptyState, GlassPanel, SearchField, Select, type Column } from "~/ui";
import { asRoute, Mono, OffsetPager, Quiet, SETTINGS_CRUMBS } from "./shared";

/** The reference tables carried over from the old system: read, search, export. Type, search and page live in the URL. */

const ANY = "any";
const PAGE_SIZE = 50;
const none = <Quiet>None</Quiet>;

const columns: Column<LookupRead>[] = [
  { key: "key1", header: "Key", primary: true, cell: (row) => <Mono>{row.key_1}</Mono> },
  { key: "type", header: "Type", mobileLabel: "Type", cell: (row) => row.lookup_type },
  { key: "key2", header: "Second key", mobileLabel: "Second key", hideOnMobile: true, cell: (row) => (row.key_2 ? <Mono>{row.key_2}</Mono> : none) },
  { key: "value1", header: "Value", mobileLabel: "Value", cell: (row) => row.value_1 ?? none },
  { key: "value2", header: "Second value", mobileLabel: "Second value", hideOnMobile: true, cell: (row) => row.value_2 ?? none },
  { key: "notes", header: "Notes", mobileLabel: "Notes", hideOnMobile: true, cell: (row) => row.notes ?? none },
];

export function Lookups({ state }: { state: LookupListState }) {
  const router = useRouter();
  const { permissionKeys, zone } = useSession();
  const allowed = permissionKeys.has(LOOKUPS_READ);
  const types = useLookupTypes(allowed);
  const rows = useLookups(state, allowed);
  const data = rows.data;

  if (!allowed) {
    return (
      <Page>
        <PageHeader breadcrumb={SETTINGS_CRUMBS} title="Lookup reference" />
        <NotPermitted what="Lookup reference" icon="database" />
      </Page>
    );
  }

  const go = (patch: Partial<LookupListState>) => router.push(asRoute(lookupHref({ ...state, offset: 0, ...patch })));
  const filtered = Boolean(state.q || state.lookupType);

  return (
    <Page>
      <PageHeader
        breadcrumb={SETTINGS_CRUMBS}
        title="Lookup reference"
        lead="Reference tables carried over from the old system, kept to look things up and export. No rule in Lamikraft One reads them."
        actions={
          <ButtonLink external href={lookupExportHref(state.lookupType, state.q)} download variant="secondary" iconLeft="download">
            Export as CSV
          </ButtonLink>
        }
      />

      <div className="flex min-w-0 flex-wrap items-center gap-3">
        <SearchField
          key={state.q}
          label="Search keys and values"
          placeholder="Search keys and values"
          defaultValue={state.q}
          onSubmit={(q) => go({ q: q.trim() })}
          onChange={(value) => {
            if (value === "" && state.q) go({ q: "" });
          }}
          className="min-w-0 flex-1 basis-64"
        />
        <Select
          label="Type"
          hideLabel
          className="w-64 max-w-full"
          options={[
            { value: ANY, label: "All types" },
            ...(types.data ?? []).map((type) => ({ value: type.lookup_type, label: type.lookup_type, description: `${formatCount(type.count, zone.locale)} rows` })),
          ]}
          value={state.lookupType ?? ANY}
          onChange={(value) => go({ lookupType: value === ANY ? null : value })}
        />
      </div>

      {rows.isError && !data ? (
        <ErrorBlock error={rows.error} what="Lookup rows" onRetry={() => void rows.refetch()} />
      ) : (
        <GlassPanel padding="none">
          <DataTable
            label="Lookup rows"
            columns={columns}
            rows={data?.items ?? []}
            rowKey={(row) => row.id}
            loading={rows.isPending}
            skeletonRows={8}
            dense
            empty={
              filtered ? (
                <EmptyState
                  compact
                  icon="search"
                  title="No row matches"
                  text="Loosen the search or choose all types."
                  actions={
                    <ButtonLink href="/settings/lookups" variant="secondary" size="sm">
                      Clear search and type
                    </ButtonLink>
                  }
                />
              ) : (
                <EmptyState
                  icon="database"
                  title="Import your lookup reference sheet"
                  text="Nothing has been brought over yet. The lookup reference import fills this list."
                  actions={
                    permissionKeys.has(IMPORTS_RUN) ? (
                      <ButtonLink href="/settings/imports/new" iconLeft="upload">
                        Start an import
                      </ButtonLink>
                    ) : undefined
                  }
                />
              )
            }
          />
        </GlassPanel>
      )}

      {data ? <OffsetPager data={data} noun="rows" label="Lookup pages" fallbackLimit={PAGE_SIZE} hrefFor={(offset) => asRoute(lookupHref({ ...state, offset }))} /> : null}
    </Page>
  );
}
