/**
 * The views behind `?view=` on the AI and WhatsApp settings screens, and their links. A plain
 * module: route files call these on the server.
 */

type Param = string | string[] | undefined;
const first = (value: Param): string | undefined => (Array.isArray(value) ? value[0] : value);

export const AI_VIEWS = ["overview", "usage", "routing"] as const;
export type AiView = (typeof AI_VIEWS)[number];

export function parseAiView(value: Param): AiView {
  const raw = first(value);
  return AI_VIEWS.find((view) => view === raw) ?? "overview";
}

/** The usage windows the server offers; 7 days is the default and stays out of the URL. */
export const USAGE_WINDOWS = [
  { days: 1, label: "Today" },
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
] as const;
const DEFAULT_DAYS = 7;

export function aiHref(view: AiView, days: number = DEFAULT_DAYS): string {
  const query = new URLSearchParams();
  if (view !== "overview") query.set("view", view);
  if (days !== DEFAULT_DAYS) query.set("days", String(days));
  const text = query.toString();
  return text ? `/settings/ai?${text}` : "/settings/ai";
}

export function traceHref(correlationId: string): string {
  return `/settings/ai/traces/${encodeURIComponent(correlationId)}`;
}

export const WHATSAPP_VIEWS = ["phone", "connection", "messages", "templates"] as const;
export type WhatsAppView = (typeof WHATSAPP_VIEWS)[number];

export function parseWhatsAppView(value: Param): WhatsAppView {
  const raw = first(value);
  return WHATSAPP_VIEWS.find((view) => view === raw) ?? "phone";
}
