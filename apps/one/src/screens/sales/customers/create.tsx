"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useRef, useState, type FormEvent } from "react";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { createParty } from "@/features/parties/api";
import { createBodyOf, EMPTY_CREATE, fieldErrorsFrom, normaliseCountry, validateCreate, type CreateForm } from "@/features/parties/form-model";
import { CUSTOMER_TYPES, PARTY_ROLES, type PartyRole, type PartyStatus } from "@/features/parties/types";
import { useResourceCommand } from "@/features/sales/resource-command";
import { invalidationMap } from "@/lib/api/query-keys";
import { CURRENCIES } from "@/lib/format/money";
import { useSession } from "@/lib/session/context";
import { Page, PageHeader } from "~/shell/page";
import { NotPermitted } from "~/shell/states";
import { useLeadSources, type Interest } from "~/data/leads";
import { Banner, Button, ButtonLink, CheckboxGroup, FormActions, FormSection, RadioCards, Select, Textarea, TextField, toast } from "~/ui";
import { INTEREST_LABEL, INTERESTS } from "../leads/labels";
import { countryName, ROLE_LABEL, STAGE_HINT, TYPE_LABEL } from "./labels";

const FIELD_NAMES: Record<string, string> = {
  legal_name: "Legal name",
  display_name: "Short name",
  country_code: "Country",
  default_currency: "Currency",
  customer_type: "Customer type",
  status: "Stage",
  roles: "Roles",
  "contact.name": "Contact name",
  "contact.email": "Contact email",
  "contact.phone": "Contact phone",
  "address.line1": "Address line 1",
  "address.line2": "Address line 2",
  "address.city": "City",
  "address.region": "State or region",
  "address.postal_code": "Postal code",
  "address.country_code": "Address country",
};

/** The old form's own messages, reworded so each says what to do. */
const CLIENT_MESSAGES: Record<string, string> = {
  legal_name: "Enter the registered name of the business.",
  country_code: "Enter the two-letter country code, for example IN, DE or US.",
  default_currency: "Choose the currency you quote this customer in.",
  roles: "Choose at least one role.",
  "contact.name": "Add the contact's name, or clear the email and phone.",
  "address.line1": "Add the first line of the address, or clear the other address fields.",
  "address.country_code": "Enter the two-letter country code for this address.",
};

const NO_TYPE = "none";

/** Add a lead or a customer. `stage` comes from `?status=` so "Add lead" opens on the right choice. */
export function CustomerCreate({ stage }: { stage: "prospect" | "active" }) {
  const { permissionKeys } = useSession();
  if (!permissionKeys.has("parties.party.create")) {
    return (
      <Page width="narrow">
        <PageHeader breadcrumb={[{ label: "Sales", href: "/sales" }, { label: "Customers", href: "/sales/parties" as Route }, { label: "Add" }]} title="Add a customer" />
        <NotPermitted what="Adding leads and customers" icon="userPlus" />
      </Page>
    );
  }
  return <CreateForm stage={stage} />;
}

function CreateForm({ stage }: { stage: "prospect" | "active" }) {
  const router = useRouter();
  const commands = useResourceCommand("customer:new", invalidationMap["parties.party_changed"]);
  const [form, setForm] = useState<CreateForm>({ ...EMPTY_CREATE, status: stage });
  const [submitted, setSubmitted] = useState(false);
  const [touched, setTouched] = useState<ReadonlySet<string>>(new Set());
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  const bannerRef = useRef<HTMLDivElement>(null);
  const isLead = form.status === "prospect";
  const sells = form.roles.includes("customer");
  const sources = useLeadSources(sells);
  const [source, setSource] = useState("none");
  const [interests, setInterests] = useState<Interest[]>([]);
  const [requirement, setRequirement] = useState("");
  const [website, setWebsite] = useState("");
  const noun = isLead ? "lead" : "customer";
  const backHref = (isLead ? "/sales/parties?status=prospect" : "/sales/parties?status=active") as Route;

  const clientErrors = validateCreate(form);
  const errorFor = (key: string): string | undefined => {
    if (serverErrors[key]) return serverErrors[key];
    if ((submitted || touched.has(key)) && clientErrors[key]) return CLIENT_MESSAGES[key] ?? clientErrors[key];
    return undefined;
  };
  const visibleErrors = Object.keys(FIELD_NAMES).flatMap((key) => {
    const message = submitted ? (serverErrors[key] || (clientErrors[key] ? (CLIENT_MESSAGES[key] ?? clientErrors[key]) : undefined)) : serverErrors[key];
    return message ? [{ key, message }] : [];
  });

  const touch = (key: string) => setTouched((current) => (current.has(key) ? current : new Set(current).add(key)));
  const clearServer = (key: string) => setServerErrors((current) => (current[key] ? { ...current, [key]: "" } : current));
  const set = <K extends keyof CreateForm>(key: K, value: CreateForm[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
    clearServer(key);
  };
  const setContact = (key: keyof CreateForm["contact"], value: string) => {
    setForm((current) => ({ ...current, contact: { ...current.contact, [key]: value } }));
    clearServer(`contact.${key}`);
  };
  const setAddress = (key: keyof CreateForm["address"], value: string) => {
    setForm((current) => ({ ...current, address: { ...current.address, [key]: value } }));
    clearServer(`address.${key}`);
  };
  const focusBanner = () => window.requestAnimationFrame(() => bannerRef.current?.focus());

  useScreenContribution({
    draft: {
      form_key: "parties.party.create",
      record_ref: null,
      dirty_fields: Object.keys(form).filter((key) => JSON.stringify(form[key as keyof CreateForm]) !== JSON.stringify(EMPTY_CREATE[key as keyof CreateForm])),
      values: { legal_name: form.legal_name, country_code: form.country_code, default_currency: form.default_currency ?? "" },
    },
  });

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (commands.pending || commands.offline) return;
    const base = createBodyOf(form);
    if (!base) {
      focusBanner();
      return;
    }
    // lead fields (spec 2026-11-25-leads-module-design.md); the API ignores them for vendors
    const body = {
      ...base,
      ...(sells
        ? {
            lead_source: source === "none" ? null : source,
            interests,
            requirement: requirement.trim() || null,
            website: website.trim() || null,
          }
        : {}),
    } as typeof base;
    setServerErrors({});
    const outcome = await commands.run("create", [JSON.stringify(body)], (key) => createParty(body, key), {
      failed: `The ${noun} was not added`,
    });
    if (outcome.ok) {
      toast.success(`${outcome.value.display_name} added`, { description: `Saved as ${outcome.value.party_number}.` });
      router.push(outcome.value.path as Route);
      return;
    }
    const mapped = fieldErrorsFrom(outcome.error);
    if (Object.keys(mapped).length > 0) {
      setServerErrors(mapped);
      focusBanner();
    }
  };

  const typedCountry = normaliseCountry(form.country_code);
  const resolvedCountry = /^[A-Z]{2}$/.test(typedCountry) ? countryName(typedCountry) : null;
  const typedAddressCountry = normaliseCountry(form.address.country_code);
  const resolvedAddressCountry = /^[A-Z]{2}$/.test(typedAddressCountry) ? countryName(typedAddressCountry) : null;

  return (
    <Page width="reading">
      <PageHeader
        breadcrumb={[{ label: "Sales", href: "/sales" }, { label: isLead ? "Leads" : "Customers", href: backHref }, { label: `Add a ${noun}` }]}
        title={`Add a ${noun}`}
        lead="Start with the business itself. Quotations, samples and orders attach to this profile from now on."
      />

      <form onSubmit={(event) => void submit(event)} noValidate className="stack">
        {commands.offline ? <Banner tone="amber" title="You are offline.">Reconnect to add this {noun}. What you have typed stays here.</Banner> : null}
        {visibleErrors.length > 0 ? (
          <div ref={bannerRef} tabIndex={-1} className="outline-none">
            <Banner tone="ember" title={visibleErrors.length === 1 ? "One thing needs fixing." : `${visibleErrors.length} things need fixing.`}>
              <ul className="mt-1 flex list-none flex-col gap-1 p-0">
                {visibleErrors.map((entry) => (
                  <li key={entry.key}>
                    <b>{FIELD_NAMES[entry.key] ?? entry.key}:</b> {entry.message}
                  </li>
                ))}
              </ul>
            </Banner>
          </div>
        ) : null}

        <FormSection title="Where they stand" description="You can change this later from their profile.">
          <RadioCards
            className="col-span-full"
            label="Stage"
            hideLabel
            value={form.status}
            onChange={(value) => set("status", value as PartyStatus)}
            options={[
              { value: "prospect", label: "Lead", description: STAGE_HINT.prospect, icon: "userPlus" },
              { value: "active", label: "Customer", description: STAGE_HINT.active, icon: "handshake" },
            ]}
          />
        </FormSection>

        <FormSection title="The business" description="The legal name prints on quotations. The short name is what the team sees day to day.">
          <TextField
            label="Legal name"
            value={form.legal_name}
            onChange={(value) => set("legal_name", value)}
            onBlur={() => touch("legal_name")}
            maxLength={200}
            isRequired
            autoComplete="organization"
            error={errorFor("legal_name")}
          />
          <TextField
            label="Short name"
            optional
            value={form.display_name}
            onChange={(value) => set("display_name", value)}
            maxLength={200}
            help="Leave empty to use the legal name."
            error={errorFor("display_name")}
          />
          <TextField
            label="Country"
            value={form.country_code}
            onChange={(value) => set("country_code", value)}
            onBlur={() => {
              set("country_code", typedCountry);
              touch("country_code");
            }}
            maxLength={2}
            autoComplete="country"
            isRequired
            placeholder="IN"
            help={resolvedCountry ?? "Two letters, for example IN, DE or US."}
            error={errorFor("country_code")}
          />
          <Select
            label="Currency"
            placeholder="Choose a currency"
            options={CURRENCIES.map((code) => ({ value: code, label: code }))}
            value={form.default_currency}
            onChange={(value) => {
              set("default_currency", value);
              touch("default_currency");
            }}
            isRequired
            help="Quotations for them start in this currency."
            error={errorFor("default_currency")}
          />
          <Select
            label="Customer type"
            optional
            options={[{ value: NO_TYPE, label: "Not set" }, ...CUSTOMER_TYPES.map((type) => ({ value: type, label: TYPE_LABEL[type] ?? type }))]}
            value={form.customer_type ?? NO_TYPE}
            onChange={(value) => set("customer_type", CUSTOMER_TYPES.find((type) => type === value) ?? null)}
            error={errorFor("customer_type")}
          />
          <CheckboxGroup
            label="Roles"
            orientation="horizontal"
            options={PARTY_ROLES.map((role) => ({ value: role, label: ROLE_LABEL[role] }))}
            value={form.roles}
            onChange={(value) => {
              set("roles", PARTY_ROLES.filter((role: PartyRole) => value.includes(role)));
              touch("roles");
            }}
            help="Tick more than one if you also buy from them."
            error={errorFor("roles")}
          />
        </FormSection>

        {sells ? (
          <FormSection title="How you met them" description="Optional. Where the lead came from and what they asked for, so the team can follow up well.">
            <Select
              label="Source"
              optional
              options={[{ value: "none", label: "Not known" }, ...(sources.data ?? []).filter((s) => s.is_active).map((s) => ({ value: s.code, label: s.label }))]}
              value={source}
              onChange={(value) => setSource(value ?? "none")}
              error={serverErrors.lead_source}
            />
            <TextField label="Website" optional value={website} onChange={setWebsite} maxLength={200} placeholder="www.example.com" error={serverErrors.website} />
            <CheckboxGroup
              className="col-span-full"
              label="Interested in"
              orientation="horizontal"
              options={INTERESTS.map((i) => ({ value: i, label: INTEREST_LABEL[i] }))}
              value={interests}
              onChange={(value) => setInterests(INTERESTS.filter((i) => value.includes(i)))}
            />
            <Textarea className="col-span-full" label="What they asked for" optional value={requirement} onChange={setRequirement} maxLength={2000} rows={3} placeholder="Chopping boards and risers for 40 outlets" error={serverErrors.requirement} />
          </FormSection>
        ) : null}

        <FormSection title="Main contact" description="Optional. The person you speak to first; add the rest from their profile.">
          <TextField
            className="col-span-full"
            label="Name"
            optional
            value={form.contact.name}
            onChange={(value) => setContact("name", value)}
            onBlur={() => touch("contact.name")}
            maxLength={200}
            autoComplete="off"
            error={errorFor("contact.name")}
          />
          <TextField label="Email" optional type="email" inputMode="email" iconLeft="mail" value={form.contact.email} onChange={(value) => setContact("email", value)} maxLength={254} error={errorFor("contact.email")} />
          <TextField label="Phone" optional type="tel" inputMode="tel" iconLeft="phone" value={form.contact.phone} onChange={(value) => setContact("phone", value)} maxLength={40} error={errorFor("contact.phone")} />
        </FormSection>

        <FormSection title="Billing address" description="Optional. Saved as their default billing address.">
          <TextField
            className="col-span-full"
            label="Address line 1"
            optional
            value={form.address.line1}
            onChange={(value) => setAddress("line1", value)}
            onBlur={() => touch("address.line1")}
            maxLength={200}
            autoComplete="address-line1"
            error={errorFor("address.line1")}
          />
          <TextField className="col-span-full" label="Address line 2" optional value={form.address.line2} onChange={(value) => setAddress("line2", value)} maxLength={200} autoComplete="address-line2" error={errorFor("address.line2")} />
          <TextField label="City" optional value={form.address.city} onChange={(value) => setAddress("city", value)} maxLength={120} autoComplete="address-level2" error={errorFor("address.city")} />
          <TextField label="State or region" optional value={form.address.region} onChange={(value) => setAddress("region", value)} maxLength={120} autoComplete="address-level1" error={errorFor("address.region")} />
          <TextField label="Postal code" optional value={form.address.postal_code} onChange={(value) => setAddress("postal_code", value)} maxLength={20} autoComplete="postal-code" error={errorFor("address.postal_code")} />
          <TextField
            label="Country"
            optional
            value={form.address.country_code}
            placeholder={typedCountry || undefined}
            onChange={(value) => setAddress("country_code", value)}
            onBlur={() => {
              setAddress("country_code", typedAddressCountry);
              touch("address.country_code");
            }}
            maxLength={2}
            help={resolvedAddressCountry ?? "Two letters. Leave empty to use the country above."}
            error={errorFor("address.country_code")}
          />
        </FormSection>

        <FormActions>
          <ButtonLink variant="ghost" href={backHref}>
            Cancel
          </ButtonLink>
          <Button type="submit" loading={commands.pending === "create"} isDisabled={Boolean(commands.offline)}>
            {isLead ? "Add lead" : "Add customer"}
          </Button>
        </FormActions>
      </form>
    </Page>
  );
}
