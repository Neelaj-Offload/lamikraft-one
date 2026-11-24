"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { createQuote, fetchEnquiry } from "@/features/sales/api";
import { usePartySearch } from "@/features/sales/pickers";
import { INCOTERMS, PRICE_TYPES } from "@/features/sales/types";
import { commandSignature, createCommandKeys } from "@/lib/api/command-keys";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { CURRENCIES } from "@/lib/format/money";
import { useOnline } from "@/lib/hooks";
import { asRoute, EMPTY_QUOTATION_DRAFT, PRICE_TYPE_LABEL, quotationCreateBody, type QuotationDraftForm } from "~/data/sales-deals";
import { Page, PageHeader } from "~/shell/page";
import {
  Banner,
  Button,
  ButtonLink,
  Code,
  ComboBox,
  FormActions,
  FormSection,
  GlassPanel,
  Icon,
  IntegerField,
  Select,
  Switch,
  Textarea,
  TextField,
  TextLink,
  toast,
} from "~/ui";
import { Steps, type StepState } from "./parts";

const CURRENCY_NAME: Record<string, string> = { INR: "Indian rupee", EUR: "Euro", USD: "US dollar", GBP: "Pound sterling" };
const NO_INCOTERM = "none";

/**
 * Start a quotation: the customer, then the few terms that shape every price. The draft opens in
 * its workspace, where lines are added. `enquiryId` starts it from an enquiry (customer prefilled,
 * enquiry linked).
 */
export function QuotationNew({ enquiryId = null }: { enquiryId?: string | null }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const online = useOnline();
  const [step, setStep] = useState<0 | 1>(0);
  const [form, setForm] = useState<QuotationDraftForm>(EMPTY_QUOTATION_DRAFT);
  const [partyText, setPartyText] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [failure, setFailure] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [commandKeys] = useState(() => createCommandKeys());

  const enquiry = useQuery({
    queryKey: queryKeys.sales.enquiry(enquiryId ?? ""),
    queryFn: ({ signal }) => fetchEnquiry(enquiryId!, signal),
    enabled: enquiryId !== null,
  });
  const [prefilledFrom, setPrefilledFrom] = useState<string | null>(null);
  if (enquiry.data && prefilledFrom !== enquiry.data.id && !form.party) {
    // Start from the enquiry's customer; the currency then defaults to theirs on the server.
    const party = enquiry.data.party;
    setPrefilledFrom(enquiry.data.id);
    setForm((current) => ({ ...current, party: { ...party, default_currency: "" } }));
    setPartyText(party.display_name);
  }

  const parties = usePartySearch(partyText);
  const options = [...(form.party ? [form.party] : []), ...(parties.data ?? []).filter((party) => party.id !== form.party?.id)];
  const set = <K extends keyof QuotationDraftForm>(key: K, value: QuotationDraftForm[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
    if (errors[key]) setErrors((current) => ({ ...current, [key]: "" }));
  };
  const days = /^\d+$/.test(form.validity_days) ? Number.parseInt(form.validity_days, 10) : null;

  const toTerms = () => {
    if (!form.party) {
      setErrors({ party_id: "Choose the customer this quotation is for. Type at least two letters of their name." });
      return;
    }
    setErrors({});
    setStep(1);
  };

  const create = async () => {
    if (days === null || days < 1) {
      setErrors({ validity_days: "Say how many days the prices hold, as a whole number. 30 is usual." });
      return;
    }
    const body = quotationCreateBody(form, enquiry.data?.id ?? null);
    if (!body || pending || !online) return;
    const signature = commandSignature("create_quote", JSON.stringify(body));
    const attempt = commandKeys.attempt(signature, () => body);
    setPending(true);
    setErrors({});
    setFailure(null);
    try {
      const quote = await createQuote(attempt.payload, attempt.key);
      commandKeys.settle(signature);
      await queryClient.invalidateQueries({ queryKey: queryKeys.sales.all() });
      toast.success(`Draft ${quote.quote_number} created`, { description: "Add its lines next." });
      router.push(asRoute(`${quote.path}?view=lines`));
    } catch (error) {
      commandKeys.settle(signature, error);
      if (error instanceof ProblemError && error.status === 422) {
        const found: Record<string, string> = {};
        for (const issue of error.validationIssues) {
          const field = String(issue.loc.at(-1) ?? "");
          if (field) found[field] = issue.msg;
        }
        setErrors(found);
        if (found.party_id) setStep(0);
      }
      setFailure(error instanceof ProblemError ? (error.detail ?? error.title ?? null) : "The connection dropped before the server answered. Check your network and try again.");
    } finally {
      setPending(false);
    }
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (step === 0) toTerms();
    else void create();
  };

  const stateOf = (index: number): StepState => (index < step ? "done" : index === step ? "current" : "todo");
  const currency = form.currency ?? (form.party?.default_currency || null);

  return (
    <Page width="narrow">
      <PageHeader
        breadcrumb={[{ label: "Sales", href: "/sales" }, { label: "Quotations", href: "/sales/quotes" }, { label: "New" }]}
        title="New quotation"
        lead="Two decisions make a draft: who it is for, and on what terms. Lines come next, in the quotation itself."
      />

      <GlassPanel padding="md" className="rise" style={{ "--i": 1 } as React.CSSProperties}>
        <Steps
          label="Steps to a draft quotation"
          steps={[
            { id: "customer", label: "Customer", hint: form.party && step > 0 ? form.party.display_name : "Who it is for", state: stateOf(0) },
            { id: "terms", label: "Terms", hint: "Currency, price type, delivery", state: stateOf(1) },
            { id: "lines", label: "Lines", hint: "Added in the draft", state: "todo" },
          ]}
        />
      </GlassPanel>

      {enquiry.data ? (
        <Banner tone="cobalt" icon="mail" title={`Answering enquiry ${enquiry.data.enquiry_number}.`}>
          The quotation is linked to it, and the customer is already filled in.
        </Banner>
      ) : null}
      {!online ? (
        <Banner tone="amber" title="You are offline.">
          The draft can be created once the connection is back.
        </Banner>
      ) : null}
      {failure ? (
        <Banner tone="ember" title="The draft was not created.">
          {failure}
        </Banner>
      ) : null}

      <form onSubmit={onSubmit} className="stack" noValidate>
        {step === 0 ? (
          <FormSection title="Who is it for?" description="Every quotation belongs to one customer. Their currency and price agreements follow from this choice.">
            <ComboBox
              className="col-span-full"
              label="Customer"
              placeholder="Type a name or customer number"
              items={options.map((party) => ({ id: party.id, label: party.display_name, description: [party.party_number, party.country_code].filter(Boolean).join(" · ") }))}
              inputValue={partyText}
              onInputChange={setPartyText}
              selectedKey={form.party?.id ?? null}
              onSelectionChange={(id) => {
                const party = options.find((candidate) => candidate.id === id) ?? null;
                set("party", party);
                if (errors.party_id) setErrors({});
                if (party) setPartyText(party.display_name);
              }}
              isLoading={parties.isFetching}
              emptyText={partyText.trim().length < 2 ? "Type at least two letters" : "No customer matches. Check the spelling, or add the customer first."}
              isRequired
              error={errors.party_id || undefined}
            />
            {form.party ? (
              <div className="rise-plain col-span-full flex min-w-0 items-center gap-3 rounded-md border border-line bg-surface px-4 py-3">
                <span className="flex h-9 w-9 flex-none items-center justify-center rounded-pill bg-gold-soft text-gold-strong">
                  <Icon name="building" size={18} />
                </span>
                <div className="flex min-w-0 flex-col">
                  <span className="t-label truncate text-ink">{form.party.display_name}</span>
                  <span className="t-caption text-ink-3">
                    {form.party.party_number ? <Code>{form.party.party_number}</Code> : null}
                    {form.party.country_code ? ` · ${form.party.country_code}` : ""}
                    {form.party.default_currency ? ` · quoted in ${form.party.default_currency}` : ""}
                  </span>
                </div>
              </div>
            ) : (
              <p className="t-body-sm col-span-full text-ink-3">
                Not in the list yet?{" "}
                <TextLink href="/sales/parties/new">Add the customer</TextLink>, then come back here.
              </p>
            )}
          </FormSection>
        ) : (
          <>
            <FormSection title="On what terms?" description="These set the prices each line gets. You can change them in the draft until it is sent.">
              <Select
                label="Currency"
                options={CURRENCIES.map((code) => ({ value: code, label: `${code} · ${CURRENCY_NAME[code] ?? code}` }))}
                value={currency}
                onChange={(value) => set("currency", value)}
                placeholder="Choose a currency"
                help={form.party?.default_currency ? `${form.party.display_name} is usually quoted in ${form.party.default_currency}.` : "Left empty, the customer's own currency is used."}
                error={errors.currency || undefined}
              />
              <Select
                label="Price type"
                options={PRICE_TYPES.map((type) => ({ value: type, label: PRICE_TYPE_LABEL[type] ?? type }))}
                value={form.price_type}
                onChange={(value) => set("price_type", PRICE_TYPES.find((type) => type === value) ?? "export")}
                help="Which price list the lines are priced from."
              />
              <Select
                label="Incoterm"
                options={[{ value: NO_INCOTERM, label: "None" }, ...INCOTERMS.map((term) => ({ value: term, label: term }))]}
                value={form.incoterm ?? NO_INCOTERM}
                onChange={(value) => set("incoterm", value === NO_INCOTERM ? null : value)}
              />
              <TextField label="Incoterm place" optional placeholder="Port or city" value={form.incoterm_place} onChange={(value) => set("incoterm_place", value)} maxLength={120} />
              <IntegerField
                label="Valid for, days"
                value={days}
                onChange={(value) => set("validity_days", value === null ? "" : String(value))}
                minValue={1}
                isRequired
                error={errors.validity_days || undefined}
                help="Counted from the day the quotation is sent."
              />
              <Select
                label="Brand"
                options={[
                  { value: "LK", label: "Lamikraft", description: "Numbered LK" },
                  { value: "CR", label: "Crown", description: "Numbered CR" },
                ]}
                value={form.brand}
                onChange={(value) => set("brand", value)}
                help="Sets the letterhead and the number series."
              />
              <Switch
                className="col-span-full"
                label="Add the minimum order surcharge"
                description="Applied only when the quotation totals less than the customer's minimum order value."
                isSelected={form.apply_minimum_surcharge}
                onChange={(value) => set("apply_minimum_surcharge", value)}
              />
            </FormSection>
            <FormSection title="For the customer" description="Optional. Both appear on the quotation they receive.">
              <TextField
                className="col-span-full"
                label="Their reference"
                optional
                placeholder="An RFQ or purchase reference they gave you"
                value={form.customer_reference}
                onChange={(value) => set("customer_reference", value)}
                maxLength={120}
              />
              <Textarea className="col-span-full" label="Remarks" optional rows={3} value={form.remarks} onChange={(value) => set("remarks", value)} />
            </FormSection>
          </>
        )}

        <FormActions note={step === 0 ? "Step 1 of 2" : "Step 2 of 2 · nothing is sent to the customer yet"}>
          {step === 0 ? (
            <ButtonLink href="/sales/quotes" variant="ghost">
              Cancel
            </ButtonLink>
          ) : (
            <Button variant="ghost" iconLeft="arrowLeft" onPress={() => setStep(0)} isDisabled={pending}>
              Back
            </Button>
          )}
          {step === 0 ? (
            <Button type="submit" variant="inverse" iconRight="arrowRight">
              Continue to terms
            </Button>
          ) : (
            <Button type="submit" loading={pending} isDisabled={!online}>
              Create draft
            </Button>
          )}
        </FormActions>
      </form>
    </Page>
  );
}
