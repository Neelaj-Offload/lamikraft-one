import type { Route } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { cx } from "@/lib/cx";
import { Sparkline } from "./charts";
import { Icon } from "./icon";

export interface StatTileProps {
  label: ReactNode;
  /** The figure, already formatted (`<Money>`, `<CountUp>`, a string). */
  value: ReactNode;
  /** Change against the comparison period: a number is shown as a signed percentage, a string as given. */
  delta?: number | string;
  /** What the change is measured against ("vs last week"). */
  deltaLabel?: ReactNode;
  /** Direction of the change; inferred from a numeric `delta` when omitted. */
  trend?: "up" | "down" | "flat";
  /** Recent values for a sparkline beside the figure. */
  data?: readonly number[];
  /** Quiet text on the last line; takes the place of `deltaLabel`. */
  foot?: ReactNode;
  size?: "xl";
  /** A dot before the label: `true` for gold, or any CSS colour (a chart series colour). */
  dot?: boolean | string;
  /** A thin progress bar under the tile, 0 to 100. */
  bar?: number;
  /** For tiles on an ink panel. */
  inverse?: boolean;
  /** Makes the whole tile a link; it lifts on hover. */
  href?: Route;
  className?: string;
}

const TREND_WORD = { up: "Up", down: "Down", flat: "No change" } as const;

/** One headline number with its label, change and optional sparkline. Place it on a glass panel. */
export function StatTile({
  label,
  value,
  delta,
  deltaLabel,
  trend,
  data,
  foot,
  size,
  dot,
  bar,
  inverse,
  href,
  className,
}: StatTileProps) {
  const direction = trend ?? (typeof delta === "number" ? (delta > 0 ? "up" : delta < 0 ? "down" : "flat") : null);
  const deltaText =
    typeof delta === "number" ? `${delta > 0 ? "+" : delta < 0 ? "−" : ""}${Math.abs(delta)}%` : delta;
  const lastLine = foot ?? deltaLabel;
  const classes = cx("lk-stat", size === "xl" && "lk-stat-xl", inverse && "lk-stat-inverse", href && "lk-stat-link", className);

  const body = (
    <>
      <div className="lk-stat-label">
        {dot ? <span className="lk-stat-label-dot" style={dot !== true ? { background: dot } : undefined} /> : null}
        {label}
      </div>
      <div className="lk-stat-row">
        <div className="lk-stat-value">{value}</div>
        {data && data.length > 1 ? (
          <Sparkline
            data={data}
            label="Trend"
            decorative
            color={direction === "down" ? "var(--ember)" : inverse ? "var(--on-inverse)" : "var(--chart-1)"}
          />
        ) : null}
      </div>
      {direction || lastLine ? (
        <div className="lk-row lk-stat-meta">
          {direction ? (
            <span className={cx("lk-stat-delta", `lk-stat-delta-${direction}`)}>
              {direction !== "flat" ? (
                <Icon name={direction === "up" ? "arrowUpRight" : "arrowDownRight"} size={12} strokeWidth={2.2} />
              ) : null}
              {/* The arrow and sign carry the direction for sighted readers; this says it in words. */}
              <span className="sr-only">{TREND_WORD[direction]} </span>
              {deltaText}
            </span>
          ) : null}
          {lastLine ? <span className="lk-stat-foot">{lastLine}</span> : null}
        </div>
      ) : null}
      {bar !== undefined ? (
        <div className="lk-stat-bar" aria-hidden="true">
          <span style={{ width: `${Math.min(100, Math.max(0, bar))}%` }} />
        </div>
      ) : null}
    </>
  );

  return href ? (
    <Link href={href} className={classes}>
      {body}
    </Link>
  ) : (
    <div className={classes}>{body}</div>
  );
}

/** Lays stat tiles out in a row: two columns on phones, as many as fit from 768px. */
export function StatRow({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("lk-stat-grid", className)}>{children}</div>;
}
