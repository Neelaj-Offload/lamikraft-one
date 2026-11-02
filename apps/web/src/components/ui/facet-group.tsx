"use client";

import { Link as RacLink } from "react-aria-components";
import { cx } from "@/lib/cx";
import { formatCount } from "@/lib/format/money";
import { useZone } from "@/lib/session/context";
import { focusRingInsetClasses } from "./styles";

export interface FacetOption {
  value: string;
  label: string;
  /** The server's exclude-self count for this value. */
  count: number;
  /** The list URL with this value applied (or removed when it is selected). */
  href: string;
  selected: boolean;
}

/**
 * One facet dimension as a list of links (state lives in the URL, so every combination is a
 * page and the back button works). Counts come from the server with every other filter
 * applied; values with zero results are still shown, muted, so the person sees why.
 */
export function FacetGroup({
  label,
  options,
  clearHref,
  max = 8,
  className,
}: {
  label: string;
  options: readonly FacetOption[];
  clearHref?: string | null;
  max?: number;
  className?: string;
}) {
  const { locale } = useZone();
  if (options.length === 0) return null;
  const selectedAny = options.some((option) => option.selected);
  const shown = options.slice(0, max);
  return (
    <fieldset className={cx("flex min-w-0 flex-col gap-1", className)}>
      <legend className="mb-1 flex w-full items-center justify-between text-xs font-semibold tracking-[0.08em] text-ink-muted uppercase">
        <span>{label}</span>
        {selectedAny && clearHref ? (
          <RacLink href={clearHref} className={cx("rounded-xs font-medium tracking-normal text-forest normal-case hover:underline", focusRingInsetClasses)}>
            Clear
          </RacLink>
        ) : null}
      </legend>
      <ul className="flex flex-col">
        {shown.map((option) => (
          <li key={option.value}>
            <RacLink
              href={option.href}
              aria-current={option.selected ? "true" : undefined}
              className={cx(
                "flex min-h-10 items-center justify-between gap-3 rounded-sm px-2 text-sm text-ink hover:bg-surface-sunken pointer-fine:min-h-8",
                focusRingInsetClasses,
                option.selected && "bg-forest-tint font-semibold text-forest hover:bg-forest-tint",
                option.count === 0 && !option.selected && "text-ink-muted",
              )}
            >
              <span className="min-w-0 truncate">{option.label}</span>
              <span className="shrink-0 text-xs text-ink-muted tabular">{formatCount(option.count, locale)}</span>
            </RacLink>
          </li>
        ))}
      </ul>
    </fieldset>
  );
}
