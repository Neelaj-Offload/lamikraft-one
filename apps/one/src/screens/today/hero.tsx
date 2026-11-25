"use client";

import type { ReactNode } from "react";
import { useSession } from "@/lib/session/context";
import { riseAt } from "./rise";

const PERIOD_WORD = { morning: "Good morning", afternoon: "Good afternoon", evening: "Good evening" } as const;

/**
 * The opening of the day: the date, a serif greeting with the person's name, one sentence that
 * says where the day stands, the quiet facts about the briefing itself, and the day's counts
 * beside it. Each part rises in turn. The greeting comes from the session, so it is on screen
 * before the briefing arrives.
 */
export function TodayHero({
  date,
  lead,
  meta,
  actions,
  aside,
}: {
  date: string;
  lead: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  /** The day at a glance: sits beside the greeting from 1024px, under it on smaller screens. */
  aside?: ReactNode;
}) {
  const { bootstrap } = useSession();
  const firstName = bootstrap.user.display_name.trim().split(/\s+/)[0] ?? "";
  const period = bootstrap.greeting_period ? PERIOD_WORD[bootstrap.greeting_period] : null;
  return (
    <header className="grid gap-6 pt-2 md:pt-6 lg:grid-cols-[minmax(0,1fr)_380px] lg:items-end lg:gap-10">
      <div className="flex min-w-0 flex-col gap-3">
        <p className="t-overline page-eyebrow rise" style={riseAt(0)}>
          {date}
        </p>
        <h1 className="t-display-lg rise" style={riseAt(1)}>
          {period && firstName ? (
            <>
              {period}, <em>{firstName}</em>.
            </>
          ) : (
            "Today"
          )}
        </h1>
        <div className="t-body-lg text-ink-2 rise max-w-[52ch]" style={riseAt(2)}>
          {lead}
        </div>
        {meta ? (
          <div className="t-body-sm text-ink-3 rise flex flex-wrap items-center gap-x-3 gap-y-2" style={riseAt(3)}>
            {meta}
          </div>
        ) : null}
        {actions ? (
          <div className="rise mt-2 flex flex-wrap items-center gap-2" style={riseAt(4)}>
            {actions}
          </div>
        ) : null}
      </div>
      {aside ? (
        <div className="rise" style={riseAt(3)}>
          {aside}
        </div>
      ) : null}
    </header>
  );
}
