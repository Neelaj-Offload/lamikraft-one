import type { Metadata } from "next";
import { InboxPage, type InboxSearchParams } from "@/features/inbox/inbox-page";
import { getRoute } from "@/lib/routes";

const route = getRoute("inbox-exceptions");

export const metadata: Metadata = { title: `${route.label} · Inbox` };

export default function InboxExceptionsPage({ searchParams }: { searchParams: InboxSearchParams }) {
  return <InboxPage tab="exceptions" searchParams={searchParams} />;
}
