import type { Metadata } from "next";
import { ReviewLinkView } from "@/features/channels/review-link-view";
import { getRoute } from "@/lib/routes";

const route = getRoute("review-link");

export const metadata: Metadata = { title: route.label, robots: { index: false, follow: false } };

/** A review link from WhatsApp (`/r/{token}`): resolved for the signed-in person, then redirected. */
export default async function ReviewLinkPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <ReviewLinkView token={token} />;
}
