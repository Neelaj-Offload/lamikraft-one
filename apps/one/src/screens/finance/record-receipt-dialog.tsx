"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { useRolePartySearch } from "@/features/challans/pickers";
import { recordReceipt, type ReceiptInput } from "@/features/finance/api";
import { useFinanceCommand } from "@/features/finance/use-finance-command";
import { queryKeys } from "@/lib/api/query-keys";
import { isPositiveDecimalStr } from "@/lib/format/decimal";
import { asRoute, METHOD_LABEL, RECEIPT_CURRENCIES, RECEIPT_METHODS } from "~/data/finance";
import { Banner, Button, ComboBox, DatePicker, DecimalField, Modal, Select, TextField } from "~/ui";

interface Form {
  partyId: string | null;
  amount: string;
  currency: ReceiptInput["currency"];
  receivedOn: string | null;
  method: ReceiptInput["method"];
  reference: string;
  bankAccount: string;
}

const EMPTY: Form = { partyId: null, amount: "", currency: "EUR", receivedOn: null, method: "bank_transfer", reference: "", bankAccount: "" };

type Errors = Partial<Record<"party" | "amount" | "receivedOn", string>>;

function check(form: Form): Errors {
  const errors: Errors = {};
  if (!form.partyId) errors.party = "Choose the customer who paid.";
  if (!isPositiveDecimalStr(form.amount)) errors.amount = "Enter the amount received, above zero.";
  if (!form.receivedOn) errors.receivedOn = "Choose the day the money arrived.";
  return errors;
}

/** Record money received from a customer. The receipt then opens, ready to be allocated to invoices. */
export function RecordReceiptDialog({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
  const router = useRouter();
  const key = useMemo(() => queryKeys.finance.receipts({}), []);
  const { run, pending, offline } = useFinanceCommand<null>(key);
  const [form, setForm] = useState<Form>(EMPTY);
  const [partyText, setPartyText] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const parties = useRolePartySearch(partyText, "customer");
  const options = parties.data ?? [];
  const busy = pending === "record";
  const set = <K extends keyof Form>(name: K, value: Form[K]) => setForm((current) => ({ ...current, [name]: value }));
  const clear = (name: keyof Errors) => setErrors((current) => (current[name] ? { ...current, [name]: undefined } : current));

  const close = () => {
    if (busy) return;
    setForm(EMPTY);
    setPartyText("");
    setErrors({});
    onClose();
  };

  const submit = async () => {
    const found = check(form);
    setErrors(found);
    if (Object.keys(found).length > 0 || !form.partyId || !form.receivedOn) return;
    const input: ReceiptInput = {
      party_id: form.partyId,
      amount: form.amount,
      currency: form.currency,
      received_on: form.receivedOn,
      method: form.method,
      reference: form.reference,
      bank_account_label: form.bankAccount,
    };
    const receipt = await run("record", (k) => recordReceipt(input, k), { done: "Receipt recorded", failed: "The receipt was not recorded" });
    if (receipt) {
      setForm(EMPTY);
      setPartyText("");
      onClose();
      router.push(asRoute(`/finance/receipts/${receipt.id}`));
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={(open) => (open ? undefined : close())}
      title="Record a receipt"
      description="Enter the money as it arrived. You allocate it to invoices on the next screen."
      actions={
        <>
          <Button variant="ghost" onPress={close} isDisabled={busy}>
            Cancel
          </Button>
          <Button loading={busy} isDisabled={Boolean(offline)} onPress={() => void submit()}>
            Record receipt
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {offline ? (
          <Banner tone="amber" title="You are offline.">
            The receipt can be recorded once the connection is back.
          </Banner>
        ) : null}
        <ComboBox
          label="Customer"
          placeholder="Type a name or customer number"
          items={options.map((party) => ({ id: party.id, label: party.display_name, description: party.party_number ?? undefined }))}
          inputValue={partyText}
          onInputChange={setPartyText}
          selectedKey={form.partyId}
          onSelectionChange={(id) => {
            const party = options.find((candidate) => candidate.id === id) ?? null;
            set("partyId", party?.id ?? null);
            if (party) {
              setPartyText(party.display_name);
              clear("party");
            }
          }}
          isLoading={parties.isFetching}
          emptyText={partyText.trim().length < 2 ? "Type at least two letters" : "No customer matches. Check the spelling."}
          isRequired
          error={errors.party}
        />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <DecimalField
            label="Amount"
            value={form.amount}
            prefix={form.currency}
            onChange={(value) => {
              set("amount", value);
              clear("amount");
            }}
            isRequired
            error={errors.amount}
          />
          <Select
            label="Currency"
            options={RECEIPT_CURRENCIES.map((currency) => ({ value: currency, label: currency }))}
            value={form.currency}
            onChange={(value) => set("currency", RECEIPT_CURRENCIES.find((currency) => currency === value) ?? "EUR")}
            isRequired
          />
          <DatePicker
            label="Received on"
            value={form.receivedOn}
            onChange={(value) => {
              set("receivedOn", value);
              clear("receivedOn");
            }}
            isRequired
            error={errors.receivedOn}
          />
          <Select
            label="Method"
            options={RECEIPT_METHODS.map((method) => ({ value: method, label: METHOD_LABEL[method] ?? method }))}
            value={form.method}
            onChange={(value) => set("method", RECEIPT_METHODS.find((method) => method === value) ?? "bank_transfer")}
            isRequired
          />
          <TextField label="Reference" optional help="The bank or cheque reference." value={form.reference} onChange={(value) => set("reference", value)} maxLength={120} />
          <TextField label="Received into" optional help="A label for the account, for example HDFC current." value={form.bankAccount} onChange={(value) => set("bankAccount", value)} maxLength={80} />
        </div>
      </div>
    </Modal>
  );
}
