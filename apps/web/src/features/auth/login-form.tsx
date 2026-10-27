"use client";

import { useRef, useState, type FormEvent } from "react";
import { Form } from "react-aria-components";
import { Button } from "@/components/ui/button";
import { ErrorIcon } from "@/components/ui/icons";
import { PasswordField, TextField } from "@/components/ui/text-field";
import { authMessages as m } from "@/messages/auth";
import { loginFailure, signIn, type AuthFailure } from "./auth-api";

/**
 * Email and password sign-in. On success the browser holds the session cookies and the
 * page does a full navigation to `next` (already validated as a same-origin path), so the
 * (app) layout bootstraps the new session on the server.
 */
export function LoginForm({ next }: { next: string }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<AuthFailure | null>(null);
  const alertRef = useRef<HTMLDivElement>(null);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setFailure(null);
    try {
      await signIn(email.trim(), password);
      window.location.assign(next);
    } catch (error) {
      setFailure(loginFailure(error));
      setPassword("");
      setPending(false);
      // Let the alert render, then move focus to it so keyboard and screen reader users hear it.
      window.requestAnimationFrame(() => alertRef.current?.focus());
    }
  };

  return (
    <Form onSubmit={onSubmit} className="flex flex-col gap-5" aria-describedby={failure ? "login-error" : undefined}>
      {failure ? (
        <div
          id="login-error"
          ref={alertRef}
          tabIndex={-1}
          role="alert"
          className="flex gap-3 rounded-lg border border-danger bg-danger-bg p-3 text-danger outline-hidden"
        >
          <ErrorIcon className="mt-0.5 shrink-0" />
          <div className="flex flex-col gap-1">
            <p className="font-semibold">{m.login.errorTitle}</p>
            <p className="text-sm">{failure.message}</p>
            {failure.requestId ? (
              <p className="text-sm">
                {m.requestId}: <span className="font-mono select-all">{failure.requestId}</span>
              </p>
            ) : null}
          </div>
        </div>
      ) : null}
      <TextField
        label={m.login.email}
        name="email"
        type="email"
        autoComplete="username"
        inputMode="email"
        isRequired
        value={email}
        onChange={setEmail}
        validationBehavior="native"
        validate={(value) => (value.trim() ? null : m.login.emailRequired)}
      />
      <PasswordField
        label={m.login.password}
        revealLabel={m.login.showPassword}
        name="password"
        autoComplete="current-password"
        isRequired
        value={password}
        onChange={setPassword}
        validationBehavior="native"
        validate={(value) => (value ? null : m.login.passwordRequired)}
      />
      <Button type="submit" variant="primary" isPending={pending} pendingLabel={m.login.submitting} className="w-full">
        {m.login.submit}
      </Button>
    </Form>
  );
}
