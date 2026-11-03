"use client";

import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";
import { Form } from "react-aria-components";
import { RailContent } from "@/components/shell/context-rail";
import { Badge } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Drawer } from "@/components/ui/dialog";
import { LocalDate, LocalDateTime } from "@/components/ui/format";
import { KeyValueGrid, type KeyValue } from "@/components/ui/key-value-grid";
import { Link } from "@/components/ui/link";
import { MetaDot, RecordHeader } from "@/components/ui/record-header";
import { SectionCard } from "@/components/ui/section-card";
import { ErrorState, Loading, NotAvailable, PermissionDenied } from "@/components/ui/states";
import { useScreenContribution } from "@/features/assistant/screen-context-store";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { challansMessages as m } from "@/messages/challans";
import { fetchChallan, updateChallanHeader } from "./api";
import { ChallanStatusPill } from "./challan-bits";
import { ChallanCommandBar, issueBlockedText } from "./challan-commands";
import { ChallanLines } from "./challan-lines";
import { ChallanHistory, ReturnLinks } from "./challan-history";
import { fieldErrorsFrom, headerChanges, headerFormOf, type HeaderForm } from "./form-model";
import { HeaderFields } from "./header-fields";
import { InternalNotePanel } from "./internal-note";
import type { ChallanDetail } from "./types";
import { useChallanCommand, type ChallanCommands } from "./use-challan-command";

const w = m.workspace;
const f = w.fields;

/** The challan workspace. 404 and out-of-scope challans are the same "not available" state on purpose. */
export function ChallanWorkspace({ challanId }: { challanId: string }) {
  const query = useQuery({ queryKey: queryKeys.challans.challan(challanId), queryFn: ({ signal }) => fetchChallan(challanId, signal) });
  if (query.isPending) return <Loading label={w.loading} variant="detail" />;
  if (query.isError) {
    const error = query.error;
    if (error instanceof ProblemError && error.status === 404) return <NotAvailable />;
    if (error instanceof ProblemError && error.status === 403) return <PermissionDenied area={w.permissionArea} />;
    return <ErrorState error={error} what={w.loading} onRetry={() => void query.refetch()} />;
  }
  return <Workspace challan={query.data} />;
}

function Workspace({ challan }: { challan: ChallanDetail }) {
  const commands = useChallanCommand(challan.id);
  const [editing, setEditing] = useState(false);
  const editable = challan.status === "draft" && !challan.deleted_at && challan.capabilities.update?.allowed === true;
  const blocked = issueBlockedText(challan);

  useScreenContribution({ focus: { type: "challans.challan", id: challan.id, version: challan.version } });

  const meta: string[] = [
    m.types[challan.challan_type] ?? challan.challan_type,
    m.returnTypes[challan.return_type] ?? challan.return_type,
    m.destinations[challan.destination_type] ?? challan.destination_type,
    challan.challan_date,
    challan.owner.display_name ?? "",
  ].filter(Boolean);

  return (
    <div className="flex flex-col gap-8">
      <RecordHeader
        back={{ href: "/operations/challans", label: w.back }}
        recordKey={challan.challan_number}
        title={challan.destination_party}
        status={
          <span className="flex flex-wrap items-center gap-2">
            <ChallanStatusPill status={challan.status} />
            {challan.deleted_at ? <Badge>{m.list.deleted}</Badge> : null}
          </span>
        }
        meta={meta.map((fact, index) => (
          <span key={`${index}-${fact}`} className="inline-flex items-center gap-2">
            {index > 0 ? <MetaDot /> : null}
            <span>{fact}</span>
          </span>
        ))}
        actions={<ChallanCommandBar challan={challan} commands={commands} />}
      />
      <div className="flex flex-col gap-1 text-sm">
        {challan.deleted_at ? <p className="text-warning-text">{w.deleted}</p> : null}
        {blocked ? <p className="text-ink">{blocked}</p> : null}
        {challan.status !== "draft" ? <p className="text-ink-muted">{w.notEditable}</p> : null}
        <p className="text-ink-muted">{w.documentOnly}</p>
        {commands.offline ? <p className="text-warning-text">{commands.offline}</p> : null}
      </div>

      <Details challan={challan} canEdit={editable} onEdit={() => setEditing(true)} />
      <ChallanLines challan={challan} editable={editable} commands={commands} />
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <ReturnLinks challan={challan} />
        <ChallanHistory challan={challan} />
      </div>
      <InternalNotePanel challanId={challan.id} />

      <RailContent>
        <ChallanContext challan={challan} />
      </RailContent>
      {editable ? (
        <Drawer title={w.editTitle} description={`${challan.challan_number} · ${challan.destination_party}`} isOpen={editing} onOpenChange={setEditing}>
          {(close) => <EditHeaderForm challan={challan} commands={commands} onDone={close} />}
        </Drawer>
      ) : null}
    </div>
  );
}

function Details({ challan, canEdit, onEdit }: { challan: ChallanDetail; canEdit: boolean; onEdit: () => void }) {
  const opt = (term: string, value: ReactNode | null | undefined, extra: Partial<KeyValue> = {}): KeyValue[] =>
    value === null || value === undefined || value === "" ? [] : [{ term, description: value, ...extra }];
  const from: KeyValue[] = [
    ...opt(f.source, challan.source_location),
    ...opt(f.date, <LocalDate value={challan.challan_date} />),
    ...opt(f.reference, challan.reference_no, { mono: true }),
    ...opt(f.expectedReturn, challan.expected_return_date ? <LocalDate value={challan.expected_return_date} /> : null),
    ...opt(f.original, challan.original_challan ? <Link href={challan.original_challan.path}>{challan.original_challan.challan_number}</Link> : null),
    ...opt(f.duplicatedFrom, challan.duplicated_from ? <Link href={challan.duplicated_from.path}>{challan.duplicated_from.challan_number}</Link> : null),
  ];
  const to: KeyValue[] = [
    ...opt(f.destinationType, m.destinations[challan.destination_type]),
    ...opt(f.destinationParty, challan.destination_party),
    ...opt(f.party, challan.party ? <Link href={`/sales/parties/${encodeURIComponent(challan.party.id)}`}>{[challan.party.party_number, challan.party.display_name].filter(Boolean).join(" · ")}</Link> : null),
    ...opt(f.shippingName, challan.shipping_name),
    ...opt(f.gstin, challan.gstin ? `${challan.gstin} (${f.gstinNote.toLowerCase()})` : null, { mono: true }),
    ...opt(f.phone, challan.phone),
    ...opt(f.email, challan.email),
    ...opt(f.address, challan.address ? <span className="whitespace-pre-line">{challan.address}</span> : null),
  ];
  return (
    <SectionCard
      title={w.header}
      actions={
        canEdit ? (
          <Button size="sm" onPress={onEdit}>
            {w.edit}
          </Button>
        ) : null
      }
    >
      <div className="flex flex-col gap-2">
        <h3 className="text-sm font-semibold text-ink-muted">{w.from}</h3>
        <KeyValueGrid items={from} />
      </div>
      <div className="flex flex-col gap-2">
        <h3 className="text-sm font-semibold text-ink-muted">{w.to}</h3>
        <KeyValueGrid items={to} />
      </div>
      {challan.remarks ? (
        <div className="flex flex-col gap-1">
          <h3 className="text-sm font-semibold text-ink-muted">{f.remarks}</h3>
          <p className="whitespace-pre-line text-ink [overflow-wrap:anywhere]">{challan.remarks}</p>
        </div>
      ) : null}
    </SectionCard>
  );
}

function EditHeaderForm({ challan, commands, onDone }: { challan: ChallanDetail; commands: ChallanCommands; onDone: () => void }) {
  const [base] = useState(() => headerFormOf(challan));
  const [form, setForm] = useState<HeaderForm>(base);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const changes = headerChanges(base, form);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (Object.keys(changes).length === 0) {
      onDone();
      return;
    }
    const outcome = await commands.run("update_header", [JSON.stringify(changes)], (key, current) => updateChallanHeader(current, changes, key), {
      done: w.saved,
      failed: w.failed(w.saveDetails),
    });
    if (outcome.ok) onDone();
    else setErrors(fieldErrorsFrom(outcome.error));
  };

  return (
    <Form onSubmit={submit} className="flex flex-col gap-6" validationBehavior="aria">
      <HeaderFields form={form} onChange={setForm} errors={errors} full />
      <div>
        <Button type="submit" variant="primary" isPending={commands.pending === "update_header"} pendingLabel={w.save.saving} {...unavailableWhen(commands.offline)}>
          {w.saveDetails}
        </Button>
      </div>
    </Form>
  );
}

function ChallanContext({ challan }: { challan: ChallanDetail }) {
  return (
    <div className="flex flex-col gap-3 text-sm">
      <h2 className="text-base font-[650] text-ink">{w.context}</h2>
      <dl className="flex flex-col gap-2">
        <div>
          <dt className="text-ink-muted">{f.owner}</dt>
          <dd>{challan.owner.display_name ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-ink-muted">{w.created}</dt>
          <dd>
            <LocalDateTime value={challan.created_at} />
          </dd>
        </div>
        {challan.issued_at ? (
          <div>
            <dt className="text-ink-muted">{f.issued}</dt>
            <dd>
              <LocalDateTime value={challan.issued_at} />
              {challan.issued_by?.display_name ? ` · ${challan.issued_by.display_name}` : null}
            </dd>
          </div>
        ) : null}
        {challan.closed_at ? (
          <div>
            <dt className="text-ink-muted">{f.closed}</dt>
            <dd>
              <LocalDateTime value={challan.closed_at} />
              {challan.close_reason ? ` · ${challan.close_reason}` : null}
            </dd>
          </div>
        ) : null}
        {challan.cancelled_at ? (
          <div>
            <dt className="text-ink-muted">{f.cancelled}</dt>
            <dd>
              <LocalDateTime value={challan.cancelled_at} />
              {challan.cancel_reason ? ` · ${challan.cancel_reason}` : null}
            </dd>
          </div>
        ) : null}
      </dl>
    </div>
  );
}
