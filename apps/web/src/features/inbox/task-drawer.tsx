"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { StatusPill } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { DescriptionList } from "@/components/ui/description-list";
import { Drawer } from "@/components/ui/dialog";
import { LocalDateTime } from "@/components/ui/format";
import { Link, LinkButton } from "@/components/ui/link";
import { Menu, MenuItem, MenuTrigger } from "@/components/ui/menu";
import { ReasonDialog } from "@/components/ui/reason-dialog";
import { buttonClasses } from "@/components/ui/styles";
import { ErrorState, Loading } from "@/components/ui/states";
import { toast } from "@/components/ui/toast";
import { Button as RacButton } from "react-aria-components";
import { DISMISSAL_REASON_CODES } from "@/features/briefing/types";
import { snoozeUntil } from "@/features/briefing/api";
import { reviewHref } from "@/lib/app-links";
import { commandSignature, createCommandKeys } from "@/lib/api/command-keys";
import { isStalenessConflict, ProblemError } from "@/lib/api/errors";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { useOnline } from "@/lib/hooks";
import { useSession } from "@/lib/session/context";
import { briefingMessages } from "@/messages/briefing";
import { inboxMessages as m } from "@/messages/inbox";
import { assignTask, fetchTask, snoozeTask, transitionTask, unsnoozeTask } from "./api";
import { assigneeLabel, inboxStatus } from "./model";
import type { TaskDetail, TaskTransitionOption } from "./types";

const DISMISS_REASONS = DISMISSAL_REASON_CODES.map((code) => ({ id: code, label: briefingMessages.dismissReasons[code] ?? code }));

/** Why a capability is off, in words (server reason codes). */
export function capabilityReason(code: string | null): string {
  return (code ? m.drawer.reasons[code] : undefined) ?? m.drawer.reasons.permission_denied!;
}

/**
 * The commands a task offers, from the server: transitions only from `allowed_transitions`,
 * assign and snooze only when their capability is allowed. Nothing else is rendered.
 */
export function taskCommands(task: TaskDetail, userId: string) {
  const assign = task.capabilities.assign;
  const snooze = task.capabilities.snooze;
  return {
    transitions: task.allowed_transitions,
    assignToMe: Boolean(assign?.allowed) && task.assignee_user_id !== userId,
    snooze: Boolean(snooze?.allowed) && !task.snoozed_until,
    unsnooze: Boolean(snooze?.allowed) && Boolean(task.snoozed_until),
    review: task.proposal_id ? reviewHref(task.proposal_id) : null,
  };
}

/** The task drawer (`?task=<id>` on any Inbox tab): detail, transitions, assign and snooze. */
export function TaskDrawer({ taskId, onClose }: { taskId: string | null; onClose: () => void }) {
  return (
    <Drawer title={m.drawer.title} isOpen={taskId !== null} onOpenChange={(open) => (open ? undefined : onClose())}>
      {taskId ? <TaskDrawerBody taskId={taskId} /> : null}
    </Drawer>
  );
}

function TaskDrawerBody({ taskId }: { taskId: string }) {
  const { bootstrap, zone } = useSession();
  const online = useOnline();
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: queryKeys.tasks.task(taskId), queryFn: ({ signal }) => fetchTask(taskId, signal) });
  const [pending, setPending] = useState<string | null>(null);
  const [dismissOpen, setDismissOpen] = useState(false);
  const [commandKeys] = useState(() => createCommandKeys());

  if (query.isPending) return <Loading label={m.drawer.loading} variant="detail" />;
  if (query.isError) return <ErrorState error={query.error} what={m.drawer.loading} onRetry={() => void query.refetch()} headingLevel={3} compact backToToday={false} />;

  const task = query.data;
  const commands = taskCommands(task, bootstrap.user.id);
  const offline = online ? null : briefingMessages.offlineActions;
  const status = inboxStatus(task, null, zone);

  const refresh = async () => {
    await Promise.all(invalidationMap["tasks.task_command"].map((queryKey) => queryClient.invalidateQueries({ queryKey })));
  };

  const run = async (label: string, signatureParts: (string | number | null)[], call: (key: string) => Promise<unknown>) => {
    if (pending || offline) return;
    const signature = commandSignature(task.id, task.version, ...signatureParts);
    const attempt = commandKeys.attempt(signature, () => null);
    setPending(label);
    try {
      await call(attempt.key);
      commandKeys.settle(signature);
      toast.success(m.drawer.done(label));
      setDismissOpen(false);
      await refresh();
    } catch (error) {
      commandKeys.settle(signature, error);
      if (isStalenessConflict(error)) {
        toast.info(m.drawer.changed);
        await refresh();
      } else if (error instanceof ProblemError && error.code === "not_complete") {
        toast.warning(m.drawer.notComplete, { description: error.detail ?? undefined });
      } else {
        toast.error(m.drawer.failed(label), {
          description: error instanceof ProblemError ? [error.detail ?? error.title, error.request_id ? `Reference: ${error.request_id}` : null].filter(Boolean).join(" ") : undefined,
        });
      }
    } finally {
      setPending(null);
    }
  };

  const transition = (option: TaskTransitionOption, reasonCode: string | null = null, note: string | null = null) =>
    run(m.drawer.transitions[option.action] ?? option.action, [option.action, reasonCode, note], (key) =>
      transitionTask(task, option.action, { reasonCode, note, idempotencyKey: key }),
    );
  const dismiss = commands.transitions.find((option) => option.action === "dismiss") ?? null;
  const hasCommands = commands.transitions.length > 0 || commands.assignToMe || commands.snooze || commands.unsnooze || commands.review;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <h3 className="text-lg font-[650] text-ink">{task.title}</h3>
        <StatusPill tone={status.tone}>{status.label}</StatusPill>
      </div>
      <DescriptionList
        items={[
          { term: m.drawer.due, description: task.due_at ? <LocalDateTime value={task.due_at} /> : m.noDue },
          {
            term: m.drawer.record,
            description: task.source ? task.source.href ? <Link href={task.source.href}>{task.source.label}</Link> : task.source.label : "—",
          },
          { term: m.drawer.assignee, description: assigneeLabel(task, bootstrap.user.id) },
          ...(task.snoozed_until ? [{ term: m.drawer.snoozedUntil, description: <LocalDateTime value={task.snoozed_until} /> }] : []),
          ...(task.created_at ? [{ term: m.drawer.created, description: <LocalDateTime value={task.created_at} /> }] : []),
        ]}
      />
      <section aria-label={m.drawer.actions} className="flex flex-col gap-3">
        {hasCommands ? (
          <div className="flex flex-wrap gap-2">
            {commands.review ? (
              <LinkButton href={commands.review} variant="primary">
                {m.drawer.review}
              </LinkButton>
            ) : null}
            {commands.transitions.map((option) => (
              <Button
                key={option.action}
                variant={option.action === "complete" ? "primary" : "secondary"}
                isPending={pending === (m.drawer.transitions[option.action] ?? option.action)}
                onPress={() => (option.requires_reason ? setDismissOpen(true) : void transition(option))}
                {...unavailableWhen(offline)}
              >
                {m.drawer.transitions[option.action] ?? option.action}
              </Button>
            ))}
            {commands.assignToMe ? (
              <Button
                variant="secondary"
                isPending={pending === m.drawer.assignToMe}
                onPress={() => void run(m.drawer.assignToMe, ["assign", bootstrap.user.id], (key) => assignTask(task, bootstrap.user.id, key))}
                {...unavailableWhen(offline)}
              >
                {m.drawer.assignToMe}
              </Button>
            ) : null}
            {commands.snooze && !offline ? (
              <MenuTrigger>
                <RacButton className={buttonClasses("secondary", "md")}>{m.drawer.snooze}</RacButton>
                <Menu
                  aria-label={m.drawer.snooze}
                  onAction={(key) => {
                    const choice = String(key) as "1h" | "3h" | "24h";
                    const until = snoozeUntil(choice, new Date());
                    void run(m.drawer.snooze, ["snooze", choice], (idempotencyKey) => snoozeTask(task.id, until, idempotencyKey));
                  }}
                >
                  <MenuItem id="1h">{briefingMessages.snooze.oneHour}</MenuItem>
                  <MenuItem id="3h">{briefingMessages.snooze.threeHours}</MenuItem>
                  <MenuItem id="24h">{briefingMessages.snooze.untilTomorrow}</MenuItem>
                </Menu>
              </MenuTrigger>
            ) : null}
            {commands.unsnooze ? (
              <Button
                variant="secondary"
                isPending={pending === m.drawer.unsnooze}
                onPress={() => void run(m.drawer.unsnooze, ["unsnooze"], () => unsnoozeTask(task.id))}
                {...unavailableWhen(offline)}
              >
                {m.drawer.unsnooze}
              </Button>
            ) : null}
          </div>
        ) : (
          <p className="text-sm text-ink-muted">{m.drawer.noActions}</p>
        )}
        {task.capabilities.assign?.allowed ? <p className="text-xs text-ink-muted">{m.drawer.assignHint}</p> : null}
        {offline ? <p className="text-sm text-warning-text">{offline}</p> : null}
      </section>
      <ReasonDialog
        title={m.drawer.transitions.dismiss!}
        description={task.title}
        reasons={DISMISS_REASONS}
        confirmLabel={m.drawer.transitions.dismiss!}
        isOpen={dismissOpen}
        isPending={pending !== null}
        disabledReason={offline}
        onOpenChange={setDismissOpen}
        onConfirm={(reasonCode, note) => (dismiss ? void transition(dismiss, reasonCode, note) : undefined)}
      />
    </div>
  );
}
