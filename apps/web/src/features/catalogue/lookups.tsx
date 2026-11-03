"use client";

import { SettingsAreaNav } from "@/features/settings/settings-hub";
import { PageHeader } from "@/components/ui/page-header";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { DataTable, OffsetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { LinkButton } from "@/components/ui/link";
import { SearchField } from "@/components/ui/search-field";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading, PermissionDenied } from "@/components/ui/states";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { fetchLookups, fetchLookupTypes, lookupExportHref } from "./api";
import type { LookupRead } from "./types";
import { lookupHref, type LookupListState } from "./lookup-state";

export { lookupStateFrom, lookupHref, type LookupListState } from "./lookup-state";

const columns: DataTableColumn<LookupRead>[] = [
  { id: "type", header: "Type", mobile: "meta", cell: (r) => r.lookup_type },
  { id: "key1", header: "Key 1", isRowHeader: true, mobile: "title", cell: (r) => <span className="font-mono">{r.key_1}</span> },
  { id: "key2", header: "Key 2", cell: (r) => r.key_2 || "—" },
  { id: "value1", header: "Value 1", mobile: "key", cell: (r) => r.value_1 ?? "—" },
  { id: "value2", header: "Value 2", cell: (r) => r.value_2 ?? "—" },
  { id: "notes", header: "Notes", cell: (r) => r.notes ?? "—" },
];

/** Lookup reference browser (FG-LKP-03, LM-34): read-only legacy reference rows, filters in the URL, safe CSV export. */
export function LookupBrowser({ state }: { state: LookupListState }) {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const types = useQuery({ queryKey: queryKeys.catalogue.lookupTypes(), queryFn: ({ signal }) => fetchLookupTypes(signal) });
  const rows = useQuery({
    queryKey: queryKeys.catalogue.lookups({ type: state.lookupType, q: state.q, offset: state.offset }),
    queryFn: ({ signal }) => fetchLookups(state, signal),
  });
  if (!permissionKeys.has("catalogue.lookup.read")) return <PermissionDenied area="Lookup reference" />;
  const go = (next: Partial<LookupListState>) => router.push(lookupHref({ ...state, offset: 0, ...next }) as Parameters<typeof router.push>[0]);
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Lookup reference"
        intro="Legacy reference data, kept for lookup and export. No business rule uses it."
        nav={<SettingsAreaNav currentId="settings-lookups" />}
        actions={
          <LinkButton href={lookupExportHref(state.lookupType, state.q)} download>
            Export CSV
          </LinkButton>
        }
      />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)] md:items-end">
        <Select
          label="Type"
          options={[{ id: "", label: "All types" }, ...(types.data ?? []).map((t) => ({ id: t.lookup_type, label: t.lookup_type, detail: String(t.count) }))]}
          value={state.lookupType ?? ""}
          onChange={(v) => go({ lookupType: v || null })}
        />
        <SearchField label="Search keys and values" defaultValue={state.q} onSubmit={(q) => go({ q })} onClear={() => go({ q: "" })} />
      </div>
      {rows.isPending ? (
        <Loading label="lookups" />
      ) : rows.isError ? (
        <ErrorState error={rows.error} what="the lookup rows" onRetry={() => void rows.refetch()} />
      ) : (
        <DataTable
          caption="Lookup rows"
          hideCaption
          columns={columns}
          rows={rows.data.items}
          rowId={(r) => r.id}
          empty={<EmptyState title="No lookup rows">Import the lookup_reference sheet to fill this list.</EmptyState>}
          footer={
            <OffsetPagination
              label="Lookup pages"
              total={rows.data.total}
              limit={rows.data.limit || 50}
              offset={rows.data.offset}
              shown={rows.data.items.length}
              control={(offset) => ({ href: lookupHref({ ...state, offset }) })}
            />
          }
        />
      )}
    </div>
  );
}
