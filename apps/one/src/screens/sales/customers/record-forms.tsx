"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { fetchParty, updateParty } from "@/features/parties/api";
import {
  contactRequestOf,
  contactsWith,
  dirtyHeaderFields,
  EMPTY_CONTACT,
  fieldErrorsFrom,
  headerChanges,
  headerFormOf,
  mergeHeaderConflict,
  normaliseCountry,
  validateHeader,
  type ContactForm,
  type HeaderField,
} from "@/features/parties/form-model";
import { CUSTOMER_TYPES, PARTY_ROLES, PARTY_STATUSES, type PartyDetail, type PartyHeaderFields, type PartyRole } from "@/features/parties/types";
import { useResourceCommand } from "@/features/sales/resource-command";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { CURRENCIES } from "@/lib/format/money";
import { Banner, Button, Checkbox, CheckboxGroup, Drawer, Modal, Select, TextField, toast } from "~/ui";
import { countryName, ROLE_LABEL, STAGE_HINT, STAGE_LABEL, TYPE_LABEL } from "./labels";

const FIELD_NAME: Record<HeaderField, string> = {
  legal_name: "legal name",
  display_name: "short name",
  country_code: "country",
  default_currency: "currency",
  customer_type: "customer type",
  status: "stage",
  roles: "roles",
};

const CLIENT_MESSAGE: Partial<Record<HeaderField, string>> = {
  legal_name: "Enter the registered name of the business.",
  country_code: "Enter the two-letter country code, for example IN, DE or US.",
  default_currency: "Choose the currency you quote this customer in.",
  roles: "Choose at least one role.",
};

const NO_TYPE = "none";

/** Edit who the customer is. Only changed fields are sent, with the version the form started from. */
export function EditCustomerDrawer({ party, isOpen, onOpenChange }: { party: PartyDetail; isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const formId = useId();
  const queryClient = useQueryClient();
  const commands = useResourceCommand(`customer:${party.id}`, invalidationMap["parties.party_changed"]);
  const [base, setBase] = useState<PartyHeaderFields>(() => headerFormOf(party));
  const [form, setForm] = useState<PartyHeaderFields>(() => headerFormOf(party));
  const [version, setVersion] = useState(party.version);
  const [submitted, setSubmitted] = useState(false);
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  const [merged, setMerged] = useState<string | null>(null);

  const clientErrors = submitted ? validateHeader(form) : {};
  const errorFor = (field: HeaderField): string | undefined => serverErrors[field] || (clientErrors[field] ? (CLIENT_MESSAGE[field] ?? clientErrors[field]) : undefined);
  const dirty = dirtyHeaderFields(base, form);
  const set = <K extends keyof PartyHeaderFields>(key: K, value: PartyHeaderFields[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
    setServerErrors((current) => (current[key] ? { ...current, [key]: "" } : current));
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (commands.pending || commands.offline) return;
    if (dirty.length === 0) {
      onOpenChange(false);
      return;
    }
    if (Object.keys(validateHeader(form)).length > 0) return;
    const changes = headerChanges(base, form);
    setServerErrors({});
    const outcome = await commands.run("update", [version, JSON.stringify(changes)], (key) => updateParty(party.id, { expected_version: version, ...changes }, key), {
      failed: "The changes were not saved",
      conflictMessage: "Someone else changed this customer",
    });
    if (outcome.ok) {
      queryClient.setQueryData(queryKeys.parties.party(party.id), outcome.value);
      toast.success("Changes saved");
      onOpenChange(false);
      return;
    }
    if (outcome.conflict) {
      // Take over their changes where this person made none; keep what this person typed.
      try {
        const latest = await queryClient.fetchQuery({ queryKey: queryKeys.parties.party(party.id), queryFn: ({ signal }) => fetchParty(party.id, signal), staleTime: 0 });
        const merge = mergeHeaderConflict(base, form, headerFormOf(latest));
        setBase(merge.base);
        setForm(merge.form);
        setVersion(latest.version);
        setMerged(
          merge.adopted.length
            ? `Their changes to ${merge.adopted.map((field) => FIELD_NAME[field]).join(", ")} are now in this form. Yours are untouched. Check them, then save again.`
            : "Their changes did not touch the fields you edited. Save again to keep yours.",
        );
      } catch {
        setMerged("Close this form and open it again to see the latest version.");
      }
      return;
    }
    setServerErrors(fieldErrorsFrom(outcome.error));
  };

  const typedCountry = normaliseCountry(form.country_code);
  const resolvedCountry = /^[A-Z]{2}$/.test(typedCountry) ? countryName(typedCountry) : null;

  return (
    <Drawer
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      title="Edit details"
      description={`${party.party_number} · ${party.display_name}`}
      footer={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" form={formId} loading={commands.pending === "update"} isDisabled={Boolean(commands.offline)}>
            Save changes
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={(event) => void submit(event)} noValidate className="flex flex-col gap-5">
        {commands.offline ? <Banner tone="amber" title="You are offline.">Reconnect to save. Your changes stay in this form.</Banner> : null}
        {merged ? (
          <Banner tone="amber" title="This customer changed while you were editing.">
            {merged}
          </Banner>
        ) : null}
        <TextField label="Legal name" value={form.legal_name} onChange={(value) => set("legal_name", value)} maxLength={200} isRequired error={errorFor("legal_name")} />
        <TextField label="Short name" optional value={form.display_name} onChange={(value) => set("display_name", value)} maxLength={200} help="What the team sees day to day." error={errorFor("display_name")} />
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          <TextField
            label="Country"
            value={form.country_code}
            onChange={(value) => set("country_code", value)}
            onBlur={() => set("country_code", typedCountry)}
            maxLength={2}
            autoComplete="country"
            isRequired
            help={resolvedCountry ?? "Two letters, for example IN."}
            error={errorFor("country_code")}
          />
          <Select
            label="Currency"
            options={CURRENCIES.map((code) => ({ value: code, label: code }))}
            value={form.default_currency || null}
            onChange={(value) => set("default_currency", value)}
            isRequired
            error={errorFor("default_currency")}
          />
          <Select
            label="Stage"
            options={PARTY_STATUSES.map((status) => ({ value: status, label: STAGE_LABEL[status], description: STAGE_HINT[status] }))}
            value={form.status}
            onChange={(value) => set("status", PARTY_STATUSES.find((status) => status === value) ?? form.status)}
            error={errorFor("status")}
          />
          <Select
            label="Customer type"
            optional
            options={[{ value: NO_TYPE, label: "Not set" }, ...CUSTOMER_TYPES.map((type) => ({ value: type, label: TYPE_LABEL[type] ?? type }))]}
            value={form.customer_type ?? NO_TYPE}
            onChange={(value) => set("customer_type", CUSTOMER_TYPES.find((type) => type === value) ?? null)}
            error={errorFor("customer_type")}
          />
        </div>
        <CheckboxGroup
          label="Roles"
          options={PARTY_ROLES.map((role) => ({ value: role, label: ROLE_LABEL[role] }))}
          value={form.roles}
          onChange={(value) => set("roles", PARTY_ROLES.filter((role: PartyRole) => value.includes(role)))}
          error={errorFor("roles")}
        />
      </form>
    </Drawer>
  );
}

/** Add one contact. `PartyUpdate.contacts` replaces the set, so the existing rows travel with the new one. */
export function AddContactModal({ party, isOpen, onOpenChange }: { party: PartyDetail; isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const formId = useId();
  const queryClient = useQueryClient();
  const commands = useResourceCommand(`customer-contact:${party.id}`, invalidationMap["parties.party_changed"]);
  const [form, setForm] = useState<ContactForm>(EMPTY_CONTACT);
  const [submitted, setSubmitted] = useState(false);
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  const set = <K extends keyof ContactForm>(key: K, value: ContactForm[K]) => setForm((current) => ({ ...current, [key]: value }));
  const nameError = submitted && !form.name.trim() ? "Enter the contact's name." : serverErrors["contact.name"];

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    const added = contactRequestOf(form);
    if (!added || commands.pending || commands.offline) return;
    const body = { expected_version: party.version, contacts: contactsWith(party.contacts, added) };
    setServerErrors({});
    const outcome = await commands.run("add_contact", [party.version, JSON.stringify(added)], (key) => updateParty(party.id, body, key), {
      failed: "The contact was not added",
      conflictMessage: "This customer changed since you opened it. The latest version is showing; add the contact again.",
    });
    if (outcome.ok) {
      queryClient.setQueryData(queryKeys.parties.party(party.id), outcome.value);
      toast.success(`${added.name} added`);
      onOpenChange(false);
    } else if (outcome.conflict) {
      onOpenChange(false);
    } else {
      setServerErrors(fieldErrorsFrom(outcome.error));
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      size="sm"
      title="Add a contact"
      description={`A person at ${party.display_name} the team can reach.`}
      actions={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" form={formId} loading={commands.pending === "add_contact"} isDisabled={Boolean(commands.offline)}>
            Add contact
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={(event) => void submit(event)} noValidate className="flex flex-col gap-4">
        <TextField label="Name" value={form.name} onChange={(value) => set("name", value)} maxLength={200} isRequired autoComplete="off" autoFocus error={nameError} />
        <TextField label="Job title" optional value={form.job_title} onChange={(value) => set("job_title", value)} maxLength={120} error={serverErrors["contact.job_title"]} />
        <TextField label="Email" optional type="email" inputMode="email" iconLeft="mail" value={form.email} onChange={(value) => set("email", value)} maxLength={254} error={serverErrors["contact.email"]} />
        <TextField label="Phone" optional type="tel" inputMode="tel" iconLeft="phone" value={form.phone} onChange={(value) => set("phone", value)} maxLength={40} error={serverErrors["contact.phone"]} />
        <Checkbox label="Make this the main contact" description="Shown first on their profile and in the customer list." isSelected={form.is_primary} onChange={(value) => set("is_primary", value)} />
      </form>
    </Modal>
  );
}
