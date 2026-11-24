"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { fetchWarehouses } from "@/features/inventory/api";
import { useCommand } from "@/features/inventory/use-command";
import { createRequisition } from "@/features/procurement/api";
import { useProductSearch, type ProductOption } from "@/features/sales/pickers";
import { queryKeys } from "@/lib/api/query-keys";
import { isPositiveDecimalStr } from "@/lib/format/decimal";
import { Banner, Button, ComboBox, DatePicker, DecimalField, Drawer, Select, Textarea } from "~/ui";
import { count, FAILED } from "./labels";
import { asRoute } from "./views";

interface LineDraft {
  key: number;
  product: ProductOption | null;
  text: string;
  quantity: string;
}

interface LineProblem {
  product?: string;
  quantity?: string;
}

const blankLine = (key: number): LineDraft => ({ key, product: null, text: "", quantity: "" });
const started = (line: LineDraft) => line.product !== null || line.quantity !== "";

/**
 * Raise a requisition without leaving the list: where the material is needed, by when, and the
 * lines. It is created as a draft and opens on its own screen, where it is submitted for approval.
 */
export function RequisitionNew({ isOpen, onOpenChange }: { isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const router = useRouter();
  const warehouses = useQuery({ queryKey: queryKeys.inventory.warehouses(), queryFn: ({ signal }) => fetchWarehouses(signal), enabled: isOpen });
  const listKey = useMemo(() => queryKeys.procurement.all(), []);
  const { run, pending, offline } = useCommand<null>(listKey);
  const [warehouse, setWarehouse] = useState<string | null>(null);
  const [requiredBy, setRequiredBy] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<LineDraft[]>([blankLine(1)]);
  const [checked, setChecked] = useState(false);

  // The first warehouse is offered until the person chooses another (as the old form did).
  const chosen = warehouse ?? warehouses.data?.[0]?.id ?? null;
  const filled = lines.filter(started);
  const problemOf = (line: LineDraft): LineProblem => {
    if (!checked || !started(line)) return {};
    return {
      product: line.product ? undefined : "Choose the product. Type at least two letters of its name or key.",
      quantity: isPositiveDecimalStr(line.quantity) ? undefined : "Enter how much is needed, more than zero.",
    };
  };
  const complete = filled.filter((line) => line.product !== null && isPositiveDecimalStr(line.quantity));
  const busy = pending === "create";

  const change = (next: LineDraft) => setLines((all) => all.map((line) => (line.key === next.key ? next : line)));
  const close = () => {
    if (!busy) onOpenChange(false);
  };

  const submit = async () => {
    setChecked(true);
    if (!chosen || filled.length === 0 || complete.length !== filled.length) return;
    const created = await run(
      "create",
      (key) =>
        createRequisition(
          { warehouse_id: chosen, required_by: requiredBy, notes, lines: complete.map((line) => ({ product_id: line.product!.id, quantity: line.quantity })) },
          key,
        ),
      { done: "Draft requisition created", failed: FAILED },
    );
    if (created) router.push(asRoute(created.path));
  };

  return (
    <Drawer
      isOpen={isOpen}
      onOpenChange={(next) => (next ? onOpenChange(true) : close())}
      width="lg"
      title="Raise a requisition"
      description="Say what is needed and where. It starts as a draft: you submit it for approval on the next screen."
      footer={
        <>
          <Button variant="ghost" onPress={close} isDisabled={busy}>
            Cancel
          </Button>
          <Button loading={busy} isDisabled={Boolean(offline)} onPress={() => void submit()}>
            Create requisition
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-6">
        {offline ? (
          <Banner tone="amber" title="You are offline.">
            The requisition can be created once the connection is back.
          </Banner>
        ) : null}
        {warehouses.isError ? (
          <Banner
            tone="ember"
            title="The warehouses could not load."
            action={
              <Button variant="secondary" size="sm" iconLeft="refresh" onPress={() => void warehouses.refetch()}>
                Try again
              </Button>
            }
          >
            A requisition needs a warehouse to deliver to.
          </Banner>
        ) : null}
        {checked && filled.length === 0 ? (
          <Banner tone="ember" title="Add at least one line.">
            Choose a product and say how much of it is needed.
          </Banner>
        ) : null}

        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          <Select
            label="Deliver to"
            placeholder={warehouses.isPending ? "Loading warehouses" : "Choose a warehouse"}
            options={(warehouses.data ?? []).map((wh) => ({ value: wh.id, label: wh.name, description: wh.code }))}
            value={chosen}
            onChange={setWarehouse}
            isDisabled={!warehouses.data}
            isRequired
            error={checked && !chosen && !warehouses.isPending && !warehouses.isError ? "Choose the warehouse the material is for." : undefined}
          />
          <DatePicker label="Needed by" optional value={requiredBy} onChange={setRequiredBy} help="The day the material must be on the floor." />
          <Textarea className="sm:col-span-2" label="Notes" optional rows={2} maxLength={1000} value={notes} onChange={setNotes} placeholder="What it is for, or anything the approver should know" />
        </div>

        <fieldset className="flex min-w-0 flex-col gap-3">
          <legend className="t-h4 mb-3 text-ink">What is needed</legend>
          {lines.map((line, index) => (
            <LineFields
              key={line.key}
              index={index}
              line={line}
              problem={problemOf(line)}
              onChange={change}
              onRemove={lines.length > 1 ? () => setLines((all) => all.filter((other) => other.key !== line.key)) : undefined}
            />
          ))}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Button variant="secondary" size="sm" iconLeft="plus" onPress={() => setLines((all) => [...all, blankLine(Math.max(...all.map((line) => line.key)) + 1)])}>
              Add another line
            </Button>
            <span className="t-caption text-ink-3">{complete.length > 0 ? `${count(complete.length, "line", "lines")} ready` : "Empty lines are left out"}</span>
          </div>
        </fieldset>
      </div>
    </Drawer>
  );
}

function LineFields({
  index,
  line,
  problem,
  onChange,
  onRemove,
}: {
  index: number;
  line: LineDraft;
  problem: LineProblem;
  onChange: (next: LineDraft) => void;
  onRemove?: () => void;
}) {
  const search = useProductSearch(line.text);
  const options = [...(line.product ? [line.product] : []), ...(search.data ?? []).filter((product) => product.id !== line.product?.id)];
  return (
    <div className="rise-plain flex min-w-0 flex-col gap-3 rounded-md border border-line bg-surface p-4">
      <div className="flex items-center justify-between gap-3">
        <span className="t-overline text-ink-3">Line {index + 1}</span>
        {onRemove ? (
          <Button variant="ghost" size="sm" iconLeft="trash" onPress={onRemove}>
            Remove
          </Button>
        ) : null}
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-[minmax(0,1fr)_168px]">
        <ComboBox
          label="Product"
          placeholder="Name or product key"
          items={options.map((product) => ({ id: product.id, label: product.product_name, description: product.product_key }))}
          inputValue={line.text}
          onInputChange={(text) => onChange({ ...line, text })}
          selectedKey={line.product?.id ?? null}
          onSelectionChange={(id) => {
            const product = options.find((option) => option.id === id) ?? null;
            onChange({ ...line, product, text: product ? product.product_name : line.text });
          }}
          isLoading={search.isFetching}
          emptyText={line.text.trim().length < 2 ? "Type at least two letters" : "No product matches. Check the spelling or try its key."}
          error={problem.product}
        />
        <DecimalField
          label="Quantity"
          value={line.quantity}
          onChange={(quantity) => onChange({ ...line, quantity })}
          suffix={line.product?.unit_of_sale ?? undefined}
          error={problem.quantity}
        />
      </div>
    </div>
  );
}
