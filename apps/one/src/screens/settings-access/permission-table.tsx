"use client";

import { useState } from "react";
import type { EffectiveKey } from "@/app/(app)/settings/_lib/types";
import { Badge, DataTable, EmptyState, GlassPanel, SearchField, type Column } from "~/ui";
import { keyLabel, SCOPE_LABEL } from "./labels";

const COLUMNS: Column<EffectiveKey>[] = [
  {
    key: "key",
    header: "Permission",
    primary: true,
    cell: (row) => (
      <span className="flex min-w-0 flex-col">
        <span className="t-label text-ink">{keyLabel(row.key)}</span>
        <span className="t-code-sm lk-mono break-all text-ink-3">{row.key}</span>
      </span>
    ),
  },
  {
    key: "scope",
    header: "Reach",
    width: "180px",
    cell: (row) => (row.scope ? <Badge outline>{SCOPE_LABEL[row.scope] ?? row.scope}</Badge> : <span className="text-ink-3">Not in effect</span>),
  },
  {
    key: "why",
    header: "Where it comes from",
    cell: (row) => <span className="text-ink-2">{row.sources.map((source) => source.label).join("; ") || "No source recorded"}</span>,
  },
];

/** A list of permissions with their reach and source, narrowed by typing part of a key. */
export function PermissionTable({ rows, label, emptyText }: { rows: readonly EffectiveKey[]; label: string; emptyText: string }) {
  const [filter, setFilter] = useState("");
  const needle = filter.trim().toLowerCase();
  const shown = needle ? rows.filter((row) => row.key.includes(needle) || keyLabel(row.key).toLowerCase().includes(needle)) : rows;
  return (
    <div className="flex min-w-0 flex-col gap-3">
      {rows.length > 8 ? (
        <SearchField className="max-w-md" label={`Filter ${label.toLowerCase()}`} placeholder="Filter by key, for example sales.quote" value={filter} onChange={setFilter} />
      ) : null}
      <GlassPanel padding="none">
        <DataTable
          label={label}
          columns={COLUMNS}
          rows={shown}
          rowKey={(row) => row.key}
          maxHeight="640px"
          empty={
            <EmptyState
              compact
              icon={needle ? "search" : "key"}
              title={needle ? "No permission matches" : "Nothing here"}
              text={needle ? "Try a shorter part of the key, such as quote or stock." : emptyText}
            />
          }
        />
      </GlassPanel>
      {needle && shown.length > 0 ? (
        <p className="t-caption text-ink-3" role="status">
          {shown.length} of {rows.length} shown
        </p>
      ) : null}
    </div>
  );
}
