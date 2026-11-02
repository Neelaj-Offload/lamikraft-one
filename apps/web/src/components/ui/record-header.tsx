import type { ReactNode } from "react";
import { Link as RacLink } from "react-aria-components";
import { cx } from "@/lib/cx";
import { linkClasses } from "./styles";

/**
 * The canonical detail header (frontend_verification §7): a link back to the list, the
 * business key in mono, the title, the status, one line of key facts, and the actions the
 * server allows (capabilities), never actions that can never be allowed.
 */
export function RecordHeader({
  back,
  recordKey,
  title,
  status,
  meta,
  actions,
  className,
}: {
  back?: { href: string; label: string };
  /** Business key such as `LK-OT-0450` or `P-00001`. */
  recordKey?: string | null;
  title: string;
  status?: ReactNode;
  /** Short facts separated by middle dots. */
  meta?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cx("flex flex-col gap-2", className)}>
      {back ? (
        <RacLink href={back.href} className={cx(linkClasses, "self-start text-sm")}>
          {back.label}
        </RacLink>
      ) : null}
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="flex min-w-0 flex-col gap-1">
          {recordKey ? <p className="font-mono text-sm text-ink-muted">{recordKey}</p> : null}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <h1 className="text-[28px] leading-tight font-bold tracking-[-0.02em] text-ink md:text-3xl">{title}</h1>
            {status}
          </div>
          {meta ? <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-ink-muted [overflow-wrap:anywhere]">{meta}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
    </header>
  );
}

/** A middle dot between header facts, hidden from assistive technology. */
export function MetaDot() {
  return <span aria-hidden="true">·</span>;
}
