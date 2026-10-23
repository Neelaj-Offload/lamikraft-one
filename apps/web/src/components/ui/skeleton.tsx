import { cx } from "@/lib/cx";

/**
 * Layout-shaped placeholders (frontend_verification §15 "Loading"). They appear only after
 * 150 ms so quick answers never flash, pulse gently (the one allowed infinite animation),
 * and are hidden from assistive technology; the surrounding region carries aria-busy and a
 * text label instead.
 */
export function Skeleton({ className }: { className?: string }) {
  return <span aria-hidden="true" className={cx("block animate-pulse rounded-md bg-surface-sunken", className)} />;
}

export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <span aria-hidden="true" className={cx("flex flex-col gap-2", className)}>
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton key={index} className={cx("h-3.5", index === lines - 1 ? "w-3/5" : "w-full")} />
      ))}
    </span>
  );
}
