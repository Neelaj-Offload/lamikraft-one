"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useState } from "react";
import type { PriceListItem } from "@/features/price-lists/types";
import {
  addPriceItem,
  createPriceList,
  duplicatePriceList,
  retirePriceItem,
  supersedePriceItem,
  updatePriceItem,
  type PriceListDetail,
} from "@/features/pricing/api";
import { useProductSearch } from "@/features/sales/pickers";
import { useResourceCommand } from "@/features/sales/resource-command";
import { queryKeys } from "@/lib/api/query-keys";
import { CURRENCIES } from "@/lib/format/money";
import { usePriceItemHistory } from "~/data/products";
import { ErrorBlock } from "~/shell/states";
import { Button, ComboBox, DatePicker, DateText, DecimalField, Drawer, EmptyState, IntegerField, Modal, Select, SkeletonText, TextField, Timeline } from "~/ui";
import { PRICE_TYPE_LABEL, UnitPrice } from "./format";

/** The dialogs of the price list screens: new list, copy of a list, and the four things you can do to one price. */

const PRICING_KEYS = [queryKeys.pricing.all()];
const UNITS = ["pcs", "set", "sheets", "box", "sqm", "sqft"];
const CONFLICT = "Someone else changed this while you were working. The latest version is on screen; check it, then try again.";

type Commands = ReturnType<typeof useResourceCommand>;

// ---- a new price list, as a draft ----

export function CreatePriceListDialog({ isOpen, onOpenChange }: { isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const router = useRouter();
  const commands = useResourceCommand("price_list:new", PRICING_KEYS);
  const [form, setForm] = useState({ code: "", name: "", price_type: "export", currency: "EUR", valid_from: null as string | null, valid_to: null as string | null, priority: null as number | null });
  const [errors, setErrors] = useState<Record<string, string>>({});

  const submit = async () => {
    const local: Record<string, string> = {};
    if (!form.code.trim()) local.code = "Give the list a code, for example EXP-EUR-2027.";
    if (!form.name.trim()) local.name = "Give the list a name people will recognise.";
    if (!form.valid_from) local.valid_from = "Choose the day these prices start.";
    if (Object.keys(local).length > 0) return setErrors(local);
    const body = {
      code: form.code.trim(),
      name: form.name.trim(),
      price_type: form.price_type,
      currency: form.currency,
      scope_kind: "standard",
      valid_from: form.valid_from,
      ...(form.valid_to ? { valid_to: form.valid_to } : {}),
      ...(form.priority !== null ? { priority: form.priority } : {}),
    };
    const outcome = await commands.run("create", [JSON.stringify(body)], () => createPriceList(body), { failed: "The price list was not created" });
    if (outcome.ok) router.push(outcome.value.path as Route);
    else setErrors(outcome.fieldErrors);
  };

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      title="New price list"
      description="It starts as a draft for all customers. Add prices, then activate it when they are right."
      actions={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onPress={() => void submit()} loading={commands.pending === "create"} isDisabled={Boolean(commands.offline)}>
            Create draft list
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
        <TextField label="Code" isRequired maxLength={40} value={form.code} onChange={(code) => setForm({ ...form, code })} error={errors.code || undefined} />
        <TextField label="Name" isRequired maxLength={200} value={form.name} onChange={(name) => setForm({ ...form, name })} error={errors.name || undefined} />
        <Select
          label="Kind of price"
          options={Object.entries(PRICE_TYPE_LABEL).map(([value, label]) => ({ value, label }))}
          value={form.price_type}
          onChange={(price_type) => setForm({ ...form, price_type })}
          error={errors.price_type || undefined}
        />
        <Select label="Currency" options={CURRENCIES.map((code) => ({ value: code, label: code }))} value={form.currency} onChange={(currency) => setForm({ ...form, currency })} error={errors.currency || undefined} />
        <DatePicker label="Prices start on" isRequired value={form.valid_from} onChange={(valid_from) => setForm({ ...form, valid_from })} error={errors.valid_from || undefined} />
        <DatePicker label="Prices end on" optional value={form.valid_to} onChange={(valid_to) => setForm({ ...form, valid_to })} minValue={form.valid_from ?? undefined} help="Leave empty for no end date." error={errors.valid_to || undefined} />
        <IntegerField
          label="Priority"
          optional
          value={form.priority}
          onChange={(priority) => setForm({ ...form, priority })}
          help="When two lists price the same product, the higher priority wins."
          error={errors.priority || undefined}
          className="sm:col-span-2"
        />
      </div>
    </Modal>
  );
}

// ---- a copy of a list, as a new draft ----

export function DuplicatePriceListDialog({ priceList, isOpen, onOpenChange }: { priceList: PriceListDetail; isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const router = useRouter();
  const commands = useResourceCommand(`price_list_dup:${priceList.id}`, PRICING_KEYS);
  const [form, setForm] = useState({ code: "", name: "", valid_from: null as string | null, valid_to: null as string | null });
  const [errors, setErrors] = useState<Record<string, string>>({});

  const submit = async () => {
    const local: Record<string, string> = {};
    if (!form.code.trim()) local.code = "Give the copy its own code.";
    if (!form.name.trim()) local.name = "Give the copy a name.";
    if (!form.valid_from) local.valid_from = "Choose the day the copy's prices start.";
    if (Object.keys(local).length > 0 || !form.valid_from) return setErrors(local);
    const body = { code: form.code.trim(), name: form.name.trim(), valid_from: form.valid_from, ...(form.valid_to ? { valid_to: form.valid_to } : {}) };
    const outcome = await commands.run("duplicate", [JSON.stringify(body)], () => duplicatePriceList(priceList.id, body), { failed: "The copy was not created" });
    if (outcome.ok) router.push(outcome.value.path as Route);
    else setErrors(outcome.fieldErrors);
  };

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      title={`Copy ${priceList.code} as a new draft`}
      description="Every price comes across. Change what you need in the draft, then activate it."
      actions={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onPress={() => void submit()} loading={commands.pending === "duplicate"} isDisabled={Boolean(commands.offline)}>
            Create the copy
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
        <TextField label="Code" isRequired maxLength={40} value={form.code} onChange={(code) => setForm({ ...form, code })} error={errors.code || undefined} />
        <TextField label="Name" isRequired maxLength={200} value={form.name} onChange={(name) => setForm({ ...form, name })} error={errors.name || undefined} />
        <DatePicker label="Prices start on" isRequired value={form.valid_from} onChange={(valid_from) => setForm({ ...form, valid_from })} error={errors.valid_from || undefined} />
        <DatePicker label="Prices end on" optional value={form.valid_to} onChange={(valid_to) => setForm({ ...form, valid_to })} minValue={form.valid_from ?? undefined} error={errors.valid_to || undefined} />
      </div>
    </Modal>
  );
}

// ---- one price: add, edit (draft), change from a date, retire ----

export type PriceDialog = { kind: "add" } | { kind: "edit" | "supersede" | "retire"; item: PriceListItem };

const DIALOG_COPY: Record<PriceDialog["kind"], { title: string; confirm: string; done: string; failed: string }> = {
  add: { title: "Add a price", confirm: "Add price", done: "Price added", failed: "The price was not added" },
  edit: { title: "Edit this price", confirm: "Save price", done: "Price saved", failed: "The price was not saved" },
  supersede: { title: "Change this price from a date", confirm: "Save the new price", done: "New price saved from its date", failed: "The new price was not saved" },
  retire: { title: "Retire this price", confirm: "Retire price", done: "Price retired", failed: "The price was not retired" },
};

export function PriceItemDialog({ priceList, dialog, commands, onClose }: { priceList: PriceListDetail; dialog: PriceDialog; commands: Commands; onClose: () => void }) {
  const item = dialog.kind === "add" ? null : dialog.item;
  const [productText, setProductText] = useState("");
  const [product, setProduct] = useState<string | null>(null);
  const [unit, setUnit] = useState("pcs");
  const [price, setPrice] = useState(item ? item.unit_price.amount : "");
  const [moq, setMoq] = useState(dialog.kind === "edit" ? (item?.moq?.value ?? "") : "");
  const [from, setFrom] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const products = useProductSearch(productText);
  const options = (products.data ?? []).map((option) => ({ id: option.id, label: option.product_name, description: option.product_key }));
  const copy = DIALOG_COPY[dialog.kind];

  const confirm = async () => {
    let call: () => Promise<unknown>;
    if (dialog.kind === "add") {
      const local: Record<string, string> = {};
      if (!product) local.product_id = "Choose the product this price is for.";
      if (!price) local.unit_price = "Enter the price.";
      if (Object.keys(local).length > 0 || !product) return setErrors(local);
      const body = { product_id: product, unit_code: unit, unit_price: price, ...(moq ? { moq } : {}) };
      call = () => addPriceItem(priceList.id, body);
    } else if (dialog.kind === "edit") {
      const changes: Record<string, unknown> = {};
      if (price && price !== dialog.item.unit_price.amount) changes.unit_price = price;
      if ((moq || null) !== (dialog.item.moq?.value ?? null)) changes.moq = moq || null;
      call = () => updatePriceItem(dialog.item, changes);
    } else if (dialog.kind === "supersede") {
      const local: Record<string, string> = {};
      if (!price) local.unit_price = "Enter the new price.";
      if (!from) local.valid_from = "Choose the day the new price starts.";
      if (Object.keys(local).length > 0 || !from) return setErrors(local);
      call = () => supersedePriceItem(dialog.item, { unit_price: price, valid_from: from, reason: reason.trim() || null });
    } else {
      if (!reason.trim()) return setErrors({ reason: "Say why this price is being retired." });
      call = () => retirePriceItem(dialog.item, { reason: reason.trim(), retire_from: from });
    }
    const outcome = await commands.run(`item:${dialog.kind}`, [dialog.kind === "add" ? product : dialog.item.id, price, from, reason], call, {
      done: copy.done,
      failed: copy.failed,
      conflictMessage: CONFLICT,
    });
    if (outcome.ok) onClose();
    else setErrors(outcome.fieldErrors);
  };

  return (
    <Modal
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={copy.title}
      description={
        dialog.kind === "add"
          ? `On ${priceList.code}, in ${priceList.currency}.`
          : dialog.kind === "supersede"
            ? `${dialog.item.product_key} on ${priceList.code}. The current price stays in the history and stops the day before.`
            : dialog.kind === "retire"
              ? `${dialog.item.product_key} on ${priceList.code}. The price stays in the history but no longer prices anything.`
              : `${dialog.item.product_key} on ${priceList.code}.`
      }
      actions={
        <>
          <Button variant="ghost" onPress={onClose}>
            Cancel
          </Button>
          <Button variant={dialog.kind === "retire" ? "danger" : "primary"} onPress={() => void confirm()} loading={commands.pending !== null} isDisabled={Boolean(commands.offline)}>
            {copy.confirm}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-5">
        {dialog.kind === "add" ? (
          <>
            <ComboBox
              label="Product"
              isRequired
              placeholder="Type a code or a name"
              emptyText={productText.trim().length < 2 ? "Type at least two letters" : "No product matches"}
              items={options}
              inputValue={productText}
              onInputChange={setProductText}
              selectedKey={product}
              onSelectionChange={(id) => {
                setProduct(id);
                const option = options.find((candidate) => candidate.id === id);
                if (option) setProductText(option.label);
              }}
              isLoading={products.isFetching}
              error={errors.product_id || undefined}
            />
            <Select label="Priced per" options={UNITS.map((value) => ({ value, label: value }))} value={unit} onChange={setUnit} error={errors.unit_code || undefined} />
          </>
        ) : null}
        {dialog.kind !== "retire" ? (
          <DecimalField
            label={dialog.kind === "supersede" ? "New unit price" : "Unit price"}
            isRequired
            value={price}
            onChange={setPrice}
            prefix={priceList.currency}
            maxFractionDigits={4}
            error={errors.unit_price || undefined}
          />
        ) : null}
        {dialog.kind === "add" || dialog.kind === "edit" ? (
          <DecimalField label="Minimum order quantity" optional value={moq} onChange={setMoq} help="Leave empty when any quantity can be ordered." error={errors.moq || undefined} />
        ) : null}
        {dialog.kind === "supersede" ? (
          <DatePicker label="New price starts on" isRequired value={from} onChange={setFrom} error={errors.valid_from || undefined} />
        ) : null}
        {dialog.kind === "retire" ? (
          <DatePicker label="Stops on" optional value={from} onChange={setFrom} help="Leave empty to retire it today." error={errors.retire_from || undefined} />
        ) : null}
        {dialog.kind === "supersede" || dialog.kind === "retire" ? (
          <TextField
            label="Reason"
            isRequired={dialog.kind === "retire"}
            optional={dialog.kind === "supersede"}
            maxLength={500}
            value={reason}
            onChange={setReason}
            help="Kept in the price's history."
            error={errors.reason || undefined}
          />
        ) : null}
      </div>
    </Modal>
  );
}

// ---- the history of one price ----

const HISTORY_KIND: Record<string, string> = {
  created: "Price added",
  edited_draft: "Edited while the list was a draft",
  superseded: "Replaced by a new price",
  retired: "Retired",
  list_activated: "List activated",
  list_retired: "List retired",
};

function PriceHistory({ item, currency }: { item: PriceListItem; currency: string }) {
  const query = usePriceItemHistory(item.id);
  if (query.isPending) return <SkeletonText lines={6} />;
  if (query.isError || !query.data) return <ErrorBlock error={query.error} what="This price's history" onRetry={() => void query.refetch()} />;
  if (query.data.length === 0) return <EmptyState compact icon="history" title="No history yet" text="Changes to this price will be listed here." />;
  const priceOf = (snapshot: Record<string, unknown> | null) =>
    snapshot && typeof snapshot.unit_price === "string" ? <UnitPrice value={{ amount: snapshot.unit_price, currency }} /> : null;
  const dateOf = (snapshot: Record<string, unknown> | null, key: string) => (snapshot && typeof snapshot[key] === "string" ? (snapshot[key] as string) : null);
  return (
    <Timeline
      label={`History of the price for ${item.product_key}`}
      items={query.data.map((entry) => {
        const before = priceOf(entry.before);
        const after = priceOf(entry.after);
        const from = dateOf(entry.after, "valid_from");
        const to = dateOf(entry.after, "valid_to");
        return {
          id: entry.id,
          title: HISTORY_KIND[entry.change_kind] ?? entry.change_kind,
          meta: (
            <>
              <DateText value={entry.occurred_at} style="dayTime" />
              {entry.actor_name ? ` · ${entry.actor_name}` : ""}
            </>
          ),
          body: (
            <>
              {before || after ? (
                <span className="block">
                  {before}
                  {before && after ? " to " : null}
                  {after}
                </span>
              ) : null}
              {from ? (
                <span className="block">
                  From <DateText value={from} style="business" />
                  {to ? (
                    <>
                      {" "}
                      to <DateText value={to} style="business" />
                    </>
                  ) : null}
                </span>
              ) : null}
              {entry.reason ? <span className="block">Reason: {entry.reason}</span> : null}
            </>
          ),
          icon: entry.change_kind === "retired" || entry.change_kind === "list_retired" ? "archive" : entry.change_kind === "superseded" ? "refresh" : entry.change_kind === "created" ? "plus" : "edit",
        };
      })}
    />
  );
}

export function PriceHistoryDrawer({ item, currency, onClose }: { item: PriceListItem | null; currency: string; onClose: () => void }) {
  return (
    <Drawer
      isOpen={item !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={item ? `Price history for ${item.product_key}` : "Price history"}
      description="Every change to this product's price on this list."
    >
      {item ? <PriceHistory item={item} currency={currency} /> : null}
    </Drawer>
  );
}
