"use client";

import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { challanPdfHref, deleteChallan, duplicateChallan, transitionChallan } from "@/features/challans/api";
import type { ChallanDetail } from "@/features/challans/types";
import type { ChallanCommands } from "@/features/challans/use-challan-command";
import { asRoute, CANCEL_REASONS, challanActions, CHALLANS_HOME, type ChallanActionModel } from "~/data/challans";
import { Button, ConfirmDialog, Modal, Select, Textarea, toast, type MenuItem } from "~/ui";

type Asking = "issue" | "close" | "cancel" | "delete" | null;

const DONE: Record<string, string> = { issue: "Challan issued", close: "Challan closed", cancel: "Challan cancelled" };
const FAILED: Record<string, string> = { issue: "The challan was not issued", close: "The challan was not closed", cancel: "The challan was not cancelled" };

/**
 * A confirmation that records why: a reason from the server's list when one is offered, and a
 * note in the person's own words (optional, as the old screen had it). It stays open while the
 * command runs and when it fails.
 */
function ReasonModal({
  isOpen,
  onOpenChange,
  title,
  description,
  confirmLabel,
  tone = "default",
  reasons,
  onConfirm,
}: {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  tone?: "default" | "danger";
  reasons?: readonly { value: string; label: string }[];
  onConfirm: (reasonCode: string | null, note: string | null) => Promise<boolean>;
}) {
  const [code, setCode] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const close = (open: boolean) => {
    if (busy) return;
    if (!open) {
      setCode(null);
      setNote("");
      setError(null);
    }
    onOpenChange(open);
  };
  const confirm = async () => {
    if (reasons && !code) {
      setError("Choose the reason. It is kept in the challan's history.");
      return;
    }
    setBusy(true);
    try {
      const ok = await onConfirm(code, note.trim() || null);
      if (ok) {
        setCode(null);
        setNote("");
        onOpenChange(false);
      }
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={close}
      title={title}
      description={description}
      size="sm"
      actions={
        <>
          <Button variant="ghost" onPress={() => close(false)} isDisabled={busy}>
            Keep as it is
          </Button>
          <Button variant={tone === "danger" ? "danger" : "inverse"} loading={busy} onPress={() => void confirm()}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {reasons ? (
          <Select
            label="Reason"
            isRequired
            placeholder="Choose a reason"
            options={reasons.map((reason) => ({ value: reason.value, label: reason.label }))}
            value={code}
            onChange={(value) => {
              setCode(value);
              setError(null);
            }}
            error={error ?? undefined}
          />
        ) : null}
        <Textarea label={reasons ? "Note" : "Reason"} optional rows={2} maxLength={500} value={note} onChange={setNote} />
      </div>
    </Modal>
  );
}

/**
 * What can be done with this challan now, split for the header: the step forward (issue or close),
 * the links to its paper, the rarer actions as a menu, and the dialogs that confirm them. Only
 * what the server offers appears (`allowed_transitions` and `capabilities`).
 */
export function useChallanActions(challan: ChallanDetail, commands: ChallanCommands) {
  const router = useRouter();
  const [asking, setAsking] = useState<Asking>(null);
  const model: ChallanActionModel = challanActions(challan);
  const number = challan.challan_number;

  const transition = async (action: "issue" | "close" | "cancel", reasonCode: string | null, note: string | null): Promise<boolean> => {
    const outcome = await commands.run(action, [reasonCode, note], (key, current) => transitionChallan(current, { action, reason_code: reasonCode, reason: note }, key), {
      done: DONE[action],
      failed: FAILED[action] ?? "The change was not saved",
      invalidation: "challans.challan_transition",
    });
    return outcome.ok;
  };

  /** For `ConfirmDialog`: a rejected promise keeps the dialog open (the command hook has already said why). */
  const confirmed = async (work: Promise<boolean>): Promise<void> => {
    if (!(await work)) throw new Error("not completed");
  };

  const duplicate = () =>
    void commands.run(
      "duplicate",
      [],
      async (key) => {
        const copy = await duplicateChallan(challan.id, key);
        toast.success(`Draft ${copy.challan_number} created`, { description: `A copy of ${number}, with the same details and lines.` });
        router.push(asRoute(copy.path));
        return null;
      },
      { failed: "The challan was not duplicated" },
    );

  const remove = async (): Promise<boolean> => {
    const outcome = await commands.run("delete", [], (key, current) => deleteChallan(current, key), { done: "Draft deleted", failed: "The draft was not deleted" });
    if (outcome.ok) router.push(asRoute(CHALLANS_HOME));
    return outcome.ok;
  };

  const menu: MenuItem[] = [];
  if (model.canDuplicate) menu.push({ id: "duplicate", label: "Duplicate", icon: "copy", description: "A new draft with the same details and lines", onAction: duplicate });
  const destructive: MenuItem[] = [];
  if (model.cancel) destructive.push({ id: "cancel", label: "Cancel challan", icon: "xCircle", tone: "danger", onAction: () => setAsking("cancel") });
  if (model.canDelete) destructive.push({ id: "delete", label: "Delete draft", icon: "trash", tone: "danger", onAction: () => setAsking("delete") });
  if (menu.length > 0 && destructive.length > 0) menu.push({ separator: true, id: "sep" });
  menu.push(...destructive);

  const forward = model.forward;
  const forwardLabel = forward ? (forward.action === "issue" ? "Issue challan" : "Close challan") : null;
  const open = (which: Exclude<Asking, null>) => (isOpen: boolean) => setAsking(isOpen ? which : null);

  const dialogs = (
    <>
      {forward?.action === "issue" ? (
        forward.requires_reason ? (
          <ReasonModal
            isOpen={asking === "issue"}
            onOpenChange={open("issue")}
            title={`Issue ${number}?`}
            description="Once issued, its lines and details are fixed. Only the internal note can still change."
            confirmLabel="Issue challan"
            onConfirm={(code, note) => transition("issue", code, note)}
          />
        ) : (
          <ConfirmDialog
            isOpen={asking === "issue"}
            onOpenChange={open("issue")}
            title={`Issue ${number}?`}
            description="Once issued, its lines and details are fixed. Only the internal note can still change."
            confirmLabel="Issue challan"
            onConfirm={() => confirmed(transition("issue", null, null))}
          />
        )
      ) : null}
      {forward?.action === "close" ? (
        forward.requires_reason ? (
          <ReasonModal
            isOpen={asking === "close"}
            onOpenChange={open("close")}
            title={`Close ${number}?`}
            description="Closing says nothing more is expected against this challan."
            confirmLabel="Close challan"
            onConfirm={(code, note) => transition("close", code, note)}
          />
        ) : (
          <ConfirmDialog
            isOpen={asking === "close"}
            onOpenChange={open("close")}
            title={`Close ${number}?`}
            description="Closing says nothing more is expected against this challan."
            confirmLabel="Close challan"
            onConfirm={() => confirmed(transition("close", null, null))}
          />
        )
      ) : null}
      {model.cancel ? (
        <ReasonModal
          isOpen={asking === "cancel"}
          onOpenChange={open("cancel")}
          title={`Cancel ${number}?`}
          description="A cancelled challan stays on file with its number and the reason you give."
          confirmLabel="Cancel challan"
          tone="danger"
          reasons={CANCEL_REASONS}
          onConfirm={(code, note) => transition("cancel", code, note)}
        />
      ) : null}
      {model.canDelete ? (
        <ConfirmDialog
          isOpen={asking === "delete"}
          onOpenChange={open("delete")}
          title={`Delete draft ${number}?`}
          description="The draft is removed. Its number stays reserved and is never given to another challan."
          confirmLabel="Delete draft"
          cancelLabel="Keep the draft"
          tone="danger"
          onConfirm={() => confirmed(remove())}
        />
      ) : null}
    </>
  );

  return {
    model,
    forward,
    forwardLabel,
    /** Opens the confirmation for the step forward. */
    startForward: () => (forward ? setAsking(forward.action) : undefined),
    pdfHref: challanPdfHref(challan.id),
    printHref: `/print/challans/${encodeURIComponent(challan.id)}`,
    menu,
    dialogs,
    pending: commands.pending,
  };
}

export type ChallanActions = ReturnType<typeof useChallanActions>;
