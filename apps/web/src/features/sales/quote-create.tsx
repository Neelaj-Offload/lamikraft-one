"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Form } from "react-aria-components";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Switch } from "@/components/ui/choice";
import { NumberField } from "@/components/ui/number-field";
import { ComboBox, Select } from "@/components/ui/select";
import { TextArea, TextField } from "@/components/ui/text-field";
import { toast } from "@/components/ui/toast";
import { createCommandKeys, commandSignature } from "@/lib/api/command-keys";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { CURRENCIES } from "@/lib/format/money";
import { useOnline } from "@/lib/hooks";
import { briefingMessages } from "@/messages/briefing";
import { salesMessages as m } from "@/messages/sales";
import { createQuote, fetchEnquiry } from "./api";
import { usePartySearch, type PartyOption } from "./pickers";
import { INCOTERMS, PRICE_TYPES, type PriceType, type QuoteCreateRequest } from "./types";

export interface QuoteDraftForm {
  party: PartyOption | null;
  brand: string;
  currency: string | null;
  price_type: PriceType;
  incoterm: string | null;
  incoterm_place: string;
  validity_days: string | null;
  customer_reference: string;
  remarks: string;
  apply_minimum_surcharge: boolean;
}

export const EMPTY_DRAFT: QuoteDraftForm = {
  party: null,
  brand: "LK",
  currency: null,
  price_type: "export",
  incoterm: "FOB",
  incoterm_place: "",
  validity_days: "30",
  customer_reference: "",
  remarks: "",
  apply_minimum_surcharge: false,
};

/** The `QuoteCreate` body: only filled fields; the currency defaults to the customer's. */
export function quoteCreateBody(form: QuoteDraftForm, enquiryId: string | null = null): QuoteCreateRequest | null {
  if (!form.party) return null;
  const body: QuoteCreateRequest = {
    party_id: form.party.id,
    ...(enquiryId ? { enquiry_id: enquiryId } : {}),
    brand: form.brand,
    price_type: form.price_type,
    incoterm: form.incoterm,
    apply_minimum_surcharge: form.apply_minimum_surcharge,
  };
  const currency = form.currency ?? form.party.default_currency;
  if (currency) body.currency = currency;
  if (form.validity_days && /^\d+$/.test(form.validity_days)) body.validity_days = Number.parseInt(form.validity_days, 10);
  if (form.incoterm_place.trim()) body.incoterm_place = form.incoterm_place.trim();
  if (form.customer_reference.trim()) body.customer_reference = form.customer_reference.trim();
  if (form.remarks.trim()) body.remarks = form.remarks.trim();
  return body;
}

export function QuoteCreate({ enquiryId = null }: { enquiryId?: string | null }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const online = useOnline();
  const [form, setForm] = useState<QuoteDraftForm>(EMPTY_DRAFT);
  const [partyText, setPartyText] = useState("");
  const enquiry = useQuery({
    queryKey: queryKeys.sales.enquiry(enquiryId ?? ""),
    queryFn: ({ signal }) => fetchEnquiry(enquiryId!, signal),
    enabled: enquiryId !== null,
  });
  const [prefilledFrom, setPrefilledFrom] = useState<string | null>(null);
  if (enquiry.data && prefilledFrom !== enquiry.data.id && !form.party) {
    // Start from the enquiry's customer (the currency then defaults to theirs on the server).
    const party = enquiry.data.party;
    setPrefilledFrom(enquiry.data.id);
    setForm((current) => ({ ...current, party: { ...party, default_currency: "" } }));
    setPartyText(party.display_name);
  }
  const [submitted, setSubmitted] = useState(false);
  const [pending, setPending] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [commandKeys] = useState(() => createCommandKeys());
  const parties = usePartySearch(partyText);
  const options = [...(form.party ? [form.party] : []), ...(parties.data ?? []).filter((party) => party.id !== form.party?.id)];
  const set = <K extends keyof QuoteDraftForm>(key: K, value: QuoteDraftForm[K]) => setForm((current) => ({ ...current, [key]: value }));
  const offline = online ? null : briefingMessages.offlineActions;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    const body = quoteCreateBody(form, enquiry.data?.id ?? null);
    if (!body || pending || offline) return;
    const signature = commandSignature("create_quote", JSON.stringify(body));
    const attempt = commandKeys.attempt(signature, () => body);
    setPending(true);
    setFieldErrors({});
    try {
      const quote = await createQuote(attempt.payload, attempt.key);
      commandKeys.settle(signature);
      await queryClient.invalidateQueries({ queryKey: queryKeys.sales.all() });
      router.push(quote.path as Parameters<typeof router.push>[0]);
    } catch (error) {
      commandKeys.settle(signature, error);
      if (error instanceof ProblemError && error.status === 422) {
        const errors: Record<string, string> = {};
        for (const issue of error.validationIssues) {
          const field = String(issue.loc.at(-1) ?? "");
          if (field) errors[field] = issue.msg;
        }
        setFieldErrors(errors);
      }
      toast.error(m.create.failed, { description: error instanceof ProblemError ? (error.detail ?? error.title) : undefined });
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="flex max-w-2xl flex-col gap-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">{m.create.title}</h1>
        <p className="text-ink-muted">{m.create.intro}</p>
        {enquiry.data ? <p className="text-sm text-ink">{m.create.fromEnquiry(enquiry.data.enquiry_number)}</p> : null}
      </header>
      <Form onSubmit={submit} className="flex flex-col gap-5" validationBehavior="aria">
        <ComboBox
          label={m.create.party}
          placeholder={m.create.partyPlaceholder}
          emptyText={partyText.trim().length < 2 ? m.create.partyPlaceholder : m.create.partyEmpty}
          options={options.map((party) => ({ id: party.id, label: party.display_name, detail: party.party_number }))}
          value={form.party?.id ?? null}
          inputValue={partyText}
          onInputChange={setPartyText}
          onChange={(id) => {
            const party = options.find((candidate) => candidate.id === id) ?? null;
            set("party", party);
            if (party) setPartyText(party.display_name);
          }}
          isRequired
          errorMessage={submitted && !form.party ? m.create.partyRequired : fieldErrors.party_id}
        />
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          <Select label={m.create.brand} options={[{ id: "LK", label: "Lamikraft (LK)" }, { id: "CR", label: "Crown (CR)" }]} value={form.brand} onChange={(value) => set("brand", value ?? "LK")} />
          <Select
            label={m.create.currency}
            options={CURRENCIES.map((code) => ({ id: code, label: code }))}
            value={form.currency ?? form.party?.default_currency ?? null}
            onChange={(value) => set("currency", value)}
            description={form.party?.default_currency ? m.create.currencyDefault(form.party.default_currency) : undefined}
            errorMessage={fieldErrors.currency}
          />
          <Select
            label={m.create.priceType}
            options={PRICE_TYPES.map((type) => ({ id: type, label: m.priceTypes[type] ?? type }))}
            value={form.price_type}
            onChange={(value) => set("price_type", (PRICE_TYPES.find((type) => type === value) ?? "export") as PriceType)}
          />
          <Select
            label={m.create.incoterm}
            options={[{ id: "", label: m.create.noIncoterm }, ...INCOTERMS.map((term) => ({ id: term, label: term }))]}
            value={form.incoterm ?? ""}
            onChange={(value) => set("incoterm", value || null)}
          />
          <TextField label={m.create.incotermPlace} value={form.incoterm_place} onChange={(value) => set("incoterm_place", value)} maxLength={120} />
          <NumberField
            label={m.create.validity}
            value={form.validity_days}
            onChange={(value) => set("validity_days", value)}
            maxFractionDigits={0}
            errorMessage={fieldErrors.validity_days}
          />
        </div>
        <TextField label={m.create.reference} value={form.customer_reference} onChange={(value) => set("customer_reference", value)} maxLength={120} />
        <TextArea label={m.create.remarks} value={form.remarks} onChange={(value) => set("remarks", value)} />
        <Switch isSelected={form.apply_minimum_surcharge} onChange={(value) => set("apply_minimum_surcharge", value)}>
          {m.create.surcharge}
        </Switch>
        <div>
          <Button type="submit" variant="primary" isPending={pending} pendingLabel={m.create.creating} {...unavailableWhen(offline)}>
            {m.create.submit}
          </Button>
        </div>
      </Form>
    </div>
  );
}
