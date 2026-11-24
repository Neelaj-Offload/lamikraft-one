"use client";

import { useRef, useState } from "react";
import { afterSignIn, signIn } from "@/features/auth/auth-api";
import { Button, TextField, TextLink } from "~/ui";
import { AuthForm, AuthHeading, AuthProblem, PasswordField } from "./parts";
import { signInFailure, type AuthFailure } from "./problems";

/**
 * Email and password. On success the browser holds the session cookies and the page does a full
 * navigation to `next` (validated by the route as a same-origin path), so the signed-in layout
 * loads the new session on the server. A second step, when the account has one, continues on
 * /two-step and then goes on to `next`.
 */
export function LoginScreen({ next }: { next: string }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [missing, setMissing] = useState<{ email?: string; password?: string }>({});
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<AuthFailure | null>(null);
  const problem = useRef<HTMLDivElement>(null);

  const submit = async () => {
    if (pending) return;
    const gaps = {
      email: email.trim() ? undefined : "Enter your work email.",
      password: password ? undefined : "Enter your password.",
    };
    setMissing(gaps);
    if (gaps.email || gaps.password) return;
    setPending(true);
    setFailure(null);
    try {
      const stage = await signIn(email.trim(), password);
      window.location.assign(afterSignIn(stage, next));
    } catch (error) {
      setFailure(signInFailure(error));
      setPassword("");
      setPending(false);
      // Let the message render, then move focus to it so keyboard and screen reader users hear it.
      window.requestAnimationFrame(() => problem.current?.focus());
    }
  };

  return (
    <>
      <AuthHeading
        title={
          <>
            Sign in to your <em>workspace</em>
          </>
        }
        lead="Use your work email and password to pick up where you left off."
      />
      <AuthForm label="Sign in" onSubmit={() => void submit()}>
        {failure ? (
          <AuthProblem ref={problem} title="You are not signed in." requestId={failure.requestId}>
            {failure.message}
          </AuthProblem>
        ) : null}
        <TextField
          label="Work email"
          name="email"
          type="email"
          size="lg"
          autoComplete="username"
          inputMode="email"
          autoFocus
          isRequired
          value={email}
          onChange={(value) => {
            setEmail(value);
            if (missing.email) setMissing((current) => ({ ...current, email: undefined }));
          }}
          onBlur={() => {
            if (!email.trim() && password) setMissing((current) => ({ ...current, email: "Enter your work email." }));
          }}
          error={missing.email}
        />
        <PasswordField
          label="Password"
          name="password"
          size="lg"
          autoComplete="current-password"
          isRequired
          value={password}
          onChange={(value) => {
            setPassword(value);
            if (missing.password) setMissing((current) => ({ ...current, password: undefined }));
          }}
          error={missing.password}
        />
        <Button type="submit" size="lg" className="w-full" loading={pending} iconRight="arrowRight">
          Sign in
        </Button>
        <p className="t-body-sm text-ink-3">
          Forgotten it? <TextLink href="/forgot-password">Reset your password</TextLink>
        </p>
      </AuthForm>
    </>
  );
}
