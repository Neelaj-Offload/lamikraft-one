/**
 * Screen-reader announcements for changes that have no focusable element of their own
 * ("3 updates available", "Saved", "Search results updated"). Text only; motion never carries
 * meaning (motion-system §5). Rendered by <LiveAnnouncer/> in the root providers.
 */

export type Politeness = "polite" | "assertive";

export interface Announcement {
  id: number;
  message: string;
}

export type AnnouncerState = Readonly<Record<Politeness, Announcement>>;

let counter = 0;
let state: AnnouncerState = { polite: { id: 0, message: "" }, assertive: { id: 0, message: "" } };
const listeners = new Set<() => void>();

export function announce(message: string, politeness: Politeness = "polite"): void {
  const text = message.trim();
  if (!text) return;
  counter += 1;
  state = { ...state, [politeness]: { id: counter, message: text } };
  for (const listener of listeners) listener();
}

export function subscribeAnnouncer(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getAnnouncerState(): AnnouncerState {
  return state;
}

/** Empty state used for server rendering and hydration. */
export const EMPTY_ANNOUNCER_STATE: AnnouncerState = Object.freeze({
  polite: { id: 0, message: "" },
  assertive: { id: 0, message: "" },
});
