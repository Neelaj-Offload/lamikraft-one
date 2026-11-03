"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { DemoBadge } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { SectionCard } from "@/components/ui/section-card";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { TextArea } from "@/components/ui/text-field";
import { LocalDateTime } from "@/components/ui/format";
import { cx } from "@/lib/cx";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { channelsMessages } from "@/messages/channels";
import { DEMO_VOICE_NOTES, fetchDemoThread, sendDemoInbound, type DemoInput, type DemoVoiceNote, type Message } from "./api";

const m = channelsMessages.simulator;
/** The worker answers within a few seconds; poll while the simulator is on screen. */
const POLL_MS = 2000;

function Bubble({ message, onButton, busy }: { message: Message; onButton: (id: string) => void; busy: boolean }) {
  const mine = message.direction === "inbound";
  const blocked = message.outbox_state === "blocked";
  const buttons = message.buttons ?? [];
  return (
    <li className={cx("flex flex-col gap-1", mine ? "items-end" : "items-start")}>
      <div
        className={cx(
          "max-w-[85%] rounded-lg border px-3 py-2 text-[15px] whitespace-pre-wrap break-words",
          mine ? "bg-forest text-on-forest border-forest" : "bg-surface-sunken text-ink",
        )}
      >
        <span className="sr-only">{mine ? m.you : m.assistant}: </span>
        {message.body ?? <span className="italic">[{message.type}]</span>}
      </div>
      {buttons.length > 0 && !mine ? (
        <div className="flex max-w-[85%] flex-wrap gap-2">
          {buttons.map((button) =>
            button.id ? (
              <Button key={button.id} size="sm" variant="secondary" onPress={() => onButton(button.id as string)} {...unavailableWhen(busy ? m.sending : null)}>
                {button.title}
              </Button>
            ) : null,
          )}
        </div>
      ) : null}
      <span className="flex items-center gap-2 text-xs text-ink-muted">
        <LocalDateTime value={message.created_at} />
        {!mine ? <span>{blocked ? `${m.blocked}: ${message.blocked_reason ?? ""}` : m.statuses[message.status]}</span> : null}
        {message.simulated ? <span>{m.simulated}</span> : null}
      </span>
    </li>
  );
}

/** The Demo simulator: the signed-in user's demo number chatting with the assistant through the real webhook. */
export function Simulator() {
  const client = useQueryClient();
  const [text, setText] = useState("");
  const [voice, setVoice] = useState<DemoVoiceNote | null>(null);
  const thread = useQuery({ queryKey: queryKeys.channels.demoThread(), queryFn: ({ signal }) => fetchDemoThread(signal), refetchInterval: POLL_MS });
  // the worker links the number after the LINK message: refresh "Linked numbers" when the thread's identity changes
  const linkedStatus = thread.data?.identity?.status ?? null;
  useEffect(() => {
    void client.invalidateQueries({ queryKey: queryKeys.channels.identities("mine") });
  }, [client, linkedStatus]);
  const send = useMutation({
    mutationFn: (input: DemoInput) => sendDemoInbound(input),
    onSuccess: () => Promise.all(invalidationMap["channels.changed"].map((queryKey) => client.invalidateQueries({ queryKey }))),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const body = text.trim();
    if (!body) return;
    send.mutate({ text: body }, { onSuccess: () => setText("") });
  };
  return (
    <SectionCard
      title={m.title}
      description={m.description}
      actions={<DemoBadge label="Demo" title={channelsMessages.status.demoNote} />}
    >
      {thread.data ? (
        <p className="text-sm text-ink-muted">
          {m.numberLabel}: <span className="font-mono">{thread.data.wa_id_masked}</span>
        </p>
      ) : null}
      <div className="max-h-[28rem] min-h-40 overflow-y-auto rounded-lg border bg-surface p-3" aria-live="polite" aria-label={m.title}>
        {thread.isPending ? (
          <Loading label={m.what} rows={3} />
        ) : thread.isError ? (
          <ErrorState error={thread.error} what={m.what} onRetry={() => void thread.refetch()} compact />
        ) : thread.data.messages.length === 0 ? (
          <EmptyState title={m.empty} />
        ) : (
          <ol className="flex flex-col gap-3">
            {thread.data.messages.map((message) => (
              <Bubble key={message.id} message={message} busy={send.isPending} onButton={(id) => send.mutate({ button_id: id })} />
            ))}
          </ol>
        )}
      </div>
      <form className="flex flex-col gap-3" onSubmit={submit}>
        <TextArea label={m.composer} placeholder={m.placeholder} value={text} onChange={setText} rows={2} />
        <div className="flex flex-wrap items-end gap-3">
          <Button type="submit" variant="primary" isPending={send.isPending} pendingLabel={m.sending} {...unavailableWhen(text.trim() ? null : m.typeFirst)}>
            {m.send}
          </Button>
          <Select
            className="min-w-64"
            label={m.voice}
            options={DEMO_VOICE_NOTES.map((key) => ({ id: key, label: m.voiceNotes[key] }))}
            value={voice}
            onChange={(value) => setVoice(value as DemoVoiceNote | null)}
          />
          <Button variant="secondary" onPress={() => voice && send.mutate({ audio_fixture: voice })} {...unavailableWhen(voice ? null : m.voiceChoose)}>
            {m.voiceSend}
          </Button>
        </div>
        {send.isError ? <ErrorState error={send.error} what={m.what} compact backToToday={false} /> : null}
      </form>
    </SectionCard>
  );
}
