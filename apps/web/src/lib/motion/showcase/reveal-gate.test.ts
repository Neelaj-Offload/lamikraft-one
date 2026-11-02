import { describe, expect, it } from "vitest";
import { markRevealed, REVEAL_STORAGE_KEY, shouldReveal, type RevealStorage } from "./reveal-gate";

function memoryStorage(initial: Record<string, string> = {}): RevealStorage & { data: Record<string, string> } {
  const data = { ...initial };
  return {
    data,
    getItem: (key) => data[key] ?? null,
    setItem: (key, value) => {
      data[key] = value;
    },
  };
}

describe("reveal gate", () => {
  it("peeks without writing, then remembers once marked", () => {
    const storage = memoryStorage();
    expect(shouldReveal("b1:3", storage)).toBe(true);
    expect(shouldReveal("b1:3", storage)).toBe(true);
    markRevealed("b1:3", storage);
    expect(storage.data[REVEAL_STORAGE_KEY]).toBe("b1:3");
    expect(shouldReveal("b1:3", storage)).toBe(false);
  });

  it("plays again for a newer version", () => {
    const storage = memoryStorage({ [REVEAL_STORAGE_KEY]: "b1:3" });
    expect(shouldReveal("b1:4", storage)).toBe(true);
  });

  it("never plays without a version key or without storage", () => {
    expect(shouldReveal(null, memoryStorage())).toBe(false);
    expect(shouldReveal("b1:3", null)).toBe(false);
  });

  it("plays nothing when storage throws, and marking never throws", () => {
    const broken: RevealStorage = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    };
    expect(shouldReveal("b1:3", broken)).toBe(false);
    expect(() => markRevealed("b1:3", broken)).not.toThrow();
  });
});
