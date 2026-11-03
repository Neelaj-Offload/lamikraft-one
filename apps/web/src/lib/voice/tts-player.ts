/**
 * Spoken replies (design §14): optional, and stopped at once by push-to-talk, typing or Stop.
 * `stop()` calls `pause()` synchronously and the state becomes `stopped` before anything else
 * happens, so an interrupt can never race the end of playback.
 */

export type TtsState = "idle" | "loading" | "playing" | "stopped" | "ended" | "failed";

export interface AudioLike {
  src: string;
  play: () => Promise<void> | void;
  pause: () => void;
  currentTime: number;
  onended: ((this: GlobalEventHandlers, ev: Event) => unknown) | null;
  onerror: OnErrorEventHandler;
}

export class TtsPlayer {
  private audio: AudioLike | null = null;
  private current: TtsState = "idle";
  private readonly listeners = new Set<(state: TtsState) => void>();

  constructor(private readonly createAudio: () => AudioLike = () => new Audio()) {}

  get state(): TtsState {
    return this.current;
  }

  subscribe(listener: (state: TtsState) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private set(state: TtsState): void {
    this.current = state;
    for (const listener of this.listeners) listener(state);
  }

  /** Plays a same-origin, session-authenticated URL; a previous reply is stopped first. */
  async play(url: string): Promise<void> {
    this.stop();
    const audio = this.createAudio();
    this.audio = audio;
    this.set("loading");
    audio.onended = () => {
      if (this.audio === audio) this.set("ended");
    };
    audio.onerror = () => {
      if (this.audio === audio && this.current !== "stopped") this.set("failed");
    };
    audio.src = url;
    try {
      await audio.play();
      if (this.audio === audio && this.current === "loading") this.set("playing");
    } catch {
      if (this.audio === audio && this.current !== "stopped") this.set("failed");
    }
  }

  /** Interrupt: pause immediately; the state is `stopped` when this returns. */
  stop(): void {
    const audio = this.audio;
    if (!audio) return;
    audio.pause();
    try {
      audio.currentTime = 0;
    } catch {
      // some engines refuse seeking before metadata; the pause above already stopped the sound
    }
    this.audio = null;
    if (this.current === "loading" || this.current === "playing") this.set("stopped");
  }

  get speaking(): boolean {
    return this.current === "loading" || this.current === "playing";
  }
}
