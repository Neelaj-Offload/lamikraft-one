"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";
import { demoSpeech, type SpeechPort } from "./speech";

/**
 * Which voice "Listen to my day" speaks with. Today mounts `VoiceSpeechProvider` (voice module TTS); without a
 * provider, Listen uses the labelled silent Demo voice.
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
