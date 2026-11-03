"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { RadioGroup } from "@/components/ui/choice";
import { Dialog } from "@/components/ui/dialog";
import { Link } from "@/components/ui/link";
import { Select } from "@/components/ui/select";
import { ErrorState, Loading } from "@/components/ui/states";
import { TextArea } from "@/components/ui/text-field";
import { queryKeys } from "@/lib/api/query-keys";
import { formatDayTime, type ZoneOptions } from "@/lib/format/time";
import { briefingMessages as m } from "@/messages/briefing";
import { fetchExplanation } from "./api";
import { actionLabel } from "./model";
import type { BriefingAction, BriefingItem, ReasonOption } from "./types";

export type SnoozeChoice = "1h" | "3h" | "24h";

/**
 * Which item and action a dialog is open for, or null while it is closed. The dialogs stay
 * mounted (for their exit animation), so their form state is reset whenever this changes.
 */
export function dialogIdentity(isOpen: boolean, item: Pick<BriefingItem, "issue_id"> | null, action: Pick<BriefingAction, "action"> | null): string | null {
  return isOpen && item ? `${item.issue_id}:${action?.action ?? ""}` : null;
}

/** Calls `reset` during render when the dialog opens or switches to another item or action. */
function useResetOnOpen(identity: string | null, reset: () => void): void {
  const [seen, setSeen] = useState(identity);
  if (identity !== seen) {
    setSeen(identity);
    if (identity !== null) reset();
  }
}

/** The chosen reason, if it is one this action offers; anything else is never sent. */
export function reasonToSubmit(reason: string | null, reasons: readonly ReasonOption[]): string | null {
  return reason !== null && reasons.some((option) => option.code === reason) ? reason : null;
}

/** A disabled Confirm (offline) says why; otherwise Confirm is enabled. */
function confirmAvailability(disabledReason: string | null | undefined) {
  return disabledReason ? ({ isDisabled: true, disabledReason } as const) : ({} as const);
}

export function SnoozeDialog({
  item,
  now,
  zone,
  isOpen,
  isPending,
  disabledReason,
  onOpenChange,
  onConfirm,
}: {
  item: BriefingItem | null;
  now: Date;
  zone: ZoneOptions;
  isOpen: boolean;
  isPending: boolean;
  /** Set while commands cannot be sent (offline). */
  disabledReason?: string | null;
  onOpenChange: (open: boolean) => void;
  onConfirm: (choice: SnoozeChoice) => void;
}) {
  const [choice, setChoice] = useState<SnoozeChoice>("1h");
  useResetOnOpen(dialogIdentity(isOpen, item, { action: "snooze" }), () => setChoice("1h"));
  const deadline = item?.due_at && item.due_kind === "hard" ? formatDayTime(item.due_at, now, zone) : null;
  return (
    <Dialog
      title={m.snooze.title}
      description={item?.title}
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      size="sm"
      footer={(close) => (
        <>
          <Button variant="quiet" onPress={close}>
            {m.reason.cancel}
          </Button>
          <Button variant="primary" isPending={isPending} onPress={() => onConfirm(choice)} {...confirmAvailability(disabledReason)}>
            {m.snooze.confirm}
          </Button>
        </>
      )}
    >
      <div className="flex flex-col gap-3">
        <p className="text-sm text-ink-muted">{m.snooze.description}</p>
        <RadioGroup
          label={m.snooze.choice}
          value={choice}
          onChange={(value) => setChoice(value as SnoozeChoice)}
          options={[
            { value: "1h", label: m.snooze.oneHour },
            { value: "3h", label: m.snooze.threeHours },
            { value: "24h", label: m.snooze.untilTomorrow },
          ]}
        />
        {deadline ? <p className="text-sm font-semibold text-ink">{m.snooze.deadline(deadline)}</p> : null}
        {disabledReason ? <p className="text-sm text-warning-text">{disabledReason}</p> : null}
      </div>
    </Dialog>
  );
}

/** Dismiss and Reject need a reason (server enum) and/or a note (briefing.md §9). */
export function ReasonDialog({
  item,
  action,
  isOpen,
  isPending,
  disabledReason,
  onOpenChange,
  onConfirm,
}: {
  item: BriefingItem | null;
  action: BriefingAction | null;
  isOpen: boolean;
  isPending: boolean;
  /** Set while commands cannot be sent (offline). */
  disabledReason?: string | null;
  onOpenChange: (open: boolean) => void;
  onConfirm: (reasonCode: string | null, note: string) => void;
}) {
  const [reason, setReason] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [submitted, setSubmitted] = useState(false);
  // Every opening starts empty: a reason or note typed for one item never reaches another.
  useResetOnOpen(dialogIdentity(isOpen, item, action), () => {
    setReason(null);
    setNote("");
    setSubmitted(false);
  });
  const reasons = action?.reasons ?? [];
  const needsReason = reasons.length > 0;
  const needsNote = Boolean(action?.requires_reason) && !needsReason;
  const chosen = reasonToSubmit(reason, reasons);
  const reasonError = submitted && needsReason && !chosen ? m.reason.reasonRequired : undefined;
  const noteError = submitted && needsNote && !note.trim() ? m.reason.noteRequired : undefined;
  const label = action ? actionLabel(action) : "";

  return (
    <Dialog
      title={m.reason.title(label)}
      description={item?.title}
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      size="sm"
      role="alertdialog"
      footer={(close) => (
        <>
          <Button variant="quiet" onPress={close}>
            {m.reason.cancel}
          </Button>
          <Button
            variant={action?.action === "reject" ? "danger" : "primary"}
            isPending={isPending}
            onPress={() => {
              setSubmitted(true);
              if ((needsReason && !chosen) || (needsNote && !note.trim())) return;
              onConfirm(needsReason ? chosen : null, note.trim());
            }}
            {...confirmAvailability(disabledReason)}
          >
            {m.reason.confirm(label)}
          </Button>
        </>
      )}
    >
      <div className="flex flex-col gap-4">
        {needsReason ? (
          <Select
            label={m.reason.reasonLabel}
            options={reasons.map((option) => ({ id: option.code, label: option.label }))}
            value={chosen}
            onChange={setReason}
            isRequired
            errorMessage={reasonError}
          />
        ) : null}
        <TextArea
          label={m.reason.noteLabel}
          value={note}
          onChange={setNote}
          isRequired={needsNote}
          isInvalid={Boolean(noteError)}
          errorMessage={noteError}
        />
        {disabledReason ? <p className="text-sm text-warning-text">{disabledReason}</p> : null}
      </div>
    </Dialog>
  );
}

/** Explain: the rule-based reasons and sources from the server (briefing.md §9 "Explain"). */
export function ExplainDialog({ item, isOpen, onOpenChange }: { item: BriefingItem | null; isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const issueId = item?.issue_id ?? "";
  const query = useQuery({
    queryKey: queryKeys.briefings.explain(issueId),
    queryFn: ({ signal }) => fetchExplanation(issueId, signal),
    enabled: isOpen && Boolean(item),
    staleTime: 60_000,
  });
  return (
    <Dialog title={m.explain.title} description={item?.title} isOpen={isOpen} onOpenChange={onOpenChange}>
      {query.isPending ? (
        <Loading label={m.explain.loading} variant="detail" />
      ) : query.isError ? (
        <ErrorState error={query.error} what="the explanation" onRetry={() => void query.refetch()} compact headingLevel={3} backToToday={false} />
      ) : (
        <div className="flex flex-col gap-3 text-[15px]">
          <p className="text-ink">{query.data.text}</p>
          {query.data.reasons.length > 0 ? (
            <ul className="list-disc ps-5 text-ink-muted">
              {query.data.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          ) : null}
          {query.data.sources.length > 0 ? (
            <div className="flex flex-col gap-1">
              <h3 className="text-sm font-semibold text-ink">{m.explain.sources}</h3>
              <ul className="flex flex-col gap-1 text-sm">
                {query.data.sources.map((source) => (
                  <li key={`${source.type}:${source.id}`}>
                    {source.href ? <Link href={source.href}>{source.label}</Link> : source.label}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {item ? (
            <p className="text-sm">
              <Link href={`/today/items/${encodeURIComponent(item.issue_id)}`}>{m.links.item}</Link>
            </p>
          ) : null}
        </div>
      )}
    </Dialog>
  );
}
