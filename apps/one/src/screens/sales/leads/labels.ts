import type { ActivityKind, Interest, LeadStage, Priority, Temperature } from "~/data/leads";

export const LEAD_STAGES: readonly LeadStage[] = ["new", "contacted", "qualified", "negotiating", "won", "lost"];
export const OPEN_LEAD_STAGES: readonly LeadStage[] = ["new", "contacted", "qualified", "negotiating"];
export const INTERESTS: readonly Interest[] = ["lamikraft", "table_top", "standard_decorative", "standard_compact"];
export const PRIORITIES: readonly Priority[] = ["A", "B", "C"];
export const TEMPERATURES: readonly Temperature[] = ["hot", "warm", "cold"];
export const ACTIVITY_KINDS: readonly ActivityKind[] = ["call", "email", "whatsapp", "meeting", "visit", "note"];

export const LEAD_STAGE_LABEL: Record<LeadStage, string> = {
  new: "New",
  contacted: "Contacted",
  qualified: "Qualified",
  negotiating: "Negotiating",
  won: "Won",
  lost: "Lost",
};

export const LEAD_STAGE_HINT: Record<LeadStage, string> = {
  new: "Not spoken to yet",
  contacted: "You have reached them",
  qualified: "A real buyer with a real need",
  negotiating: "Prices, samples or terms on the table",
  won: "Bought or took a sample: now a customer",
  lost: "Not going ahead, with the reason",
};

export const LEAD_STAGE_TONE: Record<LeadStage, "neutral" | "cobalt" | "amber" | "leaf" | "ember"> = {
  new: "neutral",
  contacted: "cobalt",
  qualified: "cobalt",
  negotiating: "amber",
  won: "leaf",
  lost: "ember",
};

export const INTEREST_LABEL: Record<Interest, string> = {
  lamikraft: "Lamikraft",
  table_top: "Table top",
  standard_decorative: "Standard decorative",
  standard_compact: "Standard compact",
};

export const PRIORITY_LABEL: Record<Priority, string> = { A: "Priority A", B: "Priority B", C: "Priority C" };

export const TEMPERATURE_LABEL: Record<Temperature, string> = { hot: "Hot", warm: "Warm", cold: "Cold" };
export const TEMPERATURE_TONE: Record<Temperature, "ember" | "amber" | "cobalt"> = { hot: "ember", warm: "amber", cold: "cobalt" };

export const ACTIVITY_LABEL: Record<ActivityKind, string> = {
  call: "Call",
  email: "Email",
  whatsapp: "WhatsApp",
  meeting: "Meeting",
  visit: "Visit",
  note: "Note",
};

export const ACTIVITY_ICON: Record<ActivityKind, "phone" | "mail" | "message" | "users" | "mapPin" | "fileText"> = {
  call: "phone",
  email: "mail",
  whatsapp: "message",
  meeting: "users",
  visit: "mapPin",
  note: "fileText",
};

/** "overdue", "today" or null for a follow-up date compared with today's ISO date in the company zone. */
export function followUpState(due: string | null | undefined, today: string): "overdue" | "today" | null {
  if (!due) return null;
  if (due < today) return "overdue";
  if (due === today) return "today";
  return null;
}

/** Today's date as `YYYY-MM-DD` in the given IANA zone (the company's). */
export function isoToday(timeZone: string, now: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(now);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}
