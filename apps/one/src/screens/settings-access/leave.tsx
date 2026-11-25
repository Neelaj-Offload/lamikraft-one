"use client";

import { useId, useState, type FormEvent, type ReactNode } from "react";
import { cancelAbsence, decideAbsence, requestAbsence } from "@/app/(app)/settings/_lib/api";
import type { AbsenceView } from "@/app/(app)/settings/_lib/types";
import { conflictFromError } from "@/lib/api/errors";
import { useAbsences, useRefreshIdentity } from "~/data/settings-access";
import { Page, PageHeader, PageSection } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import {
  Banner,
  Button,
  ConfirmDialog,
  DataTable,
  DateRangePicker,
  DateText,
  EmptyState,
  GlassPanel,
  Modal,
  Textarea,
  toast,
  type Column,
  type DateRange,
} from "~/ui";
import { fieldErrors, formFailure, problemText, SETTINGS_CRUMB } from "./labels";
import { PeoplePicker, RequestStatusBadge, RowActions } from "./parts";

type Pending = { absence: AbsenceView; kind: "reject" | "cancel" } | null;

/** Your time away, and the leave you approve for the people you look after. */
export function Leave() {
  const mine = useAbsences("mine");
  const team = useAbsences("team");
  const refresh = useRefreshIdentity();
  const [requesting, setRequesting] = useState({ open: false, round: 0 });
  const [pending, setPending] = useState<Pending>(null);
  const [approving, setApproving] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);

  const decide = async (absence: AbsenceView, decision: "approve" | "reject") => {
    try {
      await decideAbsence(absence.id, { expected_version: absence.version, decision });
      toast.success(decision === "approve" ? "Leave approved" : "Leave rejected");
      await refresh();
    } catch (error) {
      if (conflictFromError(error)) {
        setConflict(true);
        await refresh();
      } else {
        toast.error(decision === "approve" ? "The leave was not approved" : "The leave was not rejected", { description: problemText(error) });
      }
      throw error;
    }
  };

  const approve = async (absence: AbsenceView) => {
    setApproving(absence.id);
    try {
      await decide(absence, "approve");
    } catch {
      // Reported by `decide`.
    } finally {
      setApproving(null);
    }
  };

  const cancel = async (absence: AbsenceView) => {
    try {
      await cancelAbsence(absence.id);
      toast.success("Leave cancelled");
      await refresh();
    } catch (error) {
      toast.error("The leave was not cancelled", { description: problemText(error) });
      throw error;
    }
  };

  const actions = (absence: AbsenceView): ReactNode => (
    <RowActions>
      {absence.capabilities.decide.allowed ? (
        <>
          <Button variant="inverse" size="sm" iconLeft="check" loading={approving === absence.id} onPress={() => void approve(absence)}>
            Approve
          </Button>
          <Button variant="secondary" size="sm" onPress={() => setPending({ absence, kind: "reject" })}>
            Reject
          </Button>
        </>
      ) : null}
      {absence.capabilities.cancel.allowed ? (
        <Button variant="ghost" size="sm" onPress={() => setPending({ absence, kind: "cancel" })}>
          Cancel leave
        </Button>
      ) : null}
    </RowActions>
  );

  const open = () => setRequesting((state) => ({ open: true, round: state.round + 1 }));
  const requestButton = (
    <Button iconLeft="calendar" onPress={open}>
      Request leave
    </Button>
  );
  const teamRows = team.data?.items ?? [];
  const showTeam = teamRows.some((absence) => absence.capabilities.decide.allowed || absence.capabilities.cancel.allowed);

  return (
    <Page>
      <PageHeader
        breadcrumb={[SETTINGS_CRUMB, { label: "Leave" }]}
        title="Leave"
        lead="Record time away. Your manager approves it, and your open work can go to the cover you name."
        actions={requestButton}
      />

      {conflict ? (
        <Banner tone="amber" title="This leave changed before your decision landed." onClose={() => setConflict(false)}>
          The latest version is showing. Check it, then decide again.
        </Banner>
      ) : null}

      {showTeam ? (
        <PageSection index={0} title="To approve" description="Leave of the people you approve for.">
          <GlassPanel padding="none">
            <DataTable label="Leave to approve" columns={leaveColumns({ withPerson: true, actions })} rows={teamRows} rowKey={(absence) => absence.id} />
          </GlassPanel>
        </PageSection>
      ) : null}

      <PageSection index={1} title="Your leave">
        {mine.isError ? (
          <ErrorBlock error={mine.error} what="Your leave" onRetry={() => void mine.refetch()} />
        ) : (
          <GlassPanel padding="none">
            <DataTable
              label="Your leave"
              columns={leaveColumns({ withPerson: false, actions })}
              rows={mine.data?.items ?? []}
              rowKey={(absence) => absence.id}
              loading={mine.isPending}
              skeletonRows={3}
              empty={
                <EmptyState
                  compact
                  icon="calendar"
                  title="No leave recorded"
                  text="Planning time away? Request it here so your manager can approve it and your work has cover."
                  actions={requestButton}
                />
              }
            />
          </GlassPanel>
        )}
      </PageSection>

      <RequestModal key={requesting.round} isOpen={requesting.open} onOpenChange={(isOpen) => setRequesting((state) => ({ ...state, open: isOpen }))} />

      <ConfirmDialog
        isOpen={pending?.kind === "reject"}
        onOpenChange={(isOpen) => {
          if (!isOpen) setPending(null);
        }}
        tone="danger"
        title="Reject this leave"
        description={pending ? `${pending.absence.display_name} is told it was not approved. They can ask again.` : undefined}
        confirmLabel="Reject leave"
        onConfirm={() => (pending ? decide(pending.absence, "reject") : undefined)}
      />
      <ConfirmDialog
        isOpen={pending?.kind === "cancel"}
        onOpenChange={(isOpen) => {
          if (!isOpen) setPending(null);
        }}
        tone="danger"
        title="Cancel this leave"
        description="The dates are freed and any approval falls away."
        confirmLabel="Cancel leave"
        cancelLabel="Keep it"
        onConfirm={() => (pending ? cancel(pending.absence) : undefined)}
      />
    </Page>
  );
}

function leaveColumns({ withPerson, actions }: { withPerson: boolean; actions: (absence: AbsenceView) => ReactNode }): Column<AbsenceView>[] {
  return [
    ...(withPerson ? [{ key: "who", header: "Person", primary: true, cell: (absence: AbsenceView) => <span className="t-label text-ink">{absence.display_name}</span> }] : []),
    {
      key: "dates",
      header: "Dates",
      primary: !withPerson,
      cell: (absence) => (
        <span className="flex min-w-0 flex-col">
          <span className="t-label text-ink">
            <DateText value={absence.starts_on} style="business" /> to <DateText value={absence.ends_on} style="business" />
          </span>
          {absence.note ? (
            <span className="t-caption line-clamp-1 text-ink-3" title={absence.note}>
              {absence.note}
            </span>
          ) : null}
        </span>
      ),
    },
    { key: "cover", header: "Cover", cell: (absence) => absence.cover_name ?? <span className="text-ink-3">No cover named</span> },
    {
      key: "status",
      header: "Status",
      cell: (absence) => (
        <span className="flex min-w-0 flex-col items-start gap-1">
          <RequestStatusBadge status={absence.status} />
          {absence.decided_by_name ? <span className="t-caption text-ink-3">By {absence.decided_by_name}</span> : null}
        </span>
      ),
    },
    { key: "actions", header: <span className="sr-only">Actions</span>, mobileLabel: "Actions", cell: actions },
  ];
}

function RequestModal({ isOpen, onOpenChange }: { isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const formId = useId();
  const refresh = useRefreshIdentity();
  const [dates, setDates] = useState<DateRange | null>(null);
  const [cover, setCover] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const server = fieldErrors(error);
  const failure = formFailure(error);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (busy || !dates) return;
    setBusy(true);
    setError(null);
    try {
      await requestAbsence({ starts_on: dates.start, ends_on: dates.end, cover_user_id: cover, note: note.trim() || null });
      toast.success("Leave requested", { description: "Your manager is asked to approve it." });
      onOpenChange(false);
      await refresh();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      title="Request leave"
      description="Dates and cover are enough. Leave out medical details."
      actions={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" form={formId} loading={busy}>
            Request leave
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={(event) => void submit(event)} noValidate className="flex flex-col gap-4">
        {failure ? (
          <Banner tone="ember" title="The leave was not requested.">
            {failure}
          </Banner>
        ) : null}
        <DateRangePicker
          label="First and last day"
          isRequired
          value={dates}
          onChange={setDates}
          error={server.starts_on ?? server.ends_on ?? (submitted && !dates ? "Choose your first and last day away." : undefined)}
        />
        <PeoplePicker label="Cover" optional value={cover} onChange={setCover} help="Who picks up your open work." error={server.cover_user_id} />
        <Textarea label="Note" optional value={note} onChange={setNote} error={server.note} />
      </form>
    </Modal>
  );
}
