"use client";

import { useCallback, useEffect, useImperativeHandle, useRef, useState, type Ref, type RefObject } from "react";
import { Button as RacButton } from "react-aria-components";
import { Badge, DemoBadge } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { CloseIcon, EyeIcon, MicIcon } from "@/components/ui/icons";
import { buttonClasses } from "@/components/ui/styles";
import { TextArea } from "@/components/ui/text-field";
import { Switch } from "@/components/ui/choice";
import { uploadFile, purposeFor } from "@/features/collab/api";
import type { UseAssistant } from "@/features/assistant/use-assistant";
import { announce } from "@/lib/a11y/announcer";
import { uuidv7 } from "@/lib/api/client";
import { isNetworkError, ProblemError } from "@/lib/api/errors";
import { useIsMotionReduced } from "@/lib/motion/use-motion-preference";
import { useSession } from "@/lib/session/context";
import { createExtraction, createReadback, createSpeech, fetchVoiceCapabilities, submitUtterance, transcribe, createBrowserUtterance, type ExtractionCard, type Utterance, type VoiceCapabilities } from "@/lib/voice/api";
import { browserRecognitionSupported, startBrowserRecognition, type BrowserRecognition } from "@/lib/voice/browser-speech";
import { draftStore, isOffline, queuedDraft, QUEUED_LABEL, type QueuedDraft } from "@/lib/voice/offline-queue";
import { MicError, startRecording, type MicProblem, type RecorderHandle } from "@/lib/voice/recorder";
import { TtsPlayer, type TtsState } from "@/lib/voice/tts-player";
import { voiceMessages as m } from "@/messages/voice";
import { ExtractionCardView } from "./extraction-card";
import { useScreenShare } from "./use-screen-share";
import { pushLevel, Waveform } from "./waveform";

/** Held longer than this, push-to-talk stops on release; a shorter press toggles. */
export const HOLD_MS = 350;

export type Phase = "idle" | "recording" | "transcribing" | "review" | "sending";

export interface VoiceControlsHandle {
  /** Typed sends ask about an attached screenshot first. True: answered here, nothing else to send. */
  beforeSend: (text: string) => Promise<boolean>;
  /** Push-to-talk, typing or Stop: halt a spoken reply now. */
  interrupt: () => void;
}

export interface VoiceControlsProps {
  assistant: Pick<UseAssistant, "send" | "exchanges" | "busy">;
  /** The composer's root: typing anywhere in it stops speech; the text box gets focus on mic problems. */
  rootRef: RefObject<HTMLElement | null>;
  ref?: Ref<VoiceControlsHandle>;
}

interface LastVoice {
  turnId: string | null;
  runId: string;
  text: string;
}

/** What a finished voice run should read back: the drafted quote, or nothing. */
function quoteOf(run: { cards: unknown[] } | null): string | null {
  for (const card of run?.cards ?? []) {
    const value = card as { kind?: string; quote_id?: string | null };
    if (value.kind === "quote_draft" && value.quote_id) return value.quote_id;
  }
  return null;
}

/**
 * Push-to-talk, the transcript editor, offline drafts, spoken replies with read-back, "Look at my
 * screen" and photo extraction — mounted by the composer under its text box (design §14,
 * ai-routing §4.2). The utterance id is created on press and travels with the recording, the
 * submission and any queued draft, so the server yields one turn however often it is sent. A
 * partial transcript is never sendable; nothing claims success without the server's 202.
 */
export function VoiceControls({ assistant, rootRef, ref }: VoiceControlsProps) {
  const { bootstrap } = useSession();
  const voiceOn = bootstrap.capabilities.voice;
  const reduced = useIsMotionReduced();
  const [caps, setCaps] = useState<VoiceCapabilities | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const phaseRef = useRef<Phase>("idle");
  const setPhaseBoth = useCallback((next: Phase) => {
    phaseRef.current = next;
    setPhase(next);
  }, []);
  const [levels, setLevels] = useState<number[]>([]);
  const [micProblem, setMicProblem] = useState<MicProblem | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [utterance, setUtterance] = useState<Utterance | null>(null);
  const [partial, setPartial] = useState<string | null>(null);
  const [edit, setEdit] = useState("");
  const [correcting, setCorrecting] = useState<LastVoice | null>(null);
  const [last, setLast] = useState<LastVoice | null>(null);
  const [drafts, setDrafts] = useState<QueuedDraft[]>([]);
  const [online, setOnline] = useState(() => (typeof navigator === "undefined" ? true : navigator.onLine));
  const [speakOn, setSpeakOn] = useState(false);
  const [ttsState, setTtsState] = useState<TtsState>("idle");
  const [readback, setReadback] = useState<string | null>(null);
  const [extraction, setExtraction] = useState<ExtractionCard | null>(null);
  const [reading, setReading] = useState(false);
  const recorder = useRef<RecorderHandle | null>(null);
  const recognition = useRef<BrowserRecognition | null>(null);
  const utteranceId = useRef<string | null>(null);
  const startedAt = useRef(0);
  const pressedAt = useRef(0);
  const player = useRef<TtsPlayer | null>(null);
  const spokenRun = useRef<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const screen = useScreenShare(bootstrap.capabilities.assistant);

  // ---- capabilities, drafts, connectivity ----------------------------------------------------
  useEffect(() => {
    if (!voiceOn) return;
    const controller = new AbortController();
    fetchVoiceCapabilities(controller.signal)
      .then((value) => {
        setCaps(value);
        setSpeakOn(value.speak_responses && value.can_speak && value.tts.status !== "off");
      })
      .catch(() => setCaps(null));
    return () => controller.abort();
  }, [voiceOn]);

  const refreshDrafts = useCallback(() => {
    void draftStore()
      .list()
      .then(setDrafts)
      .catch(() => setDrafts([]));
  }, []);

  useEffect(() => {
    refreshDrafts();
    const up = () => {
      setOnline(true);
      refreshDrafts();
    };
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, [refreshDrafts]);

  // ---- spoken replies ------------------------------------------------------------------------
  useEffect(() => {
    const instance = new TtsPlayer();
    player.current = instance;
    const unsubscribe = instance.subscribe(setTtsState);
    return () => {
      unsubscribe();
      instance.stop();
    };
  }, []);

  const interrupt = useCallback(() => player.current?.stop(), []);

  // typing anywhere in the composer halts speech at once
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const onInput = () => interrupt();
    root.addEventListener("input", onInput);
    return () => root.removeEventListener("input", onInput);
  }, [rootRef, interrupt]);

  const focusText = useCallback(() => {
    rootRef.current?.querySelector<HTMLTextAreaElement>("textarea")?.focus();
  }, [rootRef]);

  // the voice turn finished: read back the drafted quote (shown, and spoken when enabled)
  const lastRun = last ? assistant.exchanges.find((exchange) => exchange.run?.id === last.runId)?.run ?? null : null;
  const lastRunDone = lastRun !== null && !["queued", "running"].includes(lastRun.status);
  useEffect(() => {
    if (!last || !lastRunDone || !lastRun || spokenRun.current === last.runId) return;
    spokenRun.current = last.runId;
    const quoteId = quoteOf(lastRun);
    const speakText = async (text: string) => {
      if (!speakOn) return;
      try {
        const speech = await createSpeech(text, caps?.speech_language);
        await player.current?.play(speech.url);
      } catch {
        setNotice(m.speak.failed);
      }
    };
    if (quoteId && (caps?.read_back_values ?? true)) {
      createReadback("sales.quote", quoteId)
        .then((value) => {
          setReadback(value.text);
          void speakText(value.text);
        })
        .catch(() => setReadback(m.readback.failed));
    } else if (lastRun.text) {
      void speakText(lastRun.text);
    }
  }, [last, lastRun, lastRunDone, speakOn, caps]);

  // ---- recording -----------------------------------------------------------------------------
  const browserOnly = caps !== null && caps.stt.status !== "demo" && caps.stt.status !== "configured" && caps.browser_fallback.status === "browser";
  const language = caps?.speech_language ?? "en-IN";

  const reset = useCallback(() => {
    recorder.current = null;
    recognition.current = null;
    setLevels([]);
    setPartial(null);
  }, []);

  const cancel = useCallback(() => {
    recorder.current?.cancel();
    recognition.current?.cancel();
    reset();
    utteranceId.current = null;
    setUtterance(null);
    setEdit("");
    setPhaseBoth("idle");
  }, [reset, setPhaseBoth]);

  const fail = useCallback(
    (problem: MicProblem) => {
      reset();
      utteranceId.current = null;
      setMicProblem(problem);
      setPhaseBoth("idle");
      announce(m.micProblems[problem] ?? m.micProblems.unavailable!, "assertive");
      // after the press settles (react-aria returns focus to the pressed button on release)
      window.setTimeout(focusText, 50);
    },
    [focusText, reset, setPhaseBoth],
  );

  const finish = useCallback(async () => {
    if (phaseRef.current !== "recording") return;
    if (recognition.current) {
      recognition.current.stop(); // onFinal moves on
      return;
    }
    const handle = recorder.current;
    const id = utteranceId.current;
    if (!handle || !id) return;
    setPhaseBoth("transcribing");
    try {
      const recording = await handle.stop();
      reset();
      const value = await transcribe(recording.blob, { utteranceId: id, language, durationMs: recording.durationMs });
      if (value.status !== "transcribed" || !value.text) {
        setNotice(m.transcribeFailed);
        setPhaseBoth("idle");
        return;
      }
      setUtterance(value);
      setEdit(value.text);
      setPhaseBoth("review");
    } catch (error) {
      reset();
      if (error instanceof MicError) fail(error.problem);
      else {
        setNotice(error instanceof ProblemError && error.code === "not_configured" ? m.sttNotConfigured : isNetworkError(error) ? m.offline.queued : m.transcribeFailed);
        setPhaseBoth("idle");
        focusText();
      }
    }
  }, [fail, focusText, language, reset, setPhaseBoth]);

  const start = useCallback(async () => {
    interrupt();
    setNotice(null);
    setMicProblem(null);
    utteranceId.current = uuidv7(); // created on press (design §14)
    startedAt.current = Date.now();
    setPhaseBoth("recording");
    announce(m.recordingAnnounce);
    if (browserOnly) {
      const handle = startBrowserRecognition(language, {
        onPartial: (text) => setPartial(text),
        onFinal: (text, confidence) => {
          const id = utteranceId.current;
          if (!id) return;
          setPhaseBoth("transcribing");
          createBrowserUtterance({ id, text, language, confidence, duration_ms: Date.now() - startedAt.current })
            .then((value) => {
              setUtterance(value);
              setEdit(value.text);
              setPartial(null);
              setPhaseBoth("review");
            })
            .catch(() => fail("unavailable"));
        },
        onError: (problem) => fail(problem),
      });
      if (!handle) fail("unsupported");
      recognition.current = handle;
      return;
    }
    try {
      recorder.current = await startRecording({
        onLevel: (level) => setLevels((current) => pushLevel(current, level)),
        onLimit: () => {
          setNotice(m.limitReached);
          void finish();
        },
      });
      if (phaseRef.current !== "recording") recorder.current.cancel(); // cancelled while the mic was opening
    } catch (error) {
      fail(error instanceof MicError ? error.problem : "unavailable");
    }
  }, [browserOnly, fail, finish, interrupt, language, setPhaseBoth]);


  // Esc discards a recording or an unsent transcript
  useEffect(() => {
    if (phase !== "recording" && phase !== "review") return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        cancel();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase, cancel]);

  const onPressStart = () => {
    interrupt();
    if (phaseRef.current === "recording") {
      void finish(); // toggle mode: the second press stops
      return;
    }
    if (phaseRef.current !== "idle" && phaseRef.current !== "review") return;
    pressedAt.current = Date.now();
    void start();
  };
  const onPressEnd = () => {
    if (phaseRef.current === "recording" && Date.now() - pressedAt.current > HOLD_MS) void finish(); // hold mode
  };

  // ---- sending -------------------------------------------------------------------------------
  const sendVoice = useCallback(
    async (id: string, text: string, correctsTurnId: string | null): Promise<"sent" | "queued" | "failed"> => {
      try {
        const accepted = await assistant.send(text, {
          clientUtteranceId: id,
          submit: async (conversationId, turn) => {
            const done = await submitUtterance(id, { conversationId, text: turn.text, context: turn.context as never, correctsTurnId });
            return { runId: done.turn.run_id, turnId: done.turn.turn_id };
          },
        });
        if (!accepted) return "failed";
        setLast({ turnId: accepted.turnId, runId: accepted.runId, text });
        setReadback(null);
        announce(m.sent);
        return "sent";
      } catch (error) {
        if (isOffline(error, typeof navigator === "undefined" ? true : navigator.onLine) || isNetworkError(error)) {
          await draftStore().put(queuedDraft({ utteranceId: id, conversationId: null, text, correctsTurnId }));
          refreshDrafts();
          setNotice(m.offline.queued);
          return "queued";
        }
        setNotice(error instanceof ProblemError ? (error.detail ?? m.transcribeFailed) : m.transcribeFailed);
        return "failed";
      }
    },
    [assistant, refreshDrafts],
  );

  const sendTranscript = async () => {
    const id = utteranceId.current;
    const text = edit.trim();
    if (!id || !text || phaseRef.current !== "review") return;
    if (screen.attached && (await screen.ask(text))) {
      cancel();
      return;
    }
    setPhaseBoth("sending");
    const outcome = await sendVoice(id, text, correcting?.turnId ?? null);
    if (outcome === "failed") {
      setPhaseBoth("review"); // the same id is reused on the next attempt
      return;
    }
    utteranceId.current = null;
    setUtterance(null);
    setEdit("");
    setCorrecting(null);
    setPhaseBoth("idle");
  };

  const sendDraft = async (draft: QueuedDraft) => {
    const outcome = await sendVoice(draft.utteranceId, draft.text, draft.correctsTurnId);
    if (outcome === "sent") {
      await draftStore().remove(draft.utteranceId);
      refreshDrafts();
    }
  };

  const discardDraft = async (draft: QueuedDraft) => {
    await draftStore().remove(draft.utteranceId);
    refreshDrafts();
  };

  // ---- photo extraction ----------------------------------------------------------------------
  const readPhoto = async (file: File | undefined) => {
    if (!file) return;
    setReading(true);
    setNotice(null);
    try {
      const fileId = await uploadFile(file, purposeFor(file));
      setExtraction(await createExtraction({ file_id: fileId }));
    } catch (error) {
      setNotice(error instanceof ProblemError && error.detail ? error.detail : m.photo.unavailable);
    } finally {
      setReading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  useImperativeHandle(ref, () => ({
    beforeSend: async (text: string) => (screen.attached ? screen.ask(text) : false),
    interrupt,
  }), [screen, interrupt]);

  const recording = phase === "recording";
  const speaking = ttsState === "playing" || ttsState === "loading";
  const micBlocked = micProblem !== null;
  const canTalk = voiceOn && caps !== null && caps.available && !micBlocked && (caps.stt.status === "demo" || caps.stt.status === "configured" || (browserOnly && browserRecognitionSupported()));
  const visionOn = screen.capabilities?.screen_capture_enabled ?? false;

  return (
    <div role="group" aria-label={m.region} className="flex flex-col gap-2" data-capture-exclude>
      <div className="flex flex-wrap items-center gap-2">
        {voiceOn ? (
          <RacButton
            aria-label={recording ? m.stopRecording : m.talk}
            aria-pressed={recording}
            aria-describedby="lk-voice-hint"
            isDisabled={!canTalk || phase === "transcribing" || phase === "sending"}
            onPressStart={onPressStart}
            onPressEnd={onPressEnd}
            className={buttonClasses(recording ? "primary" : "secondary", "md", "min-h-11 min-w-11 touch-none select-none")}
          >
            <MicIcon size={18} />
            <span>{recording ? m.stopRecording : m.talk}</span>
          </RacButton>
        ) : null}
        {voiceOn ? (
          <span id="lk-voice-hint" className="sr-only">
            {m.talkHint}
          </span>
        ) : null}
        {recording ? (
          <>
            <span className="inline-flex items-center gap-2 text-sm font-semibold text-danger" role="status">
              <span aria-hidden="true" className="inline-block size-2 rounded-xs bg-danger" />
              {m.recording}
            </span>
            <Waveform levels={levels} reduced={reduced} label={m.recording} active />
            <Button variant="quiet" onPress={cancel}>
              {m.cancel}
            </Button>
          </>
        ) : null}
        {phase === "transcribing" ? <span className="text-sm text-ink-muted" role="status">{m.transcribing}</span> : null}
        {speaking ? (
          <>
            <span className="text-sm text-ink" role="status">
              {m.speak.speaking}
            </span>
            <Waveform levels={[0.5]} reduced label={m.speak.speaking} active />
            <Button variant="secondary" onPress={interrupt}>
              {m.speak.stop}
            </Button>
          </>
        ) : null}
        {visionOn ? (
          <Button variant="quiet" icon={<EyeIcon size={18} />} onPress={() => void screen.look()} isPending={screen.busy} pendingLabel={m.screen.capturing} aria-describedby="lk-screen-hint">
            {m.screen.look}
          </Button>
        ) : null}
        <span id="lk-screen-hint" className="sr-only">
          {m.screen.lookHint}
        </span>
        <Button variant="quiet" onPress={() => fileInput.current?.click()} isPending={reading} pendingLabel={m.photo.reading}>
          {m.photo.attach}
        </Button>
        <input
          ref={fileInput}
          type="file"
          accept="image/png,image/jpeg,image/webp,application/pdf"
          className="sr-only"
          tabIndex={-1}
          aria-label={m.photo.attach}
          onChange={(event) => void readPhoto(event.currentTarget.files?.[0])}
        />
        {caps && voiceOn && caps.tts.status !== "off" && caps.can_speak ? (
          <Switch isSelected={speakOn} onChange={(value) => { setSpeakOn(value); if (!value) interrupt(); }}>
            {m.speak.toggle}
          </Switch>
        ) : null}
        {caps && voiceOn ? (
          caps.stt.label === "Demo" ? <DemoBadge label={m.providerBadge("Demo")} /> : <Badge>{m.providerBadge(browserOnly ? m.browserFallback : caps.stt.label)}</Badge>
        ) : null}
      </div>

      {screen.attached ? (
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-2 rounded-sm border bg-surface-sunken px-2 py-1 text-sm text-ink">
            {m.screen.chip}
          </span>
          <Button variant="quiet" icon={<CloseIcon size={16} />} onPress={() => void screen.remove()}>
            {m.screen.remove}
          </Button>
        </div>
      ) : null}
      {screen.problem ? <p className="text-sm text-warning-text">{screen.problem}</p> : null}
      {screen.answer ? (
        <section aria-label={m.screen.answerTitle} className="flex flex-col gap-1 rounded-sm border bg-surface p-3">
          <p className="text-xs font-semibold tracking-[0.06em] text-ink-muted uppercase">{m.screen.answerTitle}</p>
          <p className="text-[15px] text-ink">{screen.answer.handoff ? m.screen.handedOff : screen.answer.text}</p>
          <p className="text-xs text-ink-muted">{m.screen.tainted}</p>
        </section>
      ) : null}

      {micBlocked ? (
        <div role="alert" className="flex flex-wrap items-center gap-2 text-sm text-warning-text">
          <span>{m.micProblems[micProblem] ?? m.micProblems.unavailable}</span>
          <Button variant="secondary" onPress={() => setMicProblem(null)}>
            {m.retryMic}
          </Button>
        </div>
      ) : null}
      {notice ? <p className="text-sm text-ink-muted">{notice}</p> : null}

      {recording && partial ? (
        <p className="text-[15px] text-ink-muted italic" aria-live="polite">
          <span className="sr-only">{m.listening}: </span>
          {partial}
          <span className="block text-xs not-italic">{m.partialHint}</span>
        </p>
      ) : null}

      {phase === "review" || phase === "sending" ? (
        <div className="flex flex-col gap-2 rounded-sm border bg-surface p-3">
          {utterance?.simulated ? <p className="text-sm text-warning-text">{m.demoTranscript}</p> : null}
          {utterance?.untested_language ? (
            <p className="text-sm text-warning-text">
              {m.untestedLanguage(caps?.languages.find((l) => l.code === utterance.language)?.label ?? utterance.language ?? "")}
            </p>
          ) : null}
          <TextArea
            label={correcting ? m.correctionLabel : m.transcriptLabel}
            description={correcting ? m.correctionHint : undefined}
            rows={2}
            value={edit}
            onChange={setEdit}
            autoFocus
          />
          <div className="flex flex-wrap gap-2">
            <Button
              variant="primary"
              onPress={() => void sendTranscript()}
              isPending={phase === "sending"}
              {...unavailableWhen(!edit.trim() || assistant.busy ? m.partialHint : null)}
            >
              {m.sendTranscript}
            </Button>
            <Button variant="quiet" onPress={cancel}>
              {m.discard}
            </Button>
          </div>
        </div>
      ) : null}

      {last && phase === "idle" && !correcting ? (
        <div>
          <Button variant="quiet" onPress={() => setCorrecting(last)} {...unavailableWhen(!canTalk ? m.micProblems.unavailable : null)}>
            {m.correct}
          </Button>
        </div>
      ) : null}
      {correcting && phase === "idle" ? <p className="text-sm text-ink-muted">{m.correctionHint}</p> : null}

      {readback ? (
        <section aria-label={m.readback.title} className="flex flex-col gap-1 rounded-sm border bg-surface p-3">
          <p className="text-xs font-semibold tracking-[0.06em] text-ink-muted uppercase">{m.readback.title}</p>
          <p className="text-[15px] text-ink">{readback}</p>
          <p className="text-xs text-ink-muted">{m.readback.hint}</p>
        </section>
      ) : null}

      {drafts.length > 0 ? (
        <section aria-label={m.offline.title} className="flex flex-col gap-2 rounded-sm border border-warning-text/40 bg-warning-bg p-3">
          <p className="text-sm font-semibold text-ink">{m.offline.title}</p>
          <p className="text-sm text-ink-muted">{online ? m.offline.reconnect : m.offline.still}</p>
          <ul className="flex flex-col gap-2">
            {drafts.map((draft) => (
              <li key={draft.utteranceId} className="flex flex-col gap-1">
                <span className="text-xs font-semibold text-warning-text">{QUEUED_LABEL}</span>
                <span className="text-[15px] text-ink">{draft.text}</span>
                <span className="flex flex-wrap gap-2">
                  <Button variant="secondary" onPress={() => void sendDraft(draft)} {...unavailableWhen(!online || assistant.busy ? m.offline.still : null)}>
                    {m.offline.send}
                  </Button>
                  <Button variant="quiet" onPress={() => void discardDraft(draft)}>
                    {m.offline.discard}
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {extraction ? <ExtractionCardView key={`${extraction.request_id}-${extraction.version}`} card={extraction} onChange={setExtraction} onUse={(summary) => void assistant.send(summary, { extractionId: extraction.request_id })} /> : null}
    </div>
  );
}
