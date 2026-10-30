import { describe, expect, it } from "vitest";
import { afterSignIn } from "@/features/auth/auth-api";
import { ProblemError } from "@/lib/api/errors";
import { render, textOf } from "@/lib/test-support/render";
import { ForgotPasswordForm } from "./forgot-password/forgot-form";
import { InviteAcceptForm, linkProblem } from "./invite/invite-form";
import { ResetPasswordForm } from "./reset-password/reset-form";
import { TwoStepForm } from "./two-step/two-step-form";

describe("auth link pages (platform-2)", () => {
  it("send a second sign-in step to /two-step and keep the destination", () => {
    expect(afterSignIn("active", "/today")).toBe("/today");
    expect(afterSignIn("mfa_pending", "/sales/quotes")).toBe("/two-step?next=%2Fsales%2Fquotes");
    expect(afterSignIn("mfa_enrollment_required", "/today")).toBe("/two-step?next=%2Ftoday");
  });

  it("render their first state before reading the URL fragment (no token in the markup)", () => {
    expect(textOf(render(<TwoStepForm next="/today" />))).toContain("Two-step sign-in");
    const invite = render(<InviteAcceptForm />);
    expect(textOf(invite)).toContain("Accept your invitation");
    expect(invite).not.toContain("#t=");
    expect(textOf(render(<ResetPasswordForm />))).toContain("Choose a new password");
  });

  it("ask for an email on the forgot-password page with a way back", () => {
    const html = render(<ForgotPasswordForm />);
    expect(textOf(html)).toContain("Send the link");
    expect(html).toContain('autoComplete="username"');
    expect(html).toContain('href="/login"');
  });

  it("explain used, expired and throttled links without detail", () => {
    expect(linkProblem(new ProblemError({ title: "x", status: 401, code: "link_invalid_or_used" }))).toMatch(/invalid, expired or already used/);
    expect(linkProblem(new ProblemError({ title: "x", status: 429, code: "rate_limited" }))).toMatch(/Too many attempts/);
  });
});
