"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { DISMISSAL_REASON_CODES } from "@/features/briefing/types";
import type { TaskDetail, TaskTransitionOption } from "@/features/inbox/types";
import { reviewHref } from "@/lib/app-links";
import { useNow, useSession } from "@/lib/session/context";
import { OFFLINE_NOTE, useCustomerMessage, useMarkReplied, useTask, useTaskCommands, type SnoozeChoice } from "~/data/inbox";
import { ErrorBlock } from "~/shell/states";
import {
  Badge,
  Banner,
  Button,
  ButtonLink,
  DateText,
  Drawer,
  KeyValue,
  Menu,
  Modal,
  RadioGroup,
  SkeletonText,
  Textarea,
  TextLink,
  type KeyValueItem,
  type MenuItem,
} from "~/ui";
import { canMarkReplied, ConversationSkeleton, ConversationThread } from "./conversation";
import { holderText, KIND_LOOK, kindOf, taskBadge } from "./model";

const DISMISS_REASONS: Record<(typeof DISMISSAL_REASON_CODES)[number], string> = {
  handled_outside_system: "Handled outside Lamikraft One",
  not_applicable: "Does not apply",
  duplicate: "A duplicate of another task",
  customer_withdrew: "The customer withdrew",
  no_action_needed: "Nothing needs doing",
};

const TRANSITION_LABEL: Record<TaskTransitionOption["action"], string> = { start: "Start task", complete: "Mark as done", dismiss: "Dismiss task" };

/**
 * What the server offers for this task, and nothing else: transitions from `allowed_transitions`,
 * assign and snooze only when their capability is allowed.
 */
function commandsOf(task: TaskDetail, userId: string) {
  const find = (action: TaskTransitionOption["action"]) => task.allowed_transitions.find((option) => option.action === action) ?? null;
  return {
    start: find("start"),
    complete: find("complete"),
    dismiss: find("dismiss"),
    assignToMe: Boolean(task.capabilities.assign?.allowed) && task.assignee_user_id !== userId,
    snooze: Boolean(task.capabilities.snooze?.allowed) && !task.snoozed_until,
    unsnooze: Boolean(task.capabilities.snooze?.allowed) && Boolean(task.snoozed_until),
    review: task.proposal_id ? (reviewHref(task.proposal_id) as Route) : null,
  };
}

/**
 * One thing from the inbox, opened in place (`?task=<id>` on any view): what it is, where it
 * stands, the record it is about, and what this person may do with it. A conversation also shows
 * the customer's message as a thread.
 *
 * The footer holds one loud button and a More menu, never a row of equals: the review for an
 * approval, "Mark as replied" for a conversation, otherwise the task's own next step.
 */
export function TaskDrawer({ taskId, closeHref }: { taskId: string | null; closeHref: Route }) {
  const router = useRouter();
  const { bootstrap, zone } = useSession();
  const now = useNow();
  const query = useTask(taskId);
  const task = taskId ? query.data : undefined;
  const commands = useTaskCommands(task);
  const [dismissOpen, setDismissOpen] = useState(false);

  const messageId = task?.source?.type === "sales.customer_message" ? task.source.id : null;
  const messageQuery = useCustomerMessage(messageId);
  const message = messageId ? messageQuery.data : undefined;
  const reply = useMarkReplied();

  const close = () => router.push(closeHref, { scroll: false });
  const closeIf = (ok: boolean) => (ok ? close() : undefined);
  const offered = task ? commandsOf(task, bootstrap.user.id) : null;
  const kind = task ? kindOf(task) : "task";
  const busy = commands.pending !== null || reply.pending;
  const offline = commands.offline;

  const canReply = message !== undefined && canMarkReplied(message);
  const primary = offered?.review ? "review" : canReply ? "reply" : offered?.complete ? "complete" : offered?.start ? "start" : null;

  const more: MenuItem[] = [];
  if (offered?.start && primary !== "start") {
    const start = offered.start;
    more.push({ id: "start", label: TRANSITION_LABEL.start, icon: "play", onAction: () => void commands.transition(start) });
  }
  if (offered?.complete && primary !== "complete") {
    const complete = offered.complete;
    more.push({ id: "complete", label: TRANSITION_LABEL.complete, icon: "check", onAction: () => void commands.transition(complete).then(closeIf) });
  }
  if (offered?.assignToMe) more.push({ id: "assign", label: "Assign to me", icon: "user", onAction: () => void commands.assignToMe() });
  if (offered?.snooze) {
    const snooze = (choice: SnoozeChoice) => () => void commands.snooze(choice).then(closeIf);
    more.push({
      section: "Snooze for",
      id: "snooze",
      items: [
        { id: "1h", label: "1 hour", icon: "clock", onAction: snooze("1h") },
        { id: "3h", label: "3 hours", icon: "clock", onAction: snooze("3h") },
        { id: "24h", label: "Until this time tomorrow", icon: "calendar", onAction: snooze("24h") },
      ],
    });
  }
  if (offered?.unsnooze) more.push({ id: "unsnooze", label: "Bring back now", icon: "undo", onAction: () => void commands.unsnooze() });
  if (offered?.dismiss) {
    const dismiss = offered.dismiss;
    if (more.length > 0) more.push({ separator: true, id: "before-dismiss" });
    more.push({
      id: "dismiss",
      label: "Dismiss with a reason",
      icon: "xCircle",
      onAction: () => (dismiss.requires_reason ? setDismissOpen(true) : void commands.transition(dismiss).then(closeIf)),
    });
  }

  const hasFooter = Boolean(task) && (primary !== null || more.length > 0);

  const footer = hasFooter && offered ? (
    <>
      {more.length > 0 ? (
        <Menu
          label="More you can do with this"
          placement="top end"
          items={more}
          trigger={
            <Button variant="secondary" iconRight="chevronDown" isDisabled={offline || busy}>
              More
            </Button>
          }
        />
      ) : null}
      {primary === "review" && offered.review ? (
        <ButtonLink href={offered.review} iconRight="arrowRight">
          Open the review
        </ButtonLink>
      ) : primary === "reply" && message ? (
        <Button iconLeft="check" loading={reply.pending} isDisabled={offline} onPress={() => void reply.markReplied(message).then(closeIf)}>
          Mark as replied
        </Button>
      ) : primary === "complete" && offered.complete ? (
        <Button iconLeft="check" loading={commands.pending === "complete"} isDisabled={offline} onPress={() => void commands.transition(offered.complete!).then(closeIf)}>
          {TRANSITION_LABEL.complete}
        </Button>
      ) : primary === "start" && offered.start ? (
        <Button iconLeft="play" loading={commands.pending === "start"} isDisabled={offline} onPress={() => void commands.transition(offered.start!)}>
          {TRANSITION_LABEL.start}
        </Button>
      ) : null}
    </>
  ) : undefined;

  return (
    <>
      <Drawer
        isOpen={taskId !== null}
        onOpenChange={(open) => (open ? undefined : close())}
        title={KIND_LOOK[kind].noun}
        width={messageId ? "lg" : "md"}
        footer={footer}
      >
        {taskId === null ? null : query.isPending ? (
          <div role="status" aria-label="Loading">
            <SkeletonText lines={5} />
          </div>
        ) : query.isError || !task ? (
          <ErrorBlock error={query.error} what="This task" onRetry={() => void query.refetch()} />
        ) : (
          <div className="stack">
            <div className="flex flex-col gap-3">
              <h3 className="t-h2 [overflow-wrap:anywhere]">{task.title}</h3>
              <div>
                <Badge tone={taskBadge(task, now, zone).tone} dot>
                  {taskBadge(task, now, zone).label}
                </Badge>
              </div>
            </div>

            {offline ? <Banner tone="amber">{OFFLINE_NOTE}</Banner> : null}

            {messageId === null ? null : messageQuery.isPending ? (
              <ConversationSkeleton />
            ) : message ? (
              <ConversationThread message={message} />
            ) : (
              <ErrorBlock error={messageQuery.error} what="The customer's message" onRetry={() => void messageQuery.refetch()} />
            )}

            <KeyValue items={factsOf(task, bootstrap.user.id)} />

            {hasFooter ? null : (
              <p className="t-body-sm text-ink-3">Nothing here needs doing by hand. It closes on its own when its record changes.</p>
            )}
          </div>
        )}
      </Drawer>

      {task && offered?.dismiss ? (
        <DismissDialog
          isOpen={dismissOpen}
          onOpenChange={setDismissOpen}
          taskTitle={task.title}
          busy={commands.pending === "dismiss"}
          offline={offline}
          onDismiss={async (reasonCode, note) => {
            const ok = await commands.transition(offered.dismiss!, reasonCode, note);
            if (ok) {
              setDismissOpen(false);
              close();
            }
          }}
        />
      ) : null}
    </>
  );
}

function factsOf(task: TaskDetail, userId: string): KeyValueItem[] {
  const items: KeyValueItem[] = [
    { label: "Due", value: task.due_at && task.due_kind !== "none" ? <DateText value={task.due_at} style="dayTime" /> : "No deadline" },
    { label: "With", value: holderText(task, userId) },
  ];
  if (task.source) {
    const { href, label } = task.source;
    items.push({ label: "About", value: href ? <TextLink href={href as Route}>{label}</TextLink> : label });
  }
  if (task.snoozed_until) items.push({ label: "Snoozed until", value: <DateText value={task.snoozed_until} style="dayTime" /> });
  if (task.created_at) items.push({ label: "Raised", value: <DateText value={task.created_at} style="dayTime" /> });
  if (task.closed_at) items.push({ label: "Closed", value: <DateText value={task.closed_at} style="dayTime" /> });
  return items;
}

/** Dismissing needs one of the server's reason codes; a note is optional. */
function DismissDialog({
  isOpen,
  onOpenChange,
  taskTitle,
  busy,
  offline,
  onDismiss,
}: {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  taskTitle: string;
  busy: boolean;
  offline: boolean;
  onDismiss: (reasonCode: string, note: string | null) => Promise<void>;
}) {
  return (
    <Modal isOpen={isOpen} onOpenChange={(open) => (busy ? undefined : onOpenChange(open))} title="Dismiss this task" description={taskTitle} size="sm" isDismissable={!busy}>
      {/* Mounted with the dialog, so the choice and the note start empty every time it opens. */}
      <DismissForm busy={busy} offline={offline} onCancel={() => onOpenChange(false)} onDismiss={onDismiss} />
    </Modal>
  );
}

function DismissForm({
  busy,
  offline,
  onCancel,
  onDismiss,
}: {
  busy: boolean;
  offline: boolean;
  onCancel: () => void;
  onDismiss: (reasonCode: string, note: string | null) => Promise<void>;
}) {
  const [reason, setReason] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [attempted, setAttempted] = useState(false);

  return (
    <form
      className="flex flex-col gap-5"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (!reason) {
          setAttempted(true);
          return;
        }
        void onDismiss(reason, note.trim() || null);
      }}
    >
      <RadioGroup
        label="Why does this not need doing?"
        isRequired
        value={reason}
        onChange={setReason}
        options={DISMISSAL_REASON_CODES.map((code) => ({ value: code, label: DISMISS_REASONS[code] }))}
        error={attempted && !reason ? "Choose a reason. It is kept with the task." : undefined}
        isDisabled={busy}
      />
      <Textarea label="Note" optional value={note} onChange={setNote} rows={2} isDisabled={busy} help="Anything a teammate should know." />
      {offline ? <Banner tone="amber">{OFFLINE_NOTE}</Banner> : null}
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="ghost" onPress={onCancel} isDisabled={busy}>
          Keep task
        </Button>
        <Button type="submit" variant="inverse" loading={busy} isDisabled={offline}>
          Dismiss task
        </Button>
      </div>
    </form>
  );
}
