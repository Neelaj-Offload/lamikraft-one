"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";
import { demoSpeech, type SpeechPort } from "./speech";

/**
 * Which voice "Listen to my day" speaks with. Until the voice lane's `useSpeech()` (src/lib/voice/) is wired here
 * by the integrator, every Listen session uses the labelled Demo voice.
 */
const SpeechContext = createContext<SpeechPort | null>(null);

export function SpeechProvider({ speech, children }: { speech: SpeechPort; children: ReactNode }) {
  return <SpeechContext.Provider value={speech}>{children}</SpeechContext.Provider>;
}

export function useSpeechPort(): SpeechPort {
  const provided = useContext(SpeechContext);
  const fallback = useMemo(() => demoSpeech(), []);
  return provided ?? fallback;
}
