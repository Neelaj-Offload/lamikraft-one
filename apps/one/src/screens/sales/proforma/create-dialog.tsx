"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useId, useState, type FormEvent } from "react";
import { useResourceCommand } from "@/features/sales/resource-command";
import { fieldErrorsFrom } from "@/features/parties/form-model";
import { useZone } from "@/lib/session/context";
import { createProforma, PROFORMA_INVALIDATE } from "~/data/proforma";
import { Banner, Button, DatePicker, Modal, TextField, toast } from "~/ui";
import { isoToday } from "../leads/labels";

/**
 * Make a proforma invoice from a quotation. "new": a draft with the quotation's lines, terms edited on the PI.
 * "past": a PI already issued before Lamikraft One, entered with its original number and date.
 */
export function ProformaCreateDialog({
  quote,
  mode,
  isOpen,
  onOpenChange,
}: {
  quote: { id: string; number: string; customer: string };
  mode: "new" | "past";
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const formId = useId();
  const router = useRouter();
  const zone = useZone();
  const today = isoToday(zone.timeZone);
  const commands = useResourceCommand(`proforma:new:${quote.id}`, PROFORMA_INVALIDATE);
  const [portOfLoading, setPortOfLoading] = useState("");
  const [portOfDischarge, setPortOfDischarge] = useState("");
  const [piNumber, setPiNumber] = useState("");
  const [piDate, setPiDate] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [failure, setFailure] = useState<string | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (commands.pending || commands.offline) return;
    const local: Record<string, string> = {};
    if (mode === "past" && !piNumber.trim()) local.pi_number = "Enter the number printed on the original PI.";
    if (mode === "past" && !piDate) local.pi_date = "Pick the date printed on the original PI.";
    if (Object.keys(local).length > 0) return setErrors(local);
    const body = {
      port_of_loading: portOfLoading.trim() || undefined,
      port_of_discharge: portOfDischarge.trim() || undefined,
      ...(mode === "past" ? { pi_number: piNumber.trim(), pi_date: piDate ?? undefined } : {}),
    };
    setErrors({});
    setFailure(null);
    const result = await commands.run("create", [JSON.stringify(body)], (key) => createProforma(quote.id, body, key), {
      failed: "The proforma invoice was not created",
    });
    if (result.ok) {
      toast.success(mode === "past" ? `${result.value.pi_number} entered` : "Draft proforma invoice created", {
        description: mode === "past" ? undefined : "Check the terms, then issue it.",
      });
      onOpenChange(false);
      router.push(result.value.path as Route);
      return;
    }
    const found = fieldErrorsFrom(result.error);
    setErrors(found);
    if (Object.keys(found).length === 0 && !result.conflict) setFailure(result.error instanceof Error ? result.error.message : "Try again.");
  };

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      title={mode === "past" ? "Enter an issued proforma invoice" : "Create proforma invoice"}
      description={
        mode === "past"
          ? `A PI sent before Lamikraft One for ${quote.number}. It is saved as issued, with the number and date you give.`
          : `The items and prices come from ${quote.number} for ${quote.customer}. You can edit the terms before issuing.`
      }
      actions={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" form={formId} loading={commands.pending === "create"} isDisabled={Boolean(commands.offline)}>
            {mode === "past" ? "Enter proforma invoice" : "Create draft"}
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={(event) => void submit(event)} noValidate className="flex flex-col gap-5">
        {failure ? (
          <Banner tone="ember" title="It was not created.">
            {failure}
          </Banner>
        ) : null}
        {mode === "past" ? (
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            <TextField label="PI number" isRequired value={piNumber} onChange={setPiNumber} maxLength={40} placeholder="LK/PI/2026/014" autoFocus error={errors.pi_number} />
            <DatePicker label="PI date" isRequired value={piDate} onChange={setPiDate} maxValue={today} error={errors.pi_date} />
          </div>
        ) : null}
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          <TextField label="Port of loading" optional value={portOfLoading} onChange={setPortOfLoading} maxLength={120} placeholder="Mundra" error={errors.port_of_loading} />
          <TextField label="Port of discharge" optional value={portOfDischarge} onChange={setPortOfDischarge} maxLength={120} placeholder="Rotterdam" error={errors.port_of_discharge} />
        </div>
      </form>
    </Modal>
  );
}
