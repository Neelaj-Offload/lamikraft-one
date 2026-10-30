import type { Metadata } from "next";
import { GrainLocks } from "@/features/cutting/grain-locks";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-cutting-grain-locks");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** Grain-locked decors (read by every optimiser user, changed with cutting.grain_lock.manage). */
export default function GrainLocksPage() {
  return <GrainLocks />;
}
