"use client";

import { useId, useState, type FormEvent } from "react";
import { cancelDelegation, createDelegation } from "@/app/(app)/settings/_lib/api";
import type { DelegationView } from "@/app/(app)/settings/_lib/types";
import { useSession } from "@/lib/session/context";
import { useDelegations, useRefreshIdentity } from "~/data/settings-access";
import { Page, PageHeader } from "~/shell/page";
import { ErrorBlock } from "~/shell/states";
import {
  Banner,
  Button,
  CheckboxGroup,
  ConfirmDialog,
  DataTable,
  DatePicker,
  DateText,
  EmptyState,
  GlassPanel,
  Icon,
  Modal,
  Select,
  Textarea,
  toast,
  type Column,
} from "~/ui";
import { dayToInstant, DELEGATION_REASONS, fieldErrors, formFailure, humanise, keyLabel, problemText, SETTINGS_CRUMB } from "./labels";
import { PeoplePicker, RequestStatusBadge, RowActions } from "./parts";

/** Who may reach your records while you are away, and whose records you may reach. */
export function Delegation() {
  const query = useDelegations("mine");
  const refresh = useRefreshIdentity();
  const [creating, setCreating] = useState({ open: false, round: 0 });
  const [cancelling, setCancelling] = useState<DelegationView | null>(null);

  const cancel = async (delegation: DelegationView) => {
    try {
      await cancelDelegation(delegation.id);
      toast.success("Delegation cancelled", { description: `${delegation.delegate_name} can no longer reach these records.` });
      await refresh();
    } catch (error) {
      toast.error("The delegation was not cancelled", { description: problemText(error) });
      throw error;
    }
  };

  const open = () => setCreating((state) => ({ open: true, round: state.round + 1 }));
  const delegateButton = (
    <Button iconLeft="users" onPress={open}>
      Delegate your records
    </Button>
  );

  const columns: Column<DelegationView>[] = [
    {
      key: "who",
      header: "From and to",
      primary: true,
      cell: (row) => (
        <span className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="t-label text-ink">{row.delegator_name}</span>
          <Icon name="arrowRight" size={14} className="text-ink-3" />
          <span className="sr-only">to</span>
          <span className="t-label text-ink">{row.delegate_name}</span>
        </span>
      ),
    },
    {
      key: "keys",
      header: "Permissions",
      cell: (row) => (
        <span className="t-body-sm line-clamp-2 text-ink-2" title={row.permission_keys.map(keyLabel).join(", ")}>
          {row.permission_keys.map(keyLabel).join(", ")}
        </span>
      ),
    },
    {
      key: "when",
      header: "When",
      cell: (row) => (
        <span className="flex min-w-0 flex-col">
          <span className="t-body-sm text-ink">
            <DateText value={row.starts_at} style="dayTime" /> to <DateText value={row.ends_at} style="dayTime" />
          </span>
          <span className="t-caption text-ink-3">{humanise(row.reason)}</span>
        </span>
      ),
    },
    { key: "status", header: "Status", cell: (row) => <RequestStatusBadge status={row.status} /> },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      mobileLabel: "Actions",
      cell: (row) =>
        row.capabilities.cancel.allowed ? (
          <RowActions>
            <Button variant="ghost" size="sm" onPress={() => setCancelling(row)}>
              Cancel delegation
            </Button>
          </RowActions>
        ) : null,
    },
  ];

  return (
    <Page>
      <PageHeader
        breadcrumb={[SETTINGS_CRUMB, { label: "Delegation" }]}
        title="Delegation"
        lead="Let a colleague work on your records while you are away. They must already hold the same permissions: delegation only lets them reach your records, for up to 90 days."
        actions={delegateButton}
      />

      {query.isError ? (
        <ErrorBlock error={query.error} what="Your delegations" onRetry={() => void query.refetch()} />
      ) : (
        <GlassPanel padding="none" className="rise" style={{ "--i": 1 } as React.CSSProperties}>
          <DataTable
            label="Delegations"
            columns={columns}
            rows={query.data?.items ?? []}
            rowKey={(row) => row.id}
            loading={query.isPending}
            skeletonRows={4}
            empty={
              <EmptyState
                icon="users"
                title="No delegations"
                text="Nobody acts on your records, and you act on nobody else's. Going on leave? Hand your records to a colleague first."
                actions={delegateButton}
              />
            }
          />
        </GlassPanel>
      )}

      <DelegateModal
        key={creating.round}
        isOpen={creating.open}
        onOpenChange={(isOpen) => setCreating((state) => ({ ...state, open: isOpen }))}
        delegableKeys={query.data?.delegable_keys ?? []}
        isLoading={query.isPending}
      />
      <ConfirmDialog
        isOpen={cancelling !== null}
        onOpenChange={(isOpen) => {
          if (!isOpen) setCancelling(null);
        }}
        tone="danger"
        title="Cancel this delegation"
        description={cancelling ? `${cancelling.delegate_name} stops reaching ${cancelling.delegator_name}'s records now.` : undefined}
        confirmLabel="Cancel delegation"
        cancelLabel="Keep it"
        onConfirm={() => (cancelling ? cancel(cancelling) : undefined)}
      />
    </Page>
  );
}

function DelegateModal({
  isOpen,
  onOpenChange,
  delegableKeys,
  isLoading,
}: {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  delegableKeys: readonly string[];
  isLoading: boolean;
}) {
  const formId = useId();
  const refresh = useRefreshIdentity();
  const { bootstrap } = useSession();
  const held = new Set(bootstrap.permissions.map((permission) => permission.key));
  const offerable = delegableKeys.filter((key) => held.has(key));
  const [delegate, setDelegate] = useState<string | null>(null);
  const [keys, setKeys] = useState<string[]>([]);
  const [reason, setReason] = useState<string>("leave");
  const [starts, setStarts] = useState<string | null>(null);
  const [ends, setEnds] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const server = fieldErrors(error);
  const failure = formFailure(error);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (busy || !delegate || keys.length === 0 || !ends) return;
    setBusy(true);
    setError(null);
    try {
      await createDelegation({
        delegate_user_id: delegate,
        permission_keys: keys,
        reason,
        starts_at: dayToInstant(starts, "start"),
        ends_at: dayToInstant(ends, "end"),
        note: note.trim() || null,
      });
      toast.success("Delegation saved");
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
      size="lg"
      title="Delegate your records"
      description="Choose who, which permissions, and until when."
      actions={
        <>
          <Button variant="ghost" onPress={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" form={formId} loading={busy} isDisabled={!isLoading && offerable.length === 0}>
            Save delegation
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={(event) => void submit(event)} noValidate className="flex flex-col gap-5">
        {failure ? (
          <Banner tone="ember" title="The delegation was not saved.">
            {failure}
          </Banner>
        ) : null}
        <PeoplePicker
          label="Colleague"
          value={delegate}
          onChange={setDelegate}
          help="They must already hold the permissions you pick."
          error={server.delegate_user_id ?? (submitted && !delegate ? "Choose the colleague who covers for you." : undefined)}
        />
        {!isLoading && offerable.length === 0 ? (
          <Banner tone="neutral" title="Nothing you hold can be delegated.">
            Only some permissions can be handed over. Yours stay with you.
          </Banner>
        ) : (
          <CheckboxGroup
            label="Permissions"
            options={offerable.map((key) => ({ value: key, label: keyLabel(key) }))}
            value={keys}
            onChange={setKeys}
            help="Only the permissions you hold that can be delegated are listed."
            error={server.permission_keys ?? (submitted && keys.length === 0 ? "Tick at least one permission." : undefined)}
          />
        )}
        <div className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-3">
          <Select label="Reason" options={DELEGATION_REASONS.map((option) => ({ ...option }))} value={reason} onChange={setReason} error={server.reason} />
          <DatePicker label="Starts" optional value={starts} onChange={setStarts} help="Empty starts it now." error={server.starts_at} />
          <DatePicker
            label="Ends on"
            isRequired
            value={ends}
            onChange={setEnds}
            minValue={starts ?? undefined}
            help="At most 90 days away."
            error={server.ends_at ?? (submitted && !ends ? "Choose the last day." : undefined)}
          />
        </div>
        <Textarea label="Note" optional value={note} onChange={setNote} help="Anything your colleague should know." error={server.note} />
      </form>
    </Modal>
  );
}
