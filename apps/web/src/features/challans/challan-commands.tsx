"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, unavailableWhen } from "@/components/ui/button";
import { ReasonDialog } from "@/components/ui/reason-dialog";
import { buttonClasses } from "@/components/ui/styles";
import { toast } from "@/components/ui/toast";
import { challansMessages as m } from "@/messages/challans";
import { challanPdfHref, deleteChallan, duplicateChallan, transitionChallan } from "./api";
import type { ChallanDetail } from "./types";
import type { ChallanCommands } from "./use-challan-command";

const w = m.workspace;

export interface CommandButton {
  action: "issue" | "close" | "cancel" | "duplicate" | "delete";
  label: string;
  variant: "primary" | "secondary" | "danger";
  requiresReason: boolean;
}

const LABELS: Record<string, string> = { issue: w.issue, close: w.close, cancel: w.cancel };

/** Buttons only for what the server offers: `allowed_transitions`, plus duplicate and delete from `capabilities`. */
export function commandButtons(challan: ChallanDetail): CommandButton[] {
  const out: CommandButton[] = [];
  for (const t of challan.allowed_transitions) {
    if (t.action !== "issue" && t.action !== "close" && t.action !== "cancel") continue;
    out.push({ action: t.action, label: LABELS[t.action]!, variant: t.action === "cancel" ? "danger" : out.length === 0 ? "primary" : "secondary", requiresReason: t.requires_reason });
  }
  if (challan.capabilities.duplicate?.allowed && !challan.deleted_at) out.push({ action: "duplicate", label: w.duplicate, variant: "secondary", requiresReason: false });
  if (challan.capabilities.delete?.allowed) out.push({ action: "delete", label: w.delete, variant: "danger", requiresReason: false });
  return out;
}

/** Why Issue is not offered yet (the server's guard code), so the person knows what to do next. */
export function issueBlockedText(challan: ChallanDetail): string | null {
  const cap = challan.capabilities.issue;
  if (challan.status !== "draft" || !cap || cap.allowed || !cap.reason_code) return null;
  return w.issueBlocked[cap.reason_code] ?? null;
}

export function ChallanCommandBar({ challan, commands }: { challan: ChallanDetail; commands: ChallanCommands }) {
  const router = useRouter();
  const [asking, setAsking] = useState<CommandButton | null>(null);
  const buttons = commandButtons(challan);
  const canExport = challan.capabilities.export?.allowed === true;

  const perform = async (button: CommandButton, reasonCode: string | null, note: string | null) => {
    if (button.action === "duplicate") {
      const outcome = await commands.run("duplicate", [], async (key) => {
        const copy = await duplicateChallan(challan.id, key);
        toast.success(w.duplicated(copy.challan_number));
        router.push(copy.path as Parameters<typeof router.push>[0]);
        return null;
      }, { failed: w.failed(button.label) });
      return outcome;
    }
    if (button.action === "delete") {
      const outcome = await commands.run("delete", [], (key, current) => deleteChallan(current, key), { done: w.deletedToast, failed: w.failed(button.label) });
      if (outcome.ok) router.push("/operations/challans");
      setAsking(null);
      return outcome;
    }
    const outcome = await commands.run(
      button.action,
      [reasonCode, note],
      (key, current) => transitionChallan(current, { action: button.action, reason_code: reasonCode, reason: note }, key),
      { done: w.transitionDone[button.action] ?? button.label, failed: w.failed(button.label), invalidation: "challans.challan_transition" },
    );
    setAsking(null);
    return outcome;
  };

  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="challan-commands">
      {canExport ? (
        <>
          {/* Real links: the PDF streams from the API (inline, sandboxed); the print view is its own page. */}
          <a href={challanPdfHref(challan.id)} className={buttonClasses("secondary")} type="application/pdf">
            {w.pdf}
          </a>
          <a href={`/print/challans/${encodeURIComponent(challan.id)}`} className={buttonClasses("secondary")}>
            {w.print}
          </a>
        </>
      ) : null}
      {buttons.map((button) => (
        <Button
          key={button.action}
          variant={button.variant}
          isPending={commands.pending === button.action}
          pendingLabel={w.save.saving}
          onPress={() => (button.requiresReason || button.action === "delete" ? setAsking(button) : void perform(button, null, null))}
          {...unavailableWhen(commands.offline)}
        >
          {button.label}
        </Button>
      ))}
      <ReasonDialog
        title={asking?.label ?? ""}
        description={asking?.action === "delete" ? w.deleteConfirm : challan.challan_number}
        reasons={asking?.action === "cancel" ? w.cancelReasons : []}
        requireNote={false}
        noteLabel={w.reasonLabel}
        confirmLabel={asking?.label ?? ""}
        isOpen={asking !== null}
        isPending={commands.pending !== null}
        disabledReason={commands.offline}
        onOpenChange={(open) => (open ? null : setAsking(null))}
        onConfirm={(code, note) => (asking ? void perform(asking, code, note.trim() || null) : undefined)}
      />
    </div>
  );
}
