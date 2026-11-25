import type { Metadata, Route } from "next";
import { notFound, redirect } from "next/navigation";
import { loginUrl } from "@/lib/api/client";
import { UUID_PATTERN } from "@/lib/app-links";
import { loadSession, requestedPath } from "@/lib/session/server";
import { ChallanPrint } from "~/screens/challans/challan-print";
import { SessionUnavailable } from "~/shell/session-unavailable";

export const metadata: Metadata = { title: "Print challan" };

/**
 * The challan on paper: the data the PDF is made from, laid out for A4, never the internal note.
 * No app shell here, so the browser prints the document alone; the session is checked as in the
 * signed-in frame.
 */
export default async function ChallanPrintPage({ params }: { params: Promise<{ challanId: string }> }) {
  const { challanId } = await params;
  if (!UUID_PATTERN.test(challanId)) notFound();
  const session = await loadSession();
  if (session.status === "unauthenticated") redirect(loginUrl(await requestedPath()) as Route);
  if (session.status === "error") return <SessionUnavailable problem={session.problem} />;
  return <ChallanPrint key={challanId} challanId={challanId} />;
}
