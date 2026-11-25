"use client";

import type { Route } from "next";
import { useState } from "react";
import type { BriefingAction, BriefingItem, ReasonOption } from "@/features/briefing/types";
import { formatDayTime } from "@/lib/format/time";
import { useNow, useSession } from "@/lib/session/context";
import { actionText, itemHref, useExplanation, type ItemCommands, type SnoozeChoice } from "~/data/today";
import { ErrorBlock } from "~/shell/states";
import { Banner, Button, ButtonLink, Modal, RadioGroup, Select, SkeletonText, Textarea, TextLink } from "~/ui";

/** Which item and action a dialog is open for, or null while it is closed. */
function identity(isOpen: boolean, item: Pick<BriefingItem, "issue_id"> | null, action: string): string | null {
  return isOpen && item ? `${item.issue_id}:${action}` : null;
}

/** Calls `reset` during render when the dialog opens or switches to another item or action. */
function useResetOnOpen(key: string | null, reset: () => void): void {
  const [seen, setSeen] = useState(key);
  if (key !== seen) {
    setSeen(key);
    if (key !== null) reset();
  }
}

/**
 * The three dialogs an item command can open. They stay mounted so their exit keeps its content;
 * every opening starts empty, so a reason typed for one item never reaches another.
 */
export function ItemDialogs({ commands, showDetailsLink = true }: { commands: ItemCommands; showDetailsLink?: boolean }) {
  const { dialog, pending, disabledReason, closeDialog, confirmSnooze, confirmReason } = commands;
  const onOpenChange = (open: boolean) => {
    if (!open) closeDialog();
  };
  const busy = pending !== null;
  return (
    <>
      <SnoozeDialog
        item={dialog?.kind === "snooze" ? dialog.item : null}
        isOpen={dialog?.kind === "snooze" && dialog.open}
        busy={busy}
        disabledReason={disabledReason}
        onOpenChange={onOpenChange}
        onConfirm={confirmSnooze}
      />
      <ReasonDialog
        item={dialog?.kind === "reason" ? dialog.item : null}
        action={dialog?.kind === "reason" ? dialog.action : null}
        isOpen={dialog?.kind === "reason" && dialog.open}
        busy={busy}
        disabledReason={disabledReason}
        onOpenChange={onOpenChange}
        onConfirm={confirmReason}
      />
      <ExplainDialog
        item={dialog?.kind === "explain" ? dialog.item : null}
        isOpen={dialog?.kind === "explain" && dialog.open}
        showDetailsLink={showDetailsLink}
        onOpenChange={onOpenChange}
      />
    </>
  );
}

function SnoozeDialog({
  item,
  isOpen,
  busy,
  disabledReason,
  onOpenChange,
  onConfirm,
}: {
  item: BriefingItem | null;
  isOpen: boolean;
  busy: boolean;
  disabledReason: string | null;
  onOpenChange: (open: boolean) => void;
  onConfirm: (choice: SnoozeChoice) => void;
}) {
  const { bootstrap, zone } = useSession();
  const now = useNow() ?? new Date(bootstrap.server_now);
  const [choice, setChoice] = useState<SnoozeChoice>("1h");
  useResetOnOpen(identity(isOpen, item, "snooze"), () => setChoice("1h"));
  const deadline = item?.due_at && item.due_kind === "hard" ? formatDayTime(item.due_at, now, zone) : null;
  return (
    <Modal
      title="Snooze this item"
      description={item?.title}
      size="sm"
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      actions={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)} isDisabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" loading={busy} isDisabled={disabledReason !== null} onPress={() => onConfirm(choice)}>
            Snooze item
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <RadioGroup
          label="Bring it back in"
          value={choice}
          onChange={(value) => setChoice(value as SnoozeChoice)}
          options={[
            { value: "1h", label: "1 hour" },
            { value: "3h", label: "3 hours" },
            { value: "24h", label: "This time tomorrow" },
          ]}
          help="It leaves your briefing until then. The task and its deadline stay as they are."
        />
        {deadline ? <p className="t-body-sm text-ink">The deadline is still {deadline}.</p> : null}
        {disabledReason ? <Banner tone="amber">{disabledReason}</Banner> : null}
      </div>
    </Modal>
  );
}

/** The chosen reason, if it is one this action offers; anything else is never sent. */
function reasonToSubmit(reason: string | null, reasons: readonly ReasonOption[]): string | null {
  return reason !== null && reasons.some((option) => option.code === reason) ? reason : null;
}

/** Dismiss needs a reason from the server's list; other commands that ask for one need a note. */
function ReasonDialog({
  item,
  action,
  isOpen,
  busy,
  disabledReason,
  onOpenChange,
  onConfirm,
}: {
  item: BriefingItem | null;
  action: BriefingAction | null;
  isOpen: boolean;
  busy: boolean;
  disabledReason: string | null;
  onOpenChange: (open: boolean) => void;
  onConfirm: (reasonCode: string | null, note: string) => void;
}) {
  const [reason, setReason] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [submitted, setSubmitted] = useState(false);
  useResetOnOpen(identity(isOpen, item, action?.action ?? ""), () => {
    setReason(null);
    setNote("");
    setSubmitted(false);
  });
  const reasons = action?.reasons ?? [];
  const needsReason = reasons.length > 0;
  const needsNote = Boolean(action?.requires_reason) && !needsReason;
  const chosen = reasonToSubmit(reason, reasons);
  const reasonError = submitted && needsReason && !chosen ? "Choose the reason that fits best." : undefined;
  const noteError = submitted && needsNote && !note.trim() ? "Add a short note that says why." : undefined;
  const dismiss = action?.action === "dismiss";
  const label = action ? actionText(action) : "";

  return (
    <Modal
      title={dismiss ? "Dismiss this item" : label}
      description={item?.title}
      size="sm"
      isDismissable={false}
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      actions={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)} isDisabled={busy}>
            Cancel
          </Button>
          <Button
            variant={action?.action === "reject" ? "danger" : "primary"}
            loading={busy}
            isDisabled={disabledReason !== null}
            onPress={() => {
              setSubmitted(true);
              if ((needsReason && !chosen) || (needsNote && !note.trim())) return;
              onConfirm(needsReason ? chosen : null, note.trim());
            }}
          >
            {dismiss ? "Dismiss item" : label}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {needsReason ? (
          <Select
            label="Reason"
            placeholder="Choose a reason"
            options={reasons.map((option) => ({ value: option.code, label: option.label }))}
            value={chosen}
            onChange={setReason}
            isRequired
            error={reasonError}
          />
        ) : null}
        <Textarea
          label="Note"
          optional={!needsNote}
          value={note}
          onChange={setNote}
          isRequired={needsNote}
          error={noteError}
          rows={3}
          help={needsNote ? undefined : "Anything the next person should know."}
        />
        {disabledReason ? <Banner tone="amber">{disabledReason}</Banner> : null}
      </div>
    </Modal>
  );
}

/** The rule-based reasons and sources behind an item, read from the server when the dialog opens. */
function ExplainDialog({
  item,
  isOpen,
  showDetailsLink,
  onOpenChange,
}: {
  item: BriefingItem | null;
  isOpen: boolean;
  showDetailsLink: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const query = useExplanation(item?.issue_id ?? "", isOpen && item !== null);
  return (
    <Modal
      title="Why this is in your briefing"
      description={item?.title}
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      actions={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)}>
            Close
          </Button>
          {item && showDetailsLink ? (
            <ButtonLink variant="inverse" href={itemHref(item.issue_id) as Route} iconRight="arrowRight">
              Open the item
            </ButtonLink>
          ) : null}
        </>
      }
    >
      {query.isPending ? (
        <div role="status" aria-label="Loading the explanation">
          <SkeletonText lines={3} />
        </div>
      ) : query.isError ? (
        <ErrorBlock error={query.error} what="The explanation" onRetry={() => void query.refetch()} />
      ) : (
        <div className="flex flex-col gap-4">
          <p className="t-body text-ink">{query.data.text}</p>
          {query.data.reasons.length > 0 ? (
            <ul className="t-body-sm text-ink-2 m-0 flex list-disc flex-col gap-1 pl-5">
              {query.data.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          ) : null}
          {query.data.sources.length > 0 ? (
            <div className="flex flex-col gap-2">
              <h3 className="t-overline text-ink-3">Based on</h3>
              <ul className="t-body-sm m-0 flex list-none flex-col gap-1 p-0">
                {query.data.sources.map((source) => (
                  <li key={`${source.type}:${source.id}`}>
                    {source.href ? <TextLink href={source.href as Route}>{source.label}</TextLink> : <span className="text-ink-2">{source.label}</span>}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      )}
    </Modal>
  );
}
