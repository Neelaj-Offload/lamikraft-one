"use client";

import { motion } from "motion/react";
import type { KeyboardEvent } from "react";
import { Badge } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { LinkButton } from "@/components/ui/link";
import { appLinkFor } from "@/lib/app-links";
import { useIsMotionReduced } from "@/lib/motion/use-motion-preference";
import { briefingMessages as m } from "@/messages/briefing";
import type { ListenState } from "./use-listen";

/** Listen controls keep the 44 px target on every pointer (the shared sizes shrink to 32-36 px for a mouse). */
const TARGET = "pointer-fine:min-h-11";
const BARS = [0.45, 0.8, 1, 0.7, 0.5];

/**
 * Live level bars only while speaking (motion-system §2 "Voice recording / speaking waveform"): transform-only,
 * they stop on pause or stop, and under reduced motion they are a static meter. The Demo voice is silent, so the
 * bars show that reading is in progress, not a measured level; the label says it is a demo.
 */
export function SpeakingWaveform({ speaking }: { speaking: boolean }) {
  const reduced = useIsMotionReduced();
  return <WaveformBars moving={speaking && !reduced} />;
}

/** The bars themselves: moving (speaking, motion allowed) or a static level meter. */
export function WaveformBars({ moving }: { moving: boolean }) {
  return (
    <span aria-hidden="true" data-testid="listen-waveform" data-state={moving ? "speaking" : "static"} className="flex h-6 items-center gap-[3px]">
      {BARS.map((height, index) =>
        moving ? (
          <motion.span
            key={index}
            className="block h-6 w-[3px] origin-center rounded-sm bg-forest"
            initial={{ scaleY: height * 0.5 }}
            animate={{ scaleY: [height * 0.5, height, height * 0.35, height * 0.8] }}
            transition={{ duration: 0.9 + index * 0.12, repeat: Number.POSITIVE_INFINITY, repeatType: "mirror", ease: "easeInOut" }}
          />
        ) : (
          <span key={index} className="block h-6 w-[3px] origin-center rounded-sm bg-ink-muted/60" style={{ transform: `scaleY(${height * 0.6})` }} />
        ),
      )}
    </span>
  );
}

export interface ListenPanelProps {
  state: ListenState;
  speechLabel: string | null;
  disabledReason: string | null;
  onStart: () => void;
  onPause: () => void;
  onResume: () => void;
  onStop: () => void;
  onClose: () => void;
}

/**
 * "Listen to my day": play, pause, resume and stop, with the words being read shown as text. Escape stops
 * listening. While it is open the briefing list below is pinned (no re-sorting, no "N updates" pill).
 */
export function ListenPanel({ state, speechLabel, disabledReason, onStart, onPause, onResume, onStop, onClose }: ListenPanelProps) {
  const items = state.segments.filter((segment) => segment.kind === "item");
  const current = state.segments[state.index] ?? null;
  const active = state.phase === "starting" || state.phase === "speaking" || state.phase === "paused";

  if (state.phase === "idle" || (state.phase === "error" && state.segments.length === 0)) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant="secondary"
          className={TARGET}
          onPress={onStart}
          {...unavailableWhen(disabledReason)}
        >
          {m.listen.start}
        </Button>
        {state.phase === "error" && state.error ? <p className="text-sm text-danger-text">{state.error}</p> : null}
      </div>
    );
  }

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape" && active) {
      event.preventDefault();
      onStop();
    }
  };
  const progress =
    current?.kind === "item" && current.ordinal
      ? m.listen.progress(items.findIndex((segment) => segment.issue_id === current.issue_id) + 1, items.length)
      : state.phase === "starting"
        ? m.listen.starting
        : current?.kind === "outro"
          ? m.listen.closing
          : m.listen.overview;
  const href = current?.path ? appLinkFor(current.path) : null;

  return (
    <section
      aria-label={m.listen.region}
      onKeyDown={onKeyDown}
      data-testid="listen-panel"
      data-phase={state.phase}
      className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-4"
    >
      <div className="flex flex-wrap items-center gap-3">
        <SpeakingWaveform speaking={state.phase === "speaking"} />
        <p className="text-sm font-medium text-ink" role="status">
          {state.phase === "paused" ? m.listen.paused(progress) : state.phase === "finished" ? m.listen.finished : progress}
        </p>
        {speechLabel ? <Badge tone="neutral">{speechLabel}</Badge> : null}
        {state.aiStatus === "unavailable" ? <Badge tone="neutral">{m.standardWording}</Badge> : null}
      </div>

      {current && state.phase !== "finished" ? (
        <p className="max-w-3xl text-base text-ink" data-testid="listen-text">
          {current.lead ? <span className="font-medium">{current.lead} </span> : null}
          {current.text}
        </p>
      ) : null}
      {state.phase === "error" && state.error ? <p className="text-sm text-danger-text">{state.error}</p> : null}

      <div className="flex flex-wrap items-center gap-2">
        {active ? (
          // one toggle element, so keyboard focus stays on it between Pause and Resume
          <Button
            variant="primary"
            className={TARGET}
            onPress={state.phase === "paused" ? onResume : onPause}
            {...unavailableWhen(state.phase === "starting" ? m.listen.starting : null)}
          >
            {state.phase === "paused" ? m.listen.resume : m.listen.pause}
          </Button>
        ) : null}
        {active ? (
          <Button variant="secondary" className={TARGET} onPress={onStop}>
            {m.listen.stop}
          </Button>
        ) : null}
        {state.phase === "finished" || state.phase === "error" ? (
          <>
            <Button variant="secondary" className={TARGET} onPress={onStart}>
              {m.listen.again}
            </Button>
            <Button variant="quiet" className={TARGET} onPress={onClose}>
              {m.listen.close}
            </Button>
          </>
        ) : null}
        {href && active ? (
          <LinkButton variant="quiet" className={TARGET} href={href}>
            {m.listen.openCurrent}
          </LinkButton>
        ) : null}
      </div>
    </section>
  );
}
