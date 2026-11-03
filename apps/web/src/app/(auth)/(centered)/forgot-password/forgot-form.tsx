"use client";

import { useState } from "react";
import { Form } from "react-aria-components";
import { Button } from "@/components/ui/button";
import { Success } from "@/components/ui/states";
import { TextField } from "@/components/ui/text-field";
import { api, requestUntyped } from "@/lib/api/client";
import { isProblemError } from "@/lib/api/errors";

/** Always answers the same way whether or not the email belongs to someone (no account discovery). */
export function ForgotPasswordForm() {
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(email: string) {
    setBusy(true);
    setError(null);
    try {
      await requestUntyped(api, "post", "/api/v1/identity/password-resets", { body: { email } });
      setSent(true);
    } catch (err) {
      setError(isProblemError(err) && err.status === 429 ? "Too many requests. Wait a few minutes and try again." : "Something went wrong. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1 text-center">
        <h1 className="text-3xl font-bold tracking-tight">Forgot password</h1>
        <p className="text-ink-muted">We send a link valid for 30 minutes.</p>
      </header>
      {sent ? (
        <Success title="Check your email">
          <p>If that address belongs to an account here, a link is on its way. In demo mode it is written to the demo outbox instead of being sent.</p>
        </Success>
      ) : (
        <Form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            void submit(String(new FormData(event.currentTarget).get("email") ?? "").trim());
          }}
        >
          <TextField name="email" label="Email" type="email" autoComplete="username" isRequired />
          {error ? <p role="alert" className="text-danger">{error}</p> : null}
          <Button type="submit" variant="primary" isPending={busy} className="w-full">
            Send the link
          </Button>
          <a href="/login" className="focus-ring self-center rounded text-sm text-ink-muted underline underline-offset-2">
            Back to sign in
          </a>
        </Form>
      )}
    </div>
  );
}
