"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { useResourceCommand } from "@/features/sales/resource-command";
import { fieldErrorsFrom } from "@/features/parties/form-model";
import { useZone } from "@/lib/session/context";
import {
  changeLeadStage,
  LEAD_INVALIDATE,
  leadKeys,
  logActivity,
  updateLeadFields,
  useActivities,
  useLeadSources,
  type ActivityKind,
  type Interest,
  type LeadDetail,
  type LeadStage,
  type Priority,
  type Temperature,
} from "~/data/leads";
import { ErrorBlock } from "~/shell/states";
import {
  Badge,
  Banner,
  Button,
  CheckboxGroup,
  ConfirmDialog,
  DatePicker,
  DateText,
  Drawer,
  EmptyState,
  GlassPanel,
  KeyValue,
  Modal,
  RadioGroup,
  ReasonDialog,
  Select,
  SkeletonText,
  Textarea,
  TextField,
  Timeline,
  toast,
} from "~/ui";
import {
  ACTIVITY_ICON,
  ACTIVITY_KINDS,
  ACTIVITY_LABEL,
  followUpState,
  INTEREST_LABEL,
  INTERESTS,
  isoToday,
  LEAD_STAGE_HINT,
  LEAD_STAGE_LABEL,
  LEAD_STAGE_TONE,
  OPEN_LEAD_STAGES,
  PRIORITIES,
  PRIORITY_LABEL,
  TEMPERATURE_LABEL,
  TEMPERATURE_TONE,
  TEMPERATURES,
} from "./labels";

const addDays = (iso: string, days: number) => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
};

/** The follow-up date as a short phrase with its state, for fact strips and the overview. */
export function FollowUpValue({ due }: { due: string | null | undefined }) {
  const zone = useZone();
  const state = followUpState(due, isoToday(zone.timeZone));
  if (!due) return <span className="text-ink-3">None set</span>;
  return (
    <span className="inline-flex items-center gap-2">
      <DateText value={due} />
      {state === "overdue" ? (
        <Badge tone="amber" size="sm" icon="clock">
          Overdue
        </Badge>
      ) : state === "today" ? (
        <Badge tone="gold" size="sm">
          Today
        </Badge>
      ) : null}
    </span>
  );
}

export function LeadStageBadge({ stage }: { stage: LeadStage }) {
  return (
    <Badge tone={LEAD_STAGE_TONE[stage]} dot>
      {LEAD_STAGE_LABEL[stage]}
    </Badge>
  );
}

// ---- overview panel ------------------------------------------------------------------------------------------
/** Where this lead stands in the pipeline and what the team knows about what they want. */
export function LeadPipelinePanel({ lead, onLog, onEdit }: { lead: LeadDetail; onLog?: () => void; onEdit?: () => void }) {
  const stage = lead.lead_stage;
  if (!stage) return null;
  const reached = OPEN_LEAD_STAGES.indexOf(stage);
  return (
    <GlassPanel padding="lg" className="rise flex min-w-0 flex-col gap-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1">
          <p className="t-overline text-ink-3">Pipeline</p>
          <h2 className="t-h3 text-ink">{LEAD_STAGE_HINT[stage]}</h2>
        </div>
        <div className="flex flex-wrap gap-2">
          {onEdit ? (
            <Button variant="ghost" size="sm" iconLeft="edit" onPress={onEdit}>
              Edit lead details
            </Button>
          ) : null}
          {onLog ? (
            <Button variant="inverse" size="sm" iconLeft="phone" onPress={onLog}>
              Log activity
            </Button>
          ) : null}
        </div>
      </div>
      <ol className="flex flex-wrap gap-2" aria-label="Pipeline stages">
        {OPEN_LEAD_STAGES.map((s, i) => {
          const done = stage !== "lost" && reached >= 0 && i < reached;
          const current = s === stage;
          return (
            <li key={s}>
              <Badge tone={current ? LEAD_STAGE_TONE[s] : done ? "leaf" : "neutral"} outline={!current && !done} icon={done ? "check" : undefined}>
                {LEAD_STAGE_LABEL[s]}
              </Badge>
            </li>
          );
        })}
        {stage === "lost" ? (
          <li>
            <Badge tone="ember">Lost</Badge>
          </li>
        ) : null}
      </ol>
      {stage === "lost" && lead.lost_reason ? (
        <Banner tone="ember" title="Why it was lost">
          {lead.lost_reason}
        </Banner>
      ) : null}
      <KeyValue
        columns={2}
        items={[
          { label: "Next follow-up", value: <FollowUpValue due={lead.next_follow_up_on} /> },
          { label: "Source", value: lead.lead_source?.label ?? null },
          { label: "Interested in", value: lead.interests?.length ? lead.interests.map((i) => INTEREST_LABEL[i]).join(", ") : null },
          {
            label: "Priority and temperature",
            value: lead.priority ? (
              <span className="inline-flex items-center gap-2">
                {PRIORITY_LABEL[lead.priority]}
                {lead.temperature ? (
                  <Badge tone={TEMPERATURE_TONE[lead.temperature]} size="sm">
                    {TEMPERATURE_LABEL[lead.temperature]}
                  </Badge>
                ) : null}
              </span>
            ) : null,
          },
          { label: "First contact", value: lead.first_contact_on ? <DateText value={lead.first_contact_on} /> : null },
          {
            label: "Website",
            value: lead.website ? (
              <a className="lk-link" href={/^https?:\/\//i.test(lead.website) ? lead.website : `https://${lead.website}`} target="_blank" rel="noreferrer noopener">
                {lead.website}
              </a>
            ) : null,
          },
        ]}
      />
      {lead.requirement ? (
        <div className="flex flex-col gap-1">
          <p className="t-label text-ink-2">What they asked for</p>
          <p className="t-body text-ink whitespace-pre-line">{lead.requirement}</p>
        </div>
      ) : null}
    </GlassPanel>
  );
}

// ---- log activity ----------------------------------------------------------------------------------------------
const FOLLOW_UP_PRESETS = [
  { days: 1, label: "Tomorrow" },
  { days: 3, label: "In 3 days" },
  { days: 7, label: "Next week" },
  { days: 14, label: "In 2 weeks" },
];

export function LogActivityModal({ lead, isOpen, onOpenChange }: { lead: LeadDetail; isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const formId = useId();
  const zone = useZone();
  const today = isoToday(zone.timeZone);
  const commands = useResourceCommand(`lead-activity:${lead.id}`, LEAD_INVALIDATE);
  const [kind, setKind] = useState<ActivityKind>("call");
  const [outcome, setOutcome] = useState("");
  const [notes, setNotes] = useState("");
  const [followUp, setFollowUp] = useState<string | null>(addDays(today, 3));
  const [submitted, setSubmitted] = useState(false);
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  const empty = !outcome.trim() && !notes.trim();
  const closed = lead.lead_stage === "won" || lead.lead_stage === "lost";

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (empty || commands.pending || commands.offline) return;
    const body = {
      kind,
      outcome: outcome.trim() || null,
      notes: notes.trim() || null,
      next_follow_up_on: closed ? null : followUp,
    };
    setServerErrors({});
    const result = await commands.run("log", [JSON.stringify(body)], (key) => logActivity(lead.id, body, key), {
      failed: "The activity was not saved",
      conflictMessage: "This lead changed. Try again.",
    });
    if (result.ok) {
      toast.success(body.next_follow_up_on ? "Logged. The follow-up is in Today on that date." : "Activity logged");
      onOpenChange(false);
    } else {
      setServerErrors(fieldErrorsFrom(result.error));
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      title="Log activity"
      description={`What happened with ${lead.display_name}, and when to follow up.`}
      actions={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" form={formId} loading={commands.pending === "log"} isDisabled={Boolean(commands.offline)}>
            Save activity
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={(event) => void submit(event)} noValidate className="flex flex-col gap-5">
        {commands.offline ? <Banner tone="amber" title="You are offline.">Reconnect to save. What you typed stays here.</Banner> : null}
        <RadioGroup
          label="What was it"
          orientation="horizontal"
          options={ACTIVITY_KINDS.map((k) => ({ value: k, label: ACTIVITY_LABEL[k] }))}
          value={kind}
          onChange={(value) => setKind(ACTIVITY_KINDS.find((k) => k === value) ?? "call")}
        />
        <TextField
          label="Outcome"
          optional
          value={outcome}
          onChange={setOutcome}
          maxLength={200}
          placeholder="Sent the riser catalogue"
          autoFocus
          error={submitted && empty ? "Add an outcome or a note." : serverErrors.outcome}
        />
        <Textarea label="Notes" optional value={notes} onChange={setNotes} maxLength={4000} rows={3} error={serverErrors.notes} />
        {closed ? (
          <p className="t-body-sm text-ink-3">This lead is {LEAD_STAGE_LABEL[lead.lead_stage!].toLowerCase()}, so no follow-up is set.</p>
        ) : (
          <div className="flex flex-col gap-3">
            <DatePicker
              label="Next follow-up"
              optional
              value={followUp}
              onChange={setFollowUp}
              minValue={today}
              help="The lead's owner gets a task on this day. Leave it empty if there is nothing to chase."
              error={serverErrors.next_follow_up_on}
            />
            <div className="flex flex-wrap gap-2">
              {FOLLOW_UP_PRESETS.map((p) => (
                <Button key={p.days} variant="secondary" size="sm" onPress={() => setFollowUp(addDays(today, p.days))}>
                  {p.label}
                </Button>
              ))}
              <Button variant="ghost" size="sm" onPress={() => setFollowUp(null)}>
                No follow-up
              </Button>
            </div>
          </div>
        )}
      </form>
    </Modal>
  );
}

// ---- stage dialogs ---------------------------------------------------------------------------------------------
export type StageDialog = "move" | "won" | "lost" | null;

export function StageDialogs({ lead, open, onClose }: { lead: LeadDetail; open: StageDialog; onClose: () => void }) {
  const queryClient = useQueryClient();
  const commands = useResourceCommand(`lead-stage:${lead.id}`, LEAD_INVALIDATE);
  const [target, setTarget] = useState<LeadStage>(lead.lead_stage === "lost" ? "contacted" : (lead.lead_stage ?? "new"));

  const move = async (stage: LeadStage, lost_reason?: string) => {
    const body = { expected_version: lead.version, stage, lost_reason: lost_reason ?? null };
    const result = await commands.run("stage", [lead.version, stage], (key) => changeLeadStage(lead.id, body, key), {
      failed: "The stage was not changed",
      conflictMessage: "This lead changed since you opened it. The latest version is showing; try again.",
    });
    if (result.ok) {
      queryClient.setQueryData(leadKeys.detail(lead.id), result.value);
      toast.success(stage === "won" ? `${lead.display_name} is now a customer` : `Moved to ${LEAD_STAGE_LABEL[stage]}`);
      onClose();
      return;
    }
    throw result.error;
  };

  return (
    <>
      <Modal
        isOpen={open === "move"}
        onOpenChange={(isOpen) => (isOpen ? null : onClose())}
        size="sm"
        title="Move stage"
        description={lead.lead_stage === "lost" ? "Reopen this lead at the stage it is at now." : "Where this lead stands now."}
        actions={
          <>
            <Button variant="ghost" onPress={onClose}>
              Cancel
            </Button>
            <Button loading={commands.pending === "stage"} isDisabled={target === lead.lead_stage || Boolean(commands.offline)} onPress={() => void move(target).catch(() => undefined)}>
              Move to {LEAD_STAGE_LABEL[target]}
            </Button>
          </>
        }
      >
        <RadioGroup
          label="Stage"
          hideLabel
          options={OPEN_LEAD_STAGES.map((s) => ({ value: s, label: LEAD_STAGE_LABEL[s], description: LEAD_STAGE_HINT[s] }))}
          value={target}
          onChange={(value) => setTarget(OPEN_LEAD_STAGES.find((s) => s === value) ?? target)}
        />
      </Modal>
      <ConfirmDialog
        isOpen={open === "won"}
        onOpenChange={(isOpen) => (isOpen ? null : onClose())}
        title={`Mark ${lead.display_name} as won`}
        description="They become a customer: they move to the customer list and their follow-up closes. This cannot be undone from here."
        confirmLabel="Mark as won"
        onConfirm={() => move("won")}
      />
      <ReasonDialog
        isOpen={open === "lost"}
        onOpenChange={(isOpen) => (isOpen ? null : onClose())}
        tone="danger"
        title={`Mark ${lead.display_name} as lost`}
        description="Their follow-up closes. You can reopen the lead later."
        reasonLabel="Why was it lost"
        reasonHelp="For example: chose a local supplier, price too high, no budget this year."
        confirmLabel="Mark as lost"
        loading={commands.pending === "stage"}
        onConfirm={(reason) => move("lost", reason)}
      />
    </>
  );
}

// ---- lead details ----------------------------------------------------------------------------------------------
const NO_SOURCE = "none";

export function LeadDetailsDrawer({ lead, isOpen, onOpenChange }: { lead: LeadDetail; isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const formId = useId();
  const queryClient = useQueryClient();
  const sources = useLeadSources(isOpen);
  const commands = useResourceCommand(`lead-fields:${lead.id}`, LEAD_INVALIDATE);
  const [source, setSource] = useState(lead.lead_source?.code ?? NO_SOURCE);
  const [interests, setInterests] = useState<Interest[]>(lead.interests ?? []);
  const [priority, setPriority] = useState<Priority>(lead.priority ?? "B");
  const [temperature, setTemperature] = useState<Temperature>(lead.temperature ?? "cold");
  const [website, setWebsite] = useState(lead.website ?? "");
  const [requirement, setRequirement] = useState(lead.requirement ?? "");
  const [firstContact, setFirstContact] = useState<string | null>(lead.first_contact_on ?? null);
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});

  const options = (sources.data ?? []).filter((s) => s.is_active || s.code === lead.lead_source?.code);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (commands.pending || commands.offline) return;
    const body = {
      expected_version: lead.version,
      lead_source: source === NO_SOURCE ? null : source,
      interests,
      priority,
      temperature,
      website: website.trim() || null,
      requirement: requirement.trim() || null,
      ...(firstContact ? { first_contact_on: firstContact } : {}),
    };
    setServerErrors({});
    const result = await commands.run("fields", [lead.version, JSON.stringify(body)], (key) => updateLeadFields(lead.id, body, key), {
      failed: "The lead details were not saved",
      conflictMessage: "Someone else changed this lead. Close the form and open it again.",
    });
    if (result.ok) {
      queryClient.setQueryData(leadKeys.detail(lead.id), result.value);
      toast.success("Lead details saved");
      onOpenChange(false);
    } else if (!result.conflict) {
      setServerErrors(fieldErrorsFrom(result.error));
    }
  };

  return (
    <Drawer
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      title="Lead details"
      description={`${lead.party_number} · ${lead.display_name}`}
      footer={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" form={formId} loading={commands.pending === "fields"} isDisabled={Boolean(commands.offline)}>
            Save details
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={(event) => void submit(event)} noValidate className="flex flex-col gap-5">
        <Select
          label="Source"
          options={[{ value: NO_SOURCE, label: "Not known" }, ...options.map((s) => ({ value: s.code, label: s.label }))]}
          value={source}
          onChange={(value) => setSource(value ?? NO_SOURCE)}
          help="Add trade shows in Settings, Lead sources."
          error={serverErrors.lead_source}
        />
        <CheckboxGroup
          label="Interested in"
          options={INTERESTS.map((i) => ({ value: i, label: INTEREST_LABEL[i] }))}
          value={interests}
          onChange={(value) => setInterests(INTERESTS.filter((i) => value.includes(i)))}
        />
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          <Select label="Priority" options={PRIORITIES.map((p) => ({ value: p, label: PRIORITY_LABEL[p] }))} value={priority} onChange={(value) => setPriority(PRIORITIES.find((p) => p === value) ?? priority)} />
          <Select
            label="Temperature"
            options={TEMPERATURES.map((t) => ({ value: t, label: TEMPERATURE_LABEL[t] }))}
            value={temperature}
            onChange={(value) => setTemperature(TEMPERATURES.find((t) => t === value) ?? temperature)}
          />
        </div>
        <Textarea label="What they asked for" optional value={requirement} onChange={setRequirement} maxLength={2000} rows={3} error={serverErrors.requirement} />
        <TextField label="Website" optional value={website} onChange={setWebsite} maxLength={200} placeholder="www.example.com" error={serverErrors.website} />
        <DatePicker label="First contact" optional value={firstContact} onChange={setFirstContact} help="When the relationship started." />
      </form>
    </Drawer>
  );
}

// ---- activity log view -----------------------------------------------------------------------------------------
export function ActivityLogView({ partyId, onLog }: { partyId: string; onLog?: () => void }) {
  const query = useActivities(partyId);
  if (query.isPending) {
    return (
      <GlassPanel padding="lg">
        <SkeletonText lines={5} />
      </GlassPanel>
    );
  }
  if (query.isError) return <ErrorBlock error={query.error} what="The activity log" onRetry={() => void query.refetch()} />;
  const items = query.data.pages.flatMap((p) => p.items);
  if (items.length === 0) {
    return (
      <GlassPanel padding="lg">
        <EmptyState
          icon="phone"
          title="No calls or meetings logged yet"
          text="Log each call, email or visit. Set a follow-up and the lead's owner sees it in Today on that day."
          actions={
            onLog ? (
              <Button iconLeft="phone" onPress={onLog}>
                Log activity
              </Button>
            ) : undefined
          }
        />
      </GlassPanel>
    );
  }
  return (
    <GlassPanel padding="lg" className="flex min-w-0 flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="t-h4 text-ink">Calls and follow-ups</h2>
        {onLog ? (
          <Button variant="secondary" size="sm" iconLeft="plus" onPress={onLog}>
            Log activity
          </Button>
        ) : null}
      </div>
      <Timeline
        label="Activity log"
        items={items.map((a) => ({
          id: a.id,
          icon: ACTIVITY_ICON[a.kind],
          title: (
            <span>
              <span className="t-label">{ACTIVITY_LABEL[a.kind]}</span>
              {a.outcome ? `: ${a.outcome}` : ""}
            </span>
          ),
          meta: (
            <span className="inline-flex flex-wrap items-center gap-2">
              <DateText value={a.occurred_at} style="relative" />
              <span>{a.created_by.display_name ?? ""}</span>
              {a.next_follow_up_on ? (
                <span className="inline-flex items-center gap-1">
                  · follow up <DateText value={a.next_follow_up_on} />
                </span>
              ) : null}
            </span>
          ),
          body: a.notes ? <p className="t-body-sm whitespace-pre-line text-ink-2">{a.notes}</p> : undefined,
        }))}
      />
      {query.hasNextPage ? (
        <Button variant="ghost" size="sm" loading={query.isFetchingNextPage} onPress={() => void query.fetchNextPage()}>
          Show older activity
        </Button>
      ) : null}
    </GlassPanel>
  );
}
