"use client";

/**
 * Data for the Inbox screens: the triage lists and their counts, one task and its commands, one
 * review request and its decision, and the customer message behind a conversation.
 *
 * The wire calls, parsers and query keys are the old app's (`@/features/inbox/api`,
 * `@/features/approvals/api`, `@/features/sales/api`); the hooks below restate what lived inside
 * the old view files (task drawer, review view): the same endpoints, bodies, Idempotency-Keys,
 * conflict handling and cache invalidation.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import {
  decideProposal,
  fetchProposal,
  isReviewConflict,
  withdrawProposal,
  type Proposal,
  type ProposalTarget,
} from "@/features/approvals/api";
import { snoozeUntil } from "@/features/briefing/api";
import {
  assignTask,
  fetchInbox,
  fetchInboxCounts,
  fetchTask,
  snoozeTask,
  transitionTask,
  unsnoozeTask,
} from "@/features/inbox/api";
import type { InboxCounts, InboxTab, TaskDetail, TaskTransitionOption } from "@/features/inbox/types";
import { fetchQuote, markMessageReplied, MESSAGES_PATH } from "@/features/sales/api";
import { parseCustomerMessage } from "@/features/sales/parse";
import type { CustomerMessage } from "@/features/sales/types";
import { api, requestUntyped } from "@/lib/api/client";
import { commandSignature, createCommandKeys } from "@/lib/api/command-keys";
import { conflictFromError, isStalenessConflict, ProblemError } from "@/lib/api/errors";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { useOnline } from "@/lib/hooks";
import { useSession } from "@/lib/session/context";
import { useUiPoll } from "@/lib/session/use-ui-poll";
import { toast } from "~/ui/toast";

export const OFFLINE_NOTE = "You are offline. Actions come back when the connection does.";

/** The server's own words for a failed command, with the reference support will ask for. */
function problemText(error: unknown): string | undefined {
  if (!(error instanceof ProblemError)) return undefined;
  const text = [error.detail ?? error.title, error.request_id ? `Reference ${error.request_id}` : null].filter(Boolean).join(" ");
  return text || undefined;
}

// ---- lists and counts ----

/** One kind of work, one page. `enabled` lets a screen skip kinds it does not show. */
export function useInboxList(tab: InboxTab, cursor: string | null, enabled = true) {
  return useQuery({
    queryKey: queryKeys.tasks.inbox({ tab, cursor }),
    queryFn: ({ signal }) => fetchInbox(tab, cursor, signal),
    enabled,
  });
}

/** Counts per kind: the counts endpoint, else the UI poll, else the session bootstrap. Never invented. */
export function useInboxCounts(): InboxCounts {
  const { bootstrap } = useSession();
  const fetched = useQuery({ queryKey: queryKeys.tasks.counts(), queryFn: ({ signal }) => fetchInboxCounts(signal) });
  const poll = useUiPoll();
  const polled = poll.data?.inbox_counts.status === "ok" ? poll.data.inbox_counts.value.tabs : null;
  const booted = bootstrap.inbox_counts.status === "ok" ? bootstrap.inbox_counts.value.tabs : null;
  return fetched.data ?? (polled as InboxCounts | null) ?? (booted as InboxCounts | null) ?? {};
}

// ---- one task ----

export function useTask(taskId: string | null) {
  return useQuery({
    queryKey: queryKeys.tasks.task(taskId ?? ""),
    queryFn: ({ signal }) => fetchTask(taskId!, signal),
    enabled: taskId !== null,
  });
}

export type SnoozeChoice = "1h" | "3h" | "24h";

/**
 * The commands of one task. Each resolves true when the server accepted it; failures raise their
 * own toast (a stale version reloads the task and says so), so callers only decide what to close.
 */
export function useTaskCommands(task: TaskDetail | undefined) {
  const { bootstrap } = useSession();
  const online = useOnline();
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<string | null>(null);
  const [commandKeys] = useState(() => createCommandKeys());
  const userId = bootstrap.user.id;

  const run = useCallback(
    async (name: string, done: string, failed: string, parts: (string | number | null)[], call: (key: string) => Promise<unknown>): Promise<boolean> => {
      if (!task || pending || !online) return false;
      const signature = commandSignature(task.id, task.version, ...parts);
      const attempt = commandKeys.attempt(signature, () => null);
      const refresh = () => Promise.all(invalidationMap["tasks.task_command"].map((queryKey) => queryClient.invalidateQueries({ queryKey })));
      setPending(name);
      try {
        await call(attempt.key);
        commandKeys.settle(signature);
        toast.success(done);
        await refresh();
        return true;
      } catch (error) {
        commandKeys.settle(signature, error);
        if (isStalenessConflict(error)) {
          toast.info("This task changed while you had it open. You are now looking at the latest version.");
          await refresh();
        } else if (error instanceof ProblemError && error.code === "not_complete") {
          toast.warning("The record does not show this as done yet", { description: error.detail ?? undefined });
        } else {
          toast.error(failed, { description: problemText(error) });
        }
        return false;
      } finally {
        setPending(null);
      }
    },
    [task, pending, online, commandKeys, queryClient],
  );

  return {
    pending,
    offline: !online,
    transition: (option: TaskTransitionOption, reasonCode: string | null = null, note: string | null = null) => {
      const words: Record<TaskTransitionOption["action"], [string, string]> = {
        start: ["Started. It is yours until it is done.", "The task could not be started"],
        complete: ["Marked as done.", "The task could not be marked as done"],
        dismiss: ["Dismissed, with your reason on record.", "The task could not be dismissed"],
      };
      const [done, failed] = words[option.action];
      return run(option.action, done, failed, [option.action, reasonCode, note], (key) =>
        transitionTask(task!, option.action, { reasonCode, note, idempotencyKey: key }),
      );
    },
    assignToMe: () => run("assign", "This one is yours now.", "The task could not be assigned to you", ["assign", userId], (key) => assignTask(task!, userId, key)),
    snooze: (choice: SnoozeChoice) =>
      run("snooze", "Snoozed. It comes back on its own.", "The task could not be snoozed", ["snooze", choice], (key) =>
        snoozeTask(task!.id, snoozeUntil(choice, new Date()), key),
      ),
    unsnooze: () => run("unsnooze", "Back in your inbox.", "The task could not be brought back", ["unsnooze"], () => unsnoozeTask(task!.id)),
  };
}

// ---- the customer message behind a conversation ----

export const customerMessageKey = (messageId: string) => [...queryKeys.sales.all(), "customer-message", { message_id: messageId }] as const;

/** `GET /sales/customer-messages/{id}`. A 403 means the task is visible but the message is not. */
export function useCustomerMessage(messageId: string | null) {
  return useQuery({
    queryKey: customerMessageKey(messageId ?? ""),
    queryFn: async ({ signal }): Promise<CustomerMessage> => {
      const raw = await requestUntyped<unknown>(api, "get", `${MESSAGES_PATH}/${encodeURIComponent(messageId!)}`, { signal });
      const parsed = parseCustomerMessage(raw);
      if (!parsed) throw new Error("The customer message could not be read.");
      return parsed;
    },
    enabled: messageId !== null,
    retry: false,
  });
}

/** "Mark as replied": the same command as the customer messages screen, offered only when the server allows it. */
export function useMarkReplied() {
  const online = useOnline();
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);
  const [commandKeys] = useState(() => createCommandKeys());

  const markReplied = async (message: Pick<CustomerMessage, "id" | "version">): Promise<boolean> => {
    if (pending || !online) return false;
    const signature = commandSignature(message.id, message.version, "mark_replied");
    const attempt = commandKeys.attempt(signature, () => null);
    setPending(true);
    try {
      await markMessageReplied(message, attempt.key);
      commandKeys.settle(signature);
      toast.success("Marked as replied. The conversation leaves your inbox.");
      return true;
    } catch (error) {
      commandKeys.settle(signature, error);
      if (conflictFromError(error)) toast.warning("This message changed while you had it open. You are now looking at the latest version.");
      else toast.error("The message could not be marked as replied", { description: problemText(error) });
      return false;
    } finally {
      setPending(false);
      await Promise.all(invalidationMap["sales.message_replied"].map((queryKey) => queryClient.invalidateQueries({ queryKey })));
    }
  };

  return { markReplied, pending, offline: !online };
}

// ---- one review request ----

export function useProposal(proposalId: string) {
  return useQuery({ queryKey: queryKeys.approvals.proposal(proposalId), queryFn: ({ signal }) => fetchProposal(proposalId, signal) });
}

/** The quotation a request is about, when it is about one. */
export function useProposalQuote(target: ProposalTarget | null) {
  return useQuery({
    queryKey: queryKeys.sales.quote(target?.target_id ?? ""),
    queryFn: ({ signal }) => fetchQuote(target!.target_id, signal),
    enabled: target !== null,
  });
}

export type DecisionOutcome = "done" | "conflict" | "failed";

/**
 * Approve, reject or withdraw, sent with the exact `content_hash` and version on screen. A 409
 * that means "what you reviewed is no longer what would be decided" reloads the request and sets
 * `conflict`, so nothing is decided on a version the person did not read.
 */
export function useProposalDecision(proposal: Proposal | undefined) {
  const online = useOnline();
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [commandKeys] = useState(() => createCommandKeys());

  const act = async (name: string, done: string, failed: string, parts: (string | null)[], call: (key: string) => Promise<unknown>): Promise<DecisionOutcome> => {
    if (!proposal || pending || !online) return "failed";
    const signature = commandSignature(proposal.id, proposal.version, proposal.content_hash, ...parts);
    const attempt = commandKeys.attempt(signature, () => null);
    const refresh = () => Promise.all(invalidationMap["approvals.decide"].map((queryKey) => queryClient.invalidateQueries({ queryKey })));
    setPending(name);
    setConflict(false);
    try {
      await call(attempt.key);
      commandKeys.settle(signature);
      toast.success(done, { action: { label: "Back to approvals", href: "/inbox/approvals" } });
      await refresh();
      return "done";
    } catch (error) {
      commandKeys.settle(signature, error);
      if (isReviewConflict(error)) {
        setConflict(true);
        await refresh();
        return "conflict";
      }
      toast.error(failed, { description: problemText(error) });
      return "failed";
    } finally {
      setPending(null);
    }
  };

  return {
    pending,
    conflict,
    clearConflict: () => setConflict(false),
    offline: !online,
    approve: (done: string) => act("approve", done, "The approval did not go through", ["approve"], (key) => decideProposal(proposal!, "approve", null, key)),
    reject: (reason: string, done: string) =>
      act("reject", done, "The rejection did not go through", ["reject", reason], (key) => decideProposal(proposal!, "reject", reason, key)),
    withdraw: (done: string) => act("withdraw", done, "The request could not be withdrawn", ["withdraw"], (key) => withdrawProposal(proposal!, key)),
  };
}
