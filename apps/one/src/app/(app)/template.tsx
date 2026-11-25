import type { ReactNode } from "react";

/**
 * A template remounts on every navigation, which replays the entrance: the page fades in over
 * 180ms while its header and panels rise in sequence (the `rise` classes). Pure CSS, so the first
 * server-rendered load is readable before any script runs, and reduced motion is honoured in CSS.
 */
export default function AppTemplate({ children }: { children: ReactNode }) {
  return <div className="page-enter flex min-h-0 flex-1 flex-col">{children}</div>;
}
