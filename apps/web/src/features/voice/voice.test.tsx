import { describe, expect, it } from "vitest";
import { scaleFor } from "@/lib/screen-capture/capture";
import { MASK_SELECTOR, shouldMask } from "@/lib/screen-capture/mask";
import { render, renderInSession } from "@/lib/test-support/render";
import { testBootstrap } from "@/lib/test-support/session";
import { voiceMessages } from "@/messages/voice";
import { ExtractionCardView } from "./extraction-card";
import { VoiceControls } from "./voice-controls";
import { pushLevel, Waveform, WAVEFORM_BARS } from "./waveform";

const el = (tagName: string, attrs: Record<string, string> = {}, type?: string) => ({
  tagName,
  type: type ?? null,
  hasAttribute: (name: string) => name in attrs,
});

describe("masked screenshot rules (ai-routing §4.2)", () => {
  it("masks data-restricted, data-private and password fields only", () => {
    expect(shouldMask(el("DIV", { "data-restricted": "" }))).toBe(true);
    expect(shouldMask(el("span", { "data-private": "" }))).toBe(true);
    expect(shouldMask(el("INPUT", {}, "password"))).toBe(true);
    expect(shouldMask(el("input", {}, "text"))).toBe(false);
    expect(shouldMask(el("div"))).toBe(false);
    expect(MASK_SELECTOR).toContain("[data-restricted]");
  });

  it("downscales to at most 1568 px on the longest edge and never upscales", () => {
    expect(scaleFor(1440, 900)).toBe(1);
    expect(scaleFor(3136, 1000)).toBe(0.5);
    expect(scaleFor(900, 2000) * 2000).toBeCloseTo(1568);
  });
});

describe("waveform (motion-system: only while recording or speaking)", () => {
  it("keeps a fixed number of bars", () => {
    let levels: number[] = [];
    for (let i = 0; i < 20; i += 1) levels = pushLevel(levels, i / 20);
    expect(levels).toHaveLength(WAVEFORM_BARS);
    expect(pushLevel([], 4)).toEqual([1]);
  });

  it("renders nothing when idle, bars when active, a static meter under reduced motion", () => {
    expect(render(<Waveform levels={[0.5]} reduced={false} label="Recording" active={false} />)).toBe("");
    const bars = render(<Waveform levels={[0.5]} reduced={false} label="Recording" active />);
    expect(bars).toContain('role="meter"');
    expect(bars.match(/aria-hidden="true"/g)).toHaveLength(WAVEFORM_BARS);
    const meter = render(<Waveform levels={[0.5]} reduced label="Recording" active />);
    expect(meter).toContain('aria-valuenow="50"');
    expect(meter).not.toContain("transition-[height]");
  });
});

describe("VoiceControls", () => {
  it("offers a labelled, keyboard-operable push-to-talk control of at least 44 px when voice is on", () => {
    const html = renderInSession(
      <VoiceControls assistant={{ send: async () => null, exchanges: [], busy: false }} rootRef={{ current: null }} />,
      testBootstrap({ capabilities: { assistant: true, voice: true } }),
    );
    expect(html).toContain(`aria-label="${voiceMessages.talk}"`);
    expect(html).toContain('aria-pressed="false"');
    expect(html).toContain("min-h-11");
    expect(html).toContain(voiceMessages.talkHint);
    expect(html).toContain(voiceMessages.photo.attach);
    expect(html).not.toContain(voiceMessages.recording);
  });

  it("shows no microphone control when the bootstrap says voice is off", () => {
    const html = renderInSession(
      <VoiceControls assistant={{ send: async () => null, exchanges: [], busy: false }} rootRef={{ current: null }} />,
      testBootstrap({ capabilities: { assistant: true, voice: false } }),
    );
    expect(html).not.toContain(`aria-label="${voiceMessages.talk}"`);
  });
});

describe("ExtractionCardView", () => {
  const card = {
    kind: "extraction" as const,
    request_id: "0192a000-0000-7000-8000-000000000001",
    status: "extracted" as const,
    extraction_kind: "delivery_note" as const,
    provider_label: "Demo",
    tainted: true,
    header: [
      { key: "document_number", label: "Delivery note number", type: "text", value: "DN-4471", suggestion: null, confidence: 0.97, needs_confirmation: false },
      { key: "vehicle_number", label: "Vehicle number", type: "text", value: null, suggestion: "RJ19 GB 4471", confidence: 0.55, needs_confirmation: true },
    ],
    lines: [],
    pending_confirmations: 1,
    message: null,
    version: 1,
  };

  it("shows confident values and asks for uncertain ones without pre-filling them", () => {
    const html = render(<ExtractionCardView card={card} onChange={() => undefined} onUse={() => undefined} />);
    expect(html).toContain("DN-4471");
    expect(html).toContain("Vehicle number · Confirm this value");
    expect(html).toContain("Read as “RJ19 GB 4471” — check and confirm");
    expect(html).not.toMatch(/value="RJ19 GB 4471"/);
    expect(html).toContain("1 value needs your confirmation.");
    expect(html).toContain(voiceMessages.photo.untrusted);
  });
});
