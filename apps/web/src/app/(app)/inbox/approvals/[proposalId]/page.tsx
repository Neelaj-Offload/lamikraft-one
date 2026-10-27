import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ReviewView } from "@/features/approvals/review-view";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("inbox-approval-review");

export const metadata: Metadata = { title: `${route.label} · Inbox` };

/** The review page for one approval request: facts, the quote under review, the decision. */
export default async function ApprovalReviewPage({ params }: { params: Promise<{ proposalId: string }> }) {
  const { proposalId } = await params;
  if (!UUID_PATTERN.test(proposalId)) notFound();
  return <ReviewView proposalId={proposalId} />;
}
