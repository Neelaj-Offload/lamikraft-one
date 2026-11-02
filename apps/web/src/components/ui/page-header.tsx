import type { ReactNode } from "react";
import { cx } from "@/lib/cx";

/**
 * The page's title block: an h1 (focused after navigation by the shell), one intro sentence,
 * an optional primary action and an optional sub-navigation row (`AreaNav`) beneath.
 */
export function PageHeader({
  title,
  intro,
  actions,
  nav,
  eyebrow,
  className,
}: {
  title: string;
  intro?: ReactNode;
  actions?: ReactNode;
  /** `AreaNav` or any `NavTabs`. */
  nav?: ReactNode;
  /** A short label above the title (the area name on a sub-page). */
  eyebrow?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cx("flex flex-col gap-4", className)}>
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="flex min-w-0 flex-col gap-1">
          {eyebrow ? <p className="text-xs font-semibold tracking-[0.08em] text-ink-muted uppercase">{eyebrow}</p> : null}
          <h1 className="text-[28px] leading-tight font-bold tracking-[-0.02em] text-ink md:text-3xl">{title}</h1>
          {intro ? <p className="max-w-2xl text-ink-muted">{intro}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      {nav}
    </header>
  );
}
