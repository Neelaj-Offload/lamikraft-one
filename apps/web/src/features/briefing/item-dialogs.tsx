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
import { fetchExplanation, snoozeUntil } from "./api";
import { actionLabel } from "./model";
import type { BriefingAction, BriefingItem } from "./types";

type SnoozeChoice = "1h" | "3h" | "24h";

export function SnoozeDialog({
  item,
  now,
  zone,
  isOpen,
  isPending,
  onOpenChange,
  onConfirm,
}: {
  item: BriefingItem | null;
  now: Date;
  zone: ZoneOptions;
  isOpen: boolean;
  isPending: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (until: string) => void;
}) {
  const [choice, setChoice] = useState<SnoozeChoice>("1h");
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
          <Button variant="primary" isPending={isPending} onPress={() => onConfirm(snoozeUntil(choice, new Date()))}>
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
  onOpenChange,
  onConfirm,
}: {
  item: BriefingItem | null;
  action: BriefingAction | null;
  isOpen: boolean;
  isPending: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (reasonCode: string | null, note: string) => void;
}) {
  const [reason, setReason] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const reasons = action?.reasons ?? [];
  const needsReason = reasons.length > 0;
  const needsNote = Boolean(action?.requires_reason) && !needsReason;
  const reasonError = submitted && needsReason && !reason ? m.reason.reasonRequired : undefined;
  const noteError = submitted && needsNote && !note.trim() ? m.reason.noteRequired : undefined;
  const label = action ? actionLabel(action) : "";

  return (
    <Dialog
      title={m.reason.title(label)}
      description={item?.title}
      isOpen={isOpen}
      onOpenChange={(open) => {
        if (!open) {
          setReason(null);
          setNote("");
          setSubmitted(false);
        }
        onOpenChange(open);
      }}
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
              if ((needsReason && !reason) || (needsNote && !note.trim())) return;
              onConfirm(reason, note.trim());
            }}
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
            value={reason}
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
        <ErrorState error={query.error} what="the explanation" onRetry={() => void query.refetch()} compact headingLevel={3} />
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
        </div>
      )}
    </Dialog>
  );
}
