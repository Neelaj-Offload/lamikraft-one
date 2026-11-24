import type { Metadata } from "next";
import { sampleListStateFrom } from "@/features/samples/list-state";
import { SampleList } from "~/screens/sales/samples/list";

export const metadata: Metadata = { title: "Customer samples" };

/** Samples as a journey; `?status=` picks a stage, `?q=` searches. */
export default async function SamplesPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = sampleListStateFrom(await searchParams);
  return <SampleList key={`${state.q}|${state.status ?? ""}|${state.offset}`} state={state} />;
}
