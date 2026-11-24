"use client";

import type { Route } from "next";
import Link from "next/link";
import { useId } from "react";
import type { BriefingAction, BriefingItem } from "@/features/briefing/types";
import { formatDayTime, formatTime, parseInstant, type ZoneOptions } from "@/lib/format/time";
import {
  actionText,
  dueText,
  isCommandAction,
  isNavigationAction,
  itemHref,
  itemTone,
  kindLabel,
  primaryAction,
  secondaryActions,
  uncertaintyText,
  type ItemCommands,
} from "~/data/today";
import { riseAt } from "./rise";
import { Badge, Button, ButtonLink, IconButton, Menu, TextLink, type MenuItem } from "~/ui";
import type { IconName } from "~/ui/icon";

const ACTION_ICON: Record<string, IconName> = {
  open: "arrowUpRight",
  review: "eye",
  prepare: "edit",
  assign: "userPlus",
  snooze: "clock",
  unsnooze: "undo",
  mark_handled: "check",
  dismiss: "xCircle",
  explain: "help",
};

/**
 * The controls of one item: the server's primary action as a button, everything else it allowed
 * in a menu. Only actions the web can carry out are offered. `emphasis` marks the single gold
 * button of a screen; every other primary control is an ink pill.
 */
export function ItemActions({
  item,
  commands,
  emphasis = false,
  size = "md",
  hideExplain = false,
}: {
  item: BriefingItem;
  commands: ItemCommands;
  emphasis?: boolean;
  size?: "sm" | "md";
  /** On the item's own screen the explanation is already on the page. */
  hideExplain?: boolean;
}) {
  const primary = primaryAction(item);
  const secondary = secondaryActions(item).filter((action) => !(hideExplain && action.action === "explain"));
  if (!primary && secondary.length === 0) return null;
  const busyHere = commands.pending?.issueId === item.issue_id ? commands.pending.action : null;
  const blocked = (action: BriefingAction) => isCommandAction(action) && commands.disabledReason !== null;
  const variant = emphasis ? "primary" : "inverse";

  const menu: MenuItem[] = secondary.map((action) => ({
    id: action.action,
    label: actionText(action),
    icon: ACTION_ICON[action.action],
    ...(isNavigationAction(action) && action.href ? { href: action.href as Route } : { onAction: () => commands.run(item, action) }),
    isDisabled: blocked(action) || commands.pending !== null,
  }));

  return (
    <div className="flex shrink-0 items-center gap-2">
      {primary ? (
        isNavigationAction(primary) && primary.href ? (
          <ButtonLink href={primary.href as Route} variant={variant} size={size} iconRight="arrowRight">
            {actionText(primary)}
          </ButtonLink>
        ) : (
          <Button
            variant={primary.action === "explain" ? "secondary" : variant}
            size={size}
            loading={busyHere === primary.action}
            isDisabled={blocked(primary) || (commands.pending !== null && busyHere !== primary.action)}
            onPress={() => commands.run(item, primary)}
          >
            {actionText(primary)}
          </Button>
        )
      ) : null}
      {menu.length > 0 ? (
        <Menu
          label={`More actions for ${item.title}`}
          items={menu}
          trigger={<IconButton icon="more" label={`More actions for ${item.title}`} variant="ghost" size={size} />}
        />
      ) : null}
    </div>
  );
}

/** The quiet line above a title: what kind of thing it is, when it is due, what is new about it. */
export function ItemSignals({ item, now, zone }: { item: BriefingItem; now: Date; zone: ZoneOptions }) {
  const due = dueText(item, now, zone);
  const snoozed = item.snoozed_until ? formatDayTime(item.snoozed_until, now, zone) : null;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <Badge tone={itemTone(item)} dot>
        {kindLabel(item)}
      </Badge>
      {due ? (
        <span className={item.overdue ? "t-label lk-tnum text-ember-text" : "t-label lk-tnum text-ink-2"}>{due}</span>
      ) : null}
      {snoozed ? <span className="t-label lk-tnum text-ink-2">Snoozed until {snoozed}</span> : null}
      {item.change_kind === "new" ? (
        <Badge tone="gold" size="sm">
          New
        </Badge>
      ) : null}
      {item.change_kind === "changed" ? (
        <Badge tone="cobalt" size="sm">
          Changed
        </Badge>
      ) : null}
      {item.on_behalf_of ? (
        <Badge size="sm" outline icon="user">
          For {item.on_behalf_of.display_name}
        </Badge>
      ) : null}
      {item.member_count > 1 ? <span className="t-caption text-ink-3">{item.member_count} related</span> : null}
    </div>
  );
}

/** The records an item rests on, as links to their own screens. */
export function EvidenceLinks({ item, zone, limit }: { item: BriefingItem; zone: ZoneOptions; limit?: number }) {
  const refs = limit ? item.source_refs.slice(0, limit) : item.source_refs;
  if (refs.length === 0) return null;
  const more = item.source_refs.length - refs.length;
  return (
    <ul aria-label="Evidence" className="t-body-sm m-0 flex list-none flex-wrap items-center gap-x-4 gap-y-1 p-0">
      {refs.map((ref) => {
        const updated = parseInstant(ref.updated_at);
        return (
          <li key={`${ref.type}:${ref.id}`} className="flex items-baseline gap-2">
            {ref.href ? <TextLink href={ref.href as Route}>{ref.label}</TextLink> : <span className="text-ink-2">{ref.label}</span>}
            {updated ? <span className="lk-tnum text-ink-3">updated {formatTime(updated, zone)}</span> : null}
          </li>
        );
      })}
      {more > 0 ? <li className="text-ink-3">and {more} more</li> : null}
    </ul>
  );
}

export interface ItemRowProps {
  item: BriefingItem;
  now: Date;
  zone: ZoneOptions;
  /** Omit for a read-only row (the last briefing shown while today's could not be prepared). */
  commands?: ItemCommands;
  /** The single most important item on the screen: its action is the gold button. */
  emphasis?: boolean;
  index?: number;
}

/**
 * One briefing item in a group: what it is, the facts, the suggested next step, the records
 * behind it and its action. The title opens the item's own screen, where the reasoning lives.
 */
export function ItemRow({ item, now, zone, commands, emphasis = false, index = 0 }: ItemRowProps) {
  const titleId = useId();
  const suggested = item.recommendation ? (item.recommendation.display_text ?? item.recommendation.label) : null;
  // A suggestion that only repeats the title says nothing new.
  const suggestion = suggested && suggested.trim().toLowerCase() !== item.title.trim().toLowerCase() ? suggested : null;
  return (
    <li className="rise-plain border-line border-t first:border-t-0" style={riseAt(index)}>
      <article aria-labelledby={titleId} className="flex flex-col gap-4 p-5 md:flex-row md:items-start md:justify-between md:gap-8 md:p-6">
        <div className="flex min-w-0 flex-col gap-3">
          <ItemSignals item={item} now={now} zone={zone} />
          <div className="flex flex-col gap-1">
            <h3 id={titleId} className="t-h3">
              {commands ? (
                <Link href={itemHref(item.issue_id) as Route} className="text-ink no-underline underline-offset-4 hover:underline">
                  {item.title}
                </Link>
              ) : (
                item.title
              )}
            </h3>
            {item.summary_text ? <p className="t-body lk-tnum text-ink-2">{item.summary_text}</p> : null}
          </div>
          {suggestion ? (
            <p className="t-body-sm border-line-strong text-ink-2 border-l-2 pl-3">
              <span className="t-label text-ink">Suggested: </span>
              {suggestion}
            </p>
          ) : null}
          {item.uncertainty_flags.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {item.uncertainty_flags.map((flag) => (
                <Badge key={flag.code} tone="amber" size="sm" icon="alert">
                  {uncertaintyText(flag)}
                </Badge>
              ))}
            </div>
          ) : null}
          <EvidenceLinks item={item} zone={zone} limit={3} />
        </div>
        {commands ? <ItemActions item={item} commands={commands} emphasis={emphasis} /> : null}
      </article>
    </li>
  );
}

/** A one-line item for the quieter groups (handled for you, coming next). */
export function CompactItem({ item, now, zone, index = 0 }: { item: BriefingItem; now: Date; zone: ZoneOptions; index?: number }) {
  const due = dueText(item, now, zone);
  return (
    <li className="rise-plain border-line relative flex flex-col gap-1 border-t px-5 py-4 first:border-t-0" style={riseAt(index)}>
      <Link href={itemHref(item.issue_id) as Route} className="stretched t-h4 text-ink no-underline underline-offset-4 hover:underline">
        {item.title}
      </Link>
      <span className="t-body-sm text-ink-3">
        {kindLabel(item)}
        {due ? <span className={item.overdue ? "lk-tnum text-ember-text" : "lk-tnum"}> · {due}</span> : null}
      </span>
    </li>
  );
}
