"use client";

import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { announce } from "@/lib/a11y/announcer";
import { ProblemError } from "@/lib/api/errors";
import { askAboutScreen, fetchVisionCapabilities, removeScreenCapture, uploadScreenCapture, type ScreenAnswer, type ScreenCapture, type VisionCapabilities } from "@/lib/voice/api";
import { CaptureError, captureMaskedScreen } from "@/lib/screen-capture/capture";
import { buildScreenContext } from "@/features/assistant/screen-context";
import { currentContributions } from "@/features/assistant/screen-context-store";
import { voiceMessages } from "@/messages/voice";

const m = voiceMessages.screen;

export interface ScreenShare {
  capabilities: VisionCapabilities | null;
  attached: ScreenCapture | null;
  busy: boolean;
  problem: string | null;
  answer: (ScreenAnswer & { question: string }) | null;
  look: () => Promise<void>;
  remove: () => Promise<void>;
  /** Answers a question about the attached screenshot. True: answered here; false: send it to the assistant. */
  ask: (question: string) => Promise<boolean>;
}

/**
 * "Look at my screen" (ai-routing §4.2): an explicit, one-off masked screenshot of this page,
 * shown as a removable chip and used for the next question only. Nothing is captured in the
 * background; the company switch (`screen_capture.enabled`) hides the control entirely.
 */
export function useScreenShare(enabled: boolean): ScreenShare {
  const pathname = usePathname() ?? "/";
  const [capabilities, setCapabilities] = useState<VisionCapabilities | null>(null);
  const [attached, setAttachedState] = useState<ScreenCapture | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [answer, setAnswer] = useState<ScreenShare["answer"]>(null);
  const attachedRef = useRef<ScreenCapture | null>(null);
  const setAttached = useCallback((value: ScreenCapture | null) => {
    attachedRef.current = value;
    setAttachedState(value);
  }, []);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    fetchVisionCapabilities(controller.signal)
      .then(setCapabilities)
      .catch(() => setCapabilities(null));
    return () => controller.abort();
  }, [enabled]);

  const look = useCallback(async () => {
    setProblem(null);
    if (!capabilities?.screen_capture_enabled) {
      setProblem(m.disabled);
      return;
    }
    setBusy(true);
    announce(m.capturing);
    try {
      const shot = await captureMaskedScreen(document.body);
      if (attachedRef.current?.sha256 === shot.sha256) return; // the same screen is already attached
      const stored = await uploadScreenCapture(shot.blob, { maskedCount: shot.maskedCount, routePath: shot.routePath });
      setAttached(stored);
      setAnswer(null);
      announce(m.chip);
    } catch (error) {
      if (error instanceof CaptureError && error.reason === "too_large") setProblem(m.tooLarge);
      else if (error instanceof ProblemError && error.code === "screen_capture_disabled") setProblem(m.disabled);
      else setProblem(m.failed);
    } finally {
      setBusy(false);
    }
  }, [capabilities, setAttached]);

  const remove = useCallback(async () => {
    const capture = attachedRef.current;
    setAttached(null);
    if (!capture) return;
    announce(m.removed);
    try {
      await removeScreenCapture(capture.id);
    } catch {
      // the capture is purged after 24 hours anyway; the chip is already gone
    }
  }, [setAttached]);

  const ask = useCallback(
    async (question: string) => {
      const capture = attachedRef.current;
      if (!capture) return false;
      setAttached(null); // one screenshot per request
      setBusy(true);
      try {
        const context = buildScreenContext({
          pathname,
          contributions: currentContributions(),
          now: new Date(),
          viewport: { width: window.innerWidth, height: window.innerHeight },
        });
        const result = await askAboutScreen({ capture_id: capture.id, question, context: context as never });
        setAnswer({ ...result, question });
        announce(result.handoff ? m.handedOff : result.text);
        return !result.handoff;
      } catch {
        setProblem(m.failed);
        return false;
      } finally {
        setBusy(false);
      }
    },
    [pathname, setAttached],
  );

  return { capabilities, attached, busy, problem, answer, look, remove, ask };
}
