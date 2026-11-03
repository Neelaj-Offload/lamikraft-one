"use client";

import { useEffect, useState } from "react";
import { Form } from "react-aria-components";
import { Button } from "@/components/ui/button";
import { Loading } from "@/components/ui/states";
import { PasswordField, TextField } from "@/components/ui/text-field";
import { afterSignIn, readFragmentToken, type SignInStage } from "@/features/auth/auth-api";
import { api, requestUntyped } from "@/lib/api/client";
import { isProblemError } from "@/lib/api/errors";

interface Preview {
  email: string;
  display_name: string;
  company_name: string;
  expires_at: string;
  has_password: boolean;
}

/**
 * Reads the token from the URL fragment once and strips it with history.replaceState, so it never reaches a
 * server log, the Referer header or the browser history; the token is then only ever sent in a POST body.
 */
export function useFragmentToken(): string | null | undefined {
  const [token, setToken] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    const value = readFragmentToken(window.location.hash);
    if (window.location.hash) window.history.replaceState(window.history.state, "", window.location.pathname);
    queueMicrotask(() => setToken(value));
  }, []);
  return token;
}

export function linkProblem(error: unknown): string {
  if (isProblemError(error) && error.code === "link_invalid_or_used") return "This link is invalid, expired or already used. Ask for a new one.";
  if (isProblemError(error) && error.status === 429) return "Too many attempts. Wait a few minutes and try again.";
  if (isProblemError(error)) return error.detail ?? error.title;
  return "Something went wrong. Try again.";
}

export function InviteAcceptForm() {
  const token = useFragmentToken();
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) return;
    requestUntyped<Preview>(api, "post", "/api/v1/identity/invitations/preview", { body: { token } }).then(setPreview, setError);
  }, [token]);

  async function accept(form: FormData) {
    setBusy(true);
    setError(null);
    try {
      const info = await requestUntyped<{ stage?: SignInStage }>(api, "post", "/api/v1/identity/invitations/acceptance", {
        body: { token, password: String(form.get("password") ?? ""), display_name: String(form.get("display_name") ?? "").trim() || null },
      });
      window.location.assign(afterSignIn(info.stage ?? "active", "/today"));
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  const fieldError = isProblemError(error) && error.status === 422 ? (error.validationIssues[0]?.msg ?? error.detail ?? undefined) : undefined;
  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1 text-center">
        <h1 className="text-3xl font-bold tracking-tight">Accept your invitation</h1>
        {preview ? <p className="text-ink-muted">{preview.company_name} invited {preview.email}.</p> : null}
      </header>
      {token === undefined || (token && !preview && !error) ? <Loading label="your invitation" variant="inline" /> : null}
      {token === null ? <p role="alert">This page needs the link from your invitation email. Open that link again.</p> : null}
      {error && !preview ? <p role="alert" className="text-danger">{linkProblem(error)}</p> : null}
      {preview ? (
        <Form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            void accept(new FormData(event.currentTarget));
          }}
        >
          <TextField name="display_name" label="Your name" defaultValue={preview.display_name} isRequired />
          <PasswordField
            name="password"
            label={preview.has_password ? "Your Lamikraft One password" : "Choose a password"}
            description={preview.has_password ? "You already have an account: confirm it with your password." : "At least 12 characters; a passphrase is easiest."}
            autoComplete={preview.has_password ? "current-password" : "new-password"}
            isRequired
            isInvalid={!!fieldError}
            errorMessage={fieldError}
          />
          {error && !fieldError ? <p role="alert" className="text-danger">{linkProblem(error)}</p> : null}
          <Button type="submit" variant="primary" isPending={busy} pendingLabel="Joining…" className="w-full">
            Join {preview.company_name}
          </Button>
        </Form>
      ) : null}
    </div>
  );
}
