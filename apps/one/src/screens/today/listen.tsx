"use client";

import type { Route } from "next";
import type { KeyboardEvent } from "react";
import type { ListenState } from "@/features/briefing/listen/use-listen";
import { appLinkFor } from "@/lib/app-links";
import { Aurora, Badge, Button, ButtonLink, GlassPanel, Orb } from "~/ui";

export interface ListenControls {
  state: ListenState;
  active: boolean;
  start: () => Promise<void>;
  pause: () => void;
  resume: () => void;
  stop: () => void;
  reset: () => void;
  readback: string | null;
  readBack: () => Promise<void>;
}

/**
 * "Listen to my day" while it is running: the words being read, where it is in the briefing, and
 * pause, resume and stop. The briefing below is pinned for as long as this is open, so nothing
 * re-sorts under the voice. Escape stops. Renders nothing while idle (the header holds Start).
 */
export function ListenPanel({ listen, voiceLabel }: { listen: ListenControls; voiceLabel: string | null }) {
  const { state } = listen;
  if (state.phase === "idle") return null;
  if (state.phase === "error" && state.segments.length === 0) {
    return (
      <GlassPanel padding="md" className="rise flex flex-wrap items-center justify-between gap-3" role="alert">
        <p className="t-body text-ink">{state.error ?? "Listening could not start."}</p>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" iconLeft="refresh" onPress={() => void listen.start()}>
            Try again
          </Button>
          <Button variant="ghost" size="sm" onPress={listen.reset}>
            Close
          </Button>
        </div>
      </GlassPanel>
    );
  }

  const items = state.segments.filter((segment) => segment.kind === "item");
  const current = state.segments[state.index] ?? null;
  const live = listen.active;
  const where =
    state.phase === "starting"
      ? "Preparing your briefing"
      : current?.kind === "item" && current.ordinal
        ? `Item ${items.findIndex((segment) => segment.issue_id === current.issue_id) + 1} of ${items.length}`
        : current?.kind === "outro"
          ? "Closing"
          : "Overview";
  const status = state.phase === "paused" ? `Paused · ${where}` : state.phase === "finished" ? "Finished. Your briefing is marked as seen." : where;
  const href = current?.path ? appLinkFor(current.path) : null;
  const canReadBack = state.phase === "paused" && current?.kind === "item" && (current.readback ?? []).length > 0;

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape" && live) {
      event.preventDefault();
      listen.stop();
    }
  };

  return (
    <GlassPanel as="section" padding="lg" aria-label="Listen to my day" onKeyDown={onKeyDown} data-phase={state.phase} className="rise overflow-hidden">
      <Aurora quiet />
      <div className="relative flex flex-col gap-5 md:flex-row md:items-start md:gap-6">
        <span aria-hidden="true" className="flex-none">
          <Orb size="md" state={state.phase === "starting" ? "thinking" : state.phase === "speaking" ? "listening" : "idle"} />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-4">
          <div className="flex flex-wrap items-center gap-3">
            <p className="t-overline text-ink-2" role="status">
              {status}
            </p>
            {voiceLabel ? (
              <Badge size="sm" outline>
                {voiceLabel}
              </Badge>
            ) : null}
            {state.aiStatus === "unavailable" ? (
              <Badge size="sm" outline>
                Standard wording
              </Badge>
            ) : null}
          </div>
          {current && state.phase !== "finished" ? (
            <p className="t-display-sm text-ink max-w-[32ch] md:max-w-[44ch]">
              {current.lead ? `${current.lead} ` : null}
              {current.text}
            </p>
          ) : null}
          {state.phase === "error" && state.error ? <p className="t-body-sm text-ember-text">{state.error}</p> : null}
          {listen.readback ? <p className="t-body text-ink-2 max-w-[60ch]">{listen.readback}</p> : null}
          <div className="flex flex-wrap items-center gap-2">
            {live ? (
              // One toggle element, so keyboard focus stays on it between Pause and Resume.
              <Button
                variant="inverse"
                iconLeft={state.phase === "paused" ? "play" : "pause"}
                isDisabled={state.phase === "starting"}
                onPress={state.phase === "paused" ? listen.resume : listen.pause}
              >
                {state.phase === "paused" ? "Resume" : "Pause"}
              </Button>
            ) : null}
            {live ? (
              <Button variant="secondary" iconLeft="stop" onPress={listen.stop}>
                Stop
              </Button>
            ) : null}
            {state.phase === "finished" || state.phase === "error" ? (
              <>
                <Button variant="secondary" iconLeft="play" onPress={() => void listen.start()}>
                  Listen again
                </Button>
                <Button variant="ghost" onPress={listen.reset}>
                  Close
                </Button>
              </>
            ) : null}
            {canReadBack ? (
              <Button variant="secondary" onPress={() => void listen.readBack()}>
                Read back the details
              </Button>
            ) : null}
            {href && live ? (
              <ButtonLink variant="ghost" href={href as Route} iconRight="arrowRight">
                Open this item
              </ButtonLink>
            ) : null}
          </div>
          {live ? <p className="t-caption text-ink-3">The list below stays in this order until you stop.</p> : null}
        </div>
      </div>
    </GlassPanel>
  );
}
