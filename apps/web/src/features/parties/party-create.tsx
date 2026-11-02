"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Form } from "react-aria-components";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/choice";
import { ErrorIcon } from "@/components/ui/icons";
import { PageHeader } from "@/components/ui/page-header";
import { Select } from "@/components/ui/select";
import { PermissionDenied } from "@/components/ui/states";
import { fieldErrorClasses, labelClasses } from "@/components/ui/styles";
import { TextField } from "@/components/ui/text-field";
import { toast } from "@/components/ui/toast";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { problemDescription } from "@/features/sales/use-quote-command";
import { createCommandKeys, commandSignature } from "@/lib/api/command-keys";
import { ProblemError } from "@/lib/api/errors";
import { invalidationMap } from "@/lib/api/query-keys";
import { CURRENCIES } from "@/lib/format/money";
import { useOnline } from "@/lib/hooks";
import { useSession } from "@/lib/session/context";
import { briefingMessages } from "@/messages/briefing";
import { partiesMessages as m } from "@/messages/parties";
import { createParty } from "./api";
import { createBodyOf, EMPTY_CREATE, errorSummary, fieldErrorsFrom, normaliseCountry, validateCreate, type CreateForm } from "./form-model";
import { CUSTOMER_TYPES, PARTY_ROLES, PARTY_STATUSES, type PartyRole } from "./types";

/** New customer. Without `parties.party.create` the page explains the missing access and shows no form. */
export function PartyCreate() {
  const { permissionKeys } = useSession();
  if (!permissionKeys.has("parties.party.create")) return <PermissionDenied area={m.permission.area} />;
  return <CreateForm />;
}

function Fieldset({ legend, children, className }: { legend: string; children: ReactNode; className?: string }) {
  return (
    <fieldset className={`flex flex-col gap-5 ${className ?? ""}`}>
      <legend className="mb-3 text-lg font-[650] text-ink">{legend}</legend>
      {children}
    </fieldset>
  );
}

function CreateForm() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const online = useOnline();
  const [form, setForm] = useState<CreateForm>(EMPTY_CREATE);
  const [submitted, setSubmitted] = useState(false);
  const [pending, setPending] = useState(false);
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  const [commandKeys] = useState(() => createCommandKeys());
  const alertRef = useRef<HTMLDivElement>(null);
  const alertId = useId();
  const rolesErrorId = useId();
  const offline = online ? null : briefingMessages.offlineActions;
  const errors: Record<string, string> = { ...(submitted ? validateCreate(form) : {}), ...serverErrors };
  const summary = errorSummary(errors, m.create.fieldLabels).filter((entry) => entry.message);
  const set = <K extends keyof CreateForm>(key: K, value: CreateForm[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
    if (serverErrors[key]) setServerErrors((current) => ({ ...current, [key]: "" }));
  };
  const setContact = (key: keyof CreateForm["contact"], value: string) => {
    setForm((current) => ({ ...current, contact: { ...current.contact, [key]: value } }));
    if (serverErrors[`contact.${key}`]) setServerErrors((current) => ({ ...current, [`contact.${key}`]: "" }));
  };
  const setAddress = (key: keyof CreateForm["address"], value: string) => {
    setForm((current) => ({ ...current, address: { ...current.address, [key]: value } }));
    if (serverErrors[`address.${key}`]) setServerErrors((current) => ({ ...current, [`address.${key}`]: "" }));
  };
  const focusAlert = () => window.requestAnimationFrame(() => alertRef.current?.focus());

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
    if (pending || offline) return;
    const body = createBodyOf(form);
    if (!body) {
      focusAlert();
      return;
    }
    // The key is minted at the first press and kept until the server has created the customer, so a
    // retry of the same form (after a timeout or a server error) is replayed rather than duplicated.
    const signature = commandSignature("create_party", JSON.stringify(body));
    const attempt = commandKeys.attempt(signature, () => body);
    setPending(true);
    setServerErrors({});
    try {
      const party = await createParty(attempt.payload, attempt.key);
      commandKeys.settle(signature);
      await Promise.all(invalidationMap["parties.party_changed"].map((queryKey) => queryClient.invalidateQueries({ queryKey })));
      toast.success(m.create.created(party.party_number));
      router.push(party.path as Parameters<typeof router.push>[0]);
    } catch (error) {
      if (error instanceof ProblemError && error.status === 422) {
        commandKeys.settle(signature, error);
        setServerErrors(fieldErrorsFrom(error));
        focusAlert();
      }
      toast.error(m.create.failed, { description: problemDescription(error) });
    } finally {
      setPending(false);
    }
  };

  const toggleRole = (role: PartyRole, selected: boolean) => set("roles", selected ? [...new Set([...form.roles, role])] : form.roles.filter((r) => r !== role));

  return (
    <div className="flex max-w-2xl flex-col gap-6">
      <PageHeader eyebrow={m.area} title={m.create.title} intro={m.create.intro} />
      <Form onSubmit={submit} validationBehavior="aria" className="flex flex-col gap-8" aria-describedby={summary.length ? alertId : undefined}>
        {summary.length ? (
          <div id={alertId} ref={alertRef} tabIndex={-1} role="alert" className="flex gap-3 rounded-lg border border-danger bg-danger-bg p-3 text-danger outline-hidden">
            <ErrorIcon className="mt-0.5 shrink-0" />
            <div className="flex flex-col gap-1">
              <p className="font-semibold">{m.create.errorsTitle}</p>
              <ul className="flex flex-col gap-0.5 text-sm">
                {summary.map((entry) => (
                  <li key={entry.label}>
                    <span className="font-medium">{entry.label}:</span> {entry.message}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        ) : null}

        <Fieldset legend={m.create.company}>
          <TextField label={m.create.legalName} value={form.legal_name} onChange={(value) => set("legal_name", value)} maxLength={200} isRequired autoComplete="organization" errorMessage={errors.legal_name || undefined} />
          <TextField label={m.create.displayName} description={m.create.displayNameHint} value={form.display_name} onChange={(value) => set("display_name", value)} maxLength={200} errorMessage={errors.display_name || undefined} />
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            <TextField
              label={m.create.countryCode}
              description={m.create.countryCodeHint}
              value={form.country_code}
              onChange={(value) => set("country_code", value)}
              onBlur={() => set("country_code", normaliseCountry(form.country_code))}
              maxLength={2}
              autoComplete="country"
              inputClassName="font-mono uppercase"
              isRequired
              errorMessage={errors.country_code || undefined}
            />
            <Select
              label={m.create.currency}
              placeholder={m.create.currencyPlaceholder}
              options={CURRENCIES.map((code) => ({ id: code, label: code }))}
              value={form.default_currency}
              onChange={(value) => set("default_currency", value)}
              isRequired
              errorMessage={errors.default_currency || undefined}
            />
            <Select
              label={m.create.customerType}
              options={[{ id: "", label: m.create.noCustomerType }, ...CUSTOMER_TYPES.map((type) => ({ id: type, label: m.customerTypes[type] ?? type }))]}
              value={form.customer_type ?? ""}
              onChange={(value) => set("customer_type", CUSTOMER_TYPES.find((type) => type === value) ?? null)}
              errorMessage={errors.customer_type || undefined}
            />
            <Select
              label={m.create.status}
              options={PARTY_STATUSES.map((status) => ({ id: status, label: m.status[status] ?? status }))}
              value={form.status}
              onChange={(value) => set("status", PARTY_STATUSES.find((status) => status === value) ?? "active")}
              errorMessage={errors.status || undefined}
            />
          </div>
          <fieldset className="flex flex-col gap-1.5" aria-describedby={errors.roles ? rolesErrorId : undefined} aria-invalid={errors.roles ? true : undefined}>
            <legend className={labelClasses}>{m.create.roles}</legend>
            <div className="flex flex-wrap gap-x-6">
              {PARTY_ROLES.map((role) => (
                <Checkbox key={role} isSelected={form.roles.includes(role)} onChange={(selected) => toggleRole(role, selected)}>
                  {m.roles[role] ?? role}
                </Checkbox>
              ))}
            </div>
            {errors.roles ? (
              <p id={rolesErrorId} className={fieldErrorClasses}>
                {errors.roles}
              </p>
            ) : null}
          </fieldset>
        </Fieldset>

        <Fieldset legend={m.create.contact}>
          <TextField label={m.create.contactName} value={form.contact.name} onChange={(value) => setContact("name", value)} maxLength={200} autoComplete="off" errorMessage={errors["contact.name"] || undefined} />
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            <TextField label={m.create.contactEmail} type="email" inputMode="email" value={form.contact.email} onChange={(value) => setContact("email", value)} maxLength={254} errorMessage={errors["contact.email"] || undefined} />
            <TextField label={m.create.contactPhone} type="tel" inputMode="tel" value={form.contact.phone} onChange={(value) => setContact("phone", value)} maxLength={40} errorMessage={errors["contact.phone"] || undefined} />
          </div>
        </Fieldset>

        <Fieldset legend={m.create.address}>
          <TextField label={m.create.line1} value={form.address.line1} onChange={(value) => setAddress("line1", value)} maxLength={200} autoComplete="address-line1" errorMessage={errors["address.line1"] || undefined} />
          <TextField label={m.create.line2} value={form.address.line2} onChange={(value) => setAddress("line2", value)} maxLength={200} autoComplete="address-line2" errorMessage={errors["address.line2"] || undefined} />
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            <TextField label={m.create.city} value={form.address.city} onChange={(value) => setAddress("city", value)} maxLength={120} autoComplete="address-level2" errorMessage={errors["address.city"] || undefined} />
            <TextField label={m.create.region} value={form.address.region} onChange={(value) => setAddress("region", value)} maxLength={120} autoComplete="address-level1" errorMessage={errors["address.region"] || undefined} />
            <TextField label={m.create.postalCode} value={form.address.postal_code} onChange={(value) => setAddress("postal_code", value)} maxLength={20} autoComplete="postal-code" errorMessage={errors["address.postal_code"] || undefined} />
            <TextField
              label={m.create.addressCountry}
              description={m.create.countryCodeHint}
              value={form.address.country_code}
              placeholder={normaliseCountry(form.country_code) || undefined}
              onChange={(value) => setAddress("country_code", value)}
              onBlur={() => setAddress("country_code", normaliseCountry(form.address.country_code))}
              maxLength={2}
              inputClassName="font-mono uppercase"
              errorMessage={errors["address.country_code"] || undefined}
            />
          </div>
        </Fieldset>

        <div>
          <Button type="submit" variant="primary" isPending={pending} pendingLabel={m.create.creating} {...unavailableWhen(offline)}>
            {m.create.submit}
          </Button>
        </div>
      </Form>
    </div>
  );
}
