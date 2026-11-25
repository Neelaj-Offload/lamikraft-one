"use client";

import { useState } from "react";
import { CONSENT_PURPOSES, groupCode, type Account, type ConsentPurpose, type Enrolment, type Identity } from "@/features/channels/api";
import { isProblemError } from "@/lib/api/errors";
import { useCreateEnrolment, useMyIdentities, useUnlinkIdentity, useUpdateConsent } from "~/data/settings-ai";
import { ErrorBlock, QueryView } from "~/shell/states";
import { Badge, Banner, Button, ButtonLink, ConfirmDialog, DateText, EmptyState, GlassPanel, Switch, type Tone } from "~/ui";

// ---- link a phone ----

/**
 * "Link your phone": a one-time code (the server shows it once), when it expires, and where to
 * send it. In demo mode there is no phone to send from, so the code goes to the simulator.
 */
export function LinkPanel({
  account,
  enrolment,
  onEnrolment,
  onUseInSimulator,
}: {
  account: Account;
  enrolment: Enrolment | null;
  onEnrolment: (enrolment: Enrolment) => void;
  /** Demo mode only: put the link message in the simulator's message box. */
  onUseInSimulator?: (text: string) => void;
}) {
  const create = useCreateEnrolment();
  const createCode = () => create.mutate(undefined, { onSuccess: onEnrolment });
  const reauth = isProblemError(create.error) && create.error.code === "reauth_required";
  const problem = reauth ? (
    <Banner tone="amber" title="Linking a phone needs a recent sign-in.">
      Sign out, sign in again with your password, then create the code.
    </Banner>
  ) : create.isError ? (
    <ErrorBlock error={create.error} what="The link code" onRetry={createCode} />
  ) : null;

  return (
    <GlassPanel as="section" padding="lg" title="Link your phone" titleAs="h2" className="rise">
      <div className="flex flex-col gap-5">
        <p className="t-body text-ink-2">
          Create a one-time code and send it from your phone. It works for 10 minutes. A phone number proves nothing on its own: the code is what ties
          it to you.
        </p>

        {enrolment ? (
          <div className="flex flex-col gap-5" aria-live="polite">
            <GlassPanel variant="solid" padding="md" className="flex flex-col gap-2">
              <p className="t-caption text-ink-3">Your code</p>
              <p className="t-stat lk-mono select-all text-ink" style={{ letterSpacing: "0.14em" }}>
                {groupCode(enrolment.code)}
              </p>
              <p className="t-body-sm text-ink-3">
                Expires <DateText value={enrolment.expires_at} style="relative" />. It is shown only this once.
              </p>
            </GlassPanel>
            <p className="t-body text-ink">
              Send this message to the company WhatsApp number: <span className="t-code lk-mono select-all">{enrolment.message_text}</span>
            </p>
            <div className="flex flex-wrap gap-2">
              {enrolment.wa_me_link && account.mode === "live" ? (
                <ButtonLink href={enrolment.wa_me_link} external target="_blank" variant="primary" iconRight="external">
                  Open WhatsApp
                </ButtonLink>
              ) : null}
              {account.mode === "demo" && onUseInSimulator ? (
                <Button variant="inverse" iconLeft="send" onPress={() => onUseInSimulator(enrolment.message_text)}>
                  Put it in the simulator
                </Button>
              ) : null}
              <Button variant="secondary" iconLeft="refresh" loading={create.isPending} onPress={createCode}>
                Create a new code
              </Button>
            </div>
            {account.mode === "demo" ? (
              <p className="t-body-sm text-ink-3">Demo: there is no real phone here, so send the code from the simulator.</p>
            ) : null}
            {account.mode === "live" && !enrolment.wa_me_link ? (
              <p className="t-body-sm text-ink-3">The company number is not set up yet, so there is no WhatsApp link to open.</p>
            ) : null}
            {problem}
          </div>
        ) : (
          <div className="flex flex-col items-start gap-4">
            <Button variant="primary" iconLeft="key" loading={create.isPending} onPress={createCode}>
              Create link code
            </Button>
            {problem}
          </div>
        )}
      </div>
    </GlassPanel>
  );
}

// ---- linked numbers ----

const IDENTITY_STATE: Record<Identity["status"], { label: string; tone: Tone }> = {
  pending: { label: "Not linked", tone: "neutral" },
  active: { label: "Linked", tone: "leaf" },
  suspended: { label: "Suspended", tone: "amber" },
  revoked: { label: "Unlinked", tone: "neutral" },
};

const CONSENT: Record<ConsentPurpose, { label: string; description: string }> = {
  assistant_replies: {
    label: "Replies to my messages",
    description: "Answers to what you write to the assistant.",
  },
  daily_briefing: {
    label: "Daily briefing",
    description: "Your morning summary, sent without you asking.",
  },
  transactional: {
    label: "Updates about my work",
    description: "Approvals, assignments and changes on your records.",
  },
  marketing: {
    label: "Announcements",
    description: "News from the company.",
  },
};

function ConsentSwitches({ identity }: { identity: Identity }) {
  const save = useUpdateConsent(identity.id);
  const allowed = identity.capabilities.update_consent?.allowed ?? false;
  return (
    <fieldset className="m-0 flex min-w-0 flex-col gap-3 border-0 p-0">
      <legend className="t-label mb-3 p-0 text-ink">Messages you receive</legend>
      {CONSENT_PURPOSES.map((purpose) => {
        const current = identity.consents[purpose];
        // Replies to what the person wrote are on unless they opted out; proactive messages need an opt-in.
        const on = purpose === "assistant_replies" || purpose === "transactional" ? current !== "opted_out" : current === "opted_in";
        return (
          <Switch
            key={purpose}
            label={CONSENT[purpose].label}
            description={CONSENT[purpose].description}
            isSelected={on}
            isDisabled={!allowed || save.isPending}
            onChange={(next) => save.mutate({ purpose, on: next })}
          />
        );
      })}
      <p className="t-body-sm text-ink-3">You can also send STOP (or “band karo”) on WhatsApp to turn off messages you did not ask for.</p>
    </fieldset>
  );
}

function IdentityRow({ identity }: { identity: Identity }) {
  const [confirming, setConfirming] = useState(false);
  const unlink = useUnlinkIdentity();
  const state = IDENTITY_STATE[identity.status];
  const canUnlink = identity.capabilities.revoke?.allowed === true;

  return (
    <li className="flex flex-col gap-5 border-line py-5 first:pt-0 last:pb-0 [&:not(:first-child)]:border-t">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="t-h4 lk-mono break-all text-ink">{identity.wa_id_masked ?? identity.username ?? "WhatsApp"}</span>
            <Badge size="sm" tone={state.tone} dot={identity.status === "active"}>
              {state.label}
            </Badge>
          </div>
          <p className="t-body-sm text-ink-3">
            Linked <DateText value={identity.created_at} style="dayTime" />
            {identity.session_expires_at ? (
              <>
                {" · "}Session until <DateText value={identity.session_expires_at} style="dayTime" />
              </>
            ) : null}
          </p>
        </div>
        {canUnlink ? (
          <Button variant="secondary" size="sm" onPress={() => setConfirming(true)}>
            Unlink number
          </Button>
        ) : null}
      </div>
      {identity.status === "active" ? <ConsentSwitches identity={identity} /> : null}
      <ConfirmDialog
        isOpen={confirming}
        onOpenChange={setConfirming}
        tone="danger"
        title="Unlink this number?"
        description="The assistant stops answering this number until you link it again. Buttons it has already sent stop working."
        confirmLabel="Unlink number"
        cancelLabel="Keep it linked"
        onConfirm={() => unlink.mutateAsync(identity.id)}
      />
    </li>
  );
}

/** The signed-in person's linked numbers, each with what it may receive and a way to unlink it. */
export function LinkedNumbers() {
  const query = useMyIdentities();
  return (
    <GlassPanel as="section" padding="lg" title="Linked numbers" titleAs="h2" className="rise">
      <div className="flex flex-col gap-5">
        <p className="t-body text-ink-2">
          Numbers that can use the assistant as you. Unlinking one ends its session and cancels any buttons already sent to it.
        </p>
        <QueryView
          query={query}
          what="Your linked numbers"
          isEmpty={(data) => data.length === 0}
          empty={
            <EmptyState
              compact
              icon="phone"
              title="No number is linked yet"
              text="Create a link code above and send it from the phone you want to use."
            />
          }
        >
          {(data) => (
            <ul className="m-0 flex list-none flex-col p-0">
              {data.map((identity) => (
                <IdentityRow key={identity.id} identity={identity} />
              ))}
            </ul>
          )}
        </QueryView>
      </div>
    </GlassPanel>
  );
}
