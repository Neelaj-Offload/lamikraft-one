"use client";

import { useEffect, useState } from "react";
import { Form } from "react-aria-components";
import { Button } from "@/components/ui/button";
import { Loading } from "@/components/ui/states";
import { TextField } from "@/components/ui/text-field";
import { api, requestUntyped } from "@/lib/api/client";
import { isProblemError } from "@/lib/api/errors";
import { RecoveryCodes, TotpEnrolment } from "@/app/(app)/settings/_lib/security";

export const VERIFY_PATH = "/api/v1/identity/session/verification";
export const MFA_STATUS_PATH = "/api/v1/identity/me/mfa";

type Mode = "checking" | "verify" | "enrol" | "done";

export function TwoStepForm({ next }: { next: string }) {
  const [mode, setMode] = useState<Mode>("checking");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // An enrolment-only session can read its MFA status; a session waiting for a code cannot (401).
    requestUntyped<{ enrolled: boolean }>(api, "get", MFA_STATUS_PATH)
      .then((status) => setMode(status.enrolled ? "done" : "enrol"))
      .catch((err: unknown) => {
        if (isProblemError(err) && err.code === "mfa_verification_required") setMode("verify");
        else if (isProblemError(err) && err.status === 401) window.location.replace(`/login?next=${encodeURIComponent(next)}`);
        else setMode("verify");
      });
  }, [next]);

  useEffect(() => {
    if (mode === "done" && !codes) window.location.assign(next);
  }, [mode, codes, next]);

  async function verify(code: string) {
    setBusy(true);
    setError(null);
    try {
      await requestUntyped(api, "post", VERIFY_PATH, { body: { code } });
      window.location.assign(next);
    } catch (err) {
      if (isProblemError(err) && err.code === "invalid_code") setError("That code did not work. Use the current code from your app, or an unused recovery code.");
      else if (isProblemError(err) && err.code === "session_expired") window.location.replace(`/login?next=${encodeURIComponent(next)}`);
      else setError(isProblemError(err) ? (err.detail ?? err.title) : "Something went wrong. Try again.");
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1 text-center">
        <h1 className="text-3xl font-bold tracking-tight">Two-step sign-in</h1>
        <p className="text-ink-muted">
          {mode === "enrol" ? "Your role needs an authenticator app. Set it up once; you will use it at every sign-in." : "Enter the 6-digit code from your authenticator app."}
        </p>
      </header>
      {mode === "checking" ? <Loading label="your sign-in" variant="inline" /> : null}
      {mode === "verify" ? (
        <Form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            void verify(String(new FormData(event.currentTarget).get("code") ?? ""));
          }}
        >
          <TextField
            name="code"
            label="Code"
            description="Lost your phone? Enter one of your recovery codes instead."
            autoComplete="one-time-code"
            autoFocus
            isRequired
            isInvalid={!!error}
            errorMessage={error ?? undefined}
          />
          <Button type="submit" variant="primary" isPending={busy} pendingLabel="Checking…" className="w-full">
            Continue
          </Button>
        </Form>
      ) : null}
      {mode === "enrol" ? <TotpEnrolment onDone={(c) => setCodes(c)} /> : null}
      {codes ? (
        <div className="flex flex-col gap-3">
          <RecoveryCodes codes={codes} />
          <Button variant="primary" onPress={() => window.location.assign(next)}>
            I saved them, continue
          </Button>
        </div>
      ) : null}
    </div>
  );
}
