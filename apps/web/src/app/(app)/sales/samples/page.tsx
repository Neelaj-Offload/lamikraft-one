import type { Metadata } from "next";
import { sampleListStateFrom } from "@/features/samples/list-state";
import { SampleList } from "@/features/samples/samples";
import { getRoute } from "@/lib/routes";

const route = getRoute("sales-samples");

export const metadata: Metadata = { title: `${route.label} · Sales` };

export default async function SamplesPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = sampleListStateFrom(await searchParams);
  return <SampleList key={`${state.q}|${state.status}|${state.offset}`} state={state} />;
}
