"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Link as RacLink } from "react-aria-components";
import { StatusPill } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/choice";
import { DataTable, OffsetPagination, type DataTableColumn } from "@/components/ui/data-table";
import { DescriptionList } from "@/components/ui/description-list";
import { Dialog } from "@/components/ui/dialog";
import { RelativeTime } from "@/components/ui/format";
import { Link, LinkButton } from "@/components/ui/link";
import { SearchField } from "@/components/ui/search-field";
import { Select } from "@/components/ui/select";
import { Conflict, EmptyState, ErrorState, Loading, PermissionDenied } from "@/components/ui/states";
import { linkClasses } from "@/components/ui/styles";
import { TextField } from "@/components/ui/text-field";
import { toast } from "@/components/ui/toast";
import { uuidv7 } from "@/lib/api/client";
import { ProblemError, conflictFromError } from "@/lib/api/errors";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import { fieldErrors } from "@/features/catalogue/api";
import {
  CURRENCIES,
  PARTY_ROLES,
  PARTY_STATUSES,
  createCustomerType,
  createParty,
  fetchCustomerTypes,
  fetchParties,
  fetchParty,
  partyListHref,
  partyPatch,
  setPartyArchived,
  updateCustomerType,
  updateParty,
  type AddressRead,
  type ContactRead,
  type CustomerTypeRead,
  type PartyDetail,
  type PartyListState,
  type PartySummary,
} from "./api";

const ROLE_LABEL: Record<string, string> = { customer: "Customer", vendor: "Vendor", fabricator: "Fabricator", job_worker: "Job worker" };

function useCustomerTypes() {
  return useQuery({ queryKey: queryKeys.parties.customerTypes(), queryFn: ({ signal }) => fetchCustomerTypes(signal) });
}

const partyColumns = (types: Map<string, string>): DataTableColumn<PartySummary>[] => [
  {
    id: "number",
    header: "Number",
    isRowHeader: true,
    mobile: "title",
    mobileCell: (p) => p.display_name,
    cell: (p) => (
      <RacLink href={p.path} className={`${linkClasses} font-mono`}>
        {p.party_number}
      </RacLink>
    ),
  },
  { id: "name", header: "Name", mobile: "key", cell: (p) => p.display_name },
  { id: "country", header: "Country", cell: (p) => p.country_code },
  { id: "type", header: "Customer type", cell: (p) => (p.customer_type ? (types.get(p.customer_type) ?? p.customer_type) : "—") },
  { id: "roles", header: "Roles", cell: (p) => p.roles.map((r) => ROLE_LABEL[r] ?? r).join(", ") },
  { id: "contact", header: "Contact", cell: (p) => p.primary_contact ?? "—" },
  { id: "owner", header: "Owner", mobile: "meta", cell: (p) => p.owner.display_name ?? "—" },
  { id: "status", header: "Status", mobile: "status", cell: (p) => <StatusPill tone={p.status === "active" ? "success" : "neutral"}>{p.status}</StatusPill> },
  { id: "updated", header: "Updated", cell: (p) => <RelativeTime value={p.updated_at} className="text-ink-muted" /> },
];

/** Party list (GAP-01): scoped by the server (own/team/branch/company), filters in the URL, phone card list. */
export function PartyList({ state }: { state: PartyListState }) {
  const router = useRouter();
  const { permissionKeys } = useSession();
  const types = useCustomerTypes();
  const parties = useQuery({
    queryKey: queryKeys.parties.list({ q: state.q, role: state.role, type: state.customerType, archived: state.archived, offset: state.offset }),
    queryFn: ({ signal }) => fetchParties(state, signal),
  });
  const [creating, setCreating] = useState(false);
  if (!permissionKeys.has("parties.party.read")) return <PermissionDenied area="Customers and suppliers" />;
  const go = (next: Partial<PartyListState>) => router.push(partyListHref({ ...state, offset: 0, ...next }) as Parameters<typeof router.push>[0]);
  const typeLabels = new Map((types.data ?? []).map((t) => [t.code, t.label]));
  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">Customers and suppliers</h1>
        <div className="flex flex-wrap gap-2">
          <LinkButton href="/settings/customer-types" variant="quiet">
            Customer types
          </LinkButton>
          {permissionKeys.has("parties.party.create") ? (
            <Button variant="primary" onPress={() => setCreating(true)}>
              New party
            </Button>
          ) : null}
        </div>
      </header>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end">
        <SearchField label="Search" placeholder="Number, name or contact" defaultValue={state.q} onSubmit={(q) => go({ q })} onClear={() => go({ q: "" })} />
        <Select label="Role" options={[{ id: "", label: "Any role" }, ...PARTY_ROLES.map((r) => ({ id: r, label: ROLE_LABEL[r]! }))]} value={state.role ?? ""} onChange={(v) => go({ role: v || null })} />
        <Select
          label="Customer type"
          options={[{ id: "", label: "Any type" }, ...(types.data ?? []).map((t) => ({ id: t.code, label: t.label }))]}
          value={state.customerType ?? ""}
          onChange={(v) => go({ customerType: v || null })}
        />
        <Checkbox isSelected={state.archived} onChange={(archived) => go({ archived })}>
          Include archived
        </Checkbox>
      </div>
      {parties.isPending ? (
        <Loading label="parties" />
      ) : parties.isError ? (
        <ErrorState error={parties.error} what="the parties" onRetry={() => void parties.refetch()} />
      ) : (
        <DataTable
          caption="Parties"
          hideCaption
          columns={partyColumns(typeLabels)}
          rows={parties.data.items}
          rowId={(p) => p.id}
          rowHref={(p) => p.path}
          empty={<EmptyState title="No parties match">Change the filters or add a party.</EmptyState>}
          footer={
            <OffsetPagination label="Party pages" total={parties.data.total} limit={25} offset={parties.data.offset} shown={parties.data.items.length}
              control={(offset) => ({ href: partyListHref({ ...state, offset }) })} />
          }
        />
      )}
      {creating ? <NewPartyDialog types={types.data ?? []} onClose={() => setCreating(false)} /> : null}
    </div>
  );
}

function NewPartyDialog({ types, onClose }: { types: readonly CustomerTypeRead[]; onClose: () => void }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [key] = useState(() => uuidv7());
  const [form, setForm] = useState({ legal_name: "", country_code: "", default_currency: "EUR", customer_type: "", role: "customer" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const create = useMutation({
    mutationFn: () =>
      createParty(
        {
          legal_name: form.legal_name.trim(),
          country_code: form.country_code.trim().toUpperCase(),
          default_currency: form.default_currency,
          roles: [form.role],
          ...(form.customer_type && form.role === "customer" ? { customer_type: form.customer_type } : {}),
        },
        key,
      ),
    onSuccess: (party) => {
      for (const k of invalidationMap["parties.changed"]) void queryClient.invalidateQueries({ queryKey: k });
      toast.success(`${party.party_number} created`);
      router.push(party.path as Parameters<typeof router.push>[0]);
    },
    onError: (error) => setErrors(fieldErrors(error)),
  });
  const set = (name: keyof typeof form, value: string) => setForm((cur) => ({ ...cur, [name]: value }));
  return (
    <Dialog title="New party" isOpen onOpenChange={(open) => (open ? undefined : onClose())}
      footer={(close) => (
        <>
          <Button onPress={close}>Cancel</Button>
          <Button variant="primary" onPress={() => create.mutate()} isPending={create.isPending}>
            Create
          </Button>
        </>
      )}
    >
      <div className="flex flex-col gap-4">
        <TextField label="Legal name" isRequired value={form.legal_name} onChange={(v) => set("legal_name", v)} isInvalid={Boolean(errors.legal_name)} errorMessage={errors.legal_name} />
        <TextField label="Country (2 letters)" isRequired value={form.country_code} onChange={(v) => set("country_code", v)} isInvalid={Boolean(errors.country_code)} errorMessage={errors.country_code} />
        <Select label="Currency" options={CURRENCIES.map((c) => ({ id: c, label: c }))} value={form.default_currency} onChange={(v) => set("default_currency", v ?? "EUR")} />
        <Select label="Role" options={PARTY_ROLES.map((r) => ({ id: r, label: ROLE_LABEL[r]! }))} value={form.role} onChange={(v) => set("role", v ?? "customer")} />
        <Select
          label="Customer type"
          options={[{ id: "", label: "None" }, ...types.filter((t) => t.is_active).map((t) => ({ id: t.code, label: t.label }))]}
          value={form.customer_type}
          onChange={(v) => set("customer_type", v ?? "")}
          isInvalid={Boolean(errors.customer_type)}
          errorMessage={errors.customer_type}
          isDisabled={form.role !== "customer"}
        />
      </div>
    </Dialog>
  );
}

const EMPTY_CONTACT: ContactRead = { name: "", job_title: null, email: null, phone: null, is_primary: false };
const EMPTY_ADDRESS: AddressRead = { kind: "billing", line1: "", line2: null, city: null, region: null, postal_code: null, country_code: "", is_default: true };

function PartyEditor({ party, types, onDone }: { party: PartyDetail; types: readonly CustomerTypeRead[]; onDone: (next: PartyDetail) => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    display_name: party.display_name,
    legal_name: party.legal_name,
    country_code: party.country_code,
    default_currency: party.default_currency,
    customer_type: party.customer_type ?? "",
    status: party.status,
  });
  const [contacts, setContacts] = useState<ContactRead[]>(party.contacts);
  const [addresses, setAddresses] = useState<AddressRead[]>(party.addresses);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: () => updateParty(party.id, partyPatch(party, form, contacts, addresses)),
    onSuccess: onDone,
    onError: (error) => setErrors(fieldErrors(error)),
  });
  const conflict = save.error ? conflictFromError(save.error) : null;
  const set = (name: keyof typeof form, value: string) => setForm((cur) => ({ ...cur, [name]: value }));
  return (
    <form className="flex flex-col gap-6" aria-label="Edit party" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      {conflict ? <Conflict conflict={conflict} onReview={() => void queryClient.invalidateQueries({ queryKey: queryKeys.parties.party(party.id) })} /> : null}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <TextField label="Display name" value={form.display_name} onChange={(v) => set("display_name", v)} isInvalid={Boolean(errors.display_name)} errorMessage={errors.display_name} />
        <TextField label="Legal name" value={form.legal_name} onChange={(v) => set("legal_name", v)} isInvalid={Boolean(errors.legal_name)} errorMessage={errors.legal_name} />
        <TextField label="Country" value={form.country_code} onChange={(v) => set("country_code", v)} isInvalid={Boolean(errors.country_code)} errorMessage={errors.country_code} />
        <Select label="Currency" options={CURRENCIES.map((c) => ({ id: c, label: c }))} value={form.default_currency} onChange={(v) => set("default_currency", v ?? "EUR")} />
        <Select
          label="Customer type"
          options={[{ id: "", label: "None" }, ...types.filter((t) => t.is_active || t.code === party.customer_type).map((t) => ({ id: t.code, label: t.label }))]}
          value={form.customer_type}
          onChange={(v) => set("customer_type", v ?? "")}
          isInvalid={Boolean(errors.customer_type)}
          errorMessage={errors.customer_type}
        />
        <Select label="Status" options={PARTY_STATUSES.map((s) => ({ id: s, label: s }))} value={form.status} onChange={(v) => set("status", v ?? "active")} />
      </div>
      <fieldset className="flex flex-col gap-3">
        <legend className="mb-2 text-base font-semibold">Contacts</legend>
        {contacts.map((c, i) => (
          <div key={c.id ?? `new-${i}`} className="grid grid-cols-1 gap-3 rounded-md border p-3 md:grid-cols-4">
            <TextField label="Name" value={c.name} onChange={(v) => setContacts((cur) => cur.map((x, j) => (j === i ? { ...x, name: v } : x)))} isInvalid={Boolean(errors[`contacts.${i}.name`])} errorMessage={errors[`contacts.${i}.name`]} />
            <TextField label="Email" value={c.email ?? ""} onChange={(v) => setContacts((cur) => cur.map((x, j) => (j === i ? { ...x, email: v } : x)))} isInvalid={Boolean(errors[`contacts.${i}.email`])} errorMessage={errors[`contacts.${i}.email`]} />
            <TextField label="Phone" value={c.phone ?? ""} onChange={(v) => setContacts((cur) => cur.map((x, j) => (j === i ? { ...x, phone: v } : x)))} />
            <div className="flex items-end gap-2">
              <Checkbox isSelected={c.is_primary} onChange={(primary) => setContacts((cur) => cur.map((x, j) => ({ ...x, is_primary: j === i ? primary : primary ? false : x.is_primary })))}>
                Primary
              </Checkbox>
              <Button size="sm" variant="quiet" onPress={() => setContacts((cur) => cur.filter((_, j) => j !== i))}>
                Remove
              </Button>
            </div>
          </div>
        ))}
        <div>
          <Button size="sm" onPress={() => setContacts((cur) => [...cur, { ...EMPTY_CONTACT }])}>
            Add contact
          </Button>
        </div>
      </fieldset>
      <fieldset className="flex flex-col gap-3">
        <legend className="mb-2 text-base font-semibold">Addresses</legend>
        {addresses.map((a, i) => (
          <div key={a.id ?? `new-${i}`} className="grid grid-cols-1 gap-3 rounded-md border p-3 md:grid-cols-3">
            <Select label="Kind" options={[{ id: "billing", label: "Billing" }, { id: "shipping", label: "Shipping" }]} value={a.kind} onChange={(v) => setAddresses((cur) => cur.map((x, j) => (j === i ? { ...x, kind: (v as AddressRead["kind"]) ?? "billing" } : x)))} />
            <TextField label="Line 1" value={a.line1} onChange={(v) => setAddresses((cur) => cur.map((x, j) => (j === i ? { ...x, line1: v } : x)))} isInvalid={Boolean(errors[`addresses.${i}.line1`])} errorMessage={errors[`addresses.${i}.line1`]} />
            <TextField label="City" value={a.city ?? ""} onChange={(v) => setAddresses((cur) => cur.map((x, j) => (j === i ? { ...x, city: v } : x)))} />
            <TextField label="Postal code" value={a.postal_code ?? ""} onChange={(v) => setAddresses((cur) => cur.map((x, j) => (j === i ? { ...x, postal_code: v } : x)))} />
            <TextField label="Country" value={a.country_code} onChange={(v) => setAddresses((cur) => cur.map((x, j) => (j === i ? { ...x, country_code: v.toUpperCase() } : x)))} isInvalid={Boolean(errors[`addresses.${i}.country_code`])} errorMessage={errors[`addresses.${i}.country_code`]} />
            <div className="flex items-end gap-2">
              <Checkbox isSelected={a.is_default} onChange={(d) => setAddresses((cur) => cur.map((x, j) => (j === i ? { ...x, is_default: d } : x)))}>
                Default
              </Checkbox>
              <Button size="sm" variant="quiet" onPress={() => setAddresses((cur) => cur.filter((_, j) => j !== i))}>
                Remove
              </Button>
            </div>
          </div>
        ))}
        <div>
          <Button size="sm" onPress={() => setAddresses((cur) => [...cur, { ...EMPTY_ADDRESS, country_code: party.country_code }])}>
            Add address
          </Button>
        </div>
      </fieldset>
      {errors.contacts || errors.addresses ? <p role="alert" className="text-sm text-danger">{errors.contacts ?? errors.addresses}</p> : null}
      <div className="flex justify-end gap-2">
        <Button onPress={() => onDone(party)}>Cancel</Button>
        <Button type="submit" variant="primary" isPending={save.isPending} pendingLabel="Saving…">
          Save
        </Button>
      </div>
    </form>
  );
}

/** Party detail and edit (GAP-01): header facts, contacts, addresses, archive/restore from the server's capabilities. */
export function PartyDetailView({ partyId }: { partyId: string }) {
  const queryClient = useQueryClient();
  const types = useCustomerTypes();
  const [editing, setEditing] = useState(false);
  const query = useQuery({ queryKey: queryKeys.parties.party(partyId), queryFn: ({ signal }) => fetchParty(partyId, signal) });
  const archive = useMutation({
    mutationFn: (archived: boolean) => setPartyArchived(partyId, archived, query.data?.version ?? 0),
    onSuccess: (next) => {
      queryClient.setQueryData(queryKeys.parties.party(partyId), next);
      for (const k of invalidationMap["parties.changed"]) void queryClient.invalidateQueries({ queryKey: k });
    },
    onError: (error) => toast.error(error instanceof ProblemError ? (error.detail ?? error.title) : "Not saved"),
  });
  if (query.isPending) return <Loading label="party" />;
  if (query.isError) return <ErrorState error={query.error} what="this party" onRetry={() => void query.refetch()} />;
  const party = query.data;
  const typeLabel = types.data?.find((t) => t.code === party.customer_type)?.label ?? party.customer_type;
  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <p className="text-sm text-ink-muted">
            <Link href="/sales/parties">Customers and suppliers</Link> · <span className="font-mono">{party.party_number}</span>
          </p>
          <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">{party.display_name}</h1>
          <p className="text-sm text-ink-muted">
            {party.archived_at ? "Archived · " : ""}
            {party.roles.map((r) => ROLE_LABEL[r] ?? r).join(", ")} · owner {party.owner.display_name ?? "—"}
          </p>
        </div>
        {!editing ? (
          <div className="flex flex-wrap gap-2">
            <Button onPress={() => setEditing(true)} {...unavailableWhen((!party.capabilities.update?.allowed) ? "You cannot edit this party" : null)}>
              Edit
            </Button>
            {party.capabilities.archive?.allowed ? (
              <Button variant="danger" onPress={() => archive.mutate(true)} isPending={archive.isPending}>
                Archive
              </Button>
            ) : null}
            {party.capabilities.restore?.allowed ? (
              <Button onPress={() => archive.mutate(false)} isPending={archive.isPending}>
                Restore
              </Button>
            ) : null}
          </div>
        ) : null}
      </header>
      {editing ? (
        <PartyEditor
          party={party}
          types={types.data ?? []}
          onDone={(next) => {
            queryClient.setQueryData(queryKeys.parties.party(partyId), next);
            for (const k of invalidationMap["parties.changed"]) void queryClient.invalidateQueries({ queryKey: k });
            setEditing(false);
          }}
        />
      ) : (
        <>
          <DescriptionList
            items={[
              { term: "Legal name", description: party.legal_name },
              { term: "Country", description: party.country_code },
              { term: "Currency", description: party.default_currency },
              { term: "Customer type", description: typeLabel ?? "—" },
              { term: "Status", description: party.status },
            ]}
          />
          <section aria-label="Contacts" className="flex flex-col gap-2">
            <h2 className="text-base font-semibold">Contacts</h2>
            {party.contacts.length ? (
              <ul className="flex flex-col gap-1 text-sm">
                {party.contacts.map((c) => (
                  <li key={c.id}>
                    {c.name}
                    {c.is_primary ? " (primary)" : ""} {c.email ? `· ${c.email}` : ""} {c.phone ? `· ${c.phone}` : ""}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-ink-muted">No contacts.</p>
            )}
          </section>
          <section aria-label="Addresses" className="flex flex-col gap-2">
            <h2 className="text-base font-semibold">Addresses</h2>
            {party.addresses.length ? (
              <ul className="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
                {party.addresses.map((a) => (
                  <li key={a.id} className="rounded-md border p-3">
                    <span className="font-semibold">{a.kind === "billing" ? "Billing" : "Shipping"}{a.is_default ? " (default)" : ""}</span>
                    <br />
                    {[a.line1, a.line2, [a.postal_code, a.city].filter(Boolean).join(" "), a.region, a.country_code].filter(Boolean).join(", ")}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-ink-muted">No addresses.</p>
            )}
          </section>
        </>
      )}
    </div>
  );
}

/** Customer types (SC-13): built-in standard/dealer/distributor plus company types; relabel, reorder, deactivate. */
export function CustomerTypesManager() {
  const queryClient = useQueryClient();
  const { permissionKeys } = useSession();
  const types = useCustomerTypes();
  const [draft, setDraft] = useState({ code: "", label: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const canManage = permissionKeys.has("parties.customer_type.manage");
  const refresh = () => void queryClient.invalidateQueries({ queryKey: queryKeys.parties.all() });
  const create = useMutation({
    mutationFn: () => createCustomerType({ code: draft.code, label: draft.label }),
    onSuccess: () => {
      setDraft({ code: "", label: "" });
      setErrors({});
      refresh();
    },
    onError: (error) =>
      setErrors(error instanceof ProblemError && error.code === "customer_type_exists" ? { code: "This code already exists" } : fieldErrors(error)),
  });
  const toggle = useMutation({
    mutationFn: (t: CustomerTypeRead) => updateCustomerType(t.id, { expected_version: t.version, is_active: !t.is_active }),
    onSuccess: refresh,
    onError: () => toast.error("Changed by someone else; reload and try again"),
  });
  if (!permissionKeys.has("parties.party.read")) return <PermissionDenied area="Customer types" />;
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">Customer types</h1>
      {types.isPending ? (
        <Loading label="customer types" />
      ) : types.isError ? (
        <ErrorState error={types.error} what="the customer types" onRetry={() => void types.refetch()} />
      ) : (
        <ul className="flex flex-col divide-y rounded-md border">
          {types.data.map((t) => (
            <li key={t.id} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
              <span className="font-semibold">{t.label}</span>
              <span className="font-mono text-ink-muted">{t.code}</span>
              {t.is_system ? <StatusPill tone="info">Built in</StatusPill> : null}
              {t.is_active ? null : <StatusPill tone="neutral">Inactive</StatusPill>}
              <span className="text-ink-muted tabular">{t.party_count} parties</span>
              {canManage ? (
                <Button size="sm" className="ms-auto" onPress={() => toggle.mutate(t)} isPending={toggle.isPending}>
                  {t.is_active ? "Deactivate" : "Activate"}
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {canManage ? (
        <form className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_2fr_auto] md:items-end" aria-label="New customer type" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <TextField label="Code" description="Lower case, e.g. wholesale" value={draft.code} onChange={(v) => setDraft((d) => ({ ...d, code: v }))} isInvalid={Boolean(errors.code)} errorMessage={errors.code} />
          <TextField label="Label" value={draft.label} onChange={(v) => setDraft((d) => ({ ...d, label: v }))} isInvalid={Boolean(errors.label)} errorMessage={errors.label} />
          <Button type="submit" variant="primary" isPending={create.isPending}>
            Add type
          </Button>
        </form>
      ) : null}
    </div>
  );
}
