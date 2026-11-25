"use client";

import { useQuery } from "@tanstack/react-query";
import type { Route } from "next";
import { useEffect, useRef, useState } from "react";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { fetchCustomerMessages, markMessageReplied, QUOTES_PAGE_SIZE } from "@/features/sales/api";
import { messageListHref, type MessageFilter, type MessageListState } from "@/features/sales/list-state";
import { useResourceCommand } from "@/features/sales/resource-command";
import type { CustomerMessage } from "@/features/sales/types";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import { Avatar, Badge, Banner, Button, DateText, EmptyState, GlassPanel, Icon, PageSummary, Pagination, SegmentedLinks, Skeleton, SkeletonText, TextLink } from "~/ui";
import { stagger } from "../customers/labels";
import { CHANNEL_ICON, channelLabel } from "../enquiries/labels";

const href = (state: Partial<MessageListState>) => messageListHref(state) as Route;

const VIEW_COPY: Record<MessageFilter, { lead: string; emptyTitle: string; emptyText: string; noun: string }> = {
  received: {
    lead: "What customers have written and nobody has answered yet, newest first.",
    emptyTitle: "No one is waiting",
    emptyText: "Every customer message has a reply. New ones appear here as they arrive.",
    noun: "messages waiting",
  },
  replied: {
    lead: "Messages the team has already answered.",
    emptyTitle: "No replies recorded yet",
    emptyText: "A message moves here when someone marks it as replied.",
    noun: "replied messages",
  },
  all: {
    lead: "Everything customers have written to you, answered or not.",
    emptyTitle: "No messages yet",
    emptyText: "Messages from email, WhatsApp, the phone and the website are filed here against the customer.",
    noun: "messages",
  },
};

/** "Mark as replied" appears only when the server offers it in `allowed_transitions`. */
function canMarkReplied(message: Pick<CustomerMessage, "allowed_transitions">): boolean {
  return message.allowed_transitions.some((transition) => transition.action === "mark_replied");
}

const LONG_BODY = 320;

function MessageRow({
  message,
  index,
  focused,
  canOpenCustomer,
  onReply,
  replying,
  offline,
}: {
  message: CustomerMessage;
  index: number;
  focused: boolean;
  canOpenCustomer: boolean;
  onReply: (message: CustomerMessage) => void;
  replying: boolean;
  offline: boolean;
}) {
  const ref = useRef<HTMLLIElement>(null);
  const [expanded, setExpanded] = useState(focused);
  const long = message.body.length > LONG_BODY || message.body.split("\n").length > 4;
  const waiting = message.status !== "replied";

  useEffect(() => {
    if (focused) ref.current?.scrollIntoView({ block: "center" });
  }, [focused]);

  return (
    <li
      ref={ref}
      aria-current={focused ? "true" : undefined}
      className="rise-plain flex min-w-0 gap-4 border-line px-5 py-5 [&:not(:first-child)]:border-t md:px-6"
      style={{ ...stagger(index), ...(focused ? { boxShadow: "inset 3px 0 0 var(--gold)" } : null) }}
    >
      <div className="hidden flex-none sm:block">
        <Avatar name={message.party.display_name} />
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <p className="min-w-0">
            {canOpenCustomer ? (
              <TextLink href={`/sales/parties/${encodeURIComponent(message.party.id)}` as Route} className="t-label">
                {message.party.display_name}
              </TextLink>
            ) : (
              <span className="t-label text-ink">{message.party.display_name}</span>
            )}
            {message.contact_name ? <span className="t-body-sm text-ink-3"> · {message.contact_name}</span> : null}
          </p>
          <p className="t-caption flex flex-none items-center gap-2 text-ink-3">
            <Icon name={CHANNEL_ICON[message.channel] ?? "message"} size={14} />
            {channelLabel(message.channel)}
            <span aria-hidden="true">·</span>
            <DateText value={message.received_at} style="dayTime" />
          </p>
        </div>

        <h2 className="t-h4 text-ink [overflow-wrap:anywhere]">{message.subject ?? "No subject"}</h2>
        {/* External text: plain text only, never markup or links. */}
        <p className={`t-body whitespace-pre-wrap text-ink-2 [overflow-wrap:anywhere] ${long && !expanded ? "line-clamp-3" : ""}`}>{message.body}</p>
        {long ? (
          <div>
            <Button variant="ghost" size="sm" onPress={() => setExpanded((open) => !open)} aria-expanded={expanded}>
              {expanded ? "Show less" : "Read the whole message"}
            </Button>
          </div>
        ) : null}

        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2 pt-1">
          <Badge tone={waiting ? "amber" : "leaf"} icon={waiting ? "clock" : "check"}>
            {waiting ? "Waiting for a reply" : "Replied"}
          </Badge>
          {message.replied_at ? (
            <span className="t-caption text-ink-3">
              Answered <DateText value={message.replied_at} style="dayTime" />
            </span>
          ) : null}
          {message.quote_id ? (
            <TextLink href={`/sales/quotes/${encodeURIComponent(message.quote_id)}` as Route} className="t-body-sm">
              Quotation {message.quote_number ?? ""}
            </TextLink>
          ) : null}
          {message.enquiry_id ? (
            <TextLink href={`/sales/enquiries/${encodeURIComponent(message.enquiry_id)}` as Route} className="t-body-sm">
              Their enquiry
            </TextLink>
          ) : null}
          {canMarkReplied(message) ? (
            <span className="ml-auto">
              <Button variant="secondary" size="sm" iconLeft="check" loading={replying} isDisabled={offline} onPress={() => onReply(message)}>
                Mark as replied
              </Button>
            </span>
          ) : null}
        </div>
      </div>
    </li>
  );
}

/** Customer messages as an inbox: waiting first by default, one message per row, one action. */
export function MessageInbox({ state, focusId }: { state: MessageListState; focusId: string | null }) {
  const { permissionKeys } = useSession();
  const params = { status: state.status === "all" ? null : state.status, offset: state.offset };
  const query = useQuery({ queryKey: queryKeys.sales.messages(params), queryFn: ({ signal }) => fetchCustomerMessages(params, signal) });
  const commands = useResourceCommand("customer-messages", invalidationMap["sales.message_replied"]);
  const copy = VIEW_COPY[state.status];
  const canOpenCustomer = permissionKeys.has("parties.party.read");

  useScreenContribution(
    query.data
      ? {
          lists: [{ key: "customer_messages", rows: query.data.items.map((row, index) => ({ type: "sales.customer_message", id: row.id, version: row.version, ordinal: state.offset + index + 1 })) }],
          filters: { status: state.status },
        }
      : null,
  );

  const reply = (message: CustomerMessage) =>
    void commands.run(`reply:${message.id}`, [message.version], (key) => markMessageReplied(message, key), {
      done: `Marked as replied: ${message.party.display_name}`,
      failed: "The message was not marked as replied",
      conflictMessage: "This message changed since you opened it. The latest version is showing.",
    });

  const limit = query.data?.limit || QUOTES_PAGE_SIZE;
  const total = query.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / limit));
  const page = Math.floor((query.data?.offset ?? state.offset) / limit) + 1;

  return (
    <Page width="reading">
      <PageHeader eyebrow="Sales" title="Customer messages" lead={copy.lead} />

      <div className="rise" style={stagger(1)}>
        <SegmentedLinks
          label="Show"
          glass
          value={state.status}
          options={[
            { value: "received", label: "Waiting", href: href({ status: "received" }) },
            { value: "replied", label: "Replied", href: href({ status: "replied" }) },
            { value: "all", label: "All", href: href({ status: "all" }) },
          ]}
        />
      </div>

      {commands.offline ? <Banner tone="amber" title="You are offline.">You can read messages. Reconnect to mark one as replied.</Banner> : null}

      {query.isPending ? (
        <GlassPanel padding="none" role="status" aria-label="Loading messages">
          {[0, 1, 2].map((row) => (
            <div key={row} className="flex gap-4 border-line px-6 py-5 [&:not(:first-child)]:border-t">
              <Skeleton circle width={40} height={40} />
              <div className="flex flex-1 flex-col gap-3">
                <Skeleton width="35%" height={14} />
                <SkeletonText lines={2} />
              </div>
            </div>
          ))}
        </GlassPanel>
      ) : query.isError ? (
        <ErrorBlock error={query.error} what="Customer messages" onRetry={() => void query.refetch()} />
      ) : query.data.items.length === 0 ? (
        <GlassPanel className="rise" style={stagger(2)}>
          <EmptyState icon={state.status === "received" ? "checkCircle" : "message"} title={copy.emptyTitle} text={copy.emptyText} />
        </GlassPanel>
      ) : (
        <>
          <GlassPanel padding="none" className="rise overflow-hidden" style={stagger(2)}>
            <ul className="m-0 flex list-none flex-col p-0" aria-label="Customer messages">
              {query.data.items.map((message, index) => (
                <MessageRow
                  key={message.id}
                  message={message}
                  index={index}
                  focused={message.id === focusId}
                  canOpenCustomer={canOpenCustomer}
                  onReply={reply}
                  replying={commands.pending === `reply:${message.id}`}
                  offline={Boolean(commands.offline)}
                />
              ))}
            </ul>
          </GlassPanel>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <PageSummary from={query.data.offset + 1} to={query.data.offset + query.data.items.length} total={total} noun={copy.noun} />
            {pages > 1 ? <Pagination label="Message pages" page={page} pages={pages} hrefFor={(target) => href({ ...state, offset: (target - 1) * limit })} /> : null}
          </div>
        </>
      )}
    </Page>
  );
}
