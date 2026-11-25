"use client";

import { useState, type ReactNode } from "react";
import { PARTY_ROLE_FOR, withDestination, withType, type HeaderForm } from "@/features/challans/form-model";
import { useRolePartySearch } from "@/features/challans/pickers";
import { CHALLAN_TYPES, TYPE_POLICY, type ChallanType } from "@/features/challans/types";
import { DESTINATION_LABEL, RETURN_LABEL, TYPE_HINT, TYPE_ICON, TYPE_LABEL } from "~/data/challans";
import { ComboBox, DatePicker, FormSection, RadioCards, Select, Textarea, TextField } from "~/ui";

/** What the picker is asked for, per destination ("party" never appears on screen). */
const RECORD_LABEL: Record<string, string> = {
  customer: "Customer on record",
  fabricator: "Fabricator on record",
  vendor: "Vendor on record",
  transporter: "Transporter on record",
};

function Group({ compact, title, description, children }: { compact: boolean; title: string; description: string; children: ReactNode }) {
  if (!compact) {
    return (
      <FormSection title={title} description={description}>
        {children}
      </FormSection>
    );
  }
  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h3 className="t-h4 text-ink">{title}</h3>
        <p className="t-body-sm text-ink-3">{description}</p>
      </div>
      <div className="lk-form-grid">{children}</div>
    </section>
  );
}

/**
 * Every header field of a challan, in three topics: the movement, where it goes, the paperwork.
 * The choices follow the movement policy (which return types and destinations a type accepts); the
 * server checks everything again on save. `compact` is the edit drawer: no panels, the type as a
 * select.
 */
export function HeaderFields({
  form,
  onChange,
  errors,
  compact = false,
}: {
  form: HeaderForm;
  onChange: (form: HeaderForm) => void;
  errors: Record<string, string>;
  compact?: boolean;
}) {
  const rule = TYPE_POLICY[form.challan_type];
  const role = PARTY_ROLE_FOR[form.destination_type];
  const [partyText, setPartyText] = useState(form.party?.display_name ?? "");
  const parties = useRolePartySearch(partyText, role);
  const options = [...(form.party ? [form.party] : []), ...(parties.data ?? []).filter((party) => party.id !== form.party?.id)];
  const set = <K extends keyof HeaderForm>(key: K, value: HeaderForm[K]) => onChange({ ...form, [key]: value });
  /** A change of type or destination can drop the chosen record; the picker's text goes with it. */
  const apply = (next: HeaderForm) => {
    if (form.party && !next.party) setPartyText("");
    onChange(next);
  };
  const chooseType = (value: string) => apply(withType(form, (CHALLAN_TYPES.find((type) => type === value) ?? form.challan_type) as ChallanType));
  const returnable = form.return_type === "returnable";
  const place = (DESTINATION_LABEL[form.destination_type] ?? "destination").toLowerCase();

  return (
    <>
      <Group compact={compact} title="What is moving?" description="The kind of movement decides where it may go and whether it comes back.">
        {compact ? (
          <Select
            label="Type"
            options={CHALLAN_TYPES.map((type) => ({ value: type, label: TYPE_LABEL[type] ?? type, description: TYPE_HINT[type] }))}
            value={form.challan_type}
            onChange={chooseType}
            error={errors.challan_type || undefined}
          />
        ) : (
          <RadioCards
            className="col-span-full"
            label="Type"
            options={CHALLAN_TYPES.map((type) => ({ value: type, label: TYPE_LABEL[type] ?? type, description: TYPE_HINT[type], icon: TYPE_ICON[type] }))}
            value={form.challan_type}
            onChange={chooseType}
            error={errors.challan_type || undefined}
          />
        )}
        <Select
          label="Does it come back?"
          options={rule.returnTypes.map((type) => ({ value: type, label: RETURN_LABEL[type] ?? type }))}
          value={form.return_type}
          onChange={(value) => set("return_type", rule.returnTypes.find((type) => type === value) ?? form.return_type)}
          help={rule.returnTypes.length === 1 ? `${TYPE_LABEL[form.challan_type]} challans are always ${(RETURN_LABEL[rule.returnTypes[0]!] ?? "").toLowerCase()}.` : undefined}
          error={errors.return_type || undefined}
        />
        {returnable ? (
          <DatePicker
            label="Expected back"
            optional
            value={form.expected_return_date}
            onChange={(value) => set("expected_return_date", value)}
            help="The day you expect the goods to return."
            error={errors.expected_return_date || undefined}
          />
        ) : null}
      </Group>

      <Group compact={compact} title="Where is it going?" description="The name is the one thing a draft needs. It is printed in the To block of the challan.">
        <Select
          label="Going to"
          options={rule.destinations.map((destination) => ({ value: destination, label: DESTINATION_LABEL[destination] ?? destination }))}
          value={form.destination_type}
          onChange={(value) => apply(withDestination(form, rule.destinations.find((destination) => destination === value) ?? form.destination_type))}
          error={errors.destination_type || undefined}
        />
        {role !== null ? (
          <ComboBox
            label={RECORD_LABEL[form.destination_type] ?? "On record"}
            optional
            placeholder="Type a name or number"
            items={options.map((party) => ({ id: party.id, label: party.display_name, description: party.party_number }))}
            inputValue={partyText}
            onInputChange={setPartyText}
            selectedKey={form.party?.id ?? null}
            onSelectionChange={(id) => {
              const party = options.find((candidate) => candidate.id === id) ?? null;
              onChange({ ...form, party, destination_party: party && !form.destination_party.trim() ? party.display_name : form.destination_party });
              if (party) setPartyText(party.display_name);
            }}
            isLoading={parties.isFetching}
            emptyText={partyText.trim().length < 2 ? "Type at least two letters" : `No ${place} matches. Check the spelling, or type the name below.`}
            help="Choosing one fills in the name."
            error={errors.party_id || undefined}
          />
        ) : null}
        <TextField
          className="col-span-full"
          label="Name on the challan"
          isRequired
          value={form.destination_party}
          onChange={(value) => set("destination_party", value)}
          maxLength={200}
          error={errors.destination_party || undefined}
        />
        <TextField label="Shipping name" optional value={form.shipping_name} onChange={(value) => set("shipping_name", value)} maxLength={200} error={errors.shipping_name || undefined} />
        <TextField
          label="GSTIN"
          optional
          value={form.gstin}
          onChange={(value) => set("gstin", value.toUpperCase())}
          maxLength={15}
          help="The format is checked. The number is not verified."
          error={errors.gstin || undefined}
        />
        <TextField label="Phone" optional type="tel" value={form.phone} onChange={(value) => set("phone", value)} maxLength={30} error={errors.phone || undefined} />
        <TextField label="Email" optional type="email" value={form.email} onChange={(value) => set("email", value)} maxLength={254} error={errors.email || undefined} />
        <Textarea className="col-span-full" label="Address" optional rows={3} value={form.address} onChange={(value) => set("address", value)} error={errors.address || undefined} />
      </Group>

      <Group compact={compact} title="Paperwork" description="Dates, references and anything the receiver should read.">
        <DatePicker label="Challan date" optional value={form.challan_date} onChange={(value) => set("challan_date", value)} error={errors.challan_date || undefined} />
        <TextField label="Reference number" optional value={form.reference_no} onChange={(value) => set("reference_no", value)} maxLength={120} error={errors.reference_no || undefined} />
        <TextField
          className="col-span-full"
          label="Sent from"
          optional
          value={form.source_location}
          onChange={(value) => set("source_location", value)}
          maxLength={200}
          help="Leave empty to use the company's default location."
          error={errors.source_location || undefined}
        />
        <Textarea
          className="col-span-full"
          label="Remarks"
          optional
          rows={3}
          value={form.remarks}
          onChange={(value) => set("remarks", value)}
          help="Printed on the challan."
          error={errors.remarks || undefined}
        />
      </Group>
    </>
  );
}
