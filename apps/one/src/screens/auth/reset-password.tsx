"use client";

import { useRef, useState } from "react";
import { Button, ButtonLink } from "~/ui";
import { completePasswordReset } from "~/data/entry";
import { AuthForm, AuthHeading, AuthLoading, AuthNotice, AuthProblem, PasswordField, useFragmentToken } from "./parts";
import { isSpentLink, linkFailure, passwordRuleFailure } from "./problems";

const RULE = "At least 12 characters. A passphrase of a few plain words is easiest to remember.";

/** Choose a new password with a one-time link. Every session ends; two-step sign-in is kept. */
export function ResetPasswordScreen() {
  const token = useFragmentToken();
  const [password, setPassword] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [spent, setSpent] = useState(false);
  const [pending, setPending] = useState(false);
  const [done, setDone] = useState(false);
  const problem = useRef<HTMLDivElement>(null);

  const submit = async () => {
    if (pending || !token) return;
    if (password.length < 12) {
      setFieldError(password ? "Use at least 12 characters." : "Choose a new password.");
      return;
    }
    setPending(true);
    setFailure(null);
    setFieldError(null);
    try {
      await completePasswordReset(token, password);
      setDone(true);
    } catch (err) {
      const rule = passwordRuleFailure(err);
      if (rule) setFieldError(rule);
      else if (isSpentLink(err)) setSpent(true);
      else {
        setFailure(linkFailure(err));
        window.requestAnimationFrame(() => problem.current?.focus());
      }
    } finally {
      setPending(false);
    }
  };

  const heading = (
    <AuthHeading
      title={
        <>
          Choose a new <em>password</em>
        </>
      }
      lead={
        done
          ? "Done. Your old password no longer works."
          : token === null || spent
            ? "Reset links work once and expire after 30 minutes."
            : "Saving it signs you out everywhere, so only the new password gets back in."
      }
    />
  );

  if (done) {
    return (
      <>
        {heading}
        <AuthNotice
          icon="checkCircle"
          tone="leaf"
          title="Password changed"
          actions={
            <ButtonLink href="/login" size="lg" className="w-full" iconRight="arrowRight">
              Sign in
            </ButtonLink>
          }
        >
          You were signed out on every device. Sign in with the new password; two-step sign-in, if you use it, is unchanged.
        </AuthNotice>
      </>
    );
  }

  if (token === undefined) {
    return (
      <>
        {heading}
        <AuthLoading label="Reading your reset link" fields={1} />
      </>
    );
  }

  if (token === null || spent) {
    return (
      <>
        {heading}
        <AuthNotice
          icon="link"
          title={spent ? "This link can no longer be used" : "Open the link from your email"}
          actions={
            <>
              <ButtonLink href="/forgot-password" variant="inverse" size="lg" className="w-full">
                Send a new link
              </ButtonLink>
              <ButtonLink href="/login" variant="ghost" className="w-full">
                Back to sign in
              </ButtonLink>
            </>
          }
        >
          {spent
            ? "This one has expired or was already used. Ask for a new one and use it straight away."
            : "This page only works when it is opened from a reset email. Open that link again, or ask for a new one."}
        </AuthNotice>
      </>
    );
  }

  return (
    <>
      {heading}
      <AuthForm label="Choose a new password" onSubmit={() => void submit()}>
        {failure ? (
          <AuthProblem ref={problem} title="The password was not saved.">
            {failure}
          </AuthProblem>
        ) : null}
        <PasswordField
          label="New password"
          name="password"
          size="lg"
          autoComplete="new-password"
          autoFocus
          isRequired
          value={password}
          onChange={(value) => {
            setPassword(value);
            if (fieldError) setFieldError(null);
          }}
          help={RULE}
          error={fieldError}
        />
        <Button type="submit" size="lg" className="w-full" loading={pending}>
          Save password
        </Button>
      </AuthForm>
    </>
  );
}
