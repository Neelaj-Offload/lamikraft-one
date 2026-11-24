"use client";

import { useEffect, useRef } from "react";
import { runOutput } from "@/features/assistant/parse";
import type { AgentRun, SelectedOption } from "@/features/assistant/types";
import { useAssistant, type Exchange } from "@/features/assistant/use-assistant";
import { announce } from "@/lib/a11y/announcer";
import { isAgentRunActive } from "@/lib/api/polling";
import { useSession } from "@/lib/session/context";
import { assistantIsDemo, RUN_STATUS, runEnding, stepText } from "~/data/today";
import { Aurora, Banner, Button, Composer, GlassPanel, Icon, Orb } from "~/ui";
import { AssistantCardView, DemoBadge } from "./assistant-cards";

/**
 * The one AI entry point on Today: the composer at the foot of the column, its replies above it.
 * A message goes out with the structured screen context; the run then streams (or is polled) and
 * the server's steps, text and cards appear in a glass reply. Rendered only when the assistant is
 * switched on for this person; the aurora and the orb appear nowhere else on the screen.
 */
export function TodayAssistant() {
  const { bootstrap } = useSession();
  const demo = assistantIsDemo(bootstrap);
  const { exchanges, busy, send, cancel } = useAssistant();

  // One announcement per finished run; the reply itself is not a live region.
  const last = exchanges.at(-1);
  const lastStatus = last?.run?.status ?? null;
  const lastRunId = last?.run?.id ?? null;
  const announced = useRef<string | null>(null);
  useEffect(() => {
    if (!lastRunId || isAgentRunActive(lastStatus)) return;
    const key = `${lastRunId}:${lastStatus}`;
    if (announced.current === key) return;
    announced.current = key;
    announce(RUN_STATUS[lastStatus ?? ""] ?? RUN_STATUS.succeeded!);
  }, [lastRunId, lastStatus]);

  // A new message brings its reply into view: the composer sits at the foot of a long column.
  const endRef = useRef<HTMLDivElement>(null);
  const count = exchanges.length;
  useEffect(() => {
    if (count > 0) endRef.current?.scrollIntoView({ block: "nearest" });
  }, [count]);

  const running = Boolean(last?.run && isAgentRunActive(last.run.status));

  return (
    <section aria-label="Lamikraft assistant" className="rise flex flex-col gap-4" style={{ "--i": 6 } as React.CSSProperties}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="t-h3">Ask Lamikraft</h2>
          {demo ? <DemoBadge /> : null}
        </div>
        <p className="t-body-sm text-ink-3">It reads the briefing above, so you can say &ldquo;the second item&rdquo;.</p>
      </div>

      {exchanges.length > 0 ? (
        <ol aria-label="Conversation with Lamikraft" className="m-0 flex list-none flex-col gap-4 p-0">
          {exchanges.map((exchange) => (
            <ExchangeView
              key={exchange.id}
              exchange={exchange}
              busy={busy}
              onChoose={(value, label) => void send(label, { selectedOption: value })}
              onStop={exchange === last && running ? () => void cancel() : undefined}
            />
          ))}
        </ol>
      ) : null}

      <div ref={endRef}>
        <Composer
          label="Ask about your day, or say what to do"
          placeholder="Ask about your day, or say what to do"
          busy={busy}
          onSend={(text) => void send(text)}
        />
      </div>
    </section>
  );
}

function ExchangeView({
  exchange,
  busy,
  onChoose,
  onStop,
}: {
  exchange: Exchange;
  busy: boolean;
  onChoose: (value: SelectedOption, label: string) => void;
  onStop?: () => void;
}) {
  return (
    <li className="rise-plain flex flex-col gap-3">
      <p className="t-body bg-surface border-line text-ink max-w-[52ch] self-end rounded-lg border px-4 py-3">
        <span className="lk-sr-only">You asked: </span>
        {exchange.text}
      </p>
      {exchange.run ? <Reply run={exchange.run} busy={busy} onChoose={onChoose} onStop={onStop} /> : null}
      {exchange.problem ? <Banner tone="amber">{exchange.problem}</Banner> : null}
    </li>
  );
}

function Reply({
  run,
  busy,
  onChoose,
  onStop,
}: {
  run: AgentRun;
  busy: boolean;
  onChoose: (value: SelectedOption, label: string) => void;
  onStop?: () => void;
}) {
  const steps = run.steps.flatMap((step) => {
    const label = stepText(step);
    return label ? [{ step, label }] : [];
  });
  const { texts, cards } = runOutput(run);
  const active = isAgentRunActive(run.status);
  const ended = runEnding(run.status);

  return (
    <GlassPanel padding="md" className="overflow-hidden">
      <Aurora quiet />
      <div className="relative flex flex-col gap-4">
        <div className="flex items-start gap-3">
          <span aria-hidden="true" className="flex-none">
            <Orb size="sm" state={active ? "thinking" : "idle"} />
          </span>
          <div className="flex min-w-0 flex-1 flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="t-label text-ink">Lamikraft</p>
              {onStop ? (
                <Button variant="ghost" size="sm" iconLeft="stop" onPress={onStop}>
                  Stop
                </Button>
              ) : null}
            </div>
            {steps.length > 0 || active ? (
              <ol aria-label="What Lamikraft did" className="t-body-sm text-ink-2 m-0 flex list-none flex-col gap-1 p-0">
                {steps.map(({ step, label }) => (
                  <li key={step.seq} className={step.is_error ? "text-amber-text flex items-center gap-2" : "flex items-center gap-2"}>
                    <Icon name={step.is_error ? "alert" : "check"} size={14} />
                    {label}
                    {step.is_error ? ", did not work" : null}
                  </li>
                ))}
                {active ? <li className="t-label text-ink">{RUN_STATUS[run.status] ?? RUN_STATUS.running}</li> : null}
              </ol>
            ) : null}
            {texts.map((text, index) => (
              <p key={`text-${index}`} className="t-body-lg text-ink max-w-[68ch] whitespace-pre-line">
                {text}
              </p>
            ))}
          </div>
        </div>
        {cards.map((card, index) => (
          <AssistantCardView key={`card-${index}`} card={card} busy={busy} onChoose={(option) => onChoose(option.value, option.label)} />
        ))}
        {run.tainted ? (
          <p className="t-body-sm text-amber-text flex items-start gap-2">
            <Icon name="alert" size={16} />
            This answer used text from a customer message. Check every detail before you act on it.
          </p>
        ) : null}
        {ended ? <p className="t-body-sm text-ink-2">{ended}</p> : null}
      </div>
    </GlassPanel>
  );
}
