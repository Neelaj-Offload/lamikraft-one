"use client";

import { useEffect, useMemo, useState } from "react";
import { createIdempotencyKey } from "@/lib/api/client";
import { ProblemError } from "@/lib/api/errors";
import { createVoicePin, fetchPinScript, updatePin, type WireNarration, type WireNarrationSegment, type WirePin } from "../slice3-api";
import { createClipPlayer, type ClipPlayer, type SpeechPort } from "./speech";

/**
 * "Listen to my day" (briefing.md §13). Pressing Listen pins the version on screen (`POST …/pins`), so the
 * list cannot re-sort while it is read; the server returns the narration in the pin's order and the segments
 * are spoken one by one through the speech port. Pause, resume and stop act on the player immediately and are
 * recorded on the pin (`PATCH …/pins/{id}`, with the position). Finishing marks the pin completed, which
 * acknowledges the heard version on the server. Leaving the page stops the pin.
 */
export type ListenPhase = "idle" | "starting" | "speaking" | "paused" | "finished" | "error";

export interface ListenState {
  phase: ListenPhase;
  pinId: string | null;
  pinnedVersion: number | null;
  segments: WireNarrationSegment[];
  /** The segment being spoken (or paused on). */
  index: number;
  aiStatus: string | null;
  error: string | null;
}

export const IDLE_LISTEN: ListenState = { phase: "idle", pinId: null, pinnedVersion: null, segments: [], index: 0, aiStatus: null, error: null };

export function spokenText(segment: WireNarrationSegment): string {
  return [segment.lead, segment.text].map((part) => part.trim()).filter(Boolean).join(" ");
}

export interface ListenApi {
  createPin(briefingId: string): Promise<WirePin>;
  fetchScript(pinId: string, signal?: AbortSignal): Promise<WireNarration>;
  updatePin(pinId: string, change: { state?: "active" | "paused" | "stopped" | "completed"; position?: number }): Promise<unknown>;
}

export const listenApi: ListenApi = {
  createPin: (briefingId) => createVoicePin(briefingId, createIdempotencyKey()),
  fetchScript: (pinId, signal) => fetchPinScript(pinId, signal),
  updatePin: (pinId, change) => updatePin(pinId, change),
};

export interface ListenSession {
  readonly state: ListenState;
  start(briefingId: string): Promise<void>;
  pause(): void;
  resume(): void;
  stop(): void;
  reset(): void;
  /** Leaving the page: stop without notifying. */
  dispose(): void;
  setOnEnded(fn: ((how: "completed" | "stopped") => void) | undefined): void;
}

/**
 * The Listen state machine without React (so it is testable in node): ``onChange`` receives every new state and
 * ``onEnded`` fires once after completion (the heard version is acknowledged) or a stop.
 */
export function createListenSession(deps: {
  api: ListenApi;
  speech: SpeechPort;
  player: ClipPlayer;
  onChange: (state: ListenState) => void;
  onEnded?: (how: "completed" | "stopped") => void;
}): ListenSession {
  let state = IDLE_LISTEN;
  let onEnded = deps.onEnded;
  let run = 0;
  let live: { pinId: string; aborter: AbortController } | null = null;
  const set = (next: Partial<ListenState> | ListenState) => {
    state = { ...state, ...next };
    deps.onChange(state);
  };
  const record = (pinId: string, change: Parameters<ListenApi["updatePin"]>[1]) => {
    // Best effort: playback never waits for the server; a lost update only affects the stored position.
    void deps.api.updatePin(pinId, change).catch(() => undefined);
  };

  const speakFrom = async (token: number, pinId: string, segments: WireNarrationSegment[], aborter: AbortController) => {
    for (let index = 0; index < segments.length; index += 1) {
      if (run !== token) return;
      set({ index, phase: state.phase === "paused" ? "paused" : "speaking" });
      try {
        const clip = await deps.speech.speak(spokenText(segments[index]!), aborter.signal);
        if (run !== token) return;
        await deps.player.play(clip);
        if (run !== token) return;
      } catch (error) {
        if (run !== token) return;
        if (error instanceof DOMException && error.name === "AbortError") return;
        run += 1;
        live = null;
        record(pinId, { state: "stopped", position: index });
        set({ phase: "error", error: "The voice is unavailable. The list below is unchanged." });
        return;
      }
      if (index < segments.length - 1) record(pinId, { position: index + 1 });
    }
    if (run !== token) return;
    live = null;
    try {
      await deps.api.updatePin(pinId, { state: "completed", position: segments.length - 1 });
    } catch {
      // The heard version stays unacknowledged; nothing else depends on it.
    }
    set({ phase: "finished" });
    onEnded?.("completed");
  };

  return {
    get state() {
      return state;
    },
    async start(briefingId) {
      if (live || state.phase === "starting") return;
      const token = ++run;
      const aborter = new AbortController();
      set({ ...IDLE_LISTEN, phase: "starting" });
      try {
        const pin = await deps.api.createPin(briefingId);
        const script = await deps.api.fetchScript(pin.id, aborter.signal);
        if (run !== token) {
          record(pin.id, { state: "stopped" });
          return;
        }
        live = { pinId: pin.id, aborter };
        set({ phase: "speaking", pinId: pin.id, pinnedVersion: script.pinned_version, segments: script.segments, index: 0, aiStatus: script.ai_status, error: null });
        void speakFrom(token, pin.id, script.segments, aborter);
      } catch (error) {
        if (run !== token) return;
        set({ ...IDLE_LISTEN, phase: "error", error: error instanceof ProblemError ? (error.detail ?? error.title) : "Listening could not start." });
      }
    },
    pause() {
      if (!live || state.phase !== "speaking") return;
      deps.player.pause();
      record(live.pinId, { state: "paused", position: state.index });
      set({ phase: "paused" });
    },
    resume() {
      if (!live || state.phase !== "paused") return;
      record(live.pinId, { state: "active" });
      deps.player.resume();
      set({ phase: "speaking" });
    },
    stop() {
      const current = live;
      run += 1;
      live = null;
      deps.player.stop();
      deps.speech.stop();
      if (current) {
        current.aborter.abort();
        const position = state.index;
        set(IDLE_LISTEN);
        // refresh only once the pin has ended on the server, else Today would be served the pinned version again
        void deps.api
          .updatePin(current.pinId, { state: "stopped", position })
          .catch(() => undefined)
          .then(() => onEnded?.("stopped"));
      } else {
        set(IDLE_LISTEN);
      }
    },
    reset() {
      if (!live) set(IDLE_LISTEN);
    },
    setOnEnded(fn) {
      onEnded = fn;
    },
    dispose() {
      const current = live;
      run += 1;
      live = null;
      deps.player.stop();
      if (current) {
        current.aborter.abort();
        record(current.pinId, { state: "stopped" });
      }
    },
  };
}

export interface UseListenOptions {
  briefingId: string | null;
  speech: SpeechPort;
  /** After the pin completed (the heard version is acknowledged) or stopped: refresh Today. */
  onEnded?: (how: "completed" | "stopped") => void;
}

export function useListen({ briefingId, speech, onEnded }: UseListenOptions) {
  const [state, setState] = useState<ListenState>(IDLE_LISTEN);
  const session = useMemo(() => createListenSession({ api: listenApi, speech, player: createClipPlayer(), onChange: setState }), [speech]);
  useEffect(() => session.setOnEnded(onEnded), [session, onEnded]);
  // Leaving Today ends the session: the pin is stopped so the list is free to update again.
  useEffect(() => () => session.dispose(), [session]);

  const active = state.phase === "starting" || state.phase === "speaking" || state.phase === "paused";
  return {
    state,
    active,
    start: () => (briefingId ? session.start(briefingId) : Promise.resolve()),
    pause: () => session.pause(),
    resume: () => session.resume(),
    stop: () => session.stop(),
    reset: () => session.reset(),
  };
}
