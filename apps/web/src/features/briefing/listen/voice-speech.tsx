"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
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

/**
 * One stable port whose calls go to the voice chosen by the latest capabilities. Stable on purpose: Listen builds
 * its session per port, so swapping the port when the capabilities arrive would drop a session that had already
 * started (found by the Slice-3 stage-2 e2e: a Listen pressed before they arrived stayed "Preparing" for ever).
 */
export function delegatingSpeech(current: { readonly current: SpeechPort }): SpeechPort {
  return {
    get label() {
      return current.current.label;
    },
    speak: (text, signal) => current.current.speak(text, signal),
    stop: () => current.current.stop(),
    readback: (values) => current.current.readback(values),
  };
}

export function VoiceSpeechProvider({ children }: { children: ReactNode }) {
  const current = useRef<SpeechPort>(demoSpeech());
  const [, setCaps] = useState<VoiceCapabilities | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetchVoiceCapabilities(controller.signal)
      .then((value) => {
        current.current = speechFor(value);
        setCaps(value);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, []);
  const speech = useMemo(() => delegatingSpeech(current), []);
  return <SpeechProvider speech={speech}>{children}</SpeechProvider>;
}
