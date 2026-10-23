/** Copy for the shared state components (frontend_verification §15). */
export const stateMessages = {
  loading: (what: string) => `Loading ${what}…`,
  retry: "Try again",
  backToToday: "Back to Today",
  requestId: "Reference",
  error: {
    title: (what: string) => `${capitalise(what)} couldn't be loaded`,
    server: "The server ran into a problem. Nothing was changed. Try again in a moment.",
    unavailable: "Lamikraft One can't reach its server right now. Try again in a moment.",
    rateLimited: "Too many requests in a short time. Wait a moment, then try again.",
    generic: "Something went wrong while loading this. Try again.",
  },
  notYetAvailable: {
    title: (what: string) => `${capitalise(what)} isn't available yet`,
    body: "This part of Lamikraft One hasn't been switched on for your workspace. Everything else keeps working.",
  },
  offline: {
    title: "You're offline",
    body: "Lamikraft One can't reach the server. What's on screen may be out of date, and changes can't be sent until the connection is back.",
  },
  stale: {
    title: "This may be out of date",
    body: (asOf: string) => `Showing information as of ${asOf}. Refresh to see the latest.`,
    action: "Refresh",
  },
  conflict: {
    title: "Someone else changed this while you were editing",
    body: (who: string | null, when: string | null) =>
      `${who ?? "Another person"} saved a newer version${when ? ` at ${when}` : ""}. Your edits are still here and nothing was overwritten.`,
    hint: "Review their version next to yours: changes only they made are taken, your own changes are kept, and fields you both changed need your choice before you save again.",
    reload: "Review latest version",
    keepMine: "Keep my edits and review",
  },
  permissionDenied: {
    title: (area: string) => `You don't have access to ${area}`,
    body: "Your role doesn't include this area. If you need it for your work, ask an administrator to grant access.",
  },
  notAvailable: {
    title: "Not found or not available to you",
    body: "This record doesn't exist, was removed, or is outside what your role can see.",
  },
  success: {
    receipt: "View",
  },
} as const;

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
