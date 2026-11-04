"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type FormEvent, type ReactNode } from "react";
import { Form, Link as RacLink } from "react-aria-components";
import { RailContent } from "@/components/shell/context-rail";
import { Badge } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/choice";
import { DescriptionList } from "@/components/ui/description-list";
import { Dialog, Drawer } from "@/components/ui/dialog";
import { LocalDateTime, Money, RelativeTime } from "@/components/ui/format";
import { Link, LinkButton } from "@/components/ui/link";
import { MetaDot, RecordHeader } from "@/components/ui/record-header";
import { SectionCard } from "@/components/ui/section-card";
import { Select } from "@/components/ui/select";
import { Conflict, EmptyState, ErrorState, Loading, NotAvailable, PermissionDenied } from "@/components/ui/states";
import { fieldErrorClasses, labelClasses, linkClasses } from "@/components/ui/styles";
import { TextField } from "@/components/ui/text-field";
import { toast } from "@/components/ui/toast";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { VendorItemsSection } from "@/features/procurement/vendor-items";
import { quoteListHref } from "@/features/sales/list-state";
import { QuoteStatusPill } from "@/features/sales/quote-list";
import { problemDescription } from "@/features/sales/use-quote-command";
import { createCommandKeys, commandSignature } from "@/lib/api/command-keys";
import { conflictFromError, ProblemError, type ConflictInfo } from "@/lib/api/errors";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { CURRENCIES } from "@/lib/format/money";
import { formatDayTime } from "@/lib/format/time";
import { useOnline } from "@/lib/hooks";
import { useRecentRecord } from "@/lib/recent/recent-records";
import { useNow, useSession, useZone } from "@/lib/session/context";
import { briefingMessages } from "@/messages/briefing";
import { partiesMessages as m } from "@/messages/parties";
import { setPartyArchived } from "./customer-types-api";
import { fetchParty, fetchPartyQuotes, PARTY_QUOTES_SHOWN, partyQuotesParams, updateParty } from "./api";
import {
  addressLines,
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
} from "./form-model";
import { PartyStatusPill } from "./party-list";
import { CUSTOMER_TYPES, PARTY_ROLES, PARTY_STATUSES, type Address, type PartyDetail as Party, type PartyHeaderFields, type PartyRole } from "./types";

const FIELD_LABELS: Record<HeaderField, string> = {
  legal_name: m.edit.legalName,
  display_name: m.edit.displayName,
  country_code: m.edit.countryCode,
  default_currency: m.edit.currency,
  customer_type: m.edit.customerType,
  status: m.edit.status,
  roles: m.edit.roles,
};

/** The customer record. 404 and out-of-scope records are the same "not available" state on purpose. */
export function PartyDetail({ partyId }: { partyId: string }) {
  const query = useQuery({ queryKey: queryKeys.parties.party(partyId), queryFn: ({ signal }) => fetchParty(partyId, signal) });
  useRecentRecord("parties.party", query.data?.id, query.isSuccess);
  if (query.isPending) return <Loading label={m.detail.loading} variant="detail" />;
  if (query.isError) {
    const error = query.error;
    if (error instanceof ProblemError && error.status === 404) return <NotAvailable />;
    if (error instanceof ProblemError && error.status === 403) return <PermissionDenied area={m.permission.area} />;
    return <ErrorState error={error} what={m.detail.loading} onRetry={() => void query.refetch()} />;
  }
  return <Record party={query.data} />;
}

function Record({ party }: { party: Party }) {
  const { permissionKeys } = useSession();
  const [editing, setEditing] = useState(false);
  const [addingContact, setAddingContact] = useState(false);
  const canUpdate = party.capabilities.update?.allowed === true;
  const canArchive = party.capabilities.archive?.allowed === true;
  const canRestore = party.capabilities.restore?.allowed === true;
  const queryClient = useQueryClient();
  // catalogue lane (Slice 2): archive and restore, offered only when the server allows them
  const archive = useMutation({
    mutationFn: (archived: boolean) => setPartyArchived(party.id, archived, party.version),
    onSuccess: (_result, archived) => {
      for (const key of invalidationMap["parties.party_changed"]) void queryClient.invalidateQueries({ queryKey: key });
      toast.success(archived ? m.detail.archivedToast : m.detail.restoredToast);
    },
    onError: (error) => toast.error(conflictFromError(error) ? m.detail.archiveConflict : m.detail.archiveFailed),
  });
  const canReadQuotes = permissionKeys.has("sales.quote.read");

  useScreenContribution({ focus: { type: "parties.party", id: party.id, version: party.version } });

  const meta: ReactNode[] = [
    party.legal_name !== party.display_name ? party.legal_name : null,
    party.country_code || null,
    party.default_currency || null,
    party.customer_type ? m.customerTypes[party.customer_type] ?? party.customer_type : null,
    party.owner.display_name,
    party.roles.length ? party.roles.map((role) => m.roles[role] ?? role).join(", ") : null,
  ].filter((fact): fact is string => typeof fact === "string" && fact !== "");

  return (
    <div className="flex flex-col gap-8">
      <RecordHeader
        back={{ href: "/sales/parties", label: m.detail.back }}
        recordKey={party.party_number}
        title={party.display_name}
        status={
          <span className="flex flex-wrap items-center gap-2">
            <PartyStatusPill status={party.status} />
            {party.archived_at ? <Badge>{m.detail.archived}</Badge> : null}
          </span>
        }
        meta={meta.map((fact, index) => (
          <span key={`${index}-${fact}`} className="inline-flex items-center gap-2">
            {index > 0 ? <MetaDot /> : null}
            <span>{fact}</span>
          </span>
        ))}
        actions={
          canUpdate || canArchive || canRestore ? (
            <>
              {canUpdate ? (
                <Button variant="secondary" onPress={() => setEditing(true)}>
                  {m.detail.edit}
                </Button>
              ) : null}
              {canArchive ? (
                <Button variant="danger" onPress={() => archive.mutate(true)} isPending={archive.isPending}>
                  {m.detail.archive}
                </Button>
              ) : null}
              {canRestore ? (
                <Button onPress={() => archive.mutate(false)} isPending={archive.isPending}>
                  {m.detail.restore}
                </Button>
              ) : null}
            </>
          ) : null
        }
      />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Contacts party={party} canUpdate={canUpdate} onAdd={() => setAddingContact(true)} />
        <Addresses addresses={party.addresses} />
        <TaxIdentifiers party={party} />
        {canReadQuotes ? <Quotes party={party} /> : null}
      </div>
      {/* procurement lane (Slice 4): vendor items on a vendor's record */}
      {party.roles.includes("vendor") && permissionKeys.has("procurement.vendor_item.read") ? (
        <VendorItemsSection vendorId={party.id} defaultCurrency={party.default_currency || null} />
      ) : null}

      <RailContent>
        <PartyContext party={party} />
      </RailContent>

      {canUpdate ? (
        <Drawer title={m.edit.title} description={`${party.party_number} · ${party.display_name}`} isOpen={editing} onOpenChange={setEditing}>
          {(close) => <EditPartyForm party={party} onDone={close} />}
        </Drawer>
      ) : null}
      {canUpdate ? (
        <Dialog title={m.contact.title} description={party.display_name} size="sm" isOpen={addingContact} onOpenChange={setAddingContact}>
          {(close) => <AddContactForm party={party} onDone={close} />}
        </Dialog>
      ) : null}
    </div>
  );
}

// ---- sections ----------------------------------------------------------------------------------

function Contacts({ party, canUpdate, onAdd }: { party: Party; canUpdate: boolean; onAdd: () => void }) {
  const sorted = [...party.contacts].sort((a, b) => (a.is_primary === b.is_primary ? a.name.localeCompare(b.name) : a.is_primary ? -1 : 1));
  return (
    <SectionCard
      title={m.detail.contacts}
      actions={
        canUpdate ? (
          <Button size="sm" onPress={onAdd}>
            {m.detail.addContact}
          </Button>
        ) : null
      }
    >
      {sorted.length === 0 ? (
        <EmptyState title={m.detail.noContacts} headingLevel={3}>
          {m.detail.noContactsHint}
        </EmptyState>
      ) : (
        <ul className="flex flex-col divide-y">
          {sorted.map((contact) => (
            <li key={contact.id} className="flex flex-col gap-1 py-3 first:pt-0 last:pb-0">
              <p className="flex flex-wrap items-center gap-2">
                <span className="font-semibold text-ink">{contact.name}</span>
                {contact.is_primary ? <Badge tone="forest">{m.detail.primary}</Badge> : null}
              </p>
              {contact.job_title ? <p className="text-sm text-ink-muted">{contact.job_title}</p> : null}
              {contact.email || contact.phone ? (
                <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm [overflow-wrap:anywhere]">
                  {contact.email ? (
                    <a href={`mailto:${contact.email}`} className={linkClasses}>
                      {contact.email}
                    </a>
                  ) : null}
                  {contact.phone ? (
                    <a href={`tel:${contact.phone.replace(/[^\d+]/g, "")}`} className={linkClasses}>
                      {contact.phone}
                    </a>
                  ) : null}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </SectionCard>
  );
}

function AddressBlock({ address }: { address: Address }) {
  return (
    <div className="flex flex-col gap-1">
      <address className="text-ink not-italic [overflow-wrap:anywhere]">
        {addressLines(address).map((line, index) => (
          <span key={`${index}-${line}`} className="block">
            {line}
          </span>
        ))}
      </address>
      {address.is_default ? (
        <span>
          <Badge tone="forest">{m.detail.default}</Badge>
        </span>
      ) : null}
    </div>
  );
}

function Addresses({ addresses }: { addresses: readonly Address[] }) {
  const groups = (["billing", "shipping"] as const)
    .map((kind) => ({ kind, items: addresses.filter((address) => address.kind === kind).sort((a, b) => (a.is_default === b.is_default ? 0 : a.is_default ? -1 : 1)) }))
    .filter((group) => group.items.length > 0);
  return (
    <SectionCard title={m.detail.addresses}>
      {groups.length === 0 ? (
        <EmptyState title={m.detail.noAddresses} headingLevel={3}>
          {m.detail.noAddressesHint}
        </EmptyState>
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
          {groups.map((group) => (
            <section key={group.kind} aria-label={group.kind === "billing" ? m.detail.billing : m.detail.shipping} className="flex flex-col gap-3">
              <h3 className="text-sm font-semibold text-ink-muted">{group.kind === "billing" ? m.detail.billing : m.detail.shipping}</h3>
              {group.items.map((address) => (
                <AddressBlock key={address.id} address={address} />
              ))}
            </section>
          ))}
        </div>
      )}
    </SectionCard>
  );
}

function TaxIdentifiers({ party }: { party: Party }) {
  return (
    <SectionCard title={m.detail.taxIdentifiers}>
      {party.tax_identifiers.length === 0 ? (
        <p className="text-ink-muted">{m.detail.noTaxIdentifiers}</p>
      ) : (
        <ul className="flex flex-col divide-y">
          {party.tax_identifiers.map((identifier) => (
            <li key={identifier.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-3 first:pt-0 last:pb-0">
              <span className="text-sm font-semibold text-ink uppercase">{m.schemes[identifier.scheme] ?? identifier.scheme.toUpperCase()}</span>
              <span className="font-mono text-ink [overflow-wrap:anywhere]">{identifier.value}</span>
              {identifier.country_code ? <span className="text-sm text-ink-muted">{identifier.country_code}</span> : null}
              <Badge>{m.detail.unverified}</Badge>
            </li>
          ))}
        </ul>
      )}
    </SectionCard>
  );
}

function Quotes({ party }: { party: Party }) {
  const { permissionKeys } = useSession();
  const params = partyQuotesParams(party.id);
  // Under the sales/quotes prefix so every quote command's invalidation refreshes it.
  const query = useQuery({ queryKey: ["sales", "quotes", { party_id: party.id, scope: params.scope }] as const, queryFn: ({ signal }) => fetchPartyQuotes(party.id, signal) });
  const allHref = quoteListHref({ q: party.display_name, scope: "all" });
  const canCreate = permissionKeys.has("sales.quote.create");
  return (
    <SectionCard
      title={m.detail.quotes}
      actions={
        canCreate ? (
          <LinkButton href="/sales/quotes/new" size="sm">
            {m.detail.newQuote}
          </LinkButton>
        ) : null
      }
    >
      {query.isPending ? (
        <Loading label={m.detail.quotesLoading} variant="inline" />
      ) : query.isError ? (
        <ErrorState error={query.error} what={m.detail.quotesLoading} onRetry={() => void query.refetch()} backToToday={false} headingLevel={3} compact />
      ) : query.data.items.length === 0 ? (
        <p className="text-ink-muted">{m.detail.noQuotes}</p>
      ) : (
        <>
          <ul aria-label={m.detail.quotes} className="flex flex-col divide-y">
            {query.data.items.slice(0, PARTY_QUOTES_SHOWN).map((quote) => (
              <li key={quote.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-3 first:pt-0 last:pb-0">
                <RacLink href={quote.path} className={`${linkClasses} font-mono`}>
                  {quote.quote_number}
                </RacLink>
                <span className="flex flex-wrap items-center gap-x-4 gap-y-1">
                  <QuoteStatusPill status={quote.status} />
                  <Money value={quote.grand_total} />
                </span>
              </li>
            ))}
          </ul>
          <Link href={allHref} className="self-start text-sm">
            {m.detail.allQuotes}
          </Link>
        </>
      )}
    </SectionCard>
  );
}

function PartyContext({ party }: { party: Party }) {
  const primary = party.contacts.find((contact) => contact.is_primary) ?? null;
  return (
    <div className="flex flex-col gap-4 text-sm">
      <h2 className="text-base font-[650] text-ink">{m.detail.context}</h2>
      <DescriptionList
        items={[
          { term: m.detail.number, description: <span className="font-mono">{party.party_number}</span> },
          { term: m.detail.owner, description: party.owner.display_name ?? m.detail.noOwner },
          { term: m.detail.created, description: <LocalDateTime value={party.created_at} /> },
          { term: m.detail.updated, description: <RelativeTime value={party.updated_at} /> },
          ...(primary || party.primary_contact
            ? [{ term: m.detail.primaryContact, description: primary ? [primary.name, primary.email].filter(Boolean).join(" · ") : party.primary_contact! }]
            : []),
        ]}
      />
    </div>
  );
}

// ---- the Edit drawer --------------------------------------------------------------------------

/** A labelled group of role checkboxes; at least one must stay selected. */
function RolesField({ value, onChange, error, label = m.edit.roles }: { value: readonly PartyRole[]; onChange: (roles: PartyRole[]) => void; error?: string; label?: string }) {
  const errorId = useId();
  return (
    <fieldset className="flex flex-col gap-1.5" aria-describedby={error ? errorId : undefined} aria-invalid={error ? true : undefined}>
      <legend className={labelClasses}>{label}</legend>
      <div className="flex flex-wrap gap-x-6">
        {PARTY_ROLES.map((role) => (
          <Checkbox
            key={role}
            isSelected={value.includes(role)}
            onChange={(selected) => onChange(PARTY_ROLES.filter((known) => (known === role ? selected : value.includes(known))))}
          >
            {m.roles[role] ?? role}
          </Checkbox>
        ))}
      </div>
      {error ? (
        <p id={errorId} className={fieldErrorClasses}>
          {error}
        </p>
      ) : null}
    </fieldset>
  );
}

function EditPartyForm({ party, onDone }: { party: Party; onDone: () => void }) {
  const queryClient = useQueryClient();
  const online = useOnline();
  const zone = useZone();
  const now = useNow();
  const [commandKeys] = useState(() => createCommandKeys());
  const [base, setBase] = useState<PartyHeaderFields>(() => headerFormOf(party));
  const [form, setForm] = useState<PartyHeaderFields>(() => headerFormOf(party));
  const [version, setVersion] = useState(party.version);
  const [submitted, setSubmitted] = useState(false);
  const [pending, setPending] = useState(false);
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  const [conflict, setConflict] = useState<ConflictInfo | null>(null);
  const offline = online ? null : briefingMessages.offlineActions;
  const errors: Record<string, string | undefined> = { ...(submitted ? validateHeader(form) : {}), ...serverErrors };
  const dirty = dirtyHeaderFields(base, form);
  const set = <K extends keyof PartyHeaderFields>(key: K, value: PartyHeaderFields[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
    setServerErrors((current) => (current[key] ? { ...current, [key]: "" } : current));
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (pending || offline) return;
    if (dirty.length === 0) {
      toast.info(m.edit.noChanges);
      return;
    }
    if (Object.keys(validateHeader(form)).length > 0) return;
    const changes = headerChanges(base, form);
    const signature = commandSignature(party.id, version, "update", JSON.stringify(changes));
    const attempt = commandKeys.attempt(signature, () => ({ expected_version: version, ...changes }));
    setPending(true);
    setServerErrors({});
    try {
      const updated = await updateParty(party.id, attempt.payload, attempt.key);
      commandKeys.settle(signature);
      queryClient.setQueryData(queryKeys.parties.party(party.id), updated);
      await Promise.all(invalidationMap["parties.party_changed"].map((queryKey) => queryClient.invalidateQueries({ queryKey })));
      toast.success(m.edit.saved);
      onDone();
    } catch (error) {
      commandKeys.settle(signature, error);
      const info = conflictFromError(error);
      if (info) setConflict(info);
      else {
        if (error instanceof ProblemError && error.status === 422) setServerErrors(fieldErrorsFrom(error));
        toast.error(m.edit.failed, { description: problemDescription(error) });
      }
    } finally {
      setPending(false);
    }
  };

  /** "Review latest version": reload, take over their changes where this person made none, keep the rest. */
  const review = async () => {
    try {
      const latest = await queryClient.fetchQuery({ queryKey: queryKeys.parties.party(party.id), queryFn: ({ signal }) => fetchParty(party.id, signal), staleTime: 0 });
      const merge = mergeHeaderConflict(base, form, headerFormOf(latest));
      setBase(merge.base);
      setForm(merge.form);
      setVersion(latest.version);
      setConflict(null);
      toast.info(merge.adopted.length ? m.edit.conflictMerged(merge.adopted.map((field) => FIELD_LABELS[field]).join(", ")) : m.edit.conflictNone);
    } catch (error) {
      toast.error(m.edit.failed, { description: problemDescription(error) });
    }
  };

  return (
    <Form onSubmit={submit} validationBehavior="aria" className="flex flex-col gap-5">
      {conflict ? <Conflict conflict={conflict} changedAtLabel={conflict.changedAt && now ? formatDayTime(conflict.changedAt, now, zone) : null} onReview={() => void review()} /> : null}
      <TextField label={m.edit.legalName} value={form.legal_name} onChange={(value) => set("legal_name", value)} maxLength={200} isRequired errorMessage={errors.legal_name || undefined} />
      <TextField label={m.edit.displayName} description={m.edit.displayNameHint} value={form.display_name} onChange={(value) => set("display_name", value)} maxLength={200} errorMessage={errors.display_name || undefined} />
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
        <TextField
          label={m.edit.countryCode}
          description={m.edit.countryCodeHint}
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
          label={m.edit.currency}
          options={CURRENCIES.map((code) => ({ id: code, label: code }))}
          value={form.default_currency || null}
          onChange={(value) => set("default_currency", value ?? "")}
          isRequired
          errorMessage={errors.default_currency || undefined}
        />
        <Select
          label={m.edit.customerType}
          options={[{ id: "", label: m.edit.noCustomerType }, ...CUSTOMER_TYPES.map((type) => ({ id: type, label: m.customerTypes[type] ?? type }))]}
          value={form.customer_type ?? ""}
          onChange={(value) => set("customer_type", CUSTOMER_TYPES.find((type) => type === value) ?? null)}
          errorMessage={errors.customer_type || undefined}
        />
        <Select
          label={m.edit.status}
          options={PARTY_STATUSES.map((status) => ({ id: status, label: m.status[status] ?? status }))}
          value={form.status}
          onChange={(value) => set("status", PARTY_STATUSES.find((status) => status === value) ?? form.status)}
          errorMessage={errors.status || undefined}
        />
      </div>
      <RolesField value={form.roles} onChange={(roles) => set("roles", roles)} error={errors.roles || undefined} />
      <div className="flex flex-wrap justify-end gap-2 border-t pt-4">
        <Button variant="secondary" onPress={onDone}>
          {m.edit.cancel}
        </Button>
        <Button type="submit" variant="primary" isPending={pending} pendingLabel={m.edit.saving} {...unavailableWhen(offline)}>
          {m.edit.save}
        </Button>
      </div>
    </Form>
  );
}

// ---- Add contact --------------------------------------------------------------------------------

function AddContactForm({ party, onDone }: { party: Party; onDone: () => void }) {
  const queryClient = useQueryClient();
  const online = useOnline();
  const [commandKeys] = useState(() => createCommandKeys());
  const [form, setForm] = useState<ContactForm>(EMPTY_CONTACT);
  const [submitted, setSubmitted] = useState(false);
  const [pending, setPending] = useState(false);
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  const offline = online ? null : briefingMessages.offlineActions;
  const set = <K extends keyof ContactForm>(key: K, value: ContactForm[K]) => setForm((current) => ({ ...current, [key]: value }));
  const nameError = submitted && !form.name.trim() ? m.contact.nameRequired : serverErrors["contact.name"];

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    const added = contactRequestOf(form);
    if (!added || pending || offline) return;
    const body = { expected_version: party.version, contacts: contactsWith(party.contacts, added) };
    const signature = commandSignature(party.id, party.version, "add_contact", JSON.stringify(added));
    const attempt = commandKeys.attempt(signature, () => body);
    setPending(true);
    setServerErrors({});
    try {
      const updated = await updateParty(party.id, attempt.payload, attempt.key);
      commandKeys.settle(signature);
      queryClient.setQueryData(queryKeys.parties.party(party.id), updated);
      await Promise.all(invalidationMap["parties.party_changed"].map((queryKey) => queryClient.invalidateQueries({ queryKey })));
      toast.success(m.contact.added);
      onDone();
    } catch (error) {
      commandKeys.settle(signature, error);
      if (conflictFromError(error)) {
        await queryClient.invalidateQueries({ queryKey: queryKeys.parties.party(party.id) });
        toast.warning(m.contact.changed);
        onDone();
      } else {
        if (error instanceof ProblemError && error.status === 422) setServerErrors(fieldErrorsFrom(error));
        toast.error(m.contact.failed, { description: problemDescription(error) });
      }
    } finally {
      setPending(false);
    }
  };

  return (
    <Form onSubmit={submit} validationBehavior="aria" className="flex flex-col gap-4">
      <TextField label={m.contact.name} value={form.name} onChange={(value) => set("name", value)} maxLength={200} isRequired autoComplete="off" errorMessage={nameError} />
      <TextField label={m.contact.jobTitle} value={form.job_title} onChange={(value) => set("job_title", value)} maxLength={120} errorMessage={serverErrors["contact.job_title"]} />
      <TextField label={m.contact.email} type="email" inputMode="email" value={form.email} onChange={(value) => set("email", value)} maxLength={254} errorMessage={serverErrors["contact.email"]} />
      <TextField label={m.contact.phone} type="tel" inputMode="tel" value={form.phone} onChange={(value) => set("phone", value)} maxLength={40} errorMessage={serverErrors["contact.phone"]} />
      <Checkbox isSelected={form.is_primary} onChange={(value) => set("is_primary", value)}>
        {m.contact.isPrimary}
      </Checkbox>
      <div className="flex flex-wrap justify-end gap-2 border-t pt-4">
        <Button variant="secondary" onPress={onDone}>
          {m.contact.cancel}
        </Button>
        <Button type="submit" variant="primary" isPending={pending} pendingLabel={m.contact.adding} {...unavailableWhen(offline)}>
          {m.contact.add}
        </Button>
      </div>
    </Form>
  );
}
