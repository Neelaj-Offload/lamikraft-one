"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Form } from "react-aria-components";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { Dialog } from "@/components/ui/dialog";
import { LocalDate, LocalDateTime } from "@/components/ui/format";
import { ComboBox, Select } from "@/components/ui/select";
import { Conflict, EmptyState } from "@/components/ui/states";
import { TextArea, TextField } from "@/components/ui/text-field";
import { toast } from "@/components/ui/toast";
import { conflictFromError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { useSession } from "@/lib/session/context";
import {
  cancelAbsence,
  cancelDelegation,
  createDelegation,
  decideAbsence,
  decideAccessRequest,
  fetchAbsences,
  fetchAccessRequests,
  fetchCatalogue,
  fetchDelegations,
  requestAbsence,
  submitAccessRequest,
  withdrawAccessRequest,
} from "./api";
import { PeoplePicker } from "./people-picker";
import { useStepUp } from "./step-up";
import type { AbsenceView, AccessRequestView, DelegationView, Scope } from "./types";
import { fieldErrors, keyLabel, problemText, QueryState, RequestStatus, SCOPE_LABEL, Section, SettingsPage, useHasAny } from "./ui";

function useRefresh() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: queryKeys.identity.all() });
}

// ---- delegation -------------------------------------------------------------------------------------------------
export function DelegationScreen() {
  const refresh = useRefresh();
  const query = useQuery({ queryKey: queryKeys.identity.delegations("mine"), queryFn: ({ signal }) => fetchDelegations("mine", signal) });
  const { bootstrap } = useSession();
  const [open, setOpen] = useState(false);
  const [delegate, setDelegate] = useState<string | null>(null);
  const [keys, setKeys] = useState<string[]>([]);
  const [reason, setReason] = useState<string>("leave");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const errors = fieldErrors(error);
  const held = new Set(bootstrap.permissions.map((p) => p.key));
  const offerable = (query.data?.delegable_keys ?? []).filter((k) => held.has(k));

  async function save(form: FormData) {
    setBusy(true);
    setError(null);
    try {
      const ends = String(form.get("ends_on") ?? "");
      const starts = String(form.get("starts_on") ?? "");
      await createDelegation({
        delegate_user_id: delegate,
        permission_keys: keys,
        reason,
        starts_at: starts ? new Date(`${starts}T00:00:00`).toISOString() : null,
        ends_at: ends ? new Date(`${ends}T23:59:59`).toISOString() : null,
        note: String(form.get("note") ?? "").trim() || null,
      });
      toast.success("Delegation saved");
      setOpen(false);
      setKeys([]);
      await refresh();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <SettingsPage
      title="Delegation"
      intro="Let a colleague work on your records while you are away. They must already have the same permissions; delegation only lets them reach your records, for at most 90 days."
      actions={<Button variant="primary" onPress={() => setOpen(true)}>Delegate</Button>}
    >
      {query.isPending || query.isError ? (
        <QueryState isPending={query.isPending} error={query.error} what="your delegations" area="delegation" onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          caption="Delegations"
          hideCaption
          rows={query.data.items}
          rowId={(r) => r.id}
          columns={[
            { id: "who", header: "Between", isRowHeader: true, mobile: "title", mobileCell: (r: DelegationView) => `${r.delegator_name} → ${r.delegate_name}`, cell: (r: DelegationView) => `${r.delegator_name} → ${r.delegate_name}` },
            { id: "keys", header: "Permissions", mobile: "meta", cell: (r: DelegationView) => r.permission_keys.map(keyLabel).join(", ") },
            { id: "when", header: "When", cell: (r: DelegationView) => <><LocalDateTime value={r.starts_at} /> – <LocalDateTime value={r.ends_at} /></> },
            { id: "status", header: "Status", mobile: "status", cell: (r: DelegationView) => <RequestStatus status={r.status} /> },
            {
              id: "actions",
              header: "Actions",
              cell: (r: DelegationView) =>
                r.capabilities.cancel.allowed ? (
                  <Button size="sm" onPress={() => void cancelDelegation(r.id).then(refresh).catch((err: unknown) => toast.error(problemText(err)))}>
                    Cancel
                  </Button>
                ) : null,
            },
          ]}
          empty={<EmptyState title="No delegations">Nobody acts on your records, and you act on nobody else&apos;s records.</EmptyState>}
        />
      )}
      <Dialog isOpen={open} onOpenChange={setOpen} title="Delegate your records" description="Choose who, which permissions and until when.">
        <Form
          className="flex flex-col gap-3"
          validationErrors={errors}
          onSubmit={(event) => {
            event.preventDefault();
            void save(new FormData(event.currentTarget));
          }}
        >
          <PeoplePicker label="Colleague" value={delegate} onChange={setDelegate} errorMessage={errors.delegate_user_id} />
          <fieldset className="flex flex-col gap-1">
            <legend className="font-medium">Permissions</legend>
            {offerable.length === 0 ? <p className="text-sm text-ink-muted">You hold no permission that can be delegated.</p> : null}
            {offerable.map((k) => (
              <label key={k} className="flex items-center gap-2 text-sm">
                <input type="checkbox" className="focus-ring" checked={keys.includes(k)} onChange={(e) => setKeys(e.target.checked ? [...keys, k] : keys.filter((x) => x !== k))} />
                {keyLabel(k)}
              </label>
            ))}
            {errors.permission_keys ? <p className="text-sm text-danger">{errors.permission_keys}</p> : null}
          </fieldset>
          <Select label="Reason" options={[{ id: "leave", label: "Leave" }, { id: "travel", label: "Travel" }, { id: "workload", label: "Workload" }, { id: "other", label: "Other" }]} value={reason} onChange={(v) => setReason(v ?? "leave")} />
          <div className="grid gap-3 md:grid-cols-2">
            <TextField name="starts_on" label="Starts (blank: now)" type="date" />
            <TextField name="ends_on" label="Ends on" type="date" isRequired />
          </div>
          <TextArea name="note" label="Note (optional)" />
          {error && !Object.keys(errors).length ? <p role="alert" className="text-danger">{problemText(error)}</p> : null}
          <div className="flex justify-end">
            <Button type="submit" variant="primary" isPending={busy}>
              Save delegation
            </Button>
          </div>
        </Form>
      </Dialog>
    </SettingsPage>
  );
}

// ---- leave ------------------------------------------------------------------------------------------------------
function AbsenceTable({ rows, onDecide, onCancel }: { rows: AbsenceView[]; onDecide: (row: AbsenceView, decision: "approve" | "reject") => void; onCancel: (row: AbsenceView) => void }) {
  return (
    <DataTable
      caption="Leave"
      hideCaption
      rows={rows}
      rowId={(r) => r.id}
      columns={[
        { id: "who", header: "Person", isRowHeader: true, mobile: "title", mobileCell: (r: AbsenceView) => r.display_name, cell: (r: AbsenceView) => r.display_name },
        { id: "dates", header: "Dates", mobile: "meta", cell: (r: AbsenceView) => <><LocalDate value={r.starts_on} /> – <LocalDate value={r.ends_on} /></> },
        { id: "cover", header: "Cover", cell: (r: AbsenceView) => r.cover_name ?? "—" },
        { id: "status", header: "Status", mobile: "status", cell: (r: AbsenceView) => <RequestStatus status={r.status} /> },
        {
          id: "actions",
          header: "Actions",
          cell: (r: AbsenceView) => (
            <div className="flex gap-1">
              {r.capabilities.decide.allowed ? (
                <>
                  <Button size="sm" variant="primary" onPress={() => onDecide(r, "approve")}>
                    Approve
                  </Button>
                  <Button size="sm" onPress={() => onDecide(r, "reject")}>
                    Reject
                  </Button>
                </>
              ) : null}
              {r.capabilities.cancel.allowed ? (
                <Button size="sm" variant="quiet" onPress={() => onCancel(r)}>
                  Cancel
                </Button>
              ) : null}
            </div>
          ),
        },
      ]}
      empty={<EmptyState title="No leave recorded" headingLevel={3} />}
    />
  );
}

export function LeaveScreen() {
  const refresh = useRefresh();
  const mine = useQuery({ queryKey: queryKeys.identity.absences("mine"), queryFn: ({ signal }) => fetchAbsences("mine", signal) });
  const team = useQuery({ queryKey: queryKeys.identity.absences("team"), queryFn: ({ signal }) => fetchAbsences("team", signal) });
  const [open, setOpen] = useState(false);
  const [cover, setCover] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [conflict, setConflict] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const errors = fieldErrors(error);

  async function save(form: FormData) {
    setBusy(true);
    setError(null);
    try {
      await requestAbsence({
        starts_on: String(form.get("starts_on") ?? ""),
        ends_on: String(form.get("ends_on") ?? ""),
        cover_user_id: cover,
        note: String(form.get("note") ?? "").trim() || null,
      });
      toast.success("Leave requested");
      setOpen(false);
      await refresh();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  const decide = (row: AbsenceView, decision: "approve" | "reject") =>
    void decideAbsence(row.id, { expected_version: row.version, decision })
      .then(() => {
        toast.success(decision === "approve" ? "Leave approved" : "Leave rejected");
        return refresh();
      })
      .catch((err: unknown) => (conflictFromError(err) ? setConflict(err) : toast.error(problemText(err))));
  const cancel = (row: AbsenceView) => void cancelAbsence(row.id).then(refresh).catch((err: unknown) => toast.error(problemText(err)));

  return (
    <SettingsPage
      title="Leave"
      intro="Record time away. Your manager approves it, and your open work can be handed to the cover you name."
      actions={<Button variant="primary" onPress={() => setOpen(true)}>Request leave</Button>}
    >
      {conflict ? (
        <Conflict
          conflict={conflictFromError(conflict)!}
          onReview={() => {
            setConflict(null);
            void refresh();
          }}
        />
      ) : null}
      <Section title="My leave">
        {mine.isPending || mine.isError ? (
          <QueryState isPending={mine.isPending} error={mine.error} what="your leave" area="leave" onRetry={() => void mine.refetch()} />
        ) : (
          <AbsenceTable rows={mine.data.items} onDecide={decide} onCancel={cancel} />
        )}
      </Section>
      {team.data && team.data.items.some((r) => r.capabilities.decide.allowed || r.capabilities.cancel.allowed) ? (
        <Section title="To approve" description="Leave of the people you approve for.">
          <AbsenceTable rows={team.data.items} onDecide={decide} onCancel={cancel} />
        </Section>
      ) : null}
      <Dialog isOpen={open} onOpenChange={setOpen} title="Request leave" description="No medical details, please: dates and cover are enough.">
        <Form
          className="flex flex-col gap-3"
          validationErrors={errors}
          onSubmit={(event) => {
            event.preventDefault();
            void save(new FormData(event.currentTarget));
          }}
        >
          <div className="grid gap-3 md:grid-cols-2">
            <TextField name="starts_on" label="First day" type="date" isRequired />
            <TextField name="ends_on" label="Last day" type="date" isRequired />
          </div>
          <PeoplePicker label="Cover (optional)" value={cover} onChange={setCover} errorMessage={errors.cover_user_id} />
          <TextArea name="note" label="Note (optional)" />
          {error && !Object.keys(errors).length ? <p role="alert" className="text-danger">{problemText(error)}</p> : null}
          <div className="flex justify-end">
            <Button type="submit" variant="primary" isPending={busy}>
              Request
            </Button>
          </div>
        </Form>
      </Dialog>
    </SettingsPage>
  );
}

// ---- access requests --------------------------------------------------------------------------------------------
export function AccessRequestsScreen() {
  const refresh = useRefresh();
  const approver = useHasAny("identity.access_request.approve");
  const mine = useQuery({ queryKey: queryKeys.identity.accessRequests("mine"), queryFn: ({ signal }) => fetchAccessRequests("mine", signal) });
  const all = useQuery({ queryKey: queryKeys.identity.accessRequests("all"), queryFn: ({ signal }) => fetchAccessRequests("all", signal), enabled: approver });
  const catalogue = useQuery({ queryKey: queryKeys.identity.catalogue(), queryFn: ({ signal }) => fetchCatalogue(signal), retry: false });
  const stepUp = useStepUp();
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState<string | null>(null);
  const [scope, setScope] = useState<Scope>("own");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const errors = fieldErrors(error);

  async function save(form: FormData) {
    setBusy(true);
    setError(null);
    try {
      await submitAccessRequest({
        permission_key: key ?? String(form.get("permission_key") ?? "").trim(),
        scope,
        reason: String(form.get("reason") ?? "").trim(),
        duration_days: Number.parseInt(String(form.get("duration_days") ?? "7"), 10),
      });
      toast.success("Request sent");
      setOpen(false);
      await refresh();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  const decide = (row: AccessRequestView, decision: "approve" | "reject") =>
    void stepUp
      .run(() => decideAccessRequest(row.id, { expected_version: row.version, decision }))
      .then(() => {
        toast.success(decision === "approve" ? "Access granted" : "Request rejected");
        return refresh();
      })
      .catch((err: unknown) => toast.error(problemText(err)));

  const table = (rows: AccessRequestView[], caption: string) => (
    <DataTable
      caption={caption}
      hideCaption
      rows={rows}
      rowId={(r) => r.id}
      columns={[
        { id: "who", header: "Person", isRowHeader: true, mobile: "title", mobileCell: (r: AccessRequestView) => r.requester_name, cell: (r: AccessRequestView) => r.requester_name },
        { id: "what", header: "Permission", mobile: "meta", cell: (r: AccessRequestView) => `${keyLabel(r.permission_key)} · ${SCOPE_LABEL[r.scope]} · ${r.duration_days} days` },
        { id: "why", header: "Reason", cell: (r: AccessRequestView) => r.reason },
        { id: "status", header: "Status", mobile: "status", cell: (r: AccessRequestView) => <RequestStatus status={r.status} /> },
        {
          id: "actions",
          header: "Actions",
          cell: (r: AccessRequestView) => (
            <div className="flex gap-1">
              {r.capabilities.decide.allowed ? (
                <>
                  <Button size="sm" variant="primary" onPress={() => decide(r, "approve")}>
                    Grant
                  </Button>
                  <Button size="sm" onPress={() => decide(r, "reject")}>
                    Reject
                  </Button>
                </>
              ) : null}
              {r.capabilities.withdraw.allowed ? (
                <Button size="sm" variant="quiet" onPress={() => void withdrawAccessRequest(r.id).then(refresh).catch((err: unknown) => toast.error(problemText(err)))}>
                  Withdraw
                </Button>
              ) : null}
            </div>
          ),
        },
      ]}
      empty={<EmptyState title="No requests" headingLevel={3} />}
    />
  );

  return (
    <SettingsPage
      title="Access requests"
      intro="Ask for a permission you need for a while. An approver grants it for a limited time, and it ends by itself."
      actions={<Button variant="primary" onPress={() => setOpen(true)}>Ask for access</Button>}
    >
      <Section title="My requests">
        {mine.isPending || mine.isError ? (
          <QueryState isPending={mine.isPending} error={mine.error} what="your requests" area="access requests" onRetry={() => void mine.refetch()} />
        ) : (
          table(mine.data.items, "My access requests")
        )}
      </Section>
      {approver ? (
        <Section title="Requests to decide">
          {all.isPending || all.isError ? (
            <QueryState isPending={all.isPending} error={all.error} what="the requests" area="access requests" onRetry={() => void all.refetch()} />
          ) : (
            table(all.data.items.filter((r) => r.status === "pending"), "Pending access requests")
          )}
        </Section>
      ) : null}
      <Dialog isOpen={open} onOpenChange={setOpen} title="Ask for access">
        <Form
          className="flex flex-col gap-3"
          validationErrors={errors}
          onSubmit={(event) => {
            event.preventDefault();
            void save(new FormData(event.currentTarget));
          }}
        >
          {catalogue.data ? (
            <ComboBox label="Permission" options={catalogue.data.items.map((p) => ({ id: p.key, label: p.key }))} value={key} onChange={setKey} isRequired errorMessage={errors.permission_key} />
          ) : (
            <TextField name="permission_key" label="Permission key" description="For example sales.quote.read" isRequired />
          )}
          <Select label="Scope" options={(["own", "team", "branch", "company"] as const).map((s) => ({ id: s, label: SCOPE_LABEL[s]! }))} value={scope} onChange={(v) => setScope((v as Scope | null) ?? "own")} />
          <TextField name="duration_days" label="For how many days" type="number" defaultValue="7" isRequired />
          <TextArea name="reason" label="Why you need it" isRequired />
          {error && !Object.keys(errors).length ? <p role="alert" className="text-danger">{problemText(error)}</p> : null}
          <div className="flex justify-end">
            <Button type="submit" variant="primary" isPending={busy}>
              Send request
            </Button>
          </div>
        </Form>
      </Dialog>
      {stepUp.dialog}
    </SettingsPage>
  );
}
