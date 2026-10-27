"use client";

import { useState } from "react";
import { Button, unavailableWhen } from "./button";
import { Dialog } from "./dialog";
import { Select, type Option } from "./select";
import { TextArea } from "./text-field";

export interface ReasonDialogProps {
  title: string;
  /** One line under the title, e.g. the record it applies to. */
  description?: string;
  /** Server-defined reason codes; when present one must be chosen. */
  reasons?: readonly Option[];
  /** A written reason is required (and is the only reason when no codes are offered). */
  requireNote?: boolean;
  noteLabel?: string;
  confirmLabel: string;
  isOpen: boolean;
  isPending?: boolean;
  /** Why confirming is not possible right now (offline), shown and used as the description. */
  disabledReason?: string | null;
  onOpenChange: (open: boolean) => void;
  onConfirm: (reasonCode: string | null, note: string) => void;
}

/**
 * Asks for the reason a command needs (a dismissal code, a lost reason, a rejection note). The
 * form starts empty every time it opens, so a reason typed for one record never reaches another.
 */
export function ReasonDialog(props: ReasonDialogProps) {
  // Remount on every opening: state never carries over between records.
  return props.isOpen ? <ReasonDialogBody key="open" {...props} /> : <Dialog title={props.title} isOpen={false} onOpenChange={props.onOpenChange}>{null}</Dialog>;
}

function ReasonDialogBody({
  title,
  description,
  reasons = [],
  requireNote = false,
  noteLabel = "Reason",
  confirmLabel,
  isOpen,
  isPending = false,
  disabledReason = null,
  onOpenChange,
  onConfirm,
}: ReasonDialogProps) {
  const [reason, setReason] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const needsCode = reasons.length > 0;
  const chosen = reason !== null && reasons.some((option) => option.id === reason) ? reason : null;
  const codeError = submitted && needsCode && !chosen ? "Choose a reason." : undefined;
  const noteError = submitted && requireNote && !note.trim() ? "Write the reason." : undefined;

  const confirm = () => {
    setSubmitted(true);
    if ((needsCode && !chosen) || (requireNote && !note.trim())) return;
    onConfirm(chosen, note.trim());
  };

  return (
    <Dialog
      title={title}
      description={description}
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      size="sm"
      footer={(close) => (
        <>
          <Button variant="quiet" onPress={close}>
            Cancel
          </Button>
          <Button variant="primary" isPending={isPending} onPress={confirm} {...unavailableWhen(disabledReason)}>
            {confirmLabel}
          </Button>
        </>
      )}
    >
      <div className="flex flex-col gap-4">
        {needsCode ? (
          <Select label="Reason" options={reasons} value={reason} onChange={setReason} isRequired errorMessage={codeError} />
        ) : null}
        <TextArea
          label={needsCode ? "Note" : noteLabel}
          value={note}
          onChange={setNote}
          isRequired={requireNote}
          isInvalid={Boolean(noteError)}
          errorMessage={noteError}
        />
        {disabledReason ? <p className="text-sm text-warning-text">{disabledReason}</p> : null}
      </div>
    </Dialog>
  );
}
