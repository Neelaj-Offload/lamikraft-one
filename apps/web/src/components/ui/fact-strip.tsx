import type { ReactNode } from "react";
import { Link as RacLink } from "react-aria-components";
import { cx } from "@/lib/cx";
import { focusRingClasses } from "./styles";

export interface Fact {
  label: string;
  /** Already formatted (counts through formatCount, money through <Money>). */
  value: ReactNode;
  /** Opens the list behind the number. */
  href?: string | null;
}

/**
 * Real figures as one quiet line of facts separated by rules, not a row of KPI cards
 * (build brief <design_direction>). Values use tabular numerals; a fact with a link opens the
 * filtered list it counts.
 */
export function FactStrip({ facts, label, className }: { facts: readonly Fact[]; label: string; className?: string }) {
  if (facts.length === 0) return null;
  return (
    <dl aria-label={label} className={cx("flex flex-wrap gap-y-3 text-sm", className)}>
      {facts.map((fact, index) => {
        const value = <span className="text-2xl leading-none font-bold tracking-[-0.02em] text-ink tabular md:text-[28px]">{fact.value}</span>;
        return (
          <div key={fact.label} className={cx("flex flex-col gap-1.5 pe-6", index > 0 && "border-s ps-6")}>
            <dt className="text-ink-muted">{fact.label}</dt>
            <dd>
              {fact.href ? (
                <RacLink href={fact.href} className={cx("rounded-xs hover:text-forest", focusRingClasses)}>
                  {value}
                </RacLink>
              ) : (
                value
              )}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
