import type { Metadata } from "next";
import { messageListStateFrom } from "@/features/sales/list-state";
import { UUID_PATTERN } from "@/lib/app-links";
import { MessageInbox } from "~/screens/sales/messages/inbox";

export const metadata: Metadata = { title: "Customer messages" };

/** The message inbox; `?status=` picks waiting, replied or all, `?message=<id>` brings one message into view. */
export default async function CustomerMessagesPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const search = await searchParams;
  const state = messageListStateFrom(search);
  const raw = Array.isArray(search.message) ? search.message[0] : search.message;
  const focusId = raw && UUID_PATTERN.test(raw) ? raw : null;
  return <MessageInbox key={`${state.status}|${state.offset}`} state={state} focusId={focusId} />;
}
