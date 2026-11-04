"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { createSpeech, fetchVoiceCapabilities, type SpeechOut, type VoiceCapabilities } from "@/lib/voice/api";
import { demoSpeech, readbackSentence, type SpeechPort } from "./speech";
import { SpeechProvider } from "./speech-context";

/**
 * "Listen to my day" through the voice module (briefings request 1, Slice-3 stage-2 merge): each segment is
 * synthesised by `POST /api/v1/voice/speech` (owner-only, same-origin clip, valid five minutes) and played
 * through an audio element. The Demo TTS adapter stays the default voice and is labelled "Demo voice"; a vendor
 * voice carries no label. People who may not use spoken replies (`can_speak`), or a TTS that is off or not
 * configured, keep the labelled silent Demo voice so Listen still works.
 */
export function voiceSpeech(options: { demo: boolean }, synthesise: (text: string) => Promise<SpeechOut> = (text) => createSpeech(text)): SpeechPort {
  const aborted = () => new DOMException("Aborted", "AbortError");
  return {
    label: options.demo ? "Demo voice" : null,
    async speak(text, signal) {
      if (signal?.aborted) throw aborted();
      const out = await synthesise(text.slice(0, 1000)); // the speech endpoint takes at most 1,000 characters
      if (signal?.aborted) throw aborted();
      return { url: out.url, durationMs: out.duration_ms, silent: false };
    },
    stop() {},
    readback: readbackSentence,
  };
}

export function speechFor(caps: VoiceCapabilities | null): SpeechPort {
  if (!caps || !caps.can_speak || (caps.tts.status !== "demo" && caps.tts.status !== "configured")) return demoSpeech();
  return voiceSpeech({ demo: caps.tts.status === "demo" });
}

export function VoiceSpeechProvider({ children }: { children: ReactNode }) {
  const [caps, setCaps] = useState<VoiceCapabilities | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetchVoiceCapabilities(controller.signal)
      .then(setCaps)
      .catch(() => setCaps(null));
    return () => controller.abort();
  }, []);
  const speech = useMemo(() => speechFor(caps), [caps]);
  return <SpeechProvider speech={speech}>{children}</SpeechProvider>;
}
