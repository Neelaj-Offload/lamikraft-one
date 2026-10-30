"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { StatusPill } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { OffsetPagination } from "@/components/ui/data-table";
import { LocalDateTime } from "@/components/ui/format";
import { Link } from "@/components/ui/link";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { toast } from "@/components/ui/toast";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { createCommandKeys, commandSignature } from "@/lib/api/command-keys";
import { conflictFromError } from "@/lib/api/errors";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { useOnline } from "@/lib/hooks";
import { briefingMessages } from "@/messages/briefing";
import { salesMessages as m } from "@/messages/sales";
import { fetchCustomerMessages, markMessageReplied, QUOTES_PAGE_SIZE } from "./api";
import { messageListHref, type MessageListState } from "./list-state";
import type { CustomerMessage } from "./types";

export { messageListHref, messageListStateFrom, type MessageFilter, type MessageListState } from "./list-state";
import { problemDescription } from "./use-quote-command";

/** "Mark replied" appears only when the server offers it in `allowed_transitions`. */
export function canMarkReplied(message: Pick<CustomerMessage, "allowed_transitions">): boolean {
  return message.allowed_transitions.some((transition) => transition.action === "mark_replied");
}

export function CustomerMessageList({ state }: { state: MessageListState }) {
  const router = useRouter();
  const online = useOnline();
  const queryClient = useQueryClient();
  const params = { status: state.status === "all" ? null : state.status, offset: state.offset };
  const query = useQuery({ queryKey: queryKeys.sales.messages(params), queryFn: ({ signal }) => fetchCustomerMessages(params, signal) });
  const [pending, setPending] = useState<string | null>(null);
  const [commandKeys] = useState(() => createCommandKeys());
  const offline = online ? null : briefingMessages.offlineActions;

  useScreenContribution(
    query.data
      ? {
          lists: [
            {
              key: "customer_messages",
              rows: query.data.items.map((row, index) => ({ type: "sales.customer_message", id: row.id, version: row.version, ordinal: state.offset + index + 1 })),
            },
          ],
          filters: { status: state.status },
        }
      : null,
  );

  const markReplied = async (message: CustomerMessage) => {
    if (pending || offline) return;
    const signature = commandSignature(message.id, message.version, "mark_replied");
    const attempt = commandKeys.attempt(signature, () => null);
    setPending(message.id);
    try {
      await markMessageReplied(message, attempt.key);
      commandKeys.settle(signature);
      toast.success(m.messages.markedReplied);
    } catch (error) {
      commandKeys.settle(signature, error);
      if (conflictFromError(error)) toast.warning(m.messages.changed);
      else toast.error(m.messages.failed, { description: problemDescription(error) });
    } finally {
      setPending(null);
      await Promise.all(invalidationMap["sales.message_replied"].map((queryKey) => queryClient.invalidateQueries({ queryKey })));
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">{m.messages.title}</h1>
      <Select
        label={m.messages.filter}
        className="max-w-xs"
        options={[
          { id: "received", label: m.messages.waiting },
          { id: "replied", label: m.messages.replied },
          { id: "all", label: m.messages.all },
        ]}
        value={state.status}
        onChange={(value) =>
          router.push(messageListHref({ status: value === "replied" || value === "all" ? value : "received", offset: 0 }) as Parameters<typeof router.push>[0])
        }
      />
      {query.isPending ? (
        <Loading label="customer messages" />
      ) : query.isError ? (
        <ErrorState error={query.error} what="the customer messages" onRetry={() => void query.refetch()} />
      ) : query.data.items.length === 0 ? (
        <EmptyState title={m.messages.emptyTitle}>{m.messages.empty}</EmptyState>
      ) : (
        <>
          <ul className="flex flex-col divide-y border-y" aria-label={m.messages.caption}>
            {query.data.items.map((message) => (
              <li key={message.id} className="flex flex-col gap-2 py-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="flex min-w-0 flex-col gap-0.5">
                    <h2 className="font-semibold text-ink">{message.subject ?? m.messages.noSubject}</h2>
                    <p className="text-sm text-ink-muted">
                      {message.party.display_name}
                      {message.contact_name ? ` · ${message.contact_name}` : null} · {m.channels[message.channel] ?? message.channel} ·{" "}
                      <LocalDateTime value={message.received_at} />
                    </p>
                  </div>
                  <StatusPill tone={message.status === "replied" ? "success" : "warning"}>
                    {message.status === "replied" ? m.messages.replied : m.messages.waiting}
                  </StatusPill>
                </div>
                {/* External text: plain text only. */}
                <p className="line-clamp-4 whitespace-pre-wrap text-ink">{message.body}</p>
                <div className="flex flex-wrap items-center gap-3">
                  {message.quote_id ? (
                    <Link href={`/sales/quotes/${encodeURIComponent(message.quote_id)}`} className="text-sm">
                      {m.messages.quote} {message.quote_number ?? ""}
                    </Link>
                  ) : null}
                  {message.enquiry_id ? (
                    <Link href={`/sales/enquiries/${encodeURIComponent(message.enquiry_id)}`} className="text-sm">
                      {m.messages.enquiry}
                    </Link>
                  ) : null}
                  {message.replied_at ? (
                    <span className="text-sm text-ink-muted">
                      {m.messages.repliedAt} <LocalDateTime value={message.replied_at} />
                    </span>
                  ) : null}
                  {canMarkReplied(message) ? (
                    <Button
                      variant="secondary"
                      size="sm"
                      isPending={pending === message.id}
                      onPress={() => void markReplied(message)}
                      {...unavailableWhen(offline)}
                    >
                      {m.messages.markReplied}
                    </Button>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
          <OffsetPagination
            label={m.messages.pages}
            total={query.data.total}
            limit={query.data.limit || QUOTES_PAGE_SIZE}
            offset={query.data.offset}
            shown={query.data.items.length}
            control={(offset) => ({ href: messageListHref({ ...state, offset }) })}
          />
        </>
      )}
    </div>
  );
}
