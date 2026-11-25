/**
 * "Where do we stand with this customer, and what is next?" worked out from records that exist:
 * their samples, quotations and orders. Pure, so the rule is easy to read and to test.
 */

import type { OrderSummary } from "@/features/orders/api";
import type { PartyDetail } from "@/features/parties/types";
import type { QuoteSummary } from "@/features/sales/types";
import type { Sample } from "@/features/samples/api";
import type { IconName } from "~/ui/icon";
import { customerHref } from "./labels";

export interface NextStep {
  icon: IconName;
  /** A short serif headline. */
  title: string;
  /** One sentence of context. */
  text: string;
  /** Where the step is taken; omitted when the step is a button the record already shows. */
  action?: { label: string; href: string };
}

export interface CustomerHistory {
  quotes: readonly QuoteSummary[] | undefined;
  samples: readonly Sample[] | undefined;
  orders: readonly OrderSummary[] | undefined;
}

const sampleHref = (id: string) => `/sales/samples/${encodeURIComponent(id)}`;

/** The first thing that applies, most pressing first. */
export function nextStepFor(party: PartyDetail, history: CustomerHistory, can: { createQuote: boolean }): NextStep {
  const name = party.display_name;
  if (party.archived_at) {
    return { icon: "archive", title: "Archived", text: `${name} is put away. Restore the record to quote, sample or sell to them again.` };
  }
  if (party.status === "blocked") {
    return { icon: "lock", title: "Blocked", text: `Do not quote or ship to ${name} until the block is cleared. Change the stage when it is.` };
  }

  const delivered = history.samples?.find((sample) => sample.status === "delivered");
  if (delivered) {
    return {
      icon: "message",
      title: "Ask what they thought of the sample",
      text: `${delivered.sample_number} has reached them. Record their feedback while it is fresh.`,
      action: { label: "Open sample", href: sampleHref(delivered.id) },
    };
  }
  const requested = history.samples?.find((sample) => sample.status === "requested");
  if (requested) {
    return {
      icon: "truck",
      title: "Send the sample they asked for",
      text: `${requested.sample_number} is waiting to leave stock.`,
      action: { label: "Open sample", href: sampleHref(requested.id) },
    };
  }

  const unfinished = history.quotes?.find((quote) => quote.status === "draft" || quote.status === "internal_review");
  if (unfinished) {
    return {
      icon: "fileText",
      title: unfinished.status === "draft" ? "Finish the draft quotation" : "A quotation is waiting for approval",
      text: `${unfinished.quote_number} has not gone to the customer yet.`,
      action: { label: "Open quotation", href: unfinished.path },
    };
  }
  const awaiting = history.quotes?.find((quote) => quote.status === "sent" || quote.status === "revised");
  if (awaiting) {
    return {
      icon: "clock",
      title: "Waiting for their answer",
      text: `${awaiting.quote_number} is with the customer. Follow up before it expires.`,
      action: { label: "Open quotation", href: awaiting.path },
    };
  }

  const onHold = history.orders?.find((order) => order.status === "on_hold");
  if (onHold) {
    return {
      icon: "pause",
      title: "An order is on hold",
      text: `${onHold.order_number} cannot move until the hold is released.`,
      action: { label: "Open order", href: `/sales/orders/${encodeURIComponent(onHold.id)}` },
    };
  }
  const running = history.orders?.find((order) => order.status === "confirmed" || order.status === "draft");
  if (running) {
    return {
      icon: "cart",
      title: "An order is in progress",
      text: `${running.order_number} is ${running.status === "draft" ? "still a draft" : "confirmed and being fulfilled"}.`,
      action: { label: "Open order", href: `/sales/orders/${encodeURIComponent(running.id)}` },
    };
  }

  if (party.contacts.length === 0) {
    return {
      icon: "userPlus",
      title: "Add someone to talk to",
      text: `There is no contact for ${name} yet, so the team does not know who to call.`,
      action: { label: "Contacts and addresses", href: customerHref(party.id, "contacts") },
    };
  }
  if (party.status === "prospect" && can.createQuote) {
    return { icon: "fileText", title: "Make the first offer", text: `${name} is still a lead. A quotation or a sample moves them forward.` };
  }
  return { icon: "checkCircle", title: "Nothing is waiting", text: `Everything with ${name} is up to date. Start a quotation when they ask for one.` };
}

/** Sum of the given statuses in a status-count map; undefined while the map is not loaded. */
export function countOf(counts: Readonly<Record<string, number | undefined>> | undefined, statuses: readonly string[]): number | undefined {
  if (!counts) return undefined;
  return statuses.reduce((sum, status) => sum + (counts[status] ?? 0), 0);
}
