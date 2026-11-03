import { describe, expect, it, vi } from "vitest";
import { MemoryDraftStore, QUEUED_LABEL, isOffline, queuedDraft } from "./offline-queue";
import { MicError, micProblemOf, pickMimeType, startRecording } from "./recorder";
import { TtsPlayer, type AudioLike } from "./tts-player";
import { browserLanguage } from "./browser-speech";

function fakeAudio() {
  const audio: AudioLike & { paused: boolean; pauseCalls: number } = {
    src: "",
    currentTime: 3,
    paused: true,
    pauseCalls: 0,
    onended: null,
    onerror: null,
    play: vi.fn(async () => {
      audio.paused = false;
    }),
    pause: () => {
      audio.paused = true;
      audio.pauseCalls += 1;
    },
  };
  return audio;
}

describe("tts-interrupt (design §14, scenario J)", () => {
  it("push-to-talk, typing or Stop pauses at once and the state is 'stopped'", async () => {
    const audio = fakeAudio();
    const player = new TtsPlayer(() => audio);
    const states: string[] = [];
    player.subscribe((state) => states.push(state));
    await player.play("/api/v1/voice/speech/1/audio");
    expect(player.state).toBe("playing");
    expect(player.speaking).toBe(true);
    player.stop();
    expect(audio.pauseCalls).toBe(1);
    expect(audio.paused).toBe(true);
    expect(audio.currentTime).toBe(0);
    expect(player.state).toBe("stopped");
    expect(states).toEqual(["loading", "playing", "stopped"]);
  });

  it("a new reply stops the previous one and a late 'ended' of the old audio is ignored", async () => {
    const first = fakeAudio();
    const second = fakeAudio();
    const queue = [first, second];
    const player = new TtsPlayer(() => queue.shift()!);
    await player.play("/a");
    await player.play("/b");
    expect(first.pauseCalls).toBe(1);
    first.onended?.call({} as GlobalEventHandlers, new Event("ended"));
    expect(player.state).toBe("playing");
  });

  it("stop before play resolves never reports playing", async () => {
    let release: () => void = () => undefined;
    const audio = fakeAudio();
    audio.play = () => new Promise<void>((resolve) => (release = resolve));
    const player = new TtsPlayer(() => audio);
    const pending = player.play("/a");
    player.stop();
    release();
    await pending;
    expect(player.state).toBe("stopped");
  });
});

describe("offline-queue (design §14, scenario J)", () => {
  it("stores 'Queued draft — not sent' with the utterance id and no success state", async () => {
    const store = new MemoryDraftStore();
    const draft = queuedDraft({ utteranceId: "0192a000-0000-7000-8000-000000000001", conversationId: null, text: "change it to 300", correctsTurnId: null }, new Date("2026-10-12T03:30:00Z"));
    await store.put(draft);
    const [saved] = await store.list();
    expect(saved).toEqual({ ...draft, label: QUEUED_LABEL });
    expect(saved!.label).toBe("Queued draft — not sent");
    expect(Object.keys(saved!)).not.toContain("receipt");
    // resending keeps the same id, so the server's unique constraint yields one turn
    await store.put({ ...draft, text: "change it to 300" });
    expect(await store.list()).toHaveLength(1);
    await store.remove(draft.utteranceId);
    expect(await store.list()).toEqual([]);
  });

  it("knows a network failure from a refusal", () => {
    expect(isOffline(new Error("x"), false)).toBe(true);
    expect(isOffline(Object.assign(new Error("x"), { name: "NetworkError" }), true)).toBe(true);
    expect(isOffline(Object.assign(new Error("x"), { name: "ProblemError" }), true)).toBe(false);
  });
});

describe("recorder", () => {
  it("maps microphone errors to what the person can do", () => {
    expect(micProblemOf({ name: "NotAllowedError" })).toBe("denied");
    expect(micProblemOf({ name: "NotFoundError" })).toBe("no_device");
    expect(micProblemOf({ name: "NotReadableError" })).toBe("unavailable");
    expect(micProblemOf(null)).toBe("unavailable");
  });

  it("prefers WebM/Opus, then Ogg/Opus, then MP4", () => {
    expect(pickMimeType({ isTypeSupported: () => true })).toBe("audio/webm;codecs=opus");
    expect(pickMimeType({ isTypeSupported: (t: string) => t.startsWith("audio/mp4") })).toBe("audio/mp4");
    expect(pickMimeType(undefined)).toBeUndefined();
  });

  it("a denied microphone rejects with MicError('denied') and records nothing", async () => {
    const denied = Object.assign(new Error("blocked"), { name: "NotAllowedError" });
    const attempt = startRecording({
      env: { getUserMedia: () => Promise.reject(denied), MediaRecorder: class {} as unknown as typeof MediaRecorder },
    });
    await expect(attempt).rejects.toBeInstanceOf(MicError);
    await expect(attempt).rejects.toMatchObject({ problem: "denied" });
  });

  it("no recorder in the browser is 'unsupported'", async () => {
    await expect(startRecording({ env: {} })).rejects.toMatchObject({ problem: "unsupported" });
  });
});

describe("browser fallback", () => {
  it("recognises Hinglish as Hindi (India), labelled untested elsewhere", () => {
    expect(browserLanguage("hinglish")).toBe("hi-IN");
    expect(browserLanguage("en-IN")).toBe("en-IN");
  });
});
