/**
 * The narrow speech interface "Listen to my day" needs (voice lane contract: `POST /api/v1/voice/speech`
 * `{text} -> {url}`, and the web `useSpeech()` hook under `src/lib/voice/` with `speak(text)` / `stop()`).
 *
 * Today speaks through the voice module (`voice-speech.tsx`, `POST /api/v1/voice/speech`, Demo TTS by default;
 * Slice-3 stage-2 merge). `demoSpeech()` is the fallback when the person may not use spoken replies: a labelled,
 * silent clip whose length follows the text, so the whole Listen flow still runs.
 * Nothing here pretends to be a voice: the player labels the clip "Demo voice" and shows the words being read.
 */

export interface SpeechClip {
  /** Audio to play; a silent clip carries no audio at all and is timed instead. */
  url: string | null;
  /** How long the clip lasts (the Demo's estimate, or the real clip's duration when known). */
  durationMs: number;
  /** True for the Demo's silent clip: played by a timer, never through an audio element. */
  silent: boolean;
}

export interface SpeechPort {
  /** Shown next to the player ("Demo voice"); null for a real voice. */
  readonly label: string | null;
  /** Synthesise one segment. Rejects when the voice service is unavailable. */
  speak(text: string, signal?: AbortSignal): Promise<SpeechClip>;
  /** Cancel any synthesis in flight (playback is stopped by the player). */
  stop(): void;
  /**
   * Read back the consequential values before a confirmation by voice (voice lane `readback` contract):
   * the text spoken back to the person. The Demo returns the sentence and synthesises it like any other.
   */
  readback(values: readonly string[]): string;
}

/** Roughly 15 characters a second, the pace of calm speech; bounded so a segment never runs away. */
export function estimateDurationMs(text: string): number {
  const chars = text.trim().length;
  return Math.min(12_000, Math.max(1_200, Math.round((chars / 15) * 1000)));
}

export function readbackSentence(values: readonly string[]): string {
  const parts = values.map((value) => value.trim()).filter(Boolean);
  return parts.length > 0 ? `To confirm: ${parts.join(", ")}.` : "To confirm.";
}

export function demoSpeech(): SpeechPort {
  return {
    label: "Demo voice",
    speak(text, signal) {
      if (signal?.aborted) return Promise.reject(new DOMException("Aborted", "AbortError"));
      return Promise.resolve({ url: null, durationMs: estimateDurationMs(text), silent: true });
    },
    stop() {},
    readback: readbackSentence,
  };
}

/**
 * Plays one clip with pause/resume. Silent clips are timed (no audio element, nothing to decode); real clips
 * use an `Audio` element. `play` resolves when the clip ends and rejects with an AbortError when stopped.
 */
export interface ClipPlayer {
  play(clip: SpeechClip): Promise<void>;
  pause(): void;
  resume(): void;
  stop(): void;
}

export function createClipPlayer(now: () => number = () => performance.now()): ClipPlayer {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let audio: HTMLAudioElement | null = null;
  let remaining = 0;
  let startedAt = 0;
  let finish: (() => void) | null = null;
  let abort: ((reason: unknown) => void) | null = null;

  const clear = () => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  };
  const arm = () => {
    clear();
    startedAt = now();
    timer = setTimeout(() => finish?.(), remaining);
  };

  return {
    play(clip) {
      this.stop();
      return new Promise<void>((resolve, reject) => {
        finish = () => {
          clear();
          finish = abort = null;
          audio = null;
          resolve();
        };
        abort = reject;
        if (clip.silent || !clip.url) {
          remaining = clip.durationMs;
          arm();
          return;
        }
        audio = new Audio(clip.url);
        audio.addEventListener("ended", () => finish?.(), { once: true });
        audio.addEventListener("error", () => {
          const fail = abort;
          finish = abort = null;
          audio = null;
          fail?.(new Error("The clip could not be played."));
        }, { once: true });
        void audio.play().catch((error: unknown) => {
          if (error instanceof DOMException && error.name === "NotAllowedError" && finish) {
            // the browser blocked playback without a fresh gesture: keep the session's timing (the words are on screen)
            audio = null;
            remaining = clip.durationMs;
            arm();
            return;
          }
          const fail = abort;
          finish = abort = null;
          audio = null;
          fail?.(error);
        });
      });
    },
    pause() {
      if (audio) {
        audio.pause();
        return;
      }
      if (timer !== null) {
        remaining = Math.max(0, remaining - (now() - startedAt));
        clear();
      }
    },
    resume() {
      if (audio) {
        void audio.play();
        return;
      }
      if (finish && timer === null) arm();
    },
    stop() {
      clear();
      if (audio) {
        audio.pause();
        audio = null;
      }
      const fail = abort;
      finish = abort = null;
      fail?.(new DOMException("Stopped", "AbortError"));
    },
  };
}
