import type { Route } from "next";
import Link from "next/link";
import type { CSSProperties } from "react";
import { cx } from "@/lib/cx";
import { formatCount } from "@/lib/format/money";
import { riseIndex } from "~/lib/motion";
import { GlassPanel } from "~/ui/glass-panel";
import { Icon, type IconName } from "~/ui/icon";
import { Skeleton } from "~/ui/skeleton";

/**
 * A pipeline as a row of stages, each a link that filters the list below to that stage. The
 * count comes from the server; the chosen stage carries the gold glow. A scrolling row on
 * phones, an even grid from 768px. No directive: links only.
 */

export interface PipelineStage {
  id: string;
  label: string;
  /** What being in this stage means, in a few words. */
  hint: string;
  icon: IconName;
  /** Undefined while loading or when the count could not be read. */
  count: number | undefined;
  /** The list filtered to this stage; for the selected stage, the list with the filter removed. */
  href: Route;
}

export function PipelineStrip({ label, stages, selected, loading = false }: { label: string; stages: readonly PipelineStage[]; selected: string | null; loading?: boolean }) {
  return (
    <nav aria-label={label} className="rise min-w-0" style={riseIndex(1) as CSSProperties}>
      <ol
        className="no-scrollbar m-0 -mx-1 flex list-none gap-3 overflow-x-auto px-1 py-1 md:grid md:overflow-visible md:[grid-template-columns:repeat(var(--stages),minmax(0,1fr))]"
        style={{ "--stages": stages.length } as CSSProperties}
      >
        {stages.map((stage, index) => {
          const isSelected = stage.id === selected;
          return (
            <GlassPanel as="li" key={stage.id} padding="sm" interactive selected={isSelected} className="relative flex min-w-40 flex-none flex-col gap-2 md:min-w-0">
              <div className="flex items-center justify-between gap-2">
                <Link
                  href={stage.href}
                  scroll={false}
                  aria-current={isSelected ? "true" : undefined}
                  className={cx("stretched t-label no-underline", isSelected ? "text-ink" : "text-ink-2")}
                >
                  <span className="lk-sr-only">{isSelected ? "Showing " : "Show "}</span>
                  {stage.label}
                </Link>
                <span className={isSelected ? "text-gold-strong" : "text-ink-3"}>
                  <Icon name={stage.icon} size={16} />
                </span>
              </div>
              <div className="t-stat lk-tnum text-ink">
                {stage.count === undefined ? loading ? <Skeleton width={28} height={24} /> : <span className="text-ink-3">–</span> : formatCount(stage.count)}
              </div>
              <p className="t-caption text-ink-3">{stage.hint}</p>
              {index < stages.length - 1 ? (
                <span aria-hidden="true" className="absolute -right-[11px] top-1/2 z-[1] hidden -translate-y-1/2 text-ink-3 md:block">
                  <Icon name="chevronRight" size={12} />
                </span>
              ) : null}
            </GlassPanel>
          );
        })}
      </ol>
    </nav>
  );
}
