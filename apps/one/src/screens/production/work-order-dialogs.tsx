"use client";

import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { fetchPlans } from "@/features/cutting/api";
import {
  fetchPosition,
  issueMaterials,
  linkCutPlan,
  moveFromWip,
  recordOffcut,
  reportOutput,
  transitionWorkOrder,
  type CancelReason,
  type MaterialRead,
  type OperationRead,
  type WorkOrderRead,
} from "@/features/production/api";
import { queryKeys } from "@/lib/api/query-keys";
import { isDecimalStr, isPositiveDecimalStr, subtractDecimalStr, trimDecimalStr } from "@/lib/format/decimal";
import { CANCEL_REASONS, type ProductionRun } from "~/data/production";
import { ErrorBlock } from "~/shell/states";
import { Banner, Button, DecimalField, Modal, Select, SkeletonText, Textarea } from "~/ui";

const FAILED = "That did not go through";

export interface WorkOrderDialogProps {
  wo: WorkOrderRead;
  onClose: () => void;
  run: ProductionRun<WorkOrderRead>;
  pending: string | null;
}

const write = (record: WorkOrderRead) => record;

/** A server quantity as people edit it ("6.000000" becomes "6"). */
const plain = (value: string | null | undefined): string => (value == null ? "" : trimDecimalStr(value));

const materialOption = (material: MaterialRead, quantity: string, what: string) => ({
  value: material.id,
  label: material.component.name,
  description: `${material.component.product_key} · ${trimDecimalStr(quantity)} ${material.uom_code} ${what}`,
});

/** The shared frame of a work order dialog: a short form, Cancel, and one button that names the verb. */
function ActionModal({
  title,
  description,
  confirmLabel,
  busy,
  onClose,
  onConfirm,
  hideConfirm = false,
  tone = "default",
  size = "md",
  children,
}: {
  title: string;
  description?: ReactNode;
  confirmLabel: string;
  busy: boolean;
  onClose: () => void;
  onConfirm: () => void;
  hideConfirm?: boolean;
  tone?: "default" | "danger";
  size?: "sm" | "md";
  children: ReactNode;
}) {
  return (
    <Modal
      isOpen
      onOpenChange={(open) => {
        if (!open && !busy) onClose();
      }}
      title={title}
      description={description}
      size={size}
      actions={
        <>
          <Button variant="ghost" onPress={onClose} isDisabled={busy}>
            {hideConfirm ? "Close" : tone === "danger" ? "Keep as it is" : "Cancel"}
          </Button>
          {hideConfirm ? null : (
            <Button variant={tone === "danger" ? "danger" : "inverse"} loading={busy} onPress={onConfirm}>
              {confirmLabel}
            </Button>
          )}
        </>
      }
    >
      <div className="flex flex-col gap-4">{children}</div>
    </Modal>
  );
}

const quantityProblem = (value: string): string | null => (!value ? "Enter a quantity." : !isPositiveDecimalStr(value) ? "Enter a quantity above zero." : null);

// ---------------------------------------------------------------------------------------------
// Issue material to the floor

export function IssueDialog({ wo, onClose, run, pending }: WorkOrderDialogProps) {
  const open = wo.materials.filter((material) => isPositiveDecimalStr(material.qty_to_issue));
  const [materialId, setMaterialId] = useState<string | null>(open[0]?.id ?? null);
  const material = wo.materials.find((candidate) => candidate.id === materialId) ?? null;
  const [quantity, setQuantity] = useState(plain(material?.qty_to_issue));
  const [source, setSource] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const position = useQuery({
    queryKey: ["production", "position", material?.component.id ?? ""],
    queryFn: ({ signal }) => fetchPosition(material!.component.id, signal),
    enabled: Boolean(material),
  });
  const sources = (position.data?.balances ?? [])
    .filter((balance) => balance.location.warehouse_id === wo.warehouse.id && balance.location.location_type === "internal" && isPositiveDecimalStr(balance.quantity) && balance.lot?.lot_kind !== "offcut")
    .map((balance) => ({
      value: `${balance.location.id}|${balance.lot?.id ?? ""}`,
      label: `${balance.location.code}${balance.lot ? ` · lot ${balance.lot.lot_code}` : ""}`,
      description: `${trimDecimalStr(balance.quantity)} ${material?.uom_code ?? ""} there`.trim(),
    }));
  const chosen = source ?? sources[0]?.value ?? null;
  const [locationId, lotId] = chosen ? chosen.split("|") : [null, null];

  const confirm = () => {
    const problem = quantityProblem(quantity);
    if (!material || problem) {
      setError(problem ?? "Choose the component to issue.");
      return;
    }
    void run("issue", (key) => issueMaterials(wo, [{ material_id: material.id, quantity, lot_id: lotId || null, from_location_id: locationId || null }], key), {
      done: "Material issued to the floor",
      failed: FAILED,
      write,
    }).then((result) => {
      if (result) onClose();
    });
  };

  if (open.length === 0) {
    return (
      <ActionModal title="Issue material" confirmLabel="Issue material" busy={false} onClose={onClose} onConfirm={onClose} hideConfirm size="sm">
        <p className="t-body text-ink-2">Everything this work order needs has already been issued.</p>
      </ActionModal>
    );
  }

  return (
    <ActionModal
      title="Issue material"
      description={`Moves stock from a bin in ${wo.warehouse.name} to work in progress for ${wo.wo_number}.`}
      confirmLabel="Issue material"
      busy={pending === "issue"}
      onClose={onClose}
      onConfirm={confirm}
    >
      <Select
        label="Component"
        options={open.map((candidate) => materialOption(candidate, candidate.qty_to_issue, "still to issue"))}
        value={materialId}
        onChange={(value) => {
          setMaterialId(value);
          setSource(null);
          setError(null);
          setQuantity(plain(wo.materials.find((candidate) => candidate.id === value)?.qty_to_issue));
        }}
      />
      <Select
        label="From bin"
        placeholder={position.isPending ? "Looking up where it sits" : "No bin holds it"}
        options={sources}
        value={chosen}
        onChange={setSource}
        isDisabled={position.isPending || sources.length === 0}
        help={
          position.isError
            ? "The bins could not load, so this issue names no bin. Close and reopen to try again."
            : !position.isPending && sources.length === 0
              ? `No free stock of this component sits in ${wo.warehouse.name}.`
              : "Lot-tracked components name the lot they are taken from."
        }
      />
      <DecimalField
        label={`Quantity of ${material?.component.product_key ?? "the component"}`}
        value={quantity}
        onChange={(value) => {
          setQuantity(value);
          setError(null);
        }}
        maxFractionDigits={6}
        suffix={material?.uom_code}
        isRequired
        error={error ?? undefined}
      />
    </ActionModal>
  );
}

// ---------------------------------------------------------------------------------------------
// Consume from, or return from, work in progress

export function WipDialog({ kind, wo, onClose, run, pending }: WorkOrderDialogProps & { kind: "consume" | "return" }) {
  const inWip = wo.materials.filter((material) => isPositiveDecimalStr(material.qty_in_wip));
  const [materialId, setMaterialId] = useState<string | null>(inWip[0]?.id ?? null);
  const material = wo.materials.find((candidate) => candidate.id === materialId) ?? null;
  const [quantity, setQuantity] = useState(plain(material?.qty_in_wip));
  const [error, setError] = useState<string | null>(null);
  const consume = kind === "consume";
  const title = consume ? "Consume material" : "Return material to stock";

  const confirm = () => {
    const problem = quantityProblem(quantity);
    if (!material || problem) {
      setError(problem ?? "Choose the component.");
      return;
    }
    void run(kind, (key) => moveFromWip(wo, kind, [{ material_id: material.id, quantity }], key), {
      done: consume ? "Material consumed" : "Material returned to stock",
      failed: FAILED,
      write,
    }).then((result) => {
      if (result) onClose();
    });
  };

  if (inWip.length === 0) {
    return (
      <ActionModal title={title} confirmLabel={title} busy={false} onClose={onClose} onConfirm={onClose} hideConfirm size="sm">
        <p className="t-body text-ink-2">Nothing is in work in progress for this order. Issue material first.</p>
      </ActionModal>
    );
  }

  return (
    <ActionModal
      title={title}
      description={consume ? "Records what the floor has used up from work in progress." : "Sends unused material from work in progress back to its bin."}
      confirmLabel={consume ? "Consume material" : "Return to stock"}
      busy={pending === kind}
      onClose={onClose}
      onConfirm={confirm}
    >
      <Select
        label="Component"
        options={inWip.map((candidate) => materialOption(candidate, candidate.qty_in_wip, "in work in progress"))}
        value={materialId}
        onChange={(value) => {
          setMaterialId(value);
          setError(null);
          setQuantity(plain(wo.materials.find((candidate) => candidate.id === value)?.qty_in_wip));
        }}
      />
      <DecimalField
        label={`Quantity of ${material?.component.product_key ?? "the component"}`}
        value={quantity}
        onChange={(value) => {
          setQuantity(value);
          setError(null);
        }}
        maxFractionDigits={6}
        suffix={material?.uom_code}
        isRequired
        error={error ?? undefined}
      />
    </ActionModal>
  );
}

// ---------------------------------------------------------------------------------------------
// Report output

/** What is still to make: planned less good, never below zero. */
export function remainingToMake(wo: WorkOrderRead): string {
  if (!isDecimalStr(wo.qty_planned) || !isDecimalStr(wo.qty_good)) return "0";
  const left = subtractDecimalStr(wo.qty_planned, wo.qty_good);
  return isPositiveDecimalStr(left) ? left : "0";
}

export function OutputDialog({ wo, onClose, run, pending }: WorkOrderDialogProps) {
  const [good, setGood] = useState(remainingToMake(wo));
  const [scrap, setScrap] = useState("0");
  const [error, setError] = useState<string | null>(null);

  const confirm = () => {
    if (!good) {
      setError("Enter the good quantity. Use 0 if this report is scrap only.");
      return;
    }
    void run("output", (key) => reportOutput(wo, { qty_good: good, qty_scrap: scrap || "0" }, key), { done: "Output posted to stock", failed: FAILED, write }).then((result) => {
      if (result) onClose();
    });
  };

  return (
    <ActionModal
      title="Report output"
      description={`Good units of ${wo.product.name} go into stock in ${wo.warehouse.name}. Scrap is recorded and stays out of stock.`}
      confirmLabel="Post output"
      busy={pending === "output"}
      onClose={onClose}
      onConfirm={confirm}
    >
      <DecimalField
        label="Good quantity"
        value={good}
        onChange={(value) => {
          setGood(value);
          setError(null);
        }}
        maxFractionDigits={6}
        suffix={wo.uom_code}
        isRequired
        error={error ?? undefined}
      />
      <DecimalField label="Scrap quantity" optional value={scrap} onChange={setScrap} maxFractionDigits={6} suffix={wo.uom_code} />
    </ActionModal>
  );
}

// ---------------------------------------------------------------------------------------------
// Record a measured offcut

const NO_PREDICTION = "none";

export function OffcutDialog({ wo, onClose, run, pending }: WorkOrderDialogProps) {
  const sheets = wo.materials.filter((material) => material.is_sheet_material);
  const board = wo.operations.find((operation) => operation.is_board_cutting) ?? null;
  const predicted = board?.predicted_offcuts ?? [];
  const [materialId, setMaterialId] = useState<string | null>(sheets[0]?.id ?? null);
  const [predictedId, setPredictedId] = useState<string | null>(null);
  const [length, setLength] = useState("");
  const [width, setWidth] = useState("");
  const [thickness, setThickness] = useState("");
  const [errors, setErrors] = useState<{ material?: string; length?: string; width?: string }>({});

  const confirm = () => {
    const found: typeof errors = {};
    if (!materialId) found.material = "Choose the sheet the offcut came from.";
    if (!length) found.length = "Measure the length.";
    if (!width) found.width = "Measure the width.";
    setErrors(found);
    if (!materialId || !length || !width) return;
    void run(
      "offcut",
      (key) => recordOffcut(wo, { material_id: materialId, operation_id: board?.id ?? null, length_mm: length, width_mm: width, thickness_mm: thickness || null, predicted_offcut_id: predictedId }, key),
      { done: "Offcut recorded in stock", failed: FAILED, write },
    ).then((result) => {
      if (result) onClose();
    });
  };

  return (
    <ActionModal
      title="Record a measured offcut"
      description="Measure the piece that is left. It becomes an offcut lot in stock with these dimensions, and it never counts as available stock."
      confirmLabel="Record offcut"
      busy={pending === "offcut"}
      onClose={onClose}
      onConfirm={confirm}
    >
      <Select
        label="Sheet it came from"
        placeholder="Choose a sheet"
        options={sheets.map((sheet) => ({ value: sheet.id, label: sheet.component.name, description: sheet.component.product_key }))}
        value={materialId}
        onChange={(value) => {
          setMaterialId(value);
          setErrors((current) => ({ ...current, material: undefined }));
        }}
        error={errors.material}
      />
      {predicted.length > 0 ? (
        <Select
          label="Start from a predicted offcut"
          options={[
            { value: NO_PREDICTION, label: "None" },
            ...predicted.map((piece) => ({ value: piece.id, label: `${trimDecimalStr(piece.length_mm)} × ${trimDecimalStr(piece.width_mm)} mm`, description: `Board ${piece.board_no} of the cut plan` })),
          ]}
          value={predictedId ?? NO_PREDICTION}
          onChange={(value) => {
            const piece = predicted.find((candidate) => candidate.id === value) ?? null;
            setPredictedId(piece ? piece.id : null);
            if (piece) {
              setLength(trimDecimalStr(piece.length_mm));
              setWidth(trimDecimalStr(piece.width_mm));
              setErrors({});
            }
          }}
          help="Fills in the size the cut plan expected. Correct it to what you measured."
        />
      ) : null}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <DecimalField
          label="Length"
          value={length}
          onChange={(value) => {
            setLength(value);
            setErrors((current) => ({ ...current, length: undefined }));
          }}
          maxFractionDigits={1}
          suffix="mm"
          isRequired
          error={errors.length}
        />
        <DecimalField
          label="Width"
          value={width}
          onChange={(value) => {
            setWidth(value);
            setErrors((current) => ({ ...current, width: undefined }));
          }}
          maxFractionDigits={1}
          suffix="mm"
          isRequired
          error={errors.width}
        />
        <DecimalField label="Thickness" optional value={thickness} onChange={setThickness} maxFractionDigits={1} suffix="mm" />
      </div>
    </ActionModal>
  );
}

// ---------------------------------------------------------------------------------------------
// Link a cut plan to a board-cutting operation

export function PlanDialog({ wo, operation, onClose, run, pending }: WorkOrderDialogProps & { operation: OperationRead }) {
  const plans = useQuery({ queryKey: queryKeys.cutting.plans({ status: "calculated" }), queryFn: ({ signal }) => fetchPlans({ status: "calculated" }, signal) });
  const [planId, setPlanId] = useState<string | null>(operation.cut_plan?.id ?? null);
  const [error, setError] = useState<string | null>(null);

  const confirm = () => {
    if (!planId) {
      setError("Choose the cut plan this operation follows.");
      return;
    }
    void run("plan", (key) => linkCutPlan(wo, operation.id, planId, key), { done: "Cut plan linked", failed: FAILED, write }).then((result) => {
      if (result) onClose();
    });
  };

  const none = plans.data !== undefined && plans.data.items.length === 0;

  return (
    <ActionModal
      title="Link a cut plan"
      description={`Operation ${operation.seq}, ${operation.name}, then takes its boards from the plan in place of the bill of materials.`}
      confirmLabel="Link cut plan"
      busy={pending === "plan"}
      onClose={onClose}
      onConfirm={confirm}
      hideConfirm={plans.isError || none}
    >
      {plans.isPending ? (
        <SkeletonText lines={2} />
      ) : plans.isError ? (
        <ErrorBlock error={plans.error} what="Cut plans" onRetry={() => void plans.refetch()} />
      ) : none ? (
        <Banner tone="neutral" title="No calculated cut plan yet.">
          Calculate a plan under Cut plans, then link it here.
        </Banner>
      ) : (
        <Select
          label="Cut plan"
          placeholder="Choose a calculated plan"
          options={plans.data.items.map((plan) => ({
            value: plan.id,
            label: `${plan.plan_number} · ${plan.name}`,
            description: plan.boards != null ? (plan.boards === 1 ? "1 board" : `${plan.boards} boards`) : undefined,
          }))}
          value={planId}
          onChange={(value) => {
            setPlanId(value);
            setError(null);
          }}
          isRequired
          error={error ?? undefined}
        />
      )}
    </ActionModal>
  );
}

// ---------------------------------------------------------------------------------------------
// Cancel the work order

export function CancelDialog({ wo, onClose, run, pending }: WorkOrderDialogProps) {
  const [code, setCode] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  const confirm = () => {
    if (!code) {
      setError("Choose the reason. It is kept with the work order.");
      return;
    }
    void run("cancel", (key) => transitionWorkOrder(wo, "cancel", key, { reason_code: code as CancelReason, reason: note.trim() || undefined }), {
      done: "Work order cancelled",
      failed: FAILED,
      write,
    }).then((result) => {
      if (result) onClose();
    });
  };

  return (
    <ActionModal
      title={`Cancel ${wo.wo_number}`}
      description="Its reservations are released, so the material is free for other work. An order with output or consumption cannot be cancelled."
      confirmLabel="Cancel work order"
      tone="danger"
      size="sm"
      busy={pending === "cancel"}
      onClose={onClose}
      onConfirm={confirm}
    >
      <Select
        label="Reason"
        placeholder="Choose a reason"
        options={CANCEL_REASONS.map((reason) => ({ value: reason.id, label: reason.label }))}
        value={code}
        onChange={(value) => {
          setCode(value);
          setError(null);
        }}
        isRequired
        error={error ?? undefined}
      />
      <Textarea label="Note" optional rows={2} maxLength={500} value={note} onChange={setNote} />
    </ActionModal>
  );
}
