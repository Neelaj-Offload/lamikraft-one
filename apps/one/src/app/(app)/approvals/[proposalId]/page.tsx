import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { ReviewScreen } from "~/screens/inbox/review-screen";

export const metadata: Metadata = { title: "Review request · Inbox" };

/**
 * The address the server uses for an approval (the briefing's Review action, a task's source
 * record). It shows the same review screen as `/inbox/approvals/{id}`, so old and outside links work.
 */
export default async function Page({ params }: { params: Promise<{ proposalId: string }> }) {
  const { proposalId } = await params;
  if (!UUID_PATTERN.test(proposalId)) notFound();
  return <ReviewScreen proposalId={proposalId} />;
}
