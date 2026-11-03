"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { StatusPill, type Tone } from "@/components/ui/badge";
import { Button, unavailableWhen } from "@/components/ui/button";
import { Switch } from "@/components/ui/choice";
import { Dialog } from "@/components/ui/dialog";
import { LocalDateTime, RelativeTime } from "@/components/ui/format";
import { LinkButton } from "@/components/ui/link";
import { SectionCard } from "@/components/ui/section-card";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { toast } from "@/components/ui/toast";
import { isProblemError } from "@/lib/api/client";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { channelsMessages } from "@/messages/channels";
import {
  CONSENT_PURPOSES,
  createEnrolment,
  fetchIdentities,
  groupCode,
  unlinkIdentity,
  updateConsent,
  type Account,
  type ConsentPurpose,
  type Enrolment,
  type Identity,
} from "./api";

const m = channelsMessages;

export const IDENTITY_TONE: Record<Identity["status"], Tone> = { pending: "neutral", active: "success", suspended: "warning", revoked: "neutral" };

function useInvalidateChannels() {
  const client = useQueryClient();
  return () => Promise.all(invalidationMap["channels.changed"].map((queryKey) => client.invalidateQueries({ queryKey })));
}

/** "Link my WhatsApp": a one-time code (shown once), its expiry and the prefilled wa.me link. */
export function LinkCard({ account }: { account: Account }) {
  const invalidate = useInvalidateChannels();
  const [enrolment, setEnrolment] = useState<Enrolment | null>(null);
  const create = useMutation({
    mutationFn: () => createEnrolment(),
    onSuccess: (result) => {
      setEnrolment(result);
      void invalidate();
    },
  });
  const reauth = isProblemError(create.error) && create.error.code === "reauth_required";
  return (
    <SectionCard title={m.link.title} description={m.link.description}>
      {enrolment ? (
        <div className="flex flex-col gap-3" aria-live="polite">
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <span className="text-sm text-ink-muted">{m.link.codeLabel}</span>
            <span className="font-mono text-3xl font-bold tracking-[0.2em] text-ink select-all" data-testid="enrolment-code">
              {groupCode(enrolment.code)}
            </span>
            <span className="text-sm text-ink-muted">
              {m.link.expires} <RelativeTime value={enrolment.expires_at} />
            </span>
          </div>
          <p className="text-sm text-ink">
            {m.link.sendHint} <span className="font-mono font-semibold select-all">{enrolment.message_text}</span>
          </p>
          <div className="flex flex-wrap gap-2">
            {enrolment.wa_me_link && account.mode === "live" ? (
              <LinkButton href={enrolment.wa_me_link} variant="primary" target="_blank" rel="noopener noreferrer">
                {m.link.openWhatsApp}
              </LinkButton>
            ) : null}
            <Button variant="secondary" onPress={() => create.mutate()} isPending={create.isPending} pendingLabel={m.link.creating}>
              {m.link.again}
            </Button>
          </div>
          {account.mode === "demo" ? <p className="text-sm text-ink-muted">{m.link.demoHint}</p> : null}
          {account.mode === "live" && !enrolment.wa_me_link ? <p className="text-sm text-ink-muted">{m.link.noPhone}</p> : null}
        </div>
      ) : (
        <div className="flex flex-col items-start gap-3">
          <Button variant="primary" onPress={() => create.mutate()} isPending={create.isPending} pendingLabel={m.link.creating}>
            {m.link.create}
          </Button>
          {reauth ? (
            <p role="alert" className="text-sm text-danger">
              {m.link.reauth}
            </p>
          ) : create.isError ? (
            <ErrorState error={create.error} what={m.link.title} compact />
          ) : null}
        </div>
      )}
    </SectionCard>
  );
}

function ConsentSwitches({ identity }: { identity: Identity }) {
  const invalidate = useInvalidateChannels();
  const save = useMutation({
    mutationFn: ({ purpose, on }: { purpose: ConsentPurpose; on: boolean }) => updateConsent(identity.id, purpose, on ? "opted_in" : "opted_out"),
    onSuccess: () => {
      toast.success(m.identities.consentSaved);
      void invalidate();
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : m.identities.consentTitle),
  });
  const allowed = identity.capabilities.update_consent?.allowed ?? false;
  const reason = allowed ? null : (identity.capabilities.update_consent?.reason_code ?? "not_active");
  return (
    <fieldset className="flex flex-col gap-1">
      <legend className="mb-1 text-sm font-semibold text-ink">{m.identities.consentTitle}</legend>
      {CONSENT_PURPOSES.map((purpose) => {
        const current = identity.consents[purpose];
        // replies to what the person wrote are allowed unless they opted out; proactive purposes need an opt-in
        const on = purpose === "assistant_replies" || purpose === "transactional" ? current !== "opted_out" : current === "opted_in";
        return (
          <Switch
            key={purpose}
            isSelected={on}
            isDisabled={!allowed || save.isPending}
            onChange={(next) => save.mutate({ purpose, on: next })}
            aria-description={reason ?? undefined}
          >
            {m.identities.consents[purpose]}
          </Switch>
        );
      })}
      <p className="mt-1 text-sm text-ink-muted">{m.identities.stopHint}</p>
    </fieldset>
  );
}

function UnlinkButton({ identity }: { identity: Identity }) {
  const invalidate = useInvalidateChannels();
  const [open, setOpen] = useState(false);
  const unlink = useMutation({
    mutationFn: () => unlinkIdentity(identity.id),
    onSuccess: () => {
      setOpen(false);
      toast.success(m.identities.unlinked);
      void invalidate();
    },
  });
  const capability = identity.capabilities.revoke;
  return (
    <>
      <Button variant="secondary" size="sm" onPress={() => setOpen(true)} {...unavailableWhen(capability?.allowed ? null : (capability?.reason_code ?? "not_active"))}>
        {m.identities.unlink}
      </Button>
      <Dialog
        role="alertdialog"
        size="sm"
        title={m.identities.confirmTitle}
        isOpen={open}
        onOpenChange={setOpen}
        footer={(close) => (
          <>
            <Button variant="secondary" onPress={close}>
              {m.admin.cancel}
            </Button>
            <Button variant="danger" onPress={() => unlink.mutate()} isPending={unlink.isPending} pendingLabel={m.identities.unlinking}>
              {m.identities.unlink}
            </Button>
          </>
        )}
      >
        <p className="text-ink">{m.identities.confirmBody}</p>
        {unlink.isError ? <ErrorState error={unlink.error} what={m.identities.title} compact /> : null}
      </Dialog>
    </>
  );
}

/** The signed-in user's linked numbers, each with its consent switches and Unlink. */
export function IdentitiesCard() {
  const query = useQuery({ queryKey: queryKeys.channels.identities("mine"), queryFn: ({ signal }) => fetchIdentities("mine", signal) });
  return (
    <SectionCard title={m.identities.title} description={m.identities.description}>
      {query.isPending ? (
        <Loading label={m.identities.what} rows={2} />
      ) : query.isError ? (
        <ErrorState error={query.error} what={m.identities.what} onRetry={() => void query.refetch()} />
      ) : query.data.length === 0 ? (
        <EmptyState title={m.identities.empty} />
      ) : (
        <ul className="flex flex-col divide-y">
          {query.data.map((identity) => (
            <li key={identity.id} className="flex flex-col gap-3 py-3 first:pt-0 last:pb-0 md:flex-row md:items-start md:justify-between">
              <div className="flex min-w-0 flex-col gap-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-mono font-semibold text-ink">{identity.wa_id_masked ?? identity.username ?? "WhatsApp"}</span>
                  <StatusPill tone={IDENTITY_TONE[identity.status]}>{m.identities.statuses[identity.status]}</StatusPill>
                </span>
                <span className="text-sm text-ink-muted">
                  {m.identities.columns.linked} <LocalDateTime value={identity.created_at} />
                  {identity.session_expires_at ? (
                    <>
                      {" · "}
                      {m.identities.columns.session} <LocalDateTime value={identity.session_expires_at} />
                    </>
                  ) : null}
                </span>
                {identity.status === "active" ? <ConsentSwitches identity={identity} /> : null}
              </div>
              <div className="shrink-0">
                <UnlinkButton identity={identity} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </SectionCard>
  );
}
