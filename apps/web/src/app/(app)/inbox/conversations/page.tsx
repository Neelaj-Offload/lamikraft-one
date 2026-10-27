import type { Metadata } from "next";
import { InboxPage, type InboxSearchParams } from "@/features/inbox/inbox-page";
import { getRoute } from "@/lib/routes";

const route = getRoute("inbox-conversations");

export const metadata: Metadata = { title: `${route.label} · Inbox` };

export default function InboxConversationsPage({ searchParams }: { searchParams: InboxSearchParams }) {
  return <InboxPage tab="conversations" searchParams={searchParams} />;
}
