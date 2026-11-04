/**
 * Slice-3 stage-2 merge (briefings requests 1-2): "Listen to my day" speaks through the voice module's TTS
 * (`POST /voice/speech`), labelled "Demo voice" while the Demo adapter is the voice, with the silent Demo voice
 * as the fallback; paused on an item, the read-back speaks that item's values before anything is confirmed.
 */

import { describe, expect, it, vi } from "vitest";
import type { SpeechOut, VoiceCapabilities } from "@/lib/voice/api";
import type { WireNarration } from "../slice3-api";
import type { ClipPlayer, SpeechClip } from "./speech";
import { createListenSession, type ListenApi } from "./use-listen";
import { speechFor, switchableSpeech, voiceSpeech } from "./voice-speech";

const flush = async () => {
  for (let i = 0; i < 8; i += 1) await Promise.resolve();
};

function caps(status: VoiceCapabilities["tts"]["status"], canSpeak = true): VoiceCapabilities {
  return { can_speak: canSpeak, tts: { provider: "demo", label: "Demo", status } } as unknown as VoiceCapabilities;
}

const out = (text: string): SpeechOut =>
  ({ id: "s-1", url: `/api/v1/voice/speech/s-1/audio?len=${text.length}`, expires_at: "2026-10-12T04:00:00Z", mime_type: "audio/wav", duration_ms: 1500, provider_label: "Demo" }) as SpeechOut;

describe("voice module speech for Listen", () => {
  it("synthesises each segment through the voice module and labels the Demo voice", async () => {
    const synthesise = vi.fn(async (text: string) => out(text));
    const speech = voiceSpeech({ demo: true }, synthesise);
    expect(speech.label).toBe("Demo voice");
    const clip = await speech.speak("Good morning, Meera.");
    expect(synthesise).toHaveBeenCalledWith("Good morning, Meera.");
    expect(clip).toEqual({ url: "/api/v1/voice/speech/s-1/audio?len=20", durationMs: 1500, silent: false });
    expect(voiceSpeech({ demo: false }, synthesise).label).toBeNull();
    const aborted = new AbortController();
    aborted.abort();
    await expect(speech.speak("x", aborted.signal)).rejects.toMatchObject({ name: "AbortError" });
  });

  it("falls back to the silent Demo voice without spoken replies or with TTS off", async () => {
    expect((await speechFor(null).speak("Hello there")).silent).toBe(true);
    expect((await speechFor(caps("demo", false)).speak("Hello there")).silent).toBe(true);
    expect((await speechFor(caps("off")).speak("Hello there")).silent).toBe(true);
    expect(speechFor(caps("demo")).label).toBe("Demo voice");
    expect(speechFor(caps("configured")).label).toBeNull();
  });
});

describe("the provider's port", () => {
  it("stays one object and follows the voice chosen later", async () => {
    const { port, use } = switchableSpeech(speechFor(null));
    expect(port.label).toBe("Demo voice");
    expect((await port.speak("Hello there")).silent).toBe(true);
    use(voiceSpeech({ demo: false }, async (text) => out(text)));
    expect(port.label).toBeNull();
    expect((await port.speak("Hello there")).silent).toBe(false);
  });
});

describe("read-back before a voice confirmation", () => {
  const narration: WireNarration = {
    pin_id: "pin-1", briefing_id: "b-1", pinned_version: 2, language: "en", ai_status: "demo", state: "active", position: 0,
    segments: [
      { kind: "item", lead: "First. Decision.", text: "Nordhaus export quote, EUR 5,760.00.", text_source: "template", readback: ["Nordhaus export quote", "EUR 5,760.00"], ordinal: 1, issue_id: "i-1", path: null },
    ],
  } as WireNarration;

  it("speaks the paused item's values on its own player and leaves the segment paused", async () => {
    const api: ListenApi = {
      createPin: vi.fn(async () => ({ id: "pin-1" }) as never),
      fetchScript: vi.fn(async () => narration),
      updatePin: vi.fn(async () => ({})),
    };
    const mainPlayed: SpeechClip[] = [];
    const player: ClipPlayer = { play: (clip) => (mainPlayed.push(clip), new Promise<void>(() => {})), pause() {}, resume() {}, stop() {} };
    const readbackPlayed: SpeechClip[] = [];
    const readbackPlayer: ClipPlayer = { play: async (clip) => void readbackPlayed.push(clip), pause() {}, resume() {}, stop() {} };
    const spoken: string[] = [];
    const speech = voiceSpeech({ demo: true }, async (text) => (spoken.push(text), out(text)));
    const session = createListenSession({ api, speech, player, readbackPlayer, onChange: () => {} });
    await session.start("b-1");
    await flush();
    expect(await session.readBack()).toBeNull(); // only while paused
    session.pause();
    expect(await session.readBack()).toBe("To confirm: Nordhaus export quote, EUR 5,760.00.");
    expect(spoken.at(-1)).toBe("To confirm: Nordhaus export quote, EUR 5,760.00.");
    expect(readbackPlayed).toHaveLength(1);
    expect(mainPlayed).toHaveLength(1);
    expect(session.state.phase).toBe("paused");
  });
});
