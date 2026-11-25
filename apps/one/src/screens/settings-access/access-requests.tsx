"use client";

import { useId, useState, type FormEvent } from "react";
import { decideAccessRequest, submitAccessRequest, withdrawAccessRequest } from "@/app/(app)/settings/_lib/api";
import type { AccessRequestView, Scope } from "@/app/(app)/settings/_lib/types";
import { conflictFromError } from "@/lib/api/errors";
import { useSession } from "@/lib/session/context";
import { useAccessRequests, usePermissionCatalogue, useRefreshIdentity } from "~/data/settings-access";
import { Page, PageHeader, PageSection } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import {
  Banner,
  Button,
  ConfirmDialog,
  DataTable,
  DateText,
  EmptyState,
  GlassPanel,
  IntegerField,
  Modal,
  Select,
  Textarea,
  TextField,
  toast,
  type Column,
} from "~/ui";
import { fieldErrors, formFailure, keyLabel, problemText, SCOPE_LABEL, scopeFrom, scopeOptions, SETTINGS_CRUMB } from "./labels";
import { PermissionPicker, RequestStatusBadge, RowActions } from "./parts";
import { useStepUp } from "./step-up";

type Pending = { request: AccessRequestView; kind: "reject" | "withdraw" } | null;

/** Ask for a permission for a set number of days. Approvers see what waits for them first. */
export function AccessRequests() {
  const { permissionKeys } = useSession();
  const approver = permissionKeys.has("identity.access_request.approve");
  const mine = useAccessRequests("mine");
  const all = useAccessRequests("all", approver);
  const refresh = useRefreshIdentity();
  const stepUp = useStepUp();
  const [asking, setAsking] = useState({ open: false, round: 0 });
  const [granting, setGranting] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending>(null);

  const decide = async (request: AccessRequestView, decision: "approve" | "reject") => {
    try {
      await stepUp.run(() => decideAccessRequest(request.id, { expected_version: request.version, decision }));
      toast.success(decision === "approve" ? "Access granted" : "Request rejected", {
        description: decision === "approve" ? `${request.requester_name} has it for ${days(request.duration_days)}.` : undefined,
      });
      await refresh();
    } catch (error) {
      toast.error(decision === "approve" ? "Access was not granted" : "The request was not rejected", { description: problemText(error) });
      if (conflictFromError(error)) await refresh();
      throw error;
    }
  };

  const grant = async (request: AccessRequestView) => {
    setGranting(request.id);
    try {
      await decide(request, "approve");
    } catch {
      // Reported by `decide`.
    } finally {
      setGranting(null);
    }
  };

  const withdraw = async (request: AccessRequestView) => {
    try {
      await withdrawAccessRequest(request.id);
      toast.success("Request withdrawn");
      await refresh();
    } catch (error) {
      toast.error("The request was not withdrawn", { description: problemText(error) });
      throw error;
    }
  };

  const actions = (request: AccessRequestView) => (
    <RowActions>
      {request.capabilities.decide.allowed ? (
        <>
          <Button variant="inverse" size="sm" iconLeft="check" loading={granting === request.id} onPress={() => void grant(request)}>
            Grant
          </Button>
          <Button variant="secondary" size="sm" onPress={() => setPending({ request, kind: "reject" })}>
            Reject
          </Button>
        </>
      ) : null}
      {request.capabilities.withdraw.allowed ? (
        <Button variant="ghost" size="sm" onPress={() => setPending({ request, kind: "withdraw" })}>
          Withdraw
        </Button>
      ) : null}
    </RowActions>
  );

  const toDecide = (all.data?.items ?? []).filter((request) => request.status === "pending");
  const askButton = (
    <Button iconLeft="key" onPress={() => setAsking((state) => ({ open: true, round: state.round + 1 }))}>
      Ask for access
    </Button>
  );

  return (
    <Page>
      <PageHeader
        breadcrumb={[SETTINGS_CRUMB, { label: "Access requests" }]}
        title="Access requests"
        lead="Ask for a permission you need for a while. An approver grants it for the days you ask, and it ends by itself."
        actions={askButton}
      />

      {approver ? (
        <PageSection index={0} title="Waiting for your decision" description="Granting gives the permission at once, for the days asked.">
          {all.isError ? (
            <ErrorBlock error={all.error} what="Requests to decide" onRetry={() => void all.refetch()} />
          ) : (
            <GlassPanel padding="none">
              <DataTable
                label="Requests waiting for a decision"
                columns={requestColumns({ withPerson: true, actions })}
                rows={toDecide}
                rowKey={(request) => request.id}
                loading={all.isPending}
                skeletonRows={3}
                empty={<EmptyState compact icon="checkCircle" title="Nothing waiting" text="Every request has a decision. New ones appear here as people ask." />}
              />
            </GlassPanel>
          )}
        </PageSection>
      ) : null}

      <PageSection index={1} title="Your requests">
        {mine.isError ? (
          <ErrorBlock error={mine.error} what="Your requests" onRetry={() => void mine.refetch()} />
        ) : (
          <GlassPanel padding="none">
            <DataTable
              label="Your access requests"
              columns={requestColumns({ withPerson: false, actions })}
              rows={mine.data?.items ?? []}
              rowKey={(request) => request.id}
              loading={mine.isPending}
              skeletonRows={3}
              empty={
                <EmptyState
                  compact
                  icon="key"
                  title="You have not asked for anything"
                  text="Missing a permission for a job? Ask for it here, say why, and choose for how many days."
                  actions={askButton}
                />
              }
            />
          </GlassPanel>
        )}
      </PageSection>

      <AskModal key={asking.round} isOpen={asking.open} onOpenChange={(open) => setAsking((state) => ({ ...state, open }))} />

      <ConfirmDialog
        isOpen={pending?.kind === "reject"}
        onOpenChange={(open) => {
          if (!open) setPending(null);
        }}
        tone="danger"
        title="Reject this request"
        description={pending ? `${pending.request.requester_name} does not get ${keyLabel(pending.request.permission_key)}. They can ask again.` : undefined}
        confirmLabel="Reject request"
        onConfirm={() => (pending ? decide(pending.request, "reject") : undefined)}
      />
      <ConfirmDialog
        isOpen={pending?.kind === "withdraw"}
        onOpenChange={(open) => {
          if (!open) setPending(null);
        }}
        title="Withdraw your request"
        description={pending ? `${keyLabel(pending.request.permission_key)} stays as it is. You can ask again later.` : undefined}
        confirmLabel="Withdraw request"
        cancelLabel="Keep it"
        onConfirm={() => (pending ? withdraw(pending.request) : undefined)}
      />
      {stepUp.dialog}
    </Page>
  );
}

const days = (count: number) => `${count} ${count === 1 ? "day" : "days"}`;

function requestColumns({ withPerson, actions }: { withPerson: boolean; actions: (request: AccessRequestView) => React.ReactNode }): Column<AccessRequestView>[] {
  return [
    ...(withPerson
      ? [
          {
            key: "who",
            header: "Person",
            cell: (request: AccessRequestView) => (
              <span className="flex min-w-0 flex-col">
                <span className="t-label text-ink">{request.requester_name}</span>
                <span className="t-caption text-ink-3">
                  Asked <DateText value={request.created_at} style="relative" />
                </span>
              </span>
            ),
          },
        ]
      : []),
    {
      key: "what",
      header: "Permission",
      primary: true,
      cell: (request) => (
        <span className="flex min-w-0 flex-col">
          <span className="t-label text-ink">{keyLabel(request.permission_key)}</span>
          <span className="t-caption text-ink-3">
            {SCOPE_LABEL[request.scope] ?? request.scope} · {days(request.duration_days)}
          </span>
        </span>
      ),
    },
    {
      key: "why",
      header: "Reason",
      cell: (request) => (
        <span className="t-body-sm line-clamp-2 text-ink-2" title={request.reason}>
          {request.reason}
        </span>
      ),
    },
    {
      key: "status",
      header: "Status",
      cell: (request) => (
        <span className="flex min-w-0 flex-col items-start gap-1">
          <RequestStatusBadge status={request.status} />
          {request.status === "approved" && request.grant_expires_at ? (
            <span className="t-caption text-ink-3">
              Until <DateText value={request.grant_expires_at} style="date" />
            </span>
          ) : null}
        </span>
      ),
    },
    { key: "actions", header: <span className="sr-only">Actions</span>, mobileLabel: "Actions", cell: actions },
  ];
}

/** The request form. The permission list needs role-reading rights, so without it the key is typed. */
function AskModal({ isOpen, onOpenChange }: { isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const formId = useId();
  const refresh = useRefreshIdentity();
  const catalogue = usePermissionCatalogue({ enabled: isOpen, retry: false });
  const [key, setKey] = useState<string | null>(null);
  const [typedKey, setTypedKey] = useState("");
  const [scope, setScope] = useState<Scope>("own");
  const [duration, setDuration] = useState<number | null>(7);
  const [reason, setReason] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const useCatalogue = catalogue.isSuccess;
  const permissionKey = useCatalogue ? key : typedKey.trim() || null;
  const server = fieldErrors(error);
  const failure = formFailure(error);
  const permission = useCatalogue ? (catalogue.data.items.find((item) => item.key === key) ?? null) : null;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (busy || !permissionKey || !reason.trim() || !duration || duration < 1) return;
    setBusy(true);
    setError(null);
    try {
      await submitAccessRequest({ permission_key: permissionKey, scope, reason: reason.trim(), duration_days: duration });
      toast.success("Request sent", { description: "An approver decides. You see the answer here." });
      onOpenChange(false);
      await refresh();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const keyError = server.permission_key ?? (submitted && !permissionKey ? "Choose the permission you need." : undefined);

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      title="Ask for access"
      description="Say what you need, how far it should reach, and for how long. It ends by itself."
      actions={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" form={formId} loading={busy} iconLeft="send">
            Send request
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={(event) => void submit(event)} noValidate className="flex flex-col gap-4">
        {failure ? (
          <Banner tone="ember" title="The request was not sent.">
            {failure}
          </Banner>
        ) : null}
        {useCatalogue || catalogue.isPending ? (
          <PermissionPicker
            permissions={catalogue.data?.items ?? []}
            isLoading={catalogue.isPending && isOpen}
            value={key}
            onChange={setKey}
            isRequired
            help={permission?.description}
            error={keyError}
          />
        ) : (
          <TextField
            label="Permission key"
            isRequired
            value={typedKey}
            onChange={setTypedKey}
            placeholder="sales.quote.read"
            help="Ask your manager for the exact key if you do not know it."
            error={keyError}
          />
        )}
        <div className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2">
          <Select label="Reach" options={scopeOptions()} value={scope} onChange={(value) => setScope(scopeFrom(value, scope))} error={server.scope} />
          <IntegerField
            label="For how many days"
            isRequired
            minValue={1}
            value={duration}
            onChange={setDuration}
            error={server.duration_days ?? (submitted && (!duration || duration < 1) ? "Enter at least 1 day." : undefined)}
          />
        </div>
        <Textarea
          label="Why you need it"
          isRequired
          value={reason}
          onChange={setReason}
          help="The approver reads this. Name the job or the customer."
          error={server.reason ?? (submitted && !reason.trim() ? "Say why, in a sentence." : undefined)}
        />
      </form>
    </Modal>
  );
}
