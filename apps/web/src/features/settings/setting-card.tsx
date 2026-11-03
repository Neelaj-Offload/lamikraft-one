"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { LocalDateTime } from "@/components/ui/format";
import { KeyValueGrid, type KeyValue } from "@/components/ui/key-value-grid";
import { SectionCard } from "@/components/ui/section-card";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { queryKeys } from "@/lib/api/query-keys";
import { settingsMessages } from "@/messages/settings";
import { fetchSettingRevisions } from "./api";
import { SettingEditor } from "./setting-editor";
import { flattenValue } from "./setting-model";
import type { SettingRead, SettingRevision } from "./types";

const m = settingsMessages.company;

/** The flattened value as grid rows: booleans Yes/No, absent values a muted "Not configured". */
/** Settings whose values are restricted (masked in screenshots for the assistant). */
export const RESTRICTED_SETTINGS: ReadonlySet<string> = new Set(["bank_details"]);

export function settingItems(setting: Pick<SettingRead, "value" | "redacted_fields" | "not_configured_fields">): KeyValue[] {
  const missing = new Set(setting.not_configured_fields);
  return flattenValue(setting.value, setting.redacted_fields).map((row) => {
    const absent = row.value === null || missing.has(row.path);
    return {
      term: row.term,
      description: absent ? (
        <span className="text-ink-muted">{m.notConfiguredValue}</span>
      ) : typeof row.value === "boolean" ? (
        row.value ? m.yes : m.no
      ) : (
        row.value
      ),
      mono: row.mono && !absent,
    };
  });
}

function RevisionRows({ revisions }: { revisions: SettingRevision[] }) {
  if (revisions.length === 0) return <p className="text-sm text-ink-muted">{m.historyEmpty}</p>;
  const c = m.historyColumns;
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">{m.history}</caption>
        <thead>
          <tr className="border-b">
            <th scope="col" className="px-3 py-2 text-start text-xs font-semibold tracking-[0.04em] text-ink-muted uppercase">
              {c.version}
            </th>
            <th scope="col" className="px-3 py-2 text-start text-xs font-semibold tracking-[0.04em] text-ink-muted uppercase">
              {c.changedAt}
            </th>
            <th scope="col" className="px-3 py-2 text-start text-xs font-semibold tracking-[0.04em] text-ink-muted uppercase">
              {c.changedBy}
            </th>
            <th scope="col" className="px-3 py-2 text-start text-xs font-semibold tracking-[0.04em] text-ink-muted uppercase">
              {c.reason}
            </th>
          </tr>
        </thead>
        <tbody>
          {revisions.map((revision) => (
            <tr key={revision.version} className="border-b last:border-b-0">
              <th scope="row" className="px-3 py-2 text-start font-semibold text-ink tabular">
                {revision.version}
              </th>
              <td className="px-3 py-2 text-ink">
                <LocalDateTime value={revision.changed_at} />
              </td>
              <td className="px-3 py-2 font-mono text-xs text-ink [overflow-wrap:anywhere]">{revision.changed_by ?? "—"}</td>
              <td className="px-3 py-2 text-ink">{revision.change_reason ?? <span className="text-ink-muted">{m.noReason}</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function History({ settingKey }: { settingKey: string }) {
  const query = useQuery({ queryKey: queryKeys.org.settingRevisions(settingKey), queryFn: ({ signal }) => fetchSettingRevisions(settingKey, signal) });
  if (query.isPending) return <Loading label={m.historyWhat} variant="inline" />;
  if (query.isError) return <ErrorState error={query.error} what={m.historyWhat} onRetry={() => void query.refetch()} headingLevel={3} compact backToToday={false} />;
  return <RevisionRows revisions={query.data} />;
}

/** One company setting: its value as a grid, Edit when the server allows it, and a history disclosure. */
export function SettingCard({ setting }: { setting: SettingRead }) {
  const [editing, setEditing] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const items = settingItems(setting);
  const canUpdate = setting.capabilities.update?.allowed === true;
  const historyId = `setting-history-${setting.key}`;

  return (
    <SectionCard
      title={setting.description}
      description={
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="font-mono text-ink-muted">{setting.key}</span>
          <span aria-hidden="true">·</span>
          <span>{m.version(setting.version)}</span>
          {setting.updated_at ? (
            <>
              <span aria-hidden="true">·</span>
              <span>
                {m.updated} <LocalDateTime value={setting.updated_at} />
              </span>
            </>
          ) : null}
          {setting.configured ? null : <Badge tone="warning">{m.notConfigured}</Badge>}
        </span>
      }
      actions={
        <>
          <Button size="sm" onPress={() => setHistoryOpen((open) => !open)} aria-expanded={historyOpen} aria-controls={historyId}>
            {historyOpen ? m.hideHistory : m.history}
          </Button>
          {canUpdate ? (
            <Button size="sm" variant="primary" onPress={() => setEditing(true)}>
              {m.edit}
            </Button>
          ) : null}
        </>
      }
    >
      {items.length === 0 ? (
        <EmptyState title={m.empty} headingLevel={3} />
      ) : (
        // restricted values (bank details) are blacked out in masked screenshots (ai-routing §4.2)
        <div data-restricted={RESTRICTED_SETTINGS.has(setting.key) ? "true" : undefined}>
          <KeyValueGrid items={items} />
        </div>
      )}
      {setting.redacted_fields.length > 0 ? <p className="text-sm text-ink-muted">{m.redacted(setting.redacted_fields.length)}</p> : null}
      {historyOpen ? (
        <div id={historyId} className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold text-ink">{m.history}</h3>
          <History settingKey={setting.key} />
        </div>
      ) : (
        <div id={historyId} hidden />
      )}
      {editing ? <SettingEditor key={setting.version} setting={setting} isOpen={editing} onClose={() => setEditing(false)} /> : null}
    </SectionCard>
  );
}
