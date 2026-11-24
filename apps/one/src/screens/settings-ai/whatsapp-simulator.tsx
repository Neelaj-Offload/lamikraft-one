"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { DEMO_VOICE_NOTES, type DemoVoiceNote, type Message } from "@/features/channels/api";
import { cx } from "@/lib/cx";
import { queryKeys } from "@/lib/api/query-keys";
import { problemText, useDemoThread, useSendDemoMessage } from "~/data/settings-ai";
import { ErrorBlock } from "~/shell/states";
import { Badge, Banner, Button, Composer, DateText, EmptyState, GlassPanel, Orb, Select, SkeletonText } from "~/ui";

export const SIMULATOR_ID = "whatsapp-simulator";

const STATUS: Record<Message["status"], string> = {
  queued: "Queued",
  accepted: "Accepted",
  sent: "Sent",
  delivered: "Delivered",
  read: "Read",
  played: "Played",
  failed: "Failed",
  unknown: "Outcome unknown",
  blocked: "Blocked",
};

const VOICE_NOTES: Record<DemoVoiceNote, string> = {
  oak_tray_quote: "“Prepare Nordhaus's usual oak tray quotation”",
  hinglish_oak_tray: "Hinglish: “Nordhaus ka usual oak tray quote bana do”",
  unclear: "A recording too unclear to understand",
};

function Bubble({ message, busy, onButton }: { message: Message; busy: boolean; onButton: (id: string) => void }) {
  const mine = message.direction === "inbound";
  const blocked = message.outbox_state === "blocked";
  const buttons = mine ? [] : (message.buttons ?? []).filter((button) => Boolean(button.id));
  return (
    <li className={cx("rise-plain flex flex-col gap-1.5", mine ? "items-end" : "items-start")}>
      <p
        className={cx(
          "t-body m-0 max-w-[85%] whitespace-pre-wrap break-words rounded-lg px-3.5 py-2.5",
          mine ? "bg-inverse text-on-inverse" : "border border-line bg-surface text-ink",
        )}
      >
        <span className="lk-sr-only">{mine ? "You: " : "Lamikraft: "}</span>
        {message.body ?? <span className="text-ink-3">[{message.type}]</span>}
      </p>
      {buttons.length > 0 ? (
        <div className="flex max-w-[85%] flex-wrap gap-2">
          {buttons.map((button) => (
            <Button key={button.id} size="sm" variant="secondary" isDisabled={busy} onPress={() => onButton(button.id as string)}>
              {button.title}
            </Button>
          ))}
        </div>
      ) : null}
      <span className="t-caption flex flex-wrap items-center gap-x-2 text-ink-3">
        <DateText value={message.created_at} style="dayTime" />
        {!mine ? <span>{blocked ? `Not sent${message.blocked_reason ? `: ${message.blocked_reason}` : ""}` : STATUS[message.status]}</span> : null}
        {message.simulated ? <span>Simulated</span> : null}
      </span>
    </li>
  );
}

/**
 * Demo mode only: chat with the assistant as if from your phone. Each message goes through the
 * real signed webhook, inbox and worker, so the replies, buttons and linking behave as they would
 * on WhatsApp. The thread is polled while it is on screen.
 */
export function Simulator({ draft, onDraftChange }: { draft: string; onDraftChange: (text: string) => void }) {
  const client = useQueryClient();
  const thread = useDemoThread(true);
  const send = useSendDemoMessage();
  const [voice, setVoice] = useState<DemoVoiceNote | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const messages = thread.data?.messages ?? [];

  // The worker links the number after the LINK message: refresh "Linked numbers" when that changes.
  const linkedStatus = thread.data?.identity?.status ?? null;
  useEffect(() => {
    void client.invalidateQueries({ queryKey: queryKeys.channels.identities("mine") });
  }, [client, linkedStatus]);

  // Keep the newest message in view, as a phone would.
  useEffect(() => {
    const box = scroller.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [messages.length]);

  const sendText = (text: string) => {
    // The composer clears itself on send; put the text back if the message did not go.
    send.mutate({ text }, { onError: () => onDraftChange(text) });
  };

  return (
    <GlassPanel as="section" id={SIMULATOR_ID} padding="md" className="rise flex scroll-mt-24 flex-col gap-4" aria-labelledby={`${SIMULATOR_ID}-title`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span aria-hidden="true" className="flex-none">
            <Orb size="sm" state={send.isPending ? "thinking" : "idle"} />
          </span>
          <div className="flex min-w-0 flex-col">
            <h2 id={`${SIMULATOR_ID}-title`} className="t-h4">
              Simulator
            </h2>
            {thread.data?.wa_id_masked ? (
              <p className="t-caption text-ink-3">
                Your demo number <span className="lk-mono">{thread.data.wa_id_masked}</span>
              </p>
            ) : null}
          </div>
        </div>
        <Badge outline>Demo</Badge>
      </div>

      <p className="t-body-sm text-ink-2">Chat with the assistant as if from your phone. Nothing leaves Lamikraft One.</p>

      <div
        ref={scroller}
        className="max-h-[28rem] min-h-48 overflow-y-auto rounded-lg border border-line bg-ground p-3"
        aria-live="polite"
        aria-label="Simulator conversation"
        tabIndex={0}
      >
        {thread.isPending ? (
          <div role="status" aria-label="Loading the conversation">
            <SkeletonText lines={4} />
          </div>
        ) : thread.isError ? (
          <ErrorBlock error={thread.error} what="The simulator conversation" onRetry={() => void thread.refetch()} />
        ) : messages.length === 0 ? (
          <EmptyState compact icon="message" title="No messages yet" text="Create a link code, put it in the simulator and send it." />
        ) : (
          <ol className="m-0 flex list-none flex-col gap-3 p-0">
            {messages.map((message) => (
              <Bubble key={message.id} message={message} busy={send.isPending} onButton={(id) => send.mutate({ button_id: id })} />
            ))}
          </ol>
        )}
      </div>

      <div className="flex flex-col gap-4">
        <Composer
          label="Message to the assistant"
          placeholder="Type a message, for example LINK 1234 5678"
          value={draft}
          onChange={onDraftChange}
          onSend={sendText}
          busy={send.isPending}
        />
        <div className="flex flex-wrap items-end gap-3">
          <Select
            className="min-w-0 flex-1 basis-56"
            label="Demo voice note"
            placeholder="Choose a recording"
            options={DEMO_VOICE_NOTES.map((key) => ({ value: key, label: VOICE_NOTES[key] }))}
            value={voice}
            onChange={(value) => setVoice(value as DemoVoiceNote)}
          />
          <Button variant="secondary" iconLeft="mic" isDisabled={voice === null || send.isPending} onPress={() => voice && send.mutate({ audio_fixture: voice })}>
            Send voice note
          </Button>
        </div>
        {send.isError ? (
          <Banner tone="ember" title="The message was not sent">
            {problemText(send.error) ?? "Try again in a moment."}
          </Banner>
        ) : null}
      </div>
    </GlassPanel>
  );
}
