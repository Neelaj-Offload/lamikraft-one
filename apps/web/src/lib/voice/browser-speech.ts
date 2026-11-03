/**
 * The browser fallback (labelled "Browser fallback", off unless the server enables it): the
 * browser's own speech recognition. Interim results are partial transcripts — shown greyed and
 * never submittable; only the final result becomes an utterance (posted to the server as text).
 */

export interface BrowserRecognition {
  stop: () => void;
  cancel: () => void;
}

interface RecognitionLike {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((event: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string; confidence: number }> & { isFinal: boolean }> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
}

type RecognitionCtor = new () => RecognitionLike;

function recognitionCtor(): RecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function browserRecognitionSupported(): boolean {
  return recognitionCtor() !== null;
}

/** BCP 47 for the browser engine; Hinglish is recognised as Hindi (India) — labelled untested. */
export function browserLanguage(code: string): string {
  return code === "hinglish" ? "hi-IN" : code;
}

export interface RecognitionCallbacks {
  onPartial: (text: string) => void;
  onFinal: (text: string, confidence: number | null) => void;
  onError: (problem: "denied" | "no_device" | "unavailable") => void;
}

export function startBrowserRecognition(language: string, callbacks: RecognitionCallbacks): BrowserRecognition | null {
  const Ctor = recognitionCtor();
  if (!Ctor) return null;
  const recognition = new Ctor();
  recognition.lang = browserLanguage(language);
  recognition.interimResults = true;
  recognition.continuous = false;
  let finalText = "";
  let confidence: number | null = null;
  let cancelled = false;
  recognition.onresult = (event) => {
    let partial = "";
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const result = event.results[i]!;
      const best = result[0]!;
      if (result.isFinal) {
        finalText += best.transcript;
        confidence = best.confidence ?? null;
      } else partial += best.transcript;
    }
    callbacks.onPartial((finalText + partial).trim());
  };
  recognition.onerror = (event) => {
    if (cancelled) return;
    callbacks.onError(event.error === "not-allowed" ? "denied" : event.error === "audio-capture" ? "no_device" : "unavailable");
  };
  recognition.onend = () => {
    if (!cancelled && finalText.trim()) callbacks.onFinal(finalText.trim(), confidence);
  };
  recognition.start();
  return {
    stop: () => recognition.stop(),
    cancel: () => {
      cancelled = true;
      recognition.abort();
    },
  };
}
