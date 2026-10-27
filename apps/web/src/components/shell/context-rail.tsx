"use client";

import { createContext, useContext, useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { shellMessages as m } from "@/messages/shell";

/**
 * The optional 300 px context rail. Screens put record context into it with <RailContent>;
 * the shell decides where it renders (an inline column at ≥1280 px, an overlay drawer on
 * tablets) and whether it is open (persisted in the user's `ui` preferences).
 */

export interface RailSlot {
  target: HTMLElement | null;
  register: () => () => void;
}

export const RailContext = createContext<RailSlot | null>(null);

/** Renders its children inside the context rail when the rail is mounted. */
export function RailContent({ children }: { children: ReactNode }) {
  const slot = useContext(RailContext);
  const register = slot?.register;
  useEffect(() => register?.(), [register]);
  return slot?.target ? createPortal(children, slot.target) : null;
}

/** The rail body: registered screen content, or a calm explanation when there is none. */
export function RailBody({ hasContent, setTarget }: { hasContent: boolean; setTarget: (element: HTMLElement | null) => void }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      {hasContent ? null : (
        <div className="flex flex-col gap-1 text-sm">
          <p className="font-semibold text-ink">{m.rail.emptyTitle}</p>
          <p className="text-ink-muted">{m.rail.emptyBody}</p>
        </div>
      )}
      <div ref={setTarget} className="flex min-h-0 flex-1 flex-col gap-4" />
    </div>
  );
}
