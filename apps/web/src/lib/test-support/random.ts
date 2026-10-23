/**
 * Seeded generators for property-style vitest tests (no property-testing dependency is
 * installed). A failing case prints its seed so it can be replayed exactly.
 */

export function mulberry32(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function int(random: () => number, min: number, max: number): number {
  return min + Math.floor(random() * (max - min + 1));
}

export function pick<T>(random: () => number, items: readonly T[]): T {
  return items[Math.floor(random() * items.length)]!;
}

export function digits(random: () => number, length: number): string {
  let out = "";
  for (let i = 0; i < length; i += 1) out += String(int(random, 0, 9));
  return out;
}

/** Runs `check` for `runs` seeds; rethrows with the seed in the message. */
export function forAllSeeds(runs: number, check: (random: () => number, seed: number) => void, firstSeed = 1): void {
  for (let seed = firstSeed; seed < firstSeed + runs; seed += 1) {
    try {
      check(mulberry32(seed), seed);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      throw new Error(`property failed for seed ${seed}: ${message}`, { cause: error });
    }
  }
}
