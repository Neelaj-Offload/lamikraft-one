"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useCommand } from "@/features/inventory/use-command";
import { addsUpTo, decideInspection, fetchInspection, type ChecklistItem, type InspectionDetail } from "@/features/quality/api";
import { queryKeys } from "@/lib/api/query-keys";
import { isPositiveDecimalStr, trimDecimalStr } from "@/lib/format/decimal";
import { OfflineBanner, RecordFailure, RecordLoading, stagger, StatusBadge } from "~/screens/purchasing/parts";
import { asRoute } from "~/screens/purchasing/views";
import { Page, RecordHeader, Split } from "~/shell/page";
import { Banner, Button, DateText, DecimalField, FactStrip, FormActions, FormSection, GlassPanel, Icon, KeyValue, Qty, RadioGroup, Select, Textarea, TextLink } from "~/ui";
import { CHECK_RESULT, inspectionStatus, REJECT_REASONS, rejectReasonLabel, subjectLabel } from "./labels";

const FAILED = "That did not go through";

/** One inspection: what is held, and either the form to record the result or the result itself. */
export function InspectionRecord({ inspectionId }: { inspectionId: string }) {
  const query = useQuery({ queryKey: queryKeys.quality.inspection(inspectionId), queryFn: ({ signal }) => fetchInspection(inspectionId, signal) });
  if (query.isPending) return <RecordLoading label="Loading the inspection" />;
  if (query.isError) {
    return <RecordFailure error={query.error} what="This inspection" retry={() => void query.refetch()} backHref="/operations/quality" backLabel="All inspections" />;
  }
  return <Loaded insp={query.data} />;
}

function Loaded({ insp }: { insp: InspectionDetail }) {
  const key = useMemo(() => queryKeys.quality.inspection(insp.id), [insp.id]);
  const command = useCommand<InspectionDetail>(key);
  const decided = insp.status !== "pending";
  const canDecide = !decided && Boolean(insp.capabilities.decide?.allowed);
  const qty = (value: string) => <Qty value={{ value, uom: insp.unit }} />;
  const source = `${subjectLabel(insp.subject_type)} ${insp.subject_label}`;
  const inline = `${subjectLabel(insp.subject_type).toLowerCase()} ${insp.subject_label}`;

  return (
    <Page>
      <RecordHeader
        breadcrumb={[{ label: "Operations", href: "/operations" }, { label: "Quality", href: "/operations/quality" }, { label: insp.inspection_number }]}
        code={insp.inspection_number}
        title={insp.product.name}
        status={<StatusBadge look={inspectionStatus(insp.status)} />}
        lead={
          <>
            From {insp.source_path ? <TextLink href={asRoute(insp.source_path)}>{inline}</TextLink> : inline}, requested <DateText value={insp.requested_at} style="dayTime" />
            {insp.decided_at ? (
              <>
                {" "}
                and decided <DateText value={insp.decided_at} style="dayTime" />
              </>
            ) : null}
            .
          </>
        }
        facts={
          <FactStrip
            items={[
              { label: "Inspected quantity", icon: "box", value: qty(insp.quantity) },
              { label: "Warehouse", icon: "warehouse", value: insp.warehouse.name },
              { label: "Lot", icon: "tag", value: insp.lot_code ? <span className="lk-mono">{insp.lot_code}</span> : null },
              decided
                ? { label: "Decided by", icon: "user", value: insp.decided_by_name }
                : { label: "Requested", icon: "clock", value: <DateText value={insp.requested_at} style="date" /> },
            ]}
          />
        }
      />

      {command.offline && canDecide ? <OfflineBanner what="this inspection" /> : null}

      <Split
        main={decided ? <Result insp={insp} /> : canDecide ? <DecideForm insp={insp} command={command} /> : <Waiting insp={insp} />}
        aside={
          <GlassPanel padding="md" className="rise" title="What is held" titleAs="h2">
            <KeyValue
              rows
              items={[
                { label: "Product", value: insp.product.name },
                { label: "Product key", value: insp.product.product_key, mono: true },
                { label: "From", value: insp.source_path ? <TextLink href={asRoute(insp.source_path)}>{source}</TextLink> : source },
                { label: "Warehouse", value: `${insp.warehouse.code} · ${insp.warehouse.name}` },
                { label: "Lot", value: insp.lot_code, mono: true },
                { label: "Quantity", value: qty(insp.quantity), total: true },
              ]}
            />
          </GlassPanel>
        }
      />
    </Page>
  );
}

// ---------------------------------------------------------------------------------------------
// Waiting for someone who may decide

function Waiting({ insp }: { insp: InspectionDetail }) {
  return (
    <GlassPanel padding="lg" className="rise flex flex-col gap-3" eyebrow="Where it stands">
      <h2 className="t-display-sm text-ink">
        Waiting for <em>inspection</em>
      </h2>
      <p className="t-body max-w-prose text-ink-2">
        The goods stay in QC hold at {insp.warehouse.name} until someone with quality rights in this warehouse records the result. You can see it, but not decide it.
      </p>
    </GlassPanel>
  );
}

// ---------------------------------------------------------------------------------------------
// The result, once decided

function Result({ insp }: { insp: InspectionDetail }) {
  const qty = (value: string) => <Qty value={{ value, uom: insp.unit }} />;
  const rejected = isPositiveDecimalStr(insp.qty_rejected);
  return (
    <>
      <section aria-label="Result" className="lk-glass lk-glass-inverse rise flex min-w-0 flex-col gap-5 rounded-xl p-6">
        <div className="flex items-center justify-between gap-3">
          <h2 className="t-overline opacity-70">Result</h2>
          <span className="t-caption opacity-70">{insp.decided_by_name ? `Decided by ${insp.decided_by_name}` : inspectionStatus(insp.status).label}</span>
        </div>
        <dl className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          <div className="flex min-w-0 flex-col gap-1">
            <dt className="t-label opacity-70">Accepted into stock</dt>
            <dd className="t-stat-xl">{qty(insp.qty_accepted)}</dd>
          </div>
          <div className="flex min-w-0 flex-col gap-1">
            <dt className="t-label opacity-70">Rejected</dt>
            <dd className="t-stat-xl">{qty(insp.qty_rejected)}</dd>
          </div>
        </dl>
        {rejected || insp.reject_reason_code ? (
          <p className="t-body-sm border-t border-on-inverse/20 pt-4">
            <span className="opacity-70">Why rejected: </span>
            {rejectReasonLabel(insp.reject_reason_code) ?? "No reason recorded"}
          </p>
        ) : null}
      </section>

      <GlassPanel padding="md" className="rise" title="Findings" titleAs="h2">
        {insp.findings ? <p className="t-body max-w-prose whitespace-pre-line text-ink">{insp.findings}</p> : <p className="t-body-sm text-ink-3">No findings were written down.</p>}
      </GlassPanel>

      {insp.checklist.length > 0 ? (
        <GlassPanel padding="md" className="rise" title="Checklist" titleAs="h2">
          <ul className="flex flex-col">
            {insp.checklist.map((item, index) => (
              <li key={item.code} className="rise-plain flex min-w-0 flex-wrap items-start justify-between gap-3 border-t border-line py-3 first:border-t-0 first:pt-0 last:pb-0" style={stagger(index)}>
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className="t-label text-ink">{item.label}</span>
                  {item.note ? <span className="t-caption text-ink-3">{item.note}</span> : null}
                </span>
                <StatusBadge look={CHECK_RESULT[item.result] ?? { label: item.result, tone: "neutral" }} size="sm" />
              </li>
            ))}
          </ul>
        </GlassPanel>
      ) : null}
    </>
  );
}

// ---------------------------------------------------------------------------------------------
// Record the result

type Command = ReturnType<typeof useCommand<InspectionDetail>>;

const RESULT_OPTIONS = (["pass", "fail", "na"] as const).map((value) => ({ value, label: CHECK_RESULT[value]?.label ?? value }));

function DecideForm({ insp, command }: { insp: InspectionDetail; command: Command }) {
  const { run, pending, offline } = command;
  const total = trimDecimalStr(insp.quantity);
  const [accepted, setAccepted] = useState(total);
  const [rejected, setRejected] = useState("0");
  const [checklist, setChecklist] = useState<ChecklistItem[]>(insp.suggested_checklist);
  const [findings, setFindings] = useState("");
  const [reason, setReason] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);

  const addsUp = accepted !== "" && rejected !== "" && addsUpTo(accepted, rejected, insp.quantity);
  const rejecting = isPositiveDecimalStr(rejected);
  const explained = checklist.some((item) => item.result === "fail") || findings.trim().length > 0;
  const reasonError = checked && rejecting && !reason ? "Choose why the goods were rejected." : undefined;
  const explainError = checked && rejecting && !explained ? "Mark the check that failed, or write what you found." : undefined;
  const busy = pending === "decide";
  const qtyText = <Qty value={{ value: insp.quantity, uom: insp.unit }} />;

  const split = (nextAccepted: string, nextRejected: string) => {
    setAccepted(nextAccepted);
    setRejected(nextRejected);
  };
  const submit = () => {
    setChecked(true);
    if (!addsUp || (rejecting && (!reason || !explained))) return;
    void run(
      "decide",
      (k) => decideInspection(insp, { qty_accepted: accepted, qty_rejected: rejected, checklist, findings, reject_reason_code: rejecting ? reason : null }, k),
      { done: "Result recorded", failed: FAILED, write: (next) => next },
    );
  };

  return (
    <div className="stack">
      {checked && !addsUp ? (
        <Banner tone="ember" title="The quantities do not add up.">
          Accepted and rejected together must equal the {qtyText} inspected.
        </Banner>
      ) : null}

      <FormSection title="How much passed" description="Split the held quantity between what goes into stock and what is rejected. The stock moves once, when you record the result.">
        <div className="col-span-full flex flex-wrap gap-2">
          <Button variant="secondary" size="sm" iconLeft="check" onPress={() => split(total, "0")}>
            Accept all
          </Button>
          <Button variant="secondary" size="sm" iconLeft="x" onPress={() => split("0", total)}>
            Reject all
          </Button>
        </div>
        <DecimalField label="Accepted" value={accepted} onChange={setAccepted} suffix={insp.unit} help="Released to usable stock." />
        <DecimalField label="Rejected" value={rejected} onChange={setRejected} suffix={insp.unit} help="Moved to the rejected location." />
        <p className={`t-body-sm col-span-full flex items-center gap-2 ${addsUp ? "text-ink-2" : "text-ember"}`} aria-live="polite">
          <Icon name={addsUp ? "checkCircle" : "alert"} size={16} className="flex-none" />
          {addsUp ? <>Adds up to the {qtyText} inspected.</> : <>Accepted and rejected must add up to {qtyText}.</>}
        </p>
        {rejecting ? (
          <Select
            className="col-span-full sm:col-span-1"
            label="Why rejected"
            placeholder="Choose a reason"
            options={REJECT_REASONS.map((option) => ({ value: option.value, label: option.label }))}
            value={reason}
            onChange={setReason}
            isRequired
            error={reasonError}
          />
        ) : null}
      </FormSection>

      {checklist.length > 0 ? (
        <FormSection title="Checklist" description="Mark each check. A failed check explains a rejection.">
          {checklist.map((item) => (
            <RadioGroup
              key={item.code}
              className="col-span-full"
              label={item.label}
              orientation="horizontal"
              options={RESULT_OPTIONS}
              value={item.result}
              onChange={(value) => setChecklist((all) => all.map((other) => (other.code === item.code ? { ...other, result: value === "fail" ? "fail" : value === "na" ? "na" : "pass" } : other)))}
            />
          ))}
        </FormSection>
      ) : null}

      <FormSection title="Findings" description={rejecting ? "Say what was wrong, unless a failed check already shows it." : "Anything the next person should know about these goods."}>
        <Textarea className="col-span-full" label="Findings" optional={!rejecting} rows={3} maxLength={2000} value={findings} onChange={setFindings} error={explainError} placeholder="Chipped edges on three pieces, the rest clean" />
      </FormSection>

      <FormActions note={rejecting ? "Rejected goods move to the rejected location" : "Everything accepted goes into stock"}>
        <Button iconLeft="clipboardCheck" loading={busy} isDisabled={Boolean(offline)} onPress={submit}>
          Record result
        </Button>
      </FormActions>
    </div>
  );
}
