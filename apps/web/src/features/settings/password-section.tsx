"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Form } from "react-aria-components";
import { Button, unavailableWhen } from "@/components/ui/button";
import { SectionCard } from "@/components/ui/section-card";
import { AlertIcon } from "@/components/ui/icons";
import { StateView } from "@/components/ui/states";
import { PasswordField } from "@/components/ui/text-field";
import { toast } from "@/components/ui/toast";
import { createIdempotencyKey } from "@/lib/api/client";
import { ProblemError } from "@/lib/api/errors";
import { invalidationMap } from "@/lib/api/query-keys";
import { useOnline } from "@/lib/hooks";
import { briefingMessages } from "@/messages/briefing";
import { settingsMessages } from "@/messages/settings";
import { changePassword } from "./api";

const m = settingsMessages.profile.password;

interface PasswordForm {
  current: string;
  next: string;
  confirm: string;
}

const EMPTY: PasswordForm = { current: "", next: "", confirm: "" };

/** Field errors from a 422 (`current_password`, `new_password`), else an alert from the problem. */
export function passwordErrors(error: unknown): { fields: Record<string, string>; alert: string | null } {
  if (!(error instanceof ProblemError)) return { fields: {}, alert: null };
  if (error.code === "reauth_required") return { fields: {}, alert: m.reauth };
  if (error.status === 429) return { fields: {}, alert: error.detail ?? m.rateLimited };
  const fields: Record<string, string> = {};
  for (const issue of error.validationIssues) {
    const field = String(issue.loc.at(-1) ?? "");
    if (field === "current_password" || field === "new_password") fields[field] = issue.msg;
  }
  if (Object.keys(fields).length > 0) return { fields, alert: null };
  return { fields: {}, alert: error.detail ?? error.title };
}

export function PasswordSection() {
  const queryClient = useQueryClient();
  const online = useOnline();
  const [form, setForm] = useState<PasswordForm>(EMPTY);
  const [submitted, setSubmitted] = useState(false);
  const [pending, setPending] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [alert, setAlert] = useState<string | null>(null);
  const offline = online ? null : briefingMessages.offlineActions;
  const mismatch = submitted && form.next !== form.confirm ? m.mismatch : undefined;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (pending || offline || !form.current || !form.next || form.next !== form.confirm) return;
    setPending(true);
    setFieldErrors({});
    setAlert(null);
    try {
      await changePassword({ current_password: form.current, new_password: form.next }, createIdempotencyKey());
      await Promise.all(invalidationMap["identity.password_changed"].map((queryKey) => queryClient.invalidateQueries({ queryKey })));
      toast.success(m.done, { description: m.doneBody });
      setForm(EMPTY);
      setSubmitted(false);
    } catch (error) {
      const parsed = passwordErrors(error);
      setFieldErrors(parsed.fields);
      setAlert(parsed.alert);
      toast.error(m.failed, { description: error instanceof ProblemError ? (error.detail ?? error.title) : undefined });
    } finally {
      setPending(false);
    }
  };

  return (
    <SectionCard title={m.title} description={m.intro}>
      <Form onSubmit={submit} validationBehavior="aria" className="flex max-w-md flex-col gap-4">
        {alert ? (
          <StateView icon={<AlertIcon />} title={m.failed} tone="warning" role="alert" compact headingLevel={3}>
            {alert}
          </StateView>
        ) : null}
        <PasswordField
          label={m.current}
          value={form.current}
          onChange={(current) => setForm((state) => ({ ...state, current }))}
          autoComplete="current-password"
          isRequired
          errorMessage={fieldErrors.current_password}
        />
        <PasswordField
          label={m.next}
          value={form.next}
          onChange={(next) => setForm((state) => ({ ...state, next }))}
          autoComplete="new-password"
          description={m.policy}
          isRequired
          minLength={12}
          maxLength={256}
          errorMessage={fieldErrors.new_password}
        />
        <PasswordField
          label={m.confirm}
          value={form.confirm}
          onChange={(confirm) => setForm((state) => ({ ...state, confirm }))}
          autoComplete="new-password"
          isRequired
          errorMessage={mismatch}
        />
        <div>
          <Button type="submit" variant="primary" isPending={pending} pendingLabel={m.changing} {...unavailableWhen(offline)}>
            {m.submit}
          </Button>
        </div>
      </Form>
    </SectionCard>
  );
}
