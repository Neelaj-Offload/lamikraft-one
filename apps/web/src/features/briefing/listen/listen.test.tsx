/**
 * "Listen to my day" and the other Slice-3 Today views: the Demo speech port and clip player, the Listen state
 * machine (pin, script in the pin's order, pause/resume/stop recorded on the pin, completion), the controls
 * (44 px targets, waveform only while speaking, Escape stops), and the pure helpers of the delta and all-items
 * pages.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { meeraBriefing } from "@/lib/test-support/briefing";
import { renderInSession, textOf } from "@/lib/test-support/render";
import { filterItems } from "../all-items-view";
import { changeKindLabel, deltaSinceFrom, groupByFamily } from "../changes-view";
import { parseBriefingView } from "../parse";
import type { WireDeltaGroup, WireNarration } from "../slice3-api";
import { ListenPanel, SpeakingWaveform, WaveformBars } from "./listen-panel";
import { createClipPlayer, demoSpeech, estimateDurationMs, readbackSentence, type ClipPlayer, type SpeechClip } from "./speech";
import { createListenSession, IDLE_LISTEN, spokenText, type ListenApi, type ListenState } from "./use-listen";

const noop = () => {};

function script(): WireNarration {
  return {
    pin_id: "pin-1",
    briefing_id: "b-1",
    pinned_version: 2,
    language: "en",
    ai_status: "demo",
    state: "active",
    position: 0,
    segments: [
      { kind: "intro", lead: "Good morning, Meera.", text: "Two customer replies need attention.", text_source: "llm", readback: [], ordinal: null, issue_id: null, path: null },
      { kind: "item", lead: "First. Customer reply.", text: "Reply to Nordhaus, today 18:30.", text_source: "llm", readback: ["Reply to Nordhaus"], ordinal: 1, issue_id: "i-1", path: "/sales/messages/m1" },
      { kind: "item", lead: "Second. Decision.", text: "Nordhaus export quote, EUR 5,760.00.", text_source: "llm", readback: ["EUR 5,760.00"], ordinal: 2, issue_id: "i-2", path: null },
      { kind: "outro", lead: "", text: "That is everything for now.", text_source: "template", readback: [], ordinal: null, issue_id: null, path: null },
    ],
  };
}

/** A player whose clips end only when the test says so. */
function manualPlayer() {
  const ends: Array<() => void> = [];
  const player: ClipPlayer & { paused: boolean; played: SpeechClip[] } = {
    paused: false,
    played: [],
    play(clip) {
      this.played.push(clip);
      return new Promise<void>((resolve) => ends.push(resolve));
    },
    pause() {
      this.paused = true;
    },
    resume() {
      this.paused = false;
    },
    stop() {},
  };
  return { player, endClip: () => ends.shift()?.() };
}

const flush = async () => {
  for (let i = 0; i < 6; i += 1) await Promise.resolve();
};

function fakeApi() {
  const updates: Array<{ state?: string; position?: number }> = [];
  const api: ListenApi = {
    createPin: vi.fn(async () => ({ id: "pin-1" }) as never),
    fetchScript: vi.fn(async () => script()),
    updatePin: vi.fn(async (_pin, change) => {
      updates.push(change);
      return {};
    }),
  };
  return { api, updates };
}

describe("speech port (Demo)", () => {
  it("labels the voice, times silent clips by text length and builds the read-back sentence", async () => {
    const speech = demoSpeech();
    expect(speech.label).toBe("Demo voice");
    const clip = await speech.speak("Second. Decision. Nordhaus export quote, EUR 5,760.00.");
    expect(clip).toMatchObject({ url: null, silent: true });
    expect(estimateDurationMs("")).toBe(1200);
    expect(estimateDurationMs("x".repeat(10_000))).toBe(12_000);
    expect(readbackSentence(["LK-QT-2026-0041", " EUR 5,760.00 "])).toBe("To confirm: LK-QT-2026-0041, EUR 5,760.00.");
  });

  describe("clip player", () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it("plays a silent clip for its duration, holds while paused and rejects on stop", async () => {
      let clock = 0;
      const player = createClipPlayer(() => clock);
      let done = false;
      const playing = player.play({ url: null, durationMs: 1000, silent: true }).then(() => (done = true));
      clock = 400;
      vi.advanceTimersByTime(400);
      player.pause();
      vi.advanceTimersByTime(5000);
      await Promise.resolve();
      expect(done).toBe(false);
      player.resume();
      vi.advanceTimersByTime(600);
      await playing;
      expect(done).toBe(true);
      const stopped = player.play({ url: null, durationMs: 1000, silent: true });
      player.stop();
      await expect(stopped).rejects.toMatchObject({ name: "AbortError" });
    });
  });
});

describe("Listen session", () => {
  it("pins, speaks the script in the pin's order, records pause/resume and completes", async () => {
    const { api, updates } = fakeApi();
    const { player, endClip } = manualPlayer();
    const states: ListenState[] = [];
    const ended: string[] = [];
    const session = createListenSession({ api, speech: demoSpeech(), player, onChange: (s) => states.push(s), onEnded: (how) => ended.push(how) });
    await session.start("b-1");
    await flush();
    expect(api.createPin).toHaveBeenCalledWith("b-1");
    expect(session.state).toMatchObject({ phase: "speaking", index: 0, pinnedVersion: 2, aiStatus: "demo" });
    endClip();
    await flush();
    expect(session.state.index).toBe(1);
    session.pause();
    expect(session.state.phase).toBe("paused");
    expect(player.paused).toBe(true);
    session.resume();
    expect(session.state.phase).toBe("speaking");
    endClip();
    await flush();
    endClip();
    await flush();
    endClip();
    await flush();
    expect(session.state.phase).toBe("finished");
    expect(ended).toEqual(["completed"]);
    expect(updates).toEqual([
      { position: 1 },
      { state: "paused", position: 1 },
      { state: "active" },
      { position: 2 },
      { position: 3 },
      { state: "completed", position: 3 },
    ]);
    expect(player.played).toHaveLength(4);
    expect(states.map((s) => s.phase)).toContain("starting");
  });

  it("stop ends the pin at once and never completes", async () => {
    const { api, updates } = fakeApi();
    const { player, endClip } = manualPlayer();
    const ended: string[] = [];
    const session = createListenSession({ api, speech: demoSpeech(), player, onChange: noop, onEnded: (how) => ended.push(how) });
    await session.start("b-1");
    await flush();
    session.stop();
    expect(ended).toEqual([]); // not before the pin has ended on the server
    endClip();
    await flush();
    expect(session.state).toEqual(IDLE_LISTEN);
    expect(updates).toEqual([{ state: "stopped", position: 0 }]);
    expect(ended).toEqual(["stopped"]);
  });

  it("an unavailable voice stops the pin and says the list is unchanged", async () => {
    const { api, updates } = fakeApi();
    const speech = { ...demoSpeech(), speak: () => Promise.reject(new Error("tts down")) };
    const session = createListenSession({ api, speech, player: manualPlayer().player, onChange: noop });
    await session.start("b-1");
    await flush();
    expect(session.state.phase).toBe("error");
    expect(session.state.error).toMatch(/unchanged/);
    expect(updates).toEqual([{ state: "stopped", position: 0 }]);
  });

  it("speaks the lead and the body together", () => {
    expect(spokenText(script().segments[2]!)).toBe("Second. Decision. Nordhaus export quote, EUR 5,760.00.");
    expect(spokenText(script().segments[3]!)).toBe("That is everything for now.");
  });
});

describe("Listen controls", () => {
  const speaking: ListenState = { ...IDLE_LISTEN, phase: "speaking", pinId: "pin-1", pinnedVersion: 2, segments: script().segments, index: 2, aiStatus: "unavailable" };
  const props = { speechLabel: "Demo voice", disabledReason: null, onStart: noop, onPause: noop, onResume: noop, onStop: noop, onClose: noop };

  it("offers Listen when idle, and Pause / Stop with the words being read while speaking", () => {
    expect(textOf(renderInSession(<ListenPanel state={IDLE_LISTEN} {...props} />))).toContain("Listen to my day");
    const html = renderInSession(<ListenPanel state={speaking} {...props} />);
    const text = textOf(html);
    expect(text).toContain("Item 2 of 2");
    expect(text).toContain("Second. Decision. Nordhaus export quote, EUR 5,760.00.");
    expect(text).toContain("Pause");
    expect(text).toContain("Stop");
    expect(text).toContain("Demo voice");
    expect(text).toContain("Standard wording");
    expect(html).toContain('data-phase="speaking"');
    expect(html).toContain("pointer-fine:min-h-11"); // 44 px targets for every pointer
  });

  it("paused shows Resume; finished offers Listen again", () => {
    expect(textOf(renderInSession(<ListenPanel state={{ ...speaking, phase: "paused" }} {...props} />))).toContain("Resume");
    expect(textOf(renderInSession(<ListenPanel state={{ ...speaking, phase: "finished" }} {...props} />))).toContain("Listen again");
  });

  it("the waveform moves only while speaking, and is a static meter under reduced motion", () => {
    expect(renderInSession(<WaveformBars moving />)).toContain('data-state="speaking"');
    expect(renderInSession(<WaveformBars moving={false} />)).toContain('data-state="static"');
    // the server render (and reduced motion) never animates, even while speaking
    expect(renderInSession(<SpeakingWaveform speaking />)).toContain('data-state="static"');
  });
});

describe("delta and all-items helpers", () => {
  it("reads the since cursor and labels change kinds", () => {
    expect(deltaSinceFrom("yesterday")).toBe("yesterday");
    expect(deltaSinceFrom(["last_workday"])).toBe("last_workday");
    expect(deltaSinceFrom("2026-01-01")).toBe("last_ack");
    expect(changeKindLabel("sales.quote.changed")).toBe("Changed");
    expect(changeKindLabel("party.updated")).toBe("Updated");
    expect(changeKindLabel("x.something_new")).toBe("Something new");
  });

  it("groups issues by family in the server's order", () => {
    const group = (issue: string, family: string): WireDeltaGroup => ({ issue_id: issue, title: issue, family, changes: [] });
    const out = groupByFamily([group("a", "sales.customer_changes"), group("b", "common.approvals"), group("c", "sales.customer_changes")]);
    expect(out.map((f) => [f.label, f.groups.map((g) => g.issue_id)])).toEqual([
      ["Customer update", ["a", "c"]],
      ["Decision", ["b"]],
    ]);
  });

  it("filters every section by section and kind without reordering", () => {
    const view = parseBriefingView(meeraBriefing());
    const all = filterItems(view, { section: "all", family: null });
    expect(all.flatMap((g) => g.items.map((i) => i.issue_id))).toEqual(
      [...view.items].sort((a, b) => sectionIndex(a.section) - sectionIndex(b.section)).map((i) => i.issue_id).concat(view.snoozed.map((i) => i.issue_id)),
    );
    const family = view.items[0]!.family;
    const narrowed = filterItems(view, { section: "all", family });
    expect(narrowed.every((g) => g.items.every((i) => i.family === family))).toBe(true);
    expect(filterItems(view, { section: "coming_next", family: "nope" })).toEqual([]);
  });
});

function sectionIndex(code: string): number {
  return ["needs_you_now", "plan_for_today", "recommendations", "changes_since_last_visit", "handled_for_you", "coming_next"].indexOf(code);
}
