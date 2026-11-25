/** Words and tones for enquiries: the pipeline, the channels and the outcomes. A plain module. */

import type { Tone } from "~/ui/badge";
import type { IconName } from "~/ui/icon";

export const ENQUIRY_PIPELINE = ["received", "assigned", "quoted", "closed"] as const;
export type EnquiryStage = (typeof ENQUIRY_PIPELINE)[number];

export const ENQUIRY_STAGE_LABEL: Record<EnquiryStage, string> = {
  received: "Received",
  assigned: "Assigned",
  quoted: "Quoted",
  closed: "Closed",
};

export const ENQUIRY_STAGE_TONE: Record<EnquiryStage, Tone> = {
  received: "amber",
  assigned: "cobalt",
  quoted: "leaf",
  closed: "neutral",
};

export const ENQUIRY_STAGE_ICON: Record<EnquiryStage, IconName> = {
  received: "inbox",
  assigned: "user",
  quoted: "fileText",
  closed: "checkCircle",
};

/** What each stage means, for the pipeline strip. */
export const ENQUIRY_STAGE_HINT: Record<EnquiryStage, string> = {
  received: "Waiting to be picked up",
  assigned: "Someone is preparing a reply",
  quoted: "A quotation has gone out",
  closed: "Finished, with an outcome",
};

export const CHANNEL_LABEL: Record<string, string> = {
  email: "Email",
  phone: "Phone",
  whatsapp: "WhatsApp",
  web: "Website",
  other: "Other",
};

export const CHANNEL_ICON: Record<string, IconName> = {
  email: "mail",
  phone: "phone",
  whatsapp: "message",
  web: "globe",
  other: "message",
};

export const ENQUIRY_OUTCOMES = ["quoted", "no_response", "not_feasible", "duplicate", "other"] as const;

export const OUTCOME_LABEL: Record<string, string> = {
  quoted: "A quotation went out",
  no_response: "The customer stopped replying",
  not_feasible: "We cannot supply it",
  duplicate: "It duplicates another enquiry",
  other: "Another reason",
};

export type EnquiryView = "overview" | "activity";

export function enquiryViewFrom(raw: string | string[] | undefined): EnquiryView {
  return (Array.isArray(raw) ? raw[0] : raw) === "activity" ? "activity" : "overview";
}

export function channelLabel(channel: string): string {
  return CHANNEL_LABEL[channel] ?? channel.charAt(0).toUpperCase() + channel.slice(1).replace(/_/g, " ");
}
