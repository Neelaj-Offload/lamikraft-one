"use client";

import { useState } from "react";
import { DatePicker } from "@/components/ui/date-picker";
import { ComboBox, Select } from "@/components/ui/select";
import { TextArea, TextField } from "@/components/ui/text-field";
import { challansMessages as m } from "@/messages/challans";
import { PARTY_ROLE_FOR, withDestination, withType, type HeaderForm } from "./form-model";
import { useRolePartySearch } from "./pickers";
import { CHALLAN_TYPES, TYPE_POLICY, type ChallanType, type DestinationType, type ReturnType } from "./types";

const f = m.workspace.fields;

/**
 * Every legacy header field (CURRENT_STATE_SPEC §4.15): type, return type, destination type and party, the printed
 * TO name, date, source, shipping name, GSTIN, phone, email, address, reference, remarks and the expected return
 * date. Choices follow the movement policy; the server re-checks everything on save.
 */
export function HeaderFields({
  form,
  onChange,
  errors,
  full,
}: {
  form: HeaderForm;
  onChange: (form: HeaderForm) => void;
  errors: Record<string, string>;
  /** The edit drawer shows every field; the create form shows the essentials first. */
  full: boolean;
}) {
  const rule = TYPE_POLICY[form.challan_type];
  const role = PARTY_ROLE_FOR[form.destination_type];
  const [partyText, setPartyText] = useState(form.party?.display_name ?? "");
  const parties = useRolePartySearch(partyText, role);
  const options = [...(form.party ? [form.party] : []), ...(parties.data ?? []).filter((p) => p.id !== form.party?.id)];
  const set = <K extends keyof HeaderForm>(key: K, value: HeaderForm[K]) => onChange({ ...form, [key]: value });

  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
        <Select
          label={m.create.type}
          options={CHALLAN_TYPES.map((type) => ({ id: type, label: m.types[type] ?? type }))}
          value={form.challan_type}
          onChange={(value) => onChange(withType(form, (CHALLAN_TYPES.find((t) => t === value) ?? form.challan_type) as ChallanType))}
          errorMessage={errors.challan_type}
        />
        <Select
          label={m.create.returnType}
          options={rule.returnTypes.map((r) => ({ id: r, label: m.returnTypes[r] ?? r }))}
          value={form.return_type}
          onChange={(value) => set("return_type", (rule.returnTypes.find((r) => r === value) ?? form.return_type) as ReturnType)}
          errorMessage={errors.return_type}
        />
        <Select
          label={m.create.destinationType}
          options={rule.destinations.map((d) => ({ id: d, label: m.destinations[d] ?? d }))}
          value={form.destination_type}
          onChange={(value) => onChange(withDestination(form, (rule.destinations.find((d) => d === value) ?? form.destination_type) as DestinationType))}
          errorMessage={errors.destination_type}
        />
      </div>
      {role !== null ? (
        <ComboBox
          label={m.create.party}
          placeholder={m.create.partyHint}
          emptyText={partyText.trim().length < 2 ? m.create.partyHint : m.create.noParty}
          options={options.map((p) => ({ id: p.id, label: p.display_name, detail: p.party_number }))}
          value={form.party?.id ?? null}
          inputValue={partyText}
          onInputChange={setPartyText}
          onChange={(id) => {
            const party = options.find((candidate) => candidate.id === id) ?? null;
            onChange({ ...form, party, destination_party: party && !form.destination_party.trim() ? party.display_name : form.destination_party });
            if (party) setPartyText(party.display_name);
          }}
          errorMessage={errors.party_id}
        />
      ) : null}
      <TextField
        label={m.create.destinationParty}
        description={m.create.destinationPartyHint}
        value={form.destination_party}
        onChange={(value) => set("destination_party", value)}
        maxLength={200}
        errorMessage={errors.destination_party}
      />
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
        <DatePicker label={m.create.date} value={form.challan_date} onChange={(value) => set("challan_date", value)} errorMessage={errors.challan_date} />
        {form.return_type === "returnable" ? (
          <DatePicker label={f.expectedReturn} value={form.expected_return_date} onChange={(value) => set("expected_return_date", value)} errorMessage={errors.expected_return_date} />
        ) : null}
        <TextField label={m.create.reference} value={form.reference_no} onChange={(value) => set("reference_no", value)} maxLength={120} errorMessage={errors.reference_no} />
        <TextField
          label={m.create.source}
          description={m.create.sourceHint}
          value={form.source_location}
          onChange={(value) => set("source_location", value)}
          maxLength={200}
          errorMessage={errors.source_location}
        />
      </div>
      {full ? (
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          <TextField label={f.shippingName} value={form.shipping_name} onChange={(value) => set("shipping_name", value)} maxLength={200} errorMessage={errors.shipping_name} />
          <TextField label={f.gstin} description={f.gstinNote} value={form.gstin} onChange={(value) => set("gstin", value.toUpperCase())} maxLength={15} errorMessage={errors.gstin} />
          <TextField label={f.phone} type="tel" value={form.phone} onChange={(value) => set("phone", value)} maxLength={30} errorMessage={errors.phone} />
          <TextField label={f.email} type="email" value={form.email} onChange={(value) => set("email", value)} maxLength={254} errorMessage={errors.email} />
          <TextArea label={f.address} value={form.address} onChange={(value) => set("address", value)} errorMessage={errors.address} className="sm:col-span-2" />
        </div>
      ) : null}
      <TextArea label={m.create.remarks} value={form.remarks} onChange={(value) => set("remarks", value)} errorMessage={errors.remarks} />
    </div>
  );
}
