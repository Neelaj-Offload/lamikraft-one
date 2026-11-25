"use client";

import type { Route } from "next";
import { useRef, useState, type FormEvent } from "react";
import { invite } from "@/app/(app)/settings/_lib/api";
import type { Delivery } from "@/app/(app)/settings/_lib/types";
import { useRefreshIdentity, useRoles } from "~/data/settings-access";
import { Page, PageHeader } from "~/shell/page";
import { Banner, Button, ButtonLink, FormActions, FormSection, GlassPanel, Icon, TextField, toast } from "~/ui";
import { fieldErrors, problemText, SETTINGS_CRUMB, userHref, USERS_CRUMB } from "./labels";
import { DeliveryNote, RoleChecklist } from "./parts";
import { useStepUp } from "./step-up";

interface InviteForm {
  email: string;
  display_name: string;
  job_title: string;
}

const EMPTY: InviteForm = { email: "", display_name: "", job_title: "" };

/** Invite one person: who they are, then what they may do. The server sends (or, in demo, shows) the link. */
export function UserInvite() {
  const refresh = useRefreshIdentity();
  const roles = useRoles();
  const stepUp = useStepUp();
  const [form, setForm] = useState<InviteForm>(EMPTY);
  const [selected, setSelected] = useState<string[]>([]);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [issued, setIssued] = useState<{ delivery: Delivery; userId: string; name: string } | null>(null);
  const banner = useRef<HTMLDivElement>(null);

  const server = fieldErrors(error);
  const client: Record<string, string> = submitted
    ? {
        ...(form.email.trim() ? {} : { email: "Enter their work email. The invitation goes to this address." }),
        ...(form.display_name.trim() ? {} : { display_name: "Enter the name the team will see." }),
        ...(selected.length > 0 ? {} : { role_keys: "Choose at least one role." }),
      }
    : {};
  const errorFor = (key: string) => server[key] ?? client[key];
  const failure = error && Object.keys(server).length === 0 ? problemText(error) : null;
  const set = (key: keyof InviteForm, value: string) => setForm((current) => ({ ...current, [key]: value }));

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (busy) return;
    if (!form.email.trim() || !form.display_name.trim() || selected.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const result = await stepUp.run(() =>
        invite({
          email: form.email.trim(),
          display_name: form.display_name.trim(),
          job_title: form.job_title.trim() || null,
          role_keys: selected,
        }),
      );
      await refresh();
      setIssued({ delivery: result.delivery, userId: result.invitation.user_id, name: form.display_name.trim() });
      toast.success("Invitation created");
    } catch (err) {
      setError(err);
      window.requestAnimationFrame(() => banner.current?.focus());
    } finally {
      setBusy(false);
    }
  };

  const again = () => {
    setIssued(null);
    setForm(EMPTY);
    setSelected([]);
    setSubmitted(false);
    setError(null);
  };

  return (
    <Page width="reading">
      <PageHeader
        breadcrumb={[SETTINGS_CRUMB, USERS_CRUMB, { label: "Invite someone" }]}
        title="Invite someone"
        lead="They get a link, good for 7 days, to choose a password. People in admin roles set up two-step sign-in the first time they sign in."
      />

      {issued ? (
        <GlassPanel as="section" variant="strong" padding="lg" className="rise flex flex-col gap-5" aria-label="Invitation ready">
          <div className="flex items-start gap-4">
            <span className="grid size-11 flex-none place-items-center rounded-lg bg-leaf-soft text-leaf-text" aria-hidden>
              <Icon name="checkCircle" size={20} />
            </span>
            <div className="flex min-w-0 flex-col gap-1">
              <h2 className="t-display-sm">{issued.name} is invited</h2>
              <p className="t-body text-ink-2">Their account is waiting. It becomes active when they open the link and choose a password.</p>
            </div>
          </div>
          <DeliveryNote delivery={issued.delivery} what="invitation" />
          <div className="flex flex-wrap gap-2">
            <ButtonLink variant="inverse" href={userHref(issued.userId)} iconRight="arrowRight">
              Open their profile
            </ButtonLink>
            <Button variant="secondary" iconLeft="userPlus" onPress={again}>
              Invite another person
            </Button>
          </div>
        </GlassPanel>
      ) : (
        <form onSubmit={(event) => void submit(event)} noValidate className="stack">
          {failure ? (
            <div ref={banner} tabIndex={-1} className="outline-none">
              <Banner tone="ember" title="The invitation was not created.">
                {failure}
              </Banner>
            </div>
          ) : null}

          <FormSection title="Who you are inviting" description="The email is where the link goes and what they sign in with.">
            <TextField
              className="col-span-full"
              label="Email"
              type="email"
              inputMode="email"
              iconLeft="mail"
              autoComplete="off"
              isRequired
              maxLength={254}
              value={form.email}
              onChange={(value) => set("email", value)}
              error={errorFor("email")}
            />
            <TextField label="Name" isRequired maxLength={200} autoComplete="off" value={form.display_name} onChange={(value) => set("display_name", value)} error={errorFor("display_name")} />
            <TextField label="Job title" optional maxLength={120} autoComplete="off" value={form.job_title} onChange={(value) => set("job_title", value)} error={errorFor("job_title")} />
          </FormSection>

          <FormSection title="What they can do" description="Roles decide what they see and change. You can only give access you hold yourself.">
            <RoleChecklist
              className="col-span-full"
              roles={roles.data?.items}
              isLoading={roles.isPending}
              value={selected}
              onChange={setSelected}
              help="Tick every role that applies. You can change them later from their profile."
              error={roles.isError ? "The roles could not load. Reload the page to try again." : errorFor("role_keys")}
            />
          </FormSection>

          <FormActions>
            <ButtonLink variant="ghost" href={"/settings/users" as Route}>
              Cancel
            </ButtonLink>
            <Button type="submit" loading={busy} iconLeft="send">
              Send invitation
            </Button>
          </FormActions>
        </form>
      )}
      {stepUp.dialog}
    </Page>
  );
}
