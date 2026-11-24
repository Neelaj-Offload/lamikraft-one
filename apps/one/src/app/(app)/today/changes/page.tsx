import type { Metadata } from "next";
import { deltaSinceFrom } from "@/features/briefing/slice3-api";
import { ChangesScreen } from "~/screens/today/changes-screen";

export const metadata: Metadata = { title: "What changed · Today" };

/** `?since=last_ack|yesterday|last_workday` (default: since the last visit). */
export default async function TodayChangesPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const since = deltaSinceFrom((await searchParams).since);
  return <ChangesScreen key={since} since={since} />;
}
