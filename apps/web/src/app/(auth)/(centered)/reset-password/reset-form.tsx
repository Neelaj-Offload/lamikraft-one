"use client";

import { useState } from "react";
import { Form } from "react-aria-components";
import { Button } from "@/components/ui/button";
import { Loading, Success } from "@/components/ui/states";
import { PasswordField } from "@/components/ui/text-field";
import { api, requestUntyped } from "@/lib/api/client";
import { isProblemError } from "@/lib/api/errors";
import { linkProblem, useFragmentToken } from "../invite/invite-form";

/** Choose a new password with a one-time link; every session ends, two-step sign-in is kept. */
export function ResetPasswordForm() {
  const token = useFragmentToken();
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  async function submit(form: FormData) {
    setBusy(true);
    setError(null);
    try {
      await requestUntyped(api, "post", "/api/v1/identity/password-resets/completion", { body: { token, password: String(form.get("password") ?? "") } });
      setDone(true);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const fieldError = isProblemError(error) && error.status === 422 ? (error.validationIssues[0]?.msg ?? error.detail ?? undefined) : undefined;
  return (
    <div className="flex flex-col gap-6">
      <header className="text-center">
        <h1 className="text-3xl font-bold tracking-tight">Choose a new password</h1>
      </header>
      {token === undefined ? <Loading label="your reset link" variant="inline" /> : null}
      {token === null ? <p role="alert">This page needs the link from your reset email. Open that link again, or ask for a new one.</p> : null}
      {done ? (
        <Success title="Password changed">
          <p>
            You were signed out everywhere. <a className="underline" href="/login">Sign in</a> with the new password.
          </p>
        </Success>
      ) : token ? (
        <Form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            void submit(new FormData(event.currentTarget));
          }}
        >
          <PasswordField name="password" label="New password" description="At least 12 characters." autoComplete="new-password" isRequired isInvalid={!!fieldError} errorMessage={fieldError} />
          {error && !fieldError ? <p role="alert" className="text-danger">{linkProblem(error)}</p> : null}
          <Button type="submit" variant="primary" isPending={busy} className="w-full">
            Save password
          </Button>
        </Form>
      ) : null}
    </div>
  );
}
