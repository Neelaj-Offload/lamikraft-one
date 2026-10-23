"use client";

import { useId } from "react";
import { Button as RacButton, Disclosure, DisclosurePanel, Link as RacLink } from "react-aria-components";
import { Badge, StatusPill } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ChevronDownIcon, MoreIcon } from "@/components/ui/icons";
import { LinkButton } from "@/components/ui/link";
import { Menu, MenuItem, MenuTrigger } from "@/components/ui/menu";
import { iconButtonClasses, linkClasses } from "@/components/ui/styles";
import { cx } from "@/lib/cx";
import { formatDayTime, formatTime, parseInstant, type ZoneOptions } from "@/lib/format/time";
import { briefingMessages as m } from "@/messages/briefing";
import { actionLabel, isNavigationAction, itemStatus, primaryAction, secondaryActions } from "./model";
import type { BriefingAction, BriefingItem } from "./types";

export function dueLabel(item: Pick<BriefingItem, "due_at" | "due_kind" | "overdue">, now: Date, zone: ZoneOptions): string | null {
  if (!item.due_at || item.due_kind === "none") return null;
  const when = formatDayTime(item.due_at, now, zone);
  if (!when) return null;
  if (item.overdue) return `${m.item.overdue} · ${m.item.due(when)}`;
  return item.due_kind === "hard" ? m.item.due(when) : m.item.target(when);
}

export interface BriefingItemRowProps {
  item: BriefingItem;
  now: Date;
  zone: ZoneOptions;
  /** Command actions (snooze, mark handled, approve, …) and in-app dialogs (explain). */
  onCommand: (item: BriefingItem, action: BriefingAction) => void;
  /** The action currently being sent for this item, if any. */
  pendingAction?: string | null;
  /** Read-only rendering (fallback "last briefing"): no controls. */
  readOnly?: boolean;
}

/**
 * One briefing item: small status, the problem, the recommended action, the evidence and one
 * primary control; secondary actions are only those the server allowed (briefing.md §9).
 * Rows are separated by rules, not cards.
 */
export function BriefingItemRow({ item, now, zone, onCommand, pendingAction = null, readOnly = false }: BriefingItemRowProps) {
  const titleId = useId();
  const status = itemStatus(item);
  const due = dueLabel(item, now, zone);
  const primary = readOnly ? null : primaryAction(item);
  const secondary = readOnly ? [] : secondaryActions(item);
  const hasWhy =
    Boolean(item.recommendation?.reason_text || item.recommendation?.effect_text) ||
    (item.recommendation?.alternatives.length ?? 0) > 0 ||
    item.uncertainty_flags.length > 0;

  return (
    <article aria-labelledby={titleId} className="flex flex-col gap-3 py-5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <StatusPill tone={status.tone}>{status.label}</StatusPill>
        {due ? <span className={cx("text-sm tabular", item.overdue ? "font-semibold text-danger" : "text-ink-muted")}>{due}</span> : null}
        {item.change_kind === "changed" ? <Badge tone="info">{m.item.changed}</Badge> : null}
        {item.change_kind === "new" ? <Badge tone="forest">{m.item.new}</Badge> : null}
        {item.on_behalf_of ? <Badge tone="neutral">{m.item.forPerson(item.on_behalf_of.display_name)}</Badge> : null}
        {item.member_count > 1 ? <span className="text-sm text-ink-muted">{m.item.grouped(item.member_count)}</span> : null}
      </div>

      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between md:gap-6">
        <div className="flex min-w-0 flex-col gap-1">
          <h3 id={titleId} className="text-lg leading-snug font-[650] text-ink">
            {item.title}
          </h3>
          {item.summary_text ? <p className="tabular text-ink-muted">{item.summary_text}</p> : null}
        </div>
        {primary || secondary.length > 0 ? (
          <div className="flex shrink-0 items-center gap-1">
            {primary ? <PrimaryControl item={item} action={primary} onCommand={onCommand} pending={pendingAction === primary.action} /> : null}
            {secondary.length > 0 ? (
              <MenuTrigger>
                <RacButton aria-label={m.item.moreActions(item.title)} className={iconButtonClasses("quiet")} isDisabled={pendingAction !== null}>
                  <MoreIcon />
                </RacButton>
                <Menu
                  aria-label={m.item.moreActions(item.title)}
                  onAction={(key) => {
                    const action = secondary.find((candidate) => candidate.action === key);
                    if (action && !isNavigationAction(action)) onCommand(item, action);
                  }}
                >
                  {secondary.map((action) =>
                    isNavigationAction(action) && action.href ? (
                      <MenuItem key={action.action} id={action.action} href={action.href}>
                        {actionLabel(action)}
                      </MenuItem>
                    ) : (
                      <MenuItem key={action.action} id={action.action}>
                        {actionLabel(action)}
                      </MenuItem>
                    ),
                  )}
                </Menu>
              </MenuTrigger>
            ) : null}
          </div>
        ) : null}
      </div>

      {item.recommendation ? (
        <p className="rounded-md bg-sage px-3 py-2 text-[15px] text-ink">
          <span className="font-semibold">{m.item.suggested}:</span> {item.recommendation.label}
        </p>
      ) : null}

      {hasWhy ? (
        <Disclosure className="group">
          <RacButton slot="trigger" className={cx(linkClasses, "inline-flex min-h-11 items-center gap-1 text-sm no-underline pointer-fine:min-h-8")}>
            {m.item.why}
            <ChevronDownIcon size={16} className="transition-transform duration-150 group-data-[expanded]:rotate-180" />
          </RacButton>
          <DisclosurePanel className="text-sm text-ink-muted">
            {item.recommendation?.reason_text ? <p className="border-s-2 ps-3 text-ink">{item.recommendation.reason_text}</p> : null}
            <dl className="flex flex-col gap-2 border-s-2 ps-3">
              {item.recommendation?.effect_text ? (
                <div>
                  <dt className="font-semibold text-ink">{m.item.effect}</dt>
                  <dd>{item.recommendation.effect_text}</dd>
                </div>
              ) : null}
              {item.recommendation && item.recommendation.alternatives.length > 0 ? (
                <div>
                  <dt className="font-semibold text-ink">{m.item.alternatives}</dt>
                  <dd>{item.recommendation.alternatives.join(" · ")}</dd>
                </div>
              ) : null}
              {item.uncertainty_flags.length > 0 ? (
                <div>
                  <dt className="font-semibold text-warning-text">{m.item.uncertainty}</dt>
                  <dd>{item.uncertainty_flags.map((flag) => flag.label ?? flag.code).join(" · ")}</dd>
                </div>
              ) : null}
            </dl>
          </DisclosurePanel>
        </Disclosure>
      ) : null}

      {item.source_refs.length > 0 ? (
        <ul aria-label={m.item.evidence} className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink-muted">
          {item.source_refs.map((ref) => {
            const updated = ref.updated_at && parseInstant(ref.updated_at) ? formatTime(parseInstant(ref.updated_at)!, zone) : null;
            return (
              <li key={`${ref.type}:${ref.id}`}>
                {ref.href ? (
                  <RacLink href={ref.href} className={linkClasses}>
                    {ref.label}
                  </RacLink>
                ) : (
                  <span>{ref.label}</span>
                )}
                {updated ? <span> · {m.item.updatedAt(updated)}</span> : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </article>
  );
}

function PrimaryControl({
  item,
  action,
  onCommand,
  pending,
}: {
  item: BriefingItem;
  action: BriefingAction;
  onCommand: BriefingItemRowProps["onCommand"];
  pending: boolean;
}) {
  const label = actionLabel(action);
  if (isNavigationAction(action) && action.href) {
    return (
      <LinkButton href={action.href} variant="primary">
        {label}
      </LinkButton>
    );
  }
  return (
    <Button variant="primary" onPress={() => onCommand(item, action)} isPending={pending}>
      {label}
    </Button>
  );
}
