/**
 * Words, tones and the journey of a customer sample. A plain module (server pages and client
 * screens both read it). Today every sample goes to a customer; the backend has no exhibition
 * category and no quality grade, so neither appears here.
 */

import type { Tone } from "~/ui/badge";
import type { IconName } from "~/ui/icon";

/** The journey a sample takes, in order. `cancelled` leaves the journey and is shown apart. */
export const SAMPLE_JOURNEY = ["requested", "dispatched", "delivered", "feedback_received", "closed"] as const;
export type SampleStep = (typeof SAMPLE_JOURNEY)[number];

export const SAMPLE_STATUS_LABEL: Record<string, string> = {
  requested: "Requested",
  dispatched: "Dispatched",
  delivered: "Delivered",
  feedback_received: "Feedback received",
  closed: "Closed",
  cancelled: "Cancelled",
};

export const SAMPLE_STATUS_TONE: Record<string, Tone> = {
  requested: "amber",
  dispatched: "cobalt",
  delivered: "cobalt",
  feedback_received: "leaf",
  closed: "neutral",
  cancelled: "neutral",
};

export const SAMPLE_STEP_ICON: Record<SampleStep, IconName> = {
  requested: "clipboard",
  dispatched: "truck",
  delivered: "packageOpen",
  feedback_received: "message",
  closed: "checkCircle",
};

/** Where the sample stands, in a sentence, for the record's lead and the "what is next" panel. */
export const SAMPLE_STANDING: Record<string, { now: string; next: string }> = {
  requested: { now: "Waiting to leave stock.", next: "Pack it, hand it to the courier, then record the dispatch." },
  dispatched: { now: "On its way to the customer.", next: "When it arrives, record the delivery and how you know." },
  delivered: { now: "With the customer.", next: "Ask what they think, then record their feedback." },
  feedback_received: { now: "The customer has answered.", next: "Act on the feedback, then close the sample." },
  closed: { now: "Finished. Nothing more to record.", next: "" },
  cancelled: { now: "Cancelled before it finished.", next: "" },
};

export const SAMPLE_ACTION_LABEL: Record<string, string> = {
  dispatch: "Record dispatch",
  deliver: "Record delivery",
  record_feedback: "Record feedback",
  close: "Close sample",
  cancel: "Cancel sample",
};

export const SAMPLE_ACTION_DONE: Record<string, string> = {
  dispatch: "Dispatch recorded",
  deliver: "Delivery recorded",
  record_feedback: "Feedback recorded",
  close: "Sample closed",
  cancel: "Sample cancelled",
};

export const SAMPLE_ACTION_ICON: Record<string, IconName> = {
  dispatch: "truck",
  deliver: "packageOpen",
  record_feedback: "message",
  close: "checkCircle",
  cancel: "xCircle",
};

export const EVIDENCE_LABEL: Record<string, string> = {
  courier_tracking: "Courier tracking shows delivered",
  customer_confirmation: "The customer confirmed it",
  challan_signed: "Signed delivery challan",
  other: "Something else",
};

export const FEEDBACK_LABEL: Record<string, string> = {
  positive: "Positive",
  negative: "Negative",
  changes_requested: "Changes requested",
  no_response: "No response",
};

export const FEEDBACK_TONE: Record<string, Tone> = {
  positive: "leaf",
  negative: "ember",
  changes_requested: "amber",
  no_response: "neutral",
};

export const SAMPLE_VIEWS = ["overview", "history", "activity"] as const;
export type SampleView = (typeof SAMPLE_VIEWS)[number];

export function sampleViewFrom(raw: string | string[] | undefined): SampleView {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return SAMPLE_VIEWS.find((view) => view === value) ?? "overview";
}

export const SAMPLE_UNITS =["pcs", "set", "sheets", "box", "sqm"] as const;

/** Position on the journey: 0-based index of the current step, or -1 for a cancelled sample. */
export function journeyIndex(status: string): number {
  return SAMPLE_JOURNEY.findIndex((step) => step === status);
}
