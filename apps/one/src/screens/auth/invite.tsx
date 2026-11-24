"use client";

import { useEffect, useRef, useState } from "react";
import { afterSignIn } from "@/features/auth/auth-api";
import { Button, ButtonLink, TextField } from "~/ui";
import { acceptInvitation, previewInvitation, type InvitationPreview } from "~/data/entry";
import { AuthForm, AuthHeading, AuthLoading, AuthNotice, AuthProblem, PasswordField, useFragmentToken } from "./parts";
import { fieldIssue, isSpentLink, linkFailure, passwordRuleFailure } from "./problems";

/**
 * Accept an invitation. The token arrives in the URL fragment (`/invite#t=…`): it is read once,
 * removed from the address bar, used to preview who invited whom, then posted with the password.
 * Someone who already has an account confirms with their existing password instead of choosing one.
 */
export function InviteScreen() {
  const token = useFragmentToken();
  const [preview, setPreview] = useState<InvitationPreview | null>(null);
  const [previewError, setPreviewError] = useState<unknown>(null);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<{ name?: string; password?: string }>({});
  const [failure, setFailure] = useState<string | null>(null);
  const [spent, setSpent] = useState(false);
  const [pending, setPending] = useState(false);
  const problem = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!token) return;
    let live = true;
    previewInvitation(token).then(
      (data) => {
        if (!live) return;
        setPreview(data);
        setName(data.display_name);
      },
      (error: unknown) => {
        if (live) setPreviewError(error);
      },
    );
    return () => {
      live = false;
    };
  }, [token]);

  const submit = async () => {
    if (pending || !token || !preview) return;
    const gaps = {
      name: name.trim() ? undefined : "Enter the name your colleagues will see.",
      password: password
        ? !preview.has_password && password.length < 12
          ? "Use at least 12 characters."
          : undefined
        : preview.has_password
          ? "Enter your Lamikraft One password."
          : "Choose a password.",
    };
    setErrors(gaps);
    if (gaps.name || gaps.password) return;
    setPending(true);
    setFailure(null);
    try {
      const stage = await acceptInvitation(token, password, name);
      window.location.assign(afterSignIn(stage, "/today"));
    } catch (err) {
      const rule = passwordRuleFailure(err);
      const nameIssue = fieldIssue(err, "display_name");
      if (nameIssue) setErrors({ name: nameIssue });
      else if (rule) setErrors({ password: rule });
      else if (isSpentLink(err)) setSpent(true);
      else {
        setFailure(linkFailure(err));
        window.requestAnimationFrame(() => problem.current?.focus());
      }
      setPending(false);
    }
  };

  const plainHeading = (
    <AuthHeading
      title={
        <>
          Your <em>invitation</em>
        </>
      }
      lead="Join your team on Lamikraft One."
    />
  );

  if (token === null || spent || (previewError && !preview)) {
    const missing = token === null;
    const dead = spent || isSpentLink(previewError);
    return (
      <>
        {plainHeading}
        <AuthNotice
          icon="link"
          tone={missing || dead ? "neutral" : "ember"}
          title={missing ? "Open the link from your invitation" : dead ? "This invitation can no longer be used" : "The invitation could not be read"}
          actions={
            <ButtonLink href="/login" variant="inverse" size="lg" className="w-full">
              Go to sign in
            </ButtonLink>
          }
        >
          {missing
            ? "This page only works when it is opened from an invitation email. Open that link again."
            : dead
              ? "Invitations work once and expire. Ask the person who invited you to send a new one."
              : linkFailure(previewError)}
        </AuthNotice>
      </>
    );
  }

  if (!preview) {
    return (
      <>
        {plainHeading}
        <AuthLoading label="Reading your invitation" />
      </>
    );
  }

  return (
    <>
      <AuthHeading
        title={
          <>
            Join <em>{preview.company_name}</em>
          </>
        }
        lead={
          <>
            You were invited as <span className="font-medium text-ink break-all">{preview.email}</span>.{" "}
            {preview.has_password ? "Confirm with the password you already use." : "Choose a password and you are in."}
          </>
        }
      />
      <AuthForm label="Accept your invitation" onSubmit={() => void submit()}>
        {failure ? (
          <AuthProblem ref={problem} title="You have not joined yet.">
            {failure}
          </AuthProblem>
        ) : null}
        <TextField
          label="Your name"
          name="display_name"
          size="lg"
          autoComplete="name"
          isRequired
          value={name}
          onChange={(value) => {
            setName(value);
            if (errors.name) setErrors((current) => ({ ...current, name: undefined }));
          }}
          error={errors.name}
        />
        <PasswordField
          label={preview.has_password ? "Your Lamikraft One password" : "Choose a password"}
          name="password"
          size="lg"
          autoComplete={preview.has_password ? "current-password" : "new-password"}
          isRequired
          value={password}
          onChange={(value) => {
            setPassword(value);
            if (errors.password) setErrors((current) => ({ ...current, password: undefined }));
          }}
          help={
            preview.has_password
              ? "You already have an account. Your password confirms it is you."
              : "At least 12 characters. A passphrase of a few plain words is easiest to remember."
          }
          error={errors.password}
        />
        <Button type="submit" size="lg" className="w-full" loading={pending} iconRight="arrowRight">
          Join {preview.company_name}
        </Button>
      </AuthForm>
    </>
  );
}
