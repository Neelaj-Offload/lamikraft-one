"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Form } from "react-aria-components";
import { DemoBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SendIcon } from "@/components/ui/icons";
import { TextArea } from "@/components/ui/text-field";
import { announce } from "@/lib/a11y/announcer";
import { isAgentRunActive } from "@/lib/api/polling";
import { cx } from "@/lib/cx";
import { useSession } from "@/lib/session/context";
import type { SessionBootstrap } from "@/lib/session/types";
import { assistantMessages as m } from "@/messages/assistant";
import { VoiceControls, type VoiceControlsHandle } from "@/features/voice/voice-controls";
import { AssistantCardView } from "./cards";
import type { ScreenContribution } from "./screen-context";
import { runOutput } from "./parse";
import type { AgentRun, RunStep, SelectedOption } from "./types";
import { runEndText, useAssistant, type Exchange } from "./use-assistant";

/** Demo when the AI integration runs in demo mode (bootstrap `integration_modes.ai`). */
export function assistantIsDemo(bootstrap: Pick<SessionBootstrap, "integration_modes" | "integrations">): boolean {
  if (bootstrap.integration_modes) return bootstrap.integration_modes.ai === "demo";
  return bootstrap.integrations.status === "ok" && bootstrap.integrations.value.some((item) => item.key === "ai" && item.mode === "demo");
}

/** A step as the person reads it: tool names become plain verbs; internal steps are hidden. */
export function stepLabel(step: RunStep): string | null {
  if (step.kind === "tool_result" || step.kind === "text" || step.kind === "card") return null;
  return (step.name ? m.stepNames[step.name] : undefined) ?? m.stepKinds[step.kind] ?? null;
}

function RunView({ run, onChoose, isBusy }: { run: AgentRun; onChoose: (value: SelectedOption, label: string) => void; isBusy: boolean }) {
  const steps = run.steps.flatMap((step) => {
    const label = stepLabel(step);
    return label ? [{ step, label }] : [];
  });
  const { texts, cards } = runOutput(run);
  const active = isAgentRunActive(run.status);
  const ended = runEndText(run);
  return (
    <div className="flex flex-col gap-3">
      {steps.length > 0 || active ? (
        <div className="flex flex-col gap-1">
          <p className="text-xs font-semibold tracking-[0.06em] text-ink-muted uppercase">{m.steps}</p>
          <ol className="flex flex-col gap-0.5 text-sm text-ink-muted">
            {steps.map(({ step, label }) => (
              <li key={step.seq} className={cx(step.is_error && "text-warning-text")}>
                {label}
                {step.is_error ? ` · ${m.stepError}` : null}
              </li>
            ))}
            {active ? <li className="text-ink">{m.status[run.status] ?? m.working}</li> : null}
          </ol>
        </div>
      ) : null}
      {texts.map((text, index) => (
        <p key={`text-${index}`} className="text-[15px] text-ink">
          {text}
        </p>
      ))}
      {cards.map((card, index) => (
        <AssistantCardView key={`card-${index}`} card={card} isBusy={isBusy} onChoose={(option) => onChoose(option.value, option.label)} />
      ))}
      {run.tainted ? <p className="text-sm text-warning-text">{m.run.tainted}</p> : null}
      {ended ? <p className="text-sm text-ink-muted">{ended}</p> : null}
    </div>
  );
}

function ExchangeView({ exchange, onChoose, isBusy }: { exchange: Exchange; onChoose: (value: SelectedOption, label: string) => void; isBusy: boolean }) {
  return (
    <li className="flex flex-col gap-3 border-t pt-3 first:border-t-0 first:pt-0">
      <p className="text-[15px]">
        <span className="font-semibold text-ink">{m.you}: </span>
        <span className="text-ink">{exchange.text}</span>
      </p>
      {exchange.run ? <RunView run={exchange.run} onChoose={onChoose} isBusy={isBusy} /> : null}
      {exchange.problem ? (
        <p role="alert" className="text-sm text-warning-text">
          {exchange.problem}
        </p>
      ) : null}
    </li>
  );
}

export interface ComposerProps {
  /** `today`: the command bar under the greeting; `dock`: the composer on record pages. */
  variant?: "today" | "dock";
  /** Screen context added by the host (in addition to what the page registered). */
  context?: ScreenContribution | null;
  className?: string;
}

/**
 * The assistant composer: a text box that sends the message plus the structured screen context,
 * then shows what the assistant does (streamed over SSE, polled every 500 ms as the fallback;
 * ADR-059) and the server's cards. When the assistant is not available for the role the box
 * stays visible, disabled, and says why. Voice, "Look at my screen" and photo extraction live in
 * `VoiceControls` under the text box.
 */
export function Composer({ variant = "today", context = null, className }: ComposerProps) {
  const { bootstrap } = useSession();
  const available = bootstrap.capabilities.assistant;
  const demo = assistantIsDemo(bootstrap);
  const { exchanges, busy, send, cancel } = useAssistant(context);
  const [text, setText] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const voiceRef = useRef<VoiceControlsHandle>(null);
  const hintId = useId();
  const listId = useId();

  // One announcement per finished run (the steps list itself is not a live region).
  const last = exchanges.at(-1);
  const lastStatus = last?.run?.status ?? null;
  const announced = useRef<string | null>(null);
  useEffect(() => {
    if (!last?.run || isAgentRunActive(lastStatus)) return;
    const key = `${last.run.id}:${lastStatus}`;
    if (announced.current === key) return;
    announced.current = key;
    announce(m.status[lastStatus ?? ""] ?? m.status.succeeded!);
  }, [last, lastStatus]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const value = text.trim();
    if (!available || !value || busy) return;
    setText("");
    voiceRef.current?.interrupt();
    if (await voiceRef.current?.beforeSend(value)) return; // answered from the attached masked screenshot
    await send(value);
  };

  const label = variant === "dock" ? m.quoteLabel : m.label;
  return (
    <div ref={rootRef} className={cx("flex flex-col gap-3", className)}>
      {exchanges.length > 0 ? (
        <section aria-label={m.conversation} className="flex max-h-[60vh] flex-col gap-3 overflow-y-auto">
          <ol id={listId} className="flex flex-col gap-3">
            {exchanges.map((exchange) => (
              <ExchangeView
                key={exchange.id}
                exchange={exchange}
                isBusy={busy}
                onChoose={(value, optionLabel) => void send(optionLabel, { selectedOption: value })}
              />
            ))}
          </ol>
        </section>
      ) : null}
      <Form onSubmit={submit} className="flex flex-col gap-2">
        <div className="flex items-end gap-2">
          <TextArea
            label={label}
            placeholder={variant === "dock" ? m.quotePlaceholder : m.placeholder}
            rows={1}
            value={text}
            onChange={setText}
            isDisabled={!available}
            aria-describedby={available ? undefined : hintId}
            className="flex-1"
          />
          {busy && last?.run && isAgentRunActive(last.run.status) ? (
            <Button variant="secondary" onPress={() => void cancel()}>
              {m.cancel}
            </Button>
          ) : available ? (
            <Button type="submit" variant="primary" isPending={busy} pendingLabel={m.working} icon={<SendIcon size={18} />}>
              {m.send}
            </Button>
          ) : (
            <Button type="submit" variant="primary" isDisabled disabledReason={m.unavailable} icon={<SendIcon size={18} />}>
              {m.send}
            </Button>
          )}
        </div>
        {available ? <VoiceControls ref={voiceRef} rootRef={rootRef} assistant={{ send, exchanges, busy }} /> : null}
        <div className="flex flex-wrap items-center gap-2">
          {demo && available ? <DemoBadge label={m.demo} title={m.demoHint} /> : null}
          {available ? null : (
            <p id={hintId} className="text-xs text-ink-muted md:text-sm">
              {m.unavailable}
            </p>
          )}
        </div>
      </Form>
    </div>
  );
}
