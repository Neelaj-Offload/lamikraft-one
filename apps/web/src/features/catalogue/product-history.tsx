"use client";

import { useQuery } from "@tanstack/react-query";
import { LocalDateTime } from "@/components/ui/format";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { queryKeys } from "@/lib/api/query-keys";
import { fetchHistory } from "./api";

/** The product's audit trail (catalogue lane): who changed what, when, and why. */
export function ProductHistory({ productId }: { productId: string }) {
  const history = useQuery({ queryKey: queryKeys.catalogue.history(productId), queryFn: ({ signal }) => fetchHistory(productId, signal) });
  if (history.isPending) return <Loading label="history" />;
  if (history.isError) return <ErrorState error={history.error} what="the history" onRetry={() => void history.refetch()} compact />;
  if (!history.data.items.length) return <EmptyState title="No recorded changes" />;
  return (
    <ol className="flex flex-col divide-y rounded-md border">
      {history.data.items.map((entry) => (
        <li key={entry.id} className="flex flex-col gap-1 px-4 py-3 text-sm">
          <span className="font-semibold">{entry.action.replace(/^catalogue\./, "").replace(/[._]/g, " ")}</span>
          <span className="text-ink-muted">
            <LocalDateTime value={entry.occurred_at} /> · {entry.actor_name ?? entry.actor_type}
            {entry.changed_fields.length ? ` · ${entry.changed_fields.join(", ")}` : ""}
            {entry.reason ? ` · ${entry.reason}` : ""}
          </span>
        </li>
      ))}
    </ol>
  );
}
