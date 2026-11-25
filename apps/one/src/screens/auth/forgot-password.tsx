"use client";

import { useState } from "react";
import { isNetworkError, isProblemError } from "@/lib/api/errors";
import { Button, ButtonLink, TextField, TextLink } from "~/ui";
import { requestPasswordReset } from "~/data/entry";
import { AuthForm, AuthHeading, AuthNotice } from "./parts";

/**
 * Ask for a reset link. The answer is the same whether or not the address belongs to someone, so
 * the screen never reveals who has an account.
 */
export function ForgotPasswordScreen() {
  const [email, setEmail] = useState("");
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const submit = async () => {
    if (pending) return;
    const address = email.trim();
    if (!address) {
      setError("Enter the email you sign in with.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      await requestPasswordReset(address);
      setSentTo(address);
    } catch (err) {
      if (isNetworkError(err)) setError("Lamikraft One cannot be reached. Check your connection and try again.");
      else if (isProblemError(err) && err.status === 429) setError("Too many requests. Wait a few minutes, then try again.");
      else setError("The link could not be requested. Try again in a moment.");
    } finally {
      setPending(false);
    }
  };

  if (sentTo) {
    return (
      <>
        <AuthHeading
          title={
            <>
              Check your <em>email</em>
            </>
          }
          lead="The link works once and expires in 30 minutes."
        />
        <AuthNotice
          icon="mail"
          tone="leaf"
          title="A link is on its way"
          actions={
            <ButtonLink href="/login" variant="inverse" size="lg" className="w-full">
              Back to sign in
            </ButtonLink>
          }
        >
          <p>
            If <span className="font-medium text-ink break-all">{sentTo}</span> belongs to an account here, the reset link has been sent to it.
          </p>
          <p className="t-body-sm text-ink-3 mt-2">On a demo workspace the link goes to the demo outbox, not to a real mailbox.</p>
        </AuthNotice>
      </>
    );
  }

  return (
    <>
      <AuthHeading
        title={
          <>
            Reset your <em>password</em>
          </>
        }
        lead="Tell us the email you sign in with and we will send a link that is good for 30 minutes."
      />
      <AuthForm label="Reset your password" onSubmit={() => void submit()}>
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
            if (error) setError(null);
          }}
          error={error}
        />
        <Button type="submit" size="lg" className="w-full" loading={pending} iconRight="send">
          Send reset link
        </Button>
        <p className="t-body-sm text-ink-3">
          Remembered it? <TextLink href="/login">Back to sign in</TextLink>
        </p>
      </AuthForm>
    </>
  );
}
