"use client";

import { useQuery } from "@tanstack/react-query";
import type { Route } from "next";
import { useId, useMemo, useState, type FormEvent } from "react";
import { useResourceCommand } from "@/features/sales/resource-command";
import { fetchSample, type Sample } from "@/features/samples/api";
import { isProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession, useZone } from "@/lib/session/context";
import { DATED_ACTIONS, transitionSampleDated, type DatedTransition } from "~/data/samples-history";
import { isoToday } from "../leads/labels";
import { Page, PageHeader, RecordHeader } from "~/shell/page";
import { ErrorBlock, NotPermitted } from "~/shell/states";
import {
  Badge,
  DatePicker,
  Banner,
  Button,
  ButtonLink,
  DateText,
  FactStrip,
  GlassPanel,
  IconButton,
  KeyValue,
  Menu,
  Modal,
  Qty,
  Select,
  Skeleton,
  SkeletonText,
  Tabs,
  Textarea,
  TextField,
  TextLink,
  type MenuItem,
} from "~/ui";
import { countryName, humanise, stagger } from "../customers/labels";
import { RecordActivity } from "../customers/record-collab";
import {
  EVIDENCE_LABEL,
  FEEDBACK_LABEL,
  FEEDBACK_TONE,
  journeyIndex,
  SAMPLE_ACTION_DONE,
  SAMPLE_ACTION_ICON,
  SAMPLE_ACTION_LABEL,
  SAMPLE_JOURNEY,
  SAMPLE_STANDING,
  SAMPLE_STATUS_LABEL,
  SAMPLE_STATUS_TONE,
  SAMPLE_STEP_ICON,
  type SampleView,
} from "./labels";
import { SampleLineageView } from "./lineage";
import { Steps } from "./steps";

const CRUMBS = [
  { label: "Sales", href: "/sales" as Route },
  { label: "Samples", href: "/sales/samples" as Route },
];

export function SampleRecord({ sampleId, view }: { sampleId: string; view: SampleView }) {
  const query = useQuery({ queryKey: queryKeys.sales.sample(sampleId), queryFn: ({ signal }) => fetchSample(sampleId, signal) });
  if (query.isPending) {
    return (
      <Page>
        <div className="lk-glass record-head" role="status" aria-label="Loading the sample">
          <Skeleton width={110} height={10} />
          <Skeleton width="45%" height={28} />
          <SkeletonText lines={2} />
        </div>
      </Page>
    );
  }
  if (query.isError) {
    return (
      <Page>
        <PageHeader breadcrumb={CRUMBS} title="Sample" />
        {isProblemError(query.error) && query.error.status === 403 ? (
          <GlassPanel>
            <NotPermitted what="Samples" icon="packageOpen" />
          </GlassPanel>
        ) : (
          <ErrorBlock error={query.error} what="This sample" onRetry={() => void query.refetch()} />
        )}
      </Page>
    );
  }
  return <Loaded sample={query.data} view={view} />;
}

/** How far a cancelled sample got before it stopped, from the dates it carries. */
function reachedBeforeCancel(sample: Sample): number {
  if (sample.feedback_at) return 3;
  if (sample.delivered_at) return 2;
  if (sample.dispatched_at) return 1;
  return 0;
}

function Loaded({ sample, view }: { sample: Sample; view: SampleView }) {
  const { permissionKeys } = useSession();
  const keys = useMemo(() => [queryKeys.sales.sample(sample.id), queryKeys.sales.sampleLineage(sample.id), ["sales", "samples"], ["sales", "sample-status-counts"]], [sample.id]);
  const commands = useResourceCommand(`sample:${sample.id}`, keys);
  const [action, setAction] = useState<{ name: string; round: number } | null>(null);
  const [round, setRound] = useState(0);
  const open = (name: string) => {
    setRound((current) => current + 1);
    setAction({ name, round: round + 1 });
  };

  const cancelled = sample.status === "cancelled";
  const closed = sample.status === "closed";
  const index = cancelled ? reachedBeforeCancel(sample) + 1 : journeyIndex(sample.status);
  const standing = SAMPLE_STANDING[sample.status] ?? { now: humanise(sample.status), next: "" };
  const forward = sample.allowed_transitions.filter((transition) => transition.action !== "cancel");
  const primary = forward[0] ?? null;
  const rest = sample.allowed_transitions.filter((transition) => transition.action !== primary?.action);
  const canOpenCustomer = permissionKeys.has("parties.party.read");
  const customerHref = `/sales/parties/${encodeURIComponent(sample.party.id)}` as Route;
  const base = `/sales/samples/${encodeURIComponent(sample.id)}`;

  const menu: MenuItem[] = rest.flatMap((transition, position): MenuItem[] => {
    const item: MenuItem = {
      id: transition.action,
      label: SAMPLE_ACTION_LABEL[transition.action] ?? humanise(transition.action),
      icon: SAMPLE_ACTION_ICON[transition.action],
      tone: transition.action === "cancel" ? "danger" : undefined,
      onAction: () => open(transition.action),
    };
    return transition.action === "cancel" && position > 0 ? [{ id: "sep", separator: true }, item] : [item];
  });

  const stepCaption = (step: (typeof SAMPLE_JOURNEY)[number]) => {
    switch (step) {
      case "requested":
        return <DateText value={sample.requested_on} style="business" />;
      case "dispatched":
        return sample.dispatched_at ? (
          <>
            <DateText value={sample.dispatched_at} />
            {sample.dispatch_reference ? ` · ${sample.dispatch_reference}` : ""}
          </>
        ) : undefined;
      case "delivered":
        return sample.delivered_at ? <DateText value={sample.delivered_at} /> : undefined;
      case "feedback_received":
        return sample.feedback_at ? (
          <>
            <DateText value={sample.feedback_at} />
            {sample.feedback_outcome ? ` · ${FEEDBACK_LABEL[sample.feedback_outcome] ?? humanise(sample.feedback_outcome)}` : ""}
          </>
        ) : undefined;
      case "closed":
        return sample.closed_at && !cancelled ? <DateText value={sample.closed_at} /> : undefined;
    }
  };

  return (
    <Page>
      <RecordHeader
        breadcrumb={[...CRUMBS, { label: sample.sample_number }]}
        code={sample.sample_number}
        title={sample.description || `Sample for ${sample.party.display_name}`}
        status={
          <Badge tone={SAMPLE_STATUS_TONE[sample.status] ?? "neutral"} dot>
            {SAMPLE_STATUS_LABEL[sample.status] ?? humanise(sample.status)}
          </Badge>
        }
        lead={`Customer sample. ${standing.now}`}
        facts={
          <FactStrip
            items={[
              { label: "Customer", value: canOpenCustomer ? <TextLink href={customerHref}>{sample.party.display_name}</TextLink> : sample.party.display_name, icon: "building" },
              { label: "Quantity", value: <Qty value={{ value: sample.quantity, uom: sample.unit_code }} />, icon: "boxes" },
              { label: "Requested", value: <DateText value={sample.requested_on} style="business" />, icon: "calendar" },
              { label: "Courier or reference", value: sample.dispatch_reference, icon: "truck" },
              { label: "Looked after by", value: sample.owner.display_name, icon: "user" },
            ]}
          />
        }
        actions={
          primary || menu.length > 0 ? (
            <>
              {primary ? (
                <Button iconLeft={SAMPLE_ACTION_ICON[primary.action]} onPress={() => open(primary.action)} isDisabled={Boolean(commands.offline)}>
                  {SAMPLE_ACTION_LABEL[primary.action] ?? humanise(primary.action)}
                </Button>
              ) : null}
              {menu.length > 0 ? <Menu label="More actions" items={menu} placement="bottom end" trigger={<IconButton icon="more" label="More actions" />} /> : null}
            </>
          ) : undefined
        }
      >
        <Tabs
          label="Sample views"
          selectedKey={view}
          tabs={[
            { id: "overview", label: "Overview", href: base as Route },
            { id: "history", label: "Where it came from", href: `${base}?view=history` as Route },
            { id: "activity", label: "Activity", href: `${base}?view=activity` as Route },
          ]}
        />
      </RecordHeader>

      {commands.offline ? <Banner tone="amber" title="You are offline.">You can read this sample. Reconnect to record the next step.</Banner> : null}

      {view === "history" ? <SampleLineageView sample={sample} /> : null}
      {view === "activity" ? <RecordActivity resourceType="sales.sample" resourceId={sample.id} /> : null}
      {view === "overview" ? (
        <>
          {cancelled ? (
            <Banner tone="neutral" title="This sample was cancelled." icon="xCircle">
              {sample.close_reason ? `Reason: ${sample.close_reason}` : "It left the journey before it finished."}
            </Banner>
          ) : null}
          <GlassPanel as="section" padding="lg" className="rise flex flex-col gap-6" aria-label="Sample journey">
            <Steps
              label="Sample journey"
              current={index}
              complete={closed}
              halted={cancelled}
              steps={SAMPLE_JOURNEY.map((step) => ({ id: step, label: SAMPLE_STATUS_LABEL[step] ?? step, icon: SAMPLE_STEP_ICON[step], caption: stepCaption(step) }))}
            />
            {standing.next ? (
              <div className="hairline-top flex flex-col gap-1 pt-5">
                <p className="t-overline text-gold-strong">Next step</p>
                <p className="t-display-sm">{primary ? (SAMPLE_ACTION_LABEL[primary.action] ?? humanise(primary.action)) : "Waiting on someone else"}</p>
                <p className="t-body text-ink-2">{primary ? standing.next : "Your role cannot record the next step for this sample."}</p>
              </div>
            ) : null}
          </GlassPanel>

          <div className="split">
            <div className="stack">
              {sample.feedback || sample.feedback_outcome ? (
                <GlassPanel
                  as="section"
                  padding="lg"
                  title="What the customer said"
                  titleAs="h2"
                  className="rise flex flex-col gap-3"
                  style={stagger(1)}
                  action={
                    sample.feedback_outcome ? (
                      <Badge tone={FEEDBACK_TONE[sample.feedback_outcome] ?? "neutral"} dot>
                        {FEEDBACK_LABEL[sample.feedback_outcome] ?? humanise(sample.feedback_outcome)}
                      </Badge>
                    ) : undefined
                  }
                >
                  {sample.feedback ? <p className="t-body-lg whitespace-pre-wrap text-ink [overflow-wrap:anywhere]">{sample.feedback}</p> : <p className="t-body text-ink-3">No comment was recorded with the outcome.</p>}
                </GlassPanel>
              ) : null}
              <GlassPanel as="section" padding="lg" title="The sample" titleAs="h2" className="rise" style={stagger(2)}>
                <KeyValue
                  rows
                  items={[
                    { label: "What was sent", value: sample.description },
                    { label: "Quantity", value: <Qty value={{ value: sample.quantity, uom: sample.unit_code }} /> },
                    {
                      label: "For quotation",
                      value: sample.quote_id && sample.quote_number ? <TextLink href={`/sales/quotes/${encodeURIComponent(sample.quote_id)}` as Route}>{sample.quote_number}</TextLink> : null,
                    },
                    {
                      label: "Custom product",
                      value:
                        sample.custom_product_id && sample.custom_code ? (
                          <TextLink href={`/sales/custom-products/${encodeURIComponent(sample.custom_product_id)}` as Route}>{sample.custom_code}</TextLink>
                        ) : null,
                    },
                    { label: "How delivery was confirmed", value: sample.delivery_evidence_kind ? (EVIDENCE_LABEL[sample.delivery_evidence_kind] ?? humanise(sample.delivery_evidence_kind)) : null },
                    { label: "Notes", value: sample.notes ?? (cancelled ? null : sample.close_reason) },
                  ]}
                />
              </GlassPanel>
            </div>
            <aside className="stack">
              <GlassPanel as="section" title="Who it is for" titleAs="h2" className="rise" style={stagger(3)}>
                <KeyValue
                  rows
                  items={[
                    { label: "Customer", value: sample.party.display_name },
                    { label: "Number", value: sample.party.party_number, mono: true },
                    { label: "Country", value: countryName(sample.party.country_code) },
                  ]}
                />
                {canOpenCustomer ? (
                  <div className="mt-4">
                    <ButtonLink variant="secondary" size="sm" href={`${customerHref}?view=samples` as Route} iconRight="arrowRight">
                      All their samples
                    </ButtonLink>
                  </div>
                ) : null}
              </GlassPanel>
            </aside>
          </div>
        </>
      ) : null}

      {action ? (
        <ActionModal
          key={action.round}
          sample={sample}
          action={action.name}
          pending={commands.pending !== null}
          offline={Boolean(commands.offline)}
          onClose={() => setAction(null)}
          onRun={(request) =>
            commands.run(request.action, [sample.version, JSON.stringify(request)], (key) => transitionSampleDated(sample, request, key), {
              done: SAMPLE_ACTION_DONE[request.action] ?? "Saved",
              failed: `${SAMPLE_ACTION_LABEL[request.action] ?? "The change"} did not go through`,
              conflictMessage: "This sample changed since you opened it. The latest version is showing.",
            })
          }
        />
      ) : null}
    </Page>
  );
}

const ACTION_COPY: Record<string, { title: string; description: string }> = {
  dispatch: { title: "Record the dispatch", description: "The sample has left stock and is on its way to the customer." },
  deliver: { title: "Record the delivery", description: "The sample has reached the customer. Say how you know." },
  record_feedback: { title: "Record their feedback", description: "What the customer thought of the sample, in their words where you can." },
  close: { title: "Close this sample", description: "Nothing more will be recorded. It stays on the customer's profile." },
  cancel: { title: "Cancel this sample", description: "The sample leaves the journey and cannot be reopened." },
};

function ActionModal({
  sample,
  action,
  pending,
  offline,
  onClose,
  onRun,
}: {
  sample: Sample;
  action: string;
  pending: boolean;
  offline: boolean;
  onClose: () => void;
  onRun: (request: DatedTransition) => Promise<{ ok: true } | { ok: false; conflict: boolean; fieldErrors: Record<string, string> }>;
}) {
  const formId = useId();
  const zone = useZone();
  const today = isoToday(zone.timeZone);
  const [form, setForm] = useState<DatedTransition>({
    action,
    evidence_kind: action === "deliver" ? "courier_tracking" : null,
    feedback_outcome: action === "record_feedback" ? "positive" : null,
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const copy = ACTION_COPY[action] ?? { title: humanise(action), description: sample.sample_number };
  const label = SAMPLE_ACTION_LABEL[action] ?? humanise(action);
  const set = (changes: Partial<DatedTransition>) => {
    setForm((current) => ({ ...current, ...changes }));
    setErrors({});
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending || offline) return;
    const missing: Record<string, string> = {};
    if (action === "dispatch" && !form.dispatch_reference?.trim()) missing.dispatch_reference = "Enter the courier and tracking number, or who is carrying it.";
    if (action === "record_feedback" && !form.feedback?.trim()) missing.feedback = "Write what the customer said, even if it is short.";
    if (action === "cancel" && !form.reason?.trim()) missing.reason = "Say why the sample is cancelled.";
    if (Object.keys(missing).length > 0) return setErrors(missing);
    const outcome = await onRun(form);
    if (outcome.ok || outcome.conflict) onClose();
    else setErrors(outcome.fieldErrors);
  };

  return (
    <Modal
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      size="sm"
      title={copy.title}
      description={`${sample.sample_number} · ${sample.party.display_name}. ${copy.description}`}
      actions={
        <>
          <Button variant="ghost" onPress={onClose}>
            {action === "cancel" ? "Keep the sample" : "Not now"}
          </Button>
          <Button type="submit" form={formId} variant={action === "cancel" ? "danger" : "primary"} loading={pending} isDisabled={offline}>
            {label}
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={(event) => void submit(event)} noValidate className="flex flex-col gap-4">
        {action === "dispatch" ? (
          <TextField
            label="Courier or reference"
            value={form.dispatch_reference ?? ""}
            onChange={(value) => set({ dispatch_reference: value })}
            maxLength={120}
            isRequired
            autoFocus
            placeholder="Courier name and tracking number"
            error={errors.dispatch_reference || undefined}
          />
        ) : null}
        {action === "deliver" ? (
          <Select
            label="How you know it arrived"
            options={Object.entries(EVIDENCE_LABEL).map(([value, text]) => ({ value, label: text }))}
            value={form.evidence_kind ?? null}
            onChange={(value) => set({ evidence_kind: value })}
            error={errors.evidence_kind || undefined}
          />
        ) : null}
        {action === "record_feedback" ? (
          <>
            <Select
              label="Outcome"
              options={Object.entries(FEEDBACK_LABEL).map(([value, text]) => ({ value, label: text }))}
              value={form.feedback_outcome ?? null}
              onChange={(value) => set({ feedback_outcome: value })}
              error={errors.feedback_outcome || undefined}
            />
            <Textarea label="What they said" value={form.feedback ?? ""} onChange={(value) => set({ feedback: value })} isRequired rows={4} error={errors.feedback || undefined} />
          </>
        ) : null}
        {DATED_ACTIONS.has(action) ? (
          <DatePicker
            label="When"
            optional
            value={form.occurred_on ?? null}
            onChange={(value) => set({ occurred_on: value })}
            maxValue={today}
            help="Leave empty for today. Pick the real date when you enter a sample from the past."
            error={errors.occurred_on || undefined}
          />
        ) : null}
        {action === "cancel" || action === "close" ? (
          <Textarea
            label={action === "cancel" ? "Reason for cancelling" : "Closing note"}
            optional={action === "close"}
            isRequired={action === "cancel"}
            value={form.reason ?? ""}
            onChange={(value) => set({ reason: value })}
            rows={3}
            help={action === "close" ? "Anything the next person should know." : "Kept with the sample."}
            error={errors.reason || undefined}
          />
        ) : null}
      </form>
    </Modal>
  );
}
