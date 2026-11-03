"use client";

import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { createIdempotencyKey } from "@/lib/api/client";
import { isEndpointUnavailable, isNetworkError, ProblemError } from "@/lib/api/errors";
import { agentRunPollInterval, isAgentRunActive } from "@/lib/api/polling";
import { assistantMessages as m } from "@/messages/assistant";
import { cancelRun, createConversation, fetchRun, postTurn } from "./api";
import { lastSeq, mergeRun } from "./parse";
import { openRunStream, sseEnabled } from "./run-stream";
import { buildScreenContext, type ScreenContribution } from "./screen-context";
import { currentContributions } from "./screen-context-store";
import type { AgentRun, SelectedOption } from "./types";

export interface Exchange {
  id: string;
  text: string;
  run: AgentRun | null;
  /** Why the turn or its polling failed, in the person's words. */
  problem: string | null;
}

/** The calm message for an assistant failure (ai-routing §1.4: everything degrades, visibly). */
export function assistantProblem(error: unknown): string {
  if (isNetworkError(error)) return m.problems.offline;
  if (error instanceof ProblemError) {
    if (error.code === "not_configured") return m.problems.notConfigured;
    if (isEndpointUnavailable(error)) return m.problems.notInstalled;
    if (error.status === 403) return m.problems.notAllowed;
    if (error.status === 422) return m.problems.tooLarge;
    if (error.status === 429) return m.problems.busy;
    if (error.status >= 500) return m.problems.down;
    return error.detail ?? m.problems.down;
  }
  return m.problems.down;
}

/** The message for a run that ended without success. */
export function runEndText(run: AgentRun): string | null {
  if (run.status === "failed") return m.run.failed;
  if (run.status === "budget_exceeded") return m.run.budget;
  if (run.status === "cancelled") return m.run.cancelled;
  return null;
}

export interface UseAssistant {
  exchanges: Exchange[];
  busy: boolean;
  send: (text: string, options?: { selectedOption?: SelectedOption }) => Promise<void>;
  cancel: () => Promise<void>;
}

/**
 * One conversation per mounted composer: created on the first message, then each message is a
 * turn with the current screen context; the run streams over SSE (or is polled every 500 ms) until it ends.
 */
export function useAssistant(extra: ScreenContribution | null = null): UseAssistant {
  const pathname = usePathname() ?? "/";
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [sending, setSending] = useState(false);
  // Bumped after every poll: a run that stays queued with no new steps must still be polled again.
  const [pollTick, setPollTick] = useState(0);
  const conversation = useRef<string | null>(null);
  const extraRef = useRef(extra);
  extraRef.current = extra;

  const active = exchanges.at(-1);
  const activeRun = active?.run ?? null;
  const runActive = activeRun !== null && isAgentRunActive(activeRun.status);

  const patch = useCallback((id: string, change: (exchange: Exchange) => Exchange) => {
    setExchanges((current) => current.map((exchange) => (exchange.id === id ? change(exchange) : exchange)));
  }, []);

  const runId = activeRun?.id ?? null;
  const runStatus = activeRun?.status ?? null;
  const afterSeq = lastSeq(activeRun);
  const exchangeId = active?.id ?? null;
  // Runs whose stream failed or timed out: polled from then on (ADR-059; polling is the fallback).
  const [polled, setPolled] = useState<ReadonlySet<string>>(() => new Set());
  const streaming = runId !== null && runActive && sseEnabled() && !polled.has(runId);
  const afterSeqRef = useRef(afterSeq);
  afterSeqRef.current = afterSeq;

  // Stream the active run over SSE while it is queued or running.
  useEffect(() => {
    if (!streaming || !runId || !exchangeId) return;
    return openRunStream(runId, afterSeqRef.current, {
      onUpdate: (update) => patch(exchangeId, (exchange) => ({ ...exchange, run: mergeRun(exchange.run, update) })),
      onFallback: () => setPolled((current) => new Set(current).add(runId)),
    });
  }, [streaming, runId, exchangeId, patch]);

  // Poll the active run: every 500 ms while it is queued or running, then stop.
  useEffect(() => {
    if (!runId || !exchangeId || streaming) return;
    const delay = agentRunPollInterval(runStatus);
    if (delay === false) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      fetchRun(runId, afterSeq, controller.signal)
        .then((update) => {
          patch(exchangeId, (exchange) => ({ ...exchange, run: mergeRun(exchange.run, update) }));
          setPollTick((tick) => tick + 1);
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return;
          patch(exchangeId, (exchange) => ({
            ...exchange,
            problem: assistantProblem(error),
            run: exchange.run ? { ...exchange.run, status: "failed" } : exchange.run,
          }));
        });
    }, delay);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [runId, runStatus, afterSeq, exchangeId, patch, pollTick, streaming]);

  const send = useCallback(
    async (text: string, options: { selectedOption?: SelectedOption } = {}) => {
      const value = text.trim();
      if (!value || sending || runActive) return;
      const id = createIdempotencyKey();
      setExchanges((current) => [...current, { id, text: value, run: null, problem: null }]);
      setSending(true);
      try {
        conversation.current ??= await createConversation();
        const contributions = [...currentContributions(), ...(extraRef.current ? [extraRef.current] : [])];
        const context = buildScreenContext({
          pathname,
          contributions,
          now: new Date(),
          viewport: typeof window === "undefined" ? null : { width: window.innerWidth, height: window.innerHeight },
        });
        const run = await postTurn(conversation.current, { text: value, context, selectedOption: options.selectedOption, clientUtteranceId: id }, id);
        patch(id, (exchange) => ({ ...exchange, run: { id: run, status: "queued", error_code: null, tainted: false, provider: null, steps: [], text: null, cards: [] } }));
      } catch (error) {
        patch(id, (exchange) => ({ ...exchange, problem: assistantProblem(error) }));
      } finally {
        setSending(false);
      }
    },
    [pathname, patch, runActive, sending],
  );

  const cancel = useCallback(async () => {
    if (!activeRun || !exchangeId || !isAgentRunActive(activeRun.status)) return;
    try {
      const stopped = await cancelRun(activeRun.id);
      if (stopped) patch(exchangeId, (exchange) => ({ ...exchange, run: mergeRun(exchange.run, stopped) }));
    } catch (error) {
      patch(exchangeId, (exchange) => ({ ...exchange, problem: assistantProblem(error) }));
    }
  }, [activeRun, exchangeId, patch]);

  return { exchanges, busy: sending || runActive, send, cancel };
}
