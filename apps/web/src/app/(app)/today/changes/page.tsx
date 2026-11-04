import type { Metadata } from "next";
import { ChangesView, deltaSinceFrom } from "@/features/briefing/changes-view";
import { getRoute } from "@/lib/routes";

const route = getRoute("today-changes");

export const metadata: Metadata = { title: `${route.label} · Today` };

/** `?since=last_ack|yesterday|last_workday` (default: since the last visit). */
export default async function TodayChangesPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const since = deltaSinceFrom(params.since);
  return <ChangesView key={since} since={since} />;
}
