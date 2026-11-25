import type { CSSProperties } from "react";
import { cx } from "@/lib/cx";

export interface SkeletonProps {
  width?: CSSProperties["width"];
  height?: CSSProperties["height"];
  circle?: boolean;
  className?: string;
  style?: CSSProperties;
}

/**
 * A placeholder with the shape of what is loading. Hidden from assistive technology: the screen
 * that shows it says "Loading" once, in text. The shimmer stops under reduced motion.
 */
export function Skeleton({ width = "100%", height = 12, circle = false, className, style }: SkeletonProps) {
  return (
    <span
      className={cx("lk-skeleton", circle && "lk-skeleton-circle", className)}
      style={{ width, height, display: "block", ...style }}
      aria-hidden="true"
    />
  );
}

export interface SkeletonTextProps {
  lines?: number;
  className?: string;
}

/** Lines of text; the last one is short, the way a paragraph ends. */
export function SkeletonText({ lines = 3, className }: SkeletonTextProps) {
  return (
    <span className={cx("lk-skeleton-lines", className)} aria-hidden="true">
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton key={index} width={lines > 1 && index === lines - 1 ? "60%" : "100%"} />
      ))}
    </span>
  );
}

/** Fixed, repeating bar widths: varied enough to read as content, identical on server and client. */
const BAR_WIDTHS = ["72%", "48%", "64%", "36%", "56%", "80%", "44%"] as const;

export interface SkeletonRowsProps {
  rows?: number;
  columns?: number;
  className?: string;
}

/** A table's worth of placeholder rows, each the height of a real row so nothing jumps on load. */
export function SkeletonRows({ rows = 5, columns = 4, className }: SkeletonRowsProps) {
  return (
    <div
      className={cx("lk-skeleton-rows", className)}
      style={{ "--lk-skeleton-columns": columns } as CSSProperties}
      aria-hidden="true"
    >
      {Array.from({ length: rows }, (_, row) => (
        <div key={row} className="lk-skeleton-row">
          {Array.from({ length: columns }, (_, column) => (
            <Skeleton key={column} width={BAR_WIDTHS[(row * 3 + column * 2) % BAR_WIDTHS.length]} />
          ))}
        </div>
      ))}
    </div>
  );
}
