import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { ReviewScreen } from "~/screens/inbox/review-screen";

export const metadata: Metadata = { title: "Review request · Inbox" };

/** One review request: what is proposed, the evidence, the decision. */
export default async function Page({ params }: { params: Promise<{ proposalId: string }> }) {
  const { proposalId } = await params;
  if (!UUID_PATTERN.test(proposalId)) notFound();
  return <ReviewScreen proposalId={proposalId} />;
}
