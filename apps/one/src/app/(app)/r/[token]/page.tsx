import type { Metadata } from "next";
import { ReviewLinkScreen } from "~/screens/inbox/review-link";

export const metadata: Metadata = { title: "Review link", robots: { index: false, follow: false } };

/** A review link from WhatsApp (`/r/{token}`): checked for the signed-in person, then sent to the right screen. */
export default async function Page({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <ReviewLinkScreen token={token} />;
}
