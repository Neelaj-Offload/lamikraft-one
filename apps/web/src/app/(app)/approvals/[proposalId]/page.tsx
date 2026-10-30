import type { Route } from "next";
import { notFound, redirect } from "next/navigation";
import { reviewHref, UUID_PATTERN } from "@/lib/app-links";

/**
 * Backend modules link an approval as `/approvals/{proposal_id}` (briefing Review action,
 * task source refs); the review page lives in the Inbox. Old and external links land there.
 */
export default async function ApprovalAliasPage({ params }: { params: Promise<{ proposalId: string }> }) {
  const { proposalId } = await params;
  if (!UUID_PATTERN.test(proposalId)) notFound();
  redirect(reviewHref(proposalId) as Route);
}
