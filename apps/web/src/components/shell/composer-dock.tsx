import type { ReactNode } from "react";

/**
 * The phone composer slot: on screens below 768 px the composer is pinned just above the
 * bottom navigation, within thumb reach, and the main area reserves room for it. From tablet
 * up it renders in place. Pages put their composer (Today's command bar) inside it.
 */
export function ComposerDock({ children }: { children: ReactNode }) {
  return (
    <div
      data-composer-dock=""
      className="max-md:fixed max-md:inset-x-0 max-md:bottom-[calc(3.5rem+env(safe-area-inset-bottom))] max-md:z-30 max-md:border-t max-md:bg-surface max-md:px-4 max-md:py-3"
    >
      {children}
    </div>
  );
}
