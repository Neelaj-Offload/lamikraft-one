"use client";

import type { Route } from "next";
import type { CustomerMessage } from "@/features/sales/types";
import { Avatar, Badge, DateText, Icon, Skeleton, SkeletonText, TextLink } from "~/ui";
import { staggered } from "./model";

const CHANNEL: Record<string, string> = { email: "Email", phone: "Phone", whatsapp: "WhatsApp", web: "Website", other: "Another channel" };

/** How to answer on each channel; replies are sent on the channel itself, then recorded here. */
const REPLY_HOW: Record<string, string> = {
  email: "Answer from your email, then mark it as replied.",
  phone: "Call them back, then mark it as replied.",
  whatsapp: "Answer on WhatsApp, then mark it as replied.",
  web: "Answer the website message, then mark it as replied.",
};

/** "Mark as replied" is offered only when the server offers it for this message. */
export function canMarkReplied(message: Pick<CustomerMessage, "allowed_transitions">): boolean {
  return message.allowed_transitions.some((transition) => transition.action === "mark_replied");
}

export function ConversationSkeleton() {
  return (
    <div className="flex items-end gap-3" role="status" aria-label="Loading the conversation">
      <Skeleton width={28} height={28} circle />
      <div className="bg-surface border-line w-4/5 rounded-lg border p-4" aria-hidden="true">
        <SkeletonText lines={3} />
      </div>
    </div>
  );
}

/**
 * The customer message behind a conversation, read as a thread: the customer's words on the left,
 * the team's answer on the right. Lamikraft One records that a reply happened; it does not send
 * one, so where a message box would sit the thread says how to answer and the panel's main button
 * marks it as replied.
 */
export function ConversationThread({ message }: { message: CustomerMessage }) {
  const author = message.contact_name ?? message.party.display_name;
  const channel = CHANNEL[message.channel] ?? message.channel;
  const replied = message.status === "replied";

  return (
    <section className="flex flex-col gap-5" aria-label={`Conversation with ${message.party.display_name}`}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge icon={message.channel === "phone" ? "phone" : message.channel === "email" ? "mail" : "message"}>{channel}</Badge>
        <Badge tone={replied ? "leaf" : "amber"} dot>
          {replied ? "Replied" : "Waiting for a reply"}
        </Badge>
      </div>

      <ol className="flex flex-col gap-5">
        <li className="rise-plain flex flex-col gap-1">
          <div className="flex items-end gap-3">
            <Avatar name={author} size="sm" className="flex-none" />
            <div className="bg-surface border-line max-w-[86%] min-w-0 rounded-lg rounded-bl-xs border px-4 py-3">
              <span className="lk-sr-only">{author} wrote: </span>
              {message.subject ? <p className="t-h4 mb-1 [overflow-wrap:anywhere]">{message.subject}</p> : null}
              {/* External text: shown as plain text, never as markup. */}
              <p className="t-body [overflow-wrap:anywhere] whitespace-pre-wrap">{message.body}</p>
            </div>
          </div>
          <p className="t-caption text-ink-3 pl-10">
            {author}
            {message.contact_name ? `, ${message.party.display_name}` : ""} · <DateText value={message.received_at} style="dayTime" />
          </p>
        </li>

        <li className="rise-plain flex flex-col items-end gap-1" style={staggered(1)}>
          {replied ? (
            <>
              <div className="bg-inverse text-on-inverse flex max-w-[86%] items-center gap-2 rounded-lg rounded-br-xs px-4 py-3">
                <Icon name="check" size={16} />
                <p className="t-body">
                  <span className="lk-sr-only">Your team: </span>Replied to the customer
                </p>
              </div>
              <p className="t-caption text-ink-3">
                Marked as replied · <DateText value={message.replied_at} style="dayTime" />
              </p>
            </>
          ) : (
            <>
              <div className="border-line-strong text-ink-2 max-w-[86%] rounded-lg rounded-br-xs border border-dashed px-4 py-3">
                <p className="t-body-sm">
                  <span className="lk-sr-only">Your team: </span>No reply recorded yet
                </p>
              </div>
              {canMarkReplied(message) ? <p className="t-caption text-ink-3">{REPLY_HOW[message.channel] ?? "Answer the customer, then mark it as replied."}</p> : null}
            </>
          )}
        </li>
      </ol>

      {message.quote_id || message.enquiry_id ? (
        <p className="t-body-sm flex flex-wrap items-center gap-x-4 gap-y-1">
          <span className="text-ink-3">Linked to</span>
          {message.quote_id ? (
            <TextLink href={`/sales/quotes/${encodeURIComponent(message.quote_id)}` as Route}>Quotation {message.quote_number ?? ""}</TextLink>
          ) : null}
          {message.enquiry_id ? <TextLink href={`/sales/enquiries/${encodeURIComponent(message.enquiry_id)}` as Route}>The enquiry</TextLink> : null}
        </p>
      ) : null}
    </section>
  );
}
