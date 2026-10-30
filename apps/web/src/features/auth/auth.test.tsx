import { describe, expect, it, vi } from "vitest";
import { createApiClient } from "@/lib/api/client";
import { NetworkError, ProblemError } from "@/lib/api/errors";
import { countTags, render, textOf } from "@/lib/test-support/render";
import { demoSignIn, loginFailure, readFragmentToken, signIn } from "./auth-api";
import { DemoSignIn } from "./demo-sign-in";
import { LoginForm } from "./login-form";
import { SignOutPanel } from "./sign-out-panel";

const problem = (status: number, code: string, extra: Record<string, unknown> = {}, retryAfter: number | null = null) =>
  new ProblemError({ status, code, title: "x", request_id: "req-9", ...extra }, retryAfter);

describe("login failures", () => {
  it("use one generic message for wrong credentials, with no request id", () => {
    const message = "That email and password don't match an active account. Check them and try again.";
    expect(loginFailure(problem(401, "invalid_credentials"))).toEqual({ message, requestId: null });
    expect(loginFailure(problem(401, "unauthenticated"))).toEqual({ message, requestId: null });
    expect(loginFailure(problem(422, "validation_failed"))).toEqual({ message, requestId: null });
  });

  it("take rate-limit and lockout wording from problem+json", () => {
    expect(loginFailure(problem(429, "rate_limited", { detail: "Too many attempts from this network. Wait 10 minutes." }))).toEqual({
      message: "Too many attempts from this network. Wait 10 minutes.",
      requestId: "req-9",
    });
    expect(loginFailure(problem(429, "rate_limited", {}, 540)).message).toBe("Too many sign-in attempts. Try again in 9 minutes.");
    expect(loginFailure(problem(429, "rate_limited", {}, 30)).message).toBe("Too many sign-in attempts. Try again in 1 minute.");
    expect(loginFailure(problem(429, "account_locked", { detail: "Locked until 10:15." })).message).toBe("Locked until 10:15.");
    expect(loginFailure(problem(429, "account_locked")).message).toMatch(/temporarily locked/);
  });

  it("explain security blocks, network failures and server errors", () => {
    expect(loginFailure(problem(403, "origin_mismatch")).message).toMatch(/security check/);
    expect(loginFailure(new NetworkError(new TypeError("x"))).message).toMatch(/can't be reached/);
    expect(loginFailure(problem(500, "internal_error"))).toEqual({
      message: "Sign-in didn't work because of a problem on our side. Try again in a moment.",
      requestId: "req-9",
    });
  });
});

describe("sign-in requests", () => {
  it("POST the frozen §7.1 endpoints with JSON bodies", async () => {
    const seen: Request[] = [];
    const client = createApiClient({
      baseUrl: "http://127.0.0.1:3050",
      fetch: async (request) => {
        seen.push(request.clone());
        return Response.json({ user_id: "u1" });
      },
    });
    await signIn("meera.iyer@demo.lamikraft.test", "correct horse battery", client);
    await demoSignIn("tok_123", client);
    expect(seen.map((r) => `${r.method} ${new URL(r.url).pathname}`)).toEqual([
      "POST /api/v1/identity/session",
      "POST /api/v1/identity/demo-sign-in",
    ]);
    expect(await seen[0]!.json()).toEqual({ email: "meera.iyer@demo.lamikraft.test", password: "correct horse battery" });
    expect(await seen[1]!.json()).toEqual({ token: "tok_123" });
    // Tokens never travel in the URL.
    expect(seen[1]!.url).not.toContain("tok_123");
  });

  it("do not redirect to sign-in on a wrong password", async () => {
    const onUnauthorized = vi.fn();
    const client = createApiClient({
      baseUrl: "http://127.0.0.1:3050",
      onUnauthorized,
      fetch: async () =>
        new Response(JSON.stringify({ title: "Sign-in failed", status: 401, code: "invalid_credentials" }), {
          status: 401,
          headers: { "Content-Type": "application/problem+json" },
        }),
    });
    await expect(signIn("a@b.test", "x", client)).rejects.toBeInstanceOf(ProblemError);
    expect(onUnauthorized).not.toHaveBeenCalled();
  });
});

describe("demo link fragment", () => {
  it("reads #t= and ignores everything else", () => {
    expect(readFragmentToken("#t=abc123")).toBe("abc123");
    expect(readFragmentToken("#x=1&t=abc%2B1")).toBe("abc+1");
    expect(readFragmentToken("#t=")).toBeNull();
    expect(readFragmentToken("")).toBeNull();
    expect(readFragmentToken("#")).toBeNull();
  });
});

describe("auth pages", () => {
  it("login form: labelled email and password with autocomplete hints and a submit button", () => {
    const html = render(<LoginForm next="/today" />);
    expect(html).toMatch(/<input[^>]*type="email"[^>]*autoComplete="username"|<input[^>]*autoComplete="username"[^>]*type="email"/);
    expect(html).toMatch(/autoComplete="current-password"/);
    expect(countTags(html, "label")).toBe(2);
    expect(html).toContain('type="submit"');
    expect(textOf(html)).toBe("Email Password Sign in Forgot your password?");
  });

  it("login form: the password starts hidden with a labelled show/hide toggle (PARITY UI-26)", () => {
    const html = render(<LoginForm next="/today" />);
    expect(html).toMatch(/<input[^>]*type="password"/);
    expect(html).toMatch(/<button(?=[^>]*aria-pressed="false")(?=[^>]*aria-label="Show password")[^>]*>/);
    // The toggle is a plain button, never a second submit button inside the form.
    expect(html).toMatch(/<button(?=[^>]*aria-label="Show password")(?=[^>]*type="button")[^>]*>/);
  });

  it("demo sign-in starts as a status message (the token is read after mount)", () => {
    const html = render(<DemoSignIn />);
    expect(html).toContain('role="status"');
    expect(textOf(html)).toBe("Signing you in to the demo workspace…");
  });

  it("sign-out asks first and keeps a way back", () => {
    const html = render(<SignOutPanel />);
    expect(textOf(html)).toContain("Sign out of Lamikraft One on this device?");
    expect(html).toContain('href="/today"');
    expect(countTags(html, "button")).toBe(1);
  });
});
