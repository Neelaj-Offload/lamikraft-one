"use client";

import NextLink from "next/link";
import type { InboxItem } from "@/features/inbox/types";
import { cx } from "@/lib/cx";
import { useNow, useSession } from "@/lib/session/context";
import { Badge, ButtonLink, GlassPanel, Icon, Skeleton } from "~/ui";
import { dueText, holderText, itemBadge, itemHref, KIND_LOOK, kindOf, staggered, viewHref, type InboxView } from "./model";

/**
 * One list of things waiting. Each row is a single link: what is asked, of whom, by when, and the
 * one thing to do about it. Approvals open their review screen; everything else opens in place.
 */
export function InboxRows({
  label,
  items,
  view,
  cursor,
  nextCursor = null,
  showKind = false,
  selectedId = null,
}: {
  /** Names the list for assistive technology ("Approvals waiting on you"). */
  label: string;
  items: readonly InboxItem[];
  view: InboxView;
  cursor: string | null;
  /** The server's keyset cursor for the next page of this view, when there is one. */
  nextCursor?: string | null;
  /** Say the kind on each row: for views that mix kinds. */
  showKind?: boolean;
  /** The row whose panel is open. */
  selectedId?: string | null;
}) {
  const { bootstrap, zone } = useSession();
  const now = useNow();
  const paged = Boolean(cursor) || Boolean(nextCursor);

  return (
    <GlassPanel padding="none" className="overflow-hidden">
      <ul aria-label={label}>
        {items.map((item, index) => {
          const kind = kindOf(item);
          const look = KIND_LOOK[kind];
          const badge = itemBadge(item, now, zone);
          const urgent = badge?.tone === "ember";
          const facts = [showKind ? look.noun : null, holderText(item, bootstrap.user.id), item.source?.label ?? null, dueText(item, now, zone)].filter(
            (fact): fact is string => fact !== null,
          );
          return (
            <li
              key={item.id}
              className={cx(
                "rise-plain relative flex items-start gap-4 px-4 py-4 transition-colors duration-150 hover:bg-ink/4 md:items-center md:px-6",
                index > 0 && "hairline-top",
                selectedId === item.id && "bg-gold-soft",
              )}
              style={staggered(index)}
            >
              <span
                className={cx("grid size-10 flex-none place-items-center rounded-md", urgent ? "bg-ember-soft text-ember-text" : "bg-ink/6 text-ink-2")}
                aria-hidden="true"
              >
                <Icon name={look.icon} size={18} />
              </span>
              <div className="flex min-w-0 flex-1 flex-col gap-1">
                <NextLink href={itemHref(item, view, cursor)} className="stretched t-h4 text-ink [overflow-wrap:anywhere]" scroll={kind === "approval"}>
                  {item.title}
                </NextLink>
                <p className="t-body-sm text-ink-3 [overflow-wrap:anywhere]">{facts.join(" · ")}</p>
                {badge ? (
                  <span className="mt-1 md:hidden">
                    <Badge tone={badge.tone} dot size="sm">
                      {badge.label}
                    </Badge>
                  </span>
                ) : null}
              </div>
              {badge ? (
                <Badge tone={badge.tone} dot className="hidden flex-none md:inline-flex">
                  {badge.label}
                </Badge>
              ) : null}
              <span className="t-label hidden flex-none items-center gap-1 text-ink-2 md:inline-flex md:w-20 md:justify-end" aria-hidden="true">
                {look.action}
                <Icon name="arrowRight" size={16} />
              </span>
              <Icon name="chevronRight" size={18} className="flex-none self-center text-ink-3 md:hidden" aria-hidden="true" />
            </li>
          );
        })}
      </ul>
      {paged ? (
        <nav aria-label={`${label}, pages`} className="hairline-top flex flex-wrap items-center justify-between gap-3 px-4 py-3 md:px-6">
          <p className="t-body-sm text-ink-3">{cursor ? "You are further down the list." : "Showing the first 50."}</p>
          <div className="flex flex-wrap gap-2">
            {cursor ? (
              <ButtonLink href={viewHref(view)} variant="ghost" size="sm" iconLeft="arrowLeft">
                Back to the start
              </ButtonLink>
            ) : null}
            {nextCursor ? (
              <ButtonLink href={viewHref(view, nextCursor)} variant="secondary" size="sm" iconRight="arrowRight" rel="next">
                Show the next 50
              </ButtonLink>
            ) : null}
          </div>
        </nav>
      ) : null}
    </GlassPanel>
  );
}

/** Placeholder rows shaped like the real ones. */
export function InboxRowsSkeleton({ rows = 4, label }: { rows?: number; label: string }) {
  return (
    <GlassPanel padding="none" role="status" aria-label={label}>
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className={cx("flex items-center gap-4 px-4 py-4 md:px-6", index > 0 && "hairline-top")} aria-hidden="true">
          <Skeleton width={40} height={40} style={{ borderRadius: "var(--radius-md)", flex: "none" }} />
          <div className="flex flex-1 flex-col gap-2">
            <Skeleton width={["46%", "62%", "38%", "54%"][index % 4]} height={14} />
            <Skeleton width={["30%", "24%", "36%", "28%"][index % 4]} height={10} />
          </div>
        </div>
      ))}
    </GlassPanel>
  );
}
