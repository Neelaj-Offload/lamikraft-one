/**
 * Push-to-talk recording (design §14): MediaRecorder over the microphone, at most 60 s, with a
 * live input level for the waveform. Mic errors are mapped to the two cases the UI explains
 * (`NotAllowedError` → denied, `NotFoundError` → no microphone); anything else is "unavailable".
 * `cancel()` discards everything recorded; nothing leaves the browser until `stop()` resolves
 * and the caller uploads the blob.
 */

export const MAX_RECORDING_MS = 60_000;
export const PREFERRED_TYPES = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4", "audio/webm"] as const;

export type MicProblem = "denied" | "no_device" | "unsupported" | "unavailable";

export class MicError extends Error {
  constructor(readonly problem: MicProblem, message?: string) {
    super(message ?? problem);
    this.name = "MicError";
  }
}

/** Maps a getUserMedia / MediaRecorder failure to what the person can do about it. */
export function micProblemOf(error: unknown): MicProblem {
  const name = error && typeof error === "object" && "name" in error ? String((error as { name: unknown }).name) : "";
  if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError") return "denied";
  if (name === "NotFoundError" || name === "DevicesNotFoundError" || name === "OverconstrainedError") return "no_device";
  if (name === "NotSupportedError" || name === "TypeError") return "unsupported";
  return "unavailable";
}

export interface Recording {
  blob: Blob;
  mimeType: string;
  durationMs: number;
}

export interface RecorderEnv {
  getUserMedia?: (constraints: MediaStreamConstraints) => Promise<MediaStream>;
  MediaRecorder?: typeof MediaRecorder;
  AudioContext?: typeof AudioContext;
  now?: () => number;
}

function defaultEnv(): RecorderEnv {
  if (typeof window === "undefined") return {};
  const nav = window.navigator;
  return {
    getUserMedia: nav.mediaDevices?.getUserMedia ? (c) => nav.mediaDevices.getUserMedia(c) : undefined,
    MediaRecorder: typeof window.MediaRecorder === "function" ? window.MediaRecorder : undefined,
    AudioContext: typeof window.AudioContext === "function" ? window.AudioContext : undefined,
    now: () => performance.now(),
  };
}

export function pickMimeType(Recorder: Pick<typeof MediaRecorder, "isTypeSupported"> | undefined): string | undefined {
  if (!Recorder?.isTypeSupported) return undefined;
  return PREFERRED_TYPES.find((type) => Recorder.isTypeSupported(type));
}

export interface RecorderHandle {
  /** Resolves with the recording; rejects with MicError if nothing usable was captured. */
  stop: () => Promise<Recording>;
  /** Discards the recording (Esc / Cancel). */
  cancel: () => void;
}

export interface StartOptions {
  /** 0..1 input level, about 20 times a second while recording (drives the waveform). */
  onLevel?: (level: number) => void;
  /** Called when the 60 s limit stops the recording on its own. */
  onLimit?: () => void;
  env?: RecorderEnv;
}

export async function startRecording(options: StartOptions = {}): Promise<RecorderHandle> {
  const env = options.env ?? defaultEnv();
  if (!env.getUserMedia || !env.MediaRecorder) throw new MicError("unsupported");
  let stream: MediaStream;
  try {
    stream = await env.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  } catch (error) {
    throw new MicError(micProblemOf(error));
  }
  const now = env.now ?? (() => Date.now());
  const mimeType = pickMimeType(env.MediaRecorder);
  let recorder: MediaRecorder;
  try {
    recorder = mimeType ? new env.MediaRecorder(stream, { mimeType }) : new env.MediaRecorder(stream);
  } catch (error) {
    stream.getTracks().forEach((track) => track.stop());
    throw new MicError(micProblemOf(error));
  }
  const chunks: Blob[] = [];
  const startedAt = now();
  let cancelled = false;
  recorder.ondataavailable = (event: BlobEvent) => {
    if (event.data && event.data.size > 0) chunks.push(event.data);
  };

  let levelTimer: ReturnType<typeof setInterval> | null = null;
  let audioContext: AudioContext | null = null;
  if (options.onLevel && env.AudioContext) {
    try {
      audioContext = new env.AudioContext();
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      audioContext.createMediaStreamSource(stream).connect(analyser);
      const samples = new Uint8Array(analyser.fftSize);
      levelTimer = setInterval(() => {
        analyser.getByteTimeDomainData(samples);
        let peak = 0;
        for (const value of samples) peak = Math.max(peak, Math.abs(value - 128));
        options.onLevel?.(Math.min(1, peak / 64));
      }, 50);
    } catch {
      audioContext = null;
    }
  }

  const release = () => {
    if (levelTimer) clearInterval(levelTimer);
    levelTimer = null;
    void audioContext?.close().catch(() => undefined);
    audioContext = null;
    stream.getTracks().forEach((track) => track.stop());
  };

  const stopped = new Promise<Recording>((resolve, reject) => {
    recorder.onstop = () => {
      release();
      if (cancelled) return reject(new MicError("unavailable", "cancelled"));
      const type = recorder.mimeType || mimeType || "audio/webm";
      const blob = new Blob(chunks, { type });
      if (blob.size === 0) return reject(new MicError("unavailable", "empty"));
      resolve({ blob, mimeType: type, durationMs: Math.min(MAX_RECORDING_MS, Math.floor(0.5 + now() - startedAt)) });
    };
    recorder.onerror = () => {
      release();
      reject(new MicError("unavailable"));
    };
  });
  stopped.catch(() => undefined); // a cancelled recording is not an unhandled rejection

  const limit = setTimeout(() => {
    if (recorder.state === "recording") {
      options.onLimit?.();
      recorder.stop();
    }
  }, MAX_RECORDING_MS);
  recorder.start(250);

  return {
    stop: () => {
      clearTimeout(limit);
      if (recorder.state === "recording") recorder.stop();
      return stopped;
    },
    cancel: () => {
      clearTimeout(limit);
      cancelled = true;
      if (recorder.state === "recording") recorder.stop();
      else release();
    },
  };
}
