import type { Metadata } from "next";
import { GrainLocks } from "~/screens/cutting/grain-locks";

export const metadata: Metadata = { title: "Grain locks · Operations" };

/** Grain-locked decors: read by everyone who plans cuts, changed with cutting.grain_lock.manage. */
export default function GrainLocksPage() {
  return <GrainLocks />;
}
