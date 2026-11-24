"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useId, useState, type FormEvent } from "react";
import { usePartySearch } from "@/features/sales/pickers";
import { useResourceCommand } from "@/features/sales/resource-command";
import { createSample } from "@/features/samples/api";
import { Banner, Button, ComboBox, DecimalField, Modal, Select, TextField, toast } from "~/ui";
import { SAMPLE_UNITS } from "./labels";

const SAMPLE_QUERIES = [["sales", "samples"], ["sales", "sample-status-counts"]] as const;

/**
 * Add a customer sample (it starts as "Requested"). On a customer's profile the customer is
 * already known and is passed as `customer`; on the samples list the person picks one.
 */
export function SampleCreateDialog({
  isOpen,
  onOpenChange,
  customer,
}: {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  customer?: { id: string; name: string };
}) {
  const formId = useId();
  const router = useRouter();
  const commands = useResourceCommand("sample:new", SAMPLE_QUERIES);
  const [partyText, setPartyText] = useState("");
  const [partyId, setPartyId] = useState<string | null>(customer?.id ?? null);
  const [description, setDescription] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [unit, setUnit] = useState<string>("pcs");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const search = usePartySearch(customer ? "" : partyText);
  const options = (search.data ?? []).map((party) => ({ id: party.id, label: party.display_name, description: party.party_number }));

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (commands.pending || commands.offline) return;
    const next: Record<string, string> = {};
    if (!partyId) next.party_id = "Choose the customer this sample is for.";
    if (!quantity) next.quantity = "Enter how many you are sending.";
    if (Object.keys(next).length > 0) return setErrors(next);
    const body = { party_id: partyId, description: description.trim() || undefined, quantity, unit_code: unit };
    const outcome = await commands.run("create", [JSON.stringify(body)], (key) => createSample(body, key), { failed: "The sample was not added" });
    if (outcome.ok) {
      toast.success(`${outcome.value.sample_number} added`);
      onOpenChange(false);
      router.push(outcome.value.path as Route);
    } else {
      setErrors(outcome.fieldErrors);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      title="Add a customer sample"
      description="Samples come out of stock. Record the request now; you record the dispatch when it leaves."
      actions={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" form={formId} loading={commands.pending === "create"} isDisabled={Boolean(commands.offline)}>
            Add sample
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={(event) => void submit(event)} noValidate className="flex flex-col gap-4">
        {commands.offline ? <Banner tone="amber" title="You are offline.">Reconnect to add this sample.</Banner> : null}
        {customer ? (
          <TextField label="Customer" value={customer.name} isReadOnly />
        ) : (
          <ComboBox
            label="Customer"
            placeholder="Type a name or customer number"
            emptyText={partyText.trim().length < 2 ? "Type at least two letters" : "No customer matches. Add them under Customers first."}
            items={options}
            inputValue={partyText}
            onInputChange={(text) => {
              setPartyText(text);
              if (partyId && options.find((option) => option.id === partyId)?.label !== text) setPartyId(null);
            }}
            selectedKey={partyId}
            onSelectionChange={(id) => {
              setPartyId(id);
              const option = options.find((candidate) => candidate.id === id);
              if (option) setPartyText(option.label);
              setErrors((current) => ({ ...current, party_id: "" }));
            }}
            isLoading={search.isFetching}
            isRequired
            help="Receiving a sample is what turns a lead into a customer."
            error={errors.party_id || undefined}
          />
        )}
        <TextField
          label="What you are sending"
          optional
          value={description}
          onChange={setDescription}
          maxLength={500}
          placeholder="Product, decor and size"
          error={errors.description || undefined}
        />
        <div className="grid grid-cols-2 gap-4">
          <DecimalField
            label="Quantity"
            value={quantity}
            onChange={(value) => {
              setQuantity(value);
              setErrors((current) => ({ ...current, quantity: "" }));
            }}
            maxFractionDigits={unit === "pcs" || unit === "set" ? 0 : 4}
            isRequired
            error={errors.quantity || undefined}
          />
          <Select label="Unit" options={SAMPLE_UNITS.map((code) => ({ value: code, label: code }))} value={unit} onChange={setUnit} error={errors.unit_code || undefined} />
        </div>
      </form>
    </Modal>
  );
}
