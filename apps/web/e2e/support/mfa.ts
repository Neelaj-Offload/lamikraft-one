/**
 * Two-step verification for e2e specs: enrols the signed-in person's authenticator through the real API
 * (`POST /api/v1/identity/me/mfa/totp`, then the confirmation with the first code), which makes the session MFA-verified, the
 * state MFA-flagged reads (audit log, migration, backups) need. RFC 6238 codes are computed here with node:crypto
 * (SHA-1, 30-second steps, six digits, like pyotp's defaults); the e2e API runs on the system clock.
 */

import { createHmac } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";

function base32(secret: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const ch of secret.replace(/=+$/, "").toUpperCase()) {
    const index = alphabet.indexOf(ch);
    if (index < 0) throw new Error(`not base32: ${ch}`);
    bits += index.toString(2).padStart(5, "0");
  }
  const bytes: number[] = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(Number.parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(bytes);
}

const STEP_MS = 30_000;
/** The last time step each secret's code was used in (the server refuses a code of an already used step). */
const lastUsed = new Map<string, number>();

/** The six-digit code for `at` (default now). */
export function totp(secret: string, at: number = Date.now()): string {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at / STEP_MS)));
  const digest = createHmac("sha1", base32(secret)).update(counter).digest();
  const offset = digest[digest.length - 1]! & 0x0f;
  const value = (digest.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return value.toString().padStart(6, "0");
}

/**
 * A code nobody has used yet: waits (at most one 30-second step) until a step this secret has not used begins, then
 * returns its code and records the step.
 */
export async function freshCode(page: Page, secret: string): Promise<string> {
  const used = lastUsed.get(secret) ?? -1;
  let step = Math.floor(Date.now() / STEP_MS);
  if (step <= used) {
    await page.waitForTimeout((used + 1) * STEP_MS - Date.now() + 250);
    step = Math.floor(Date.now() / STEP_MS);
  }
  lastUsed.set(secret, step);
  return totp(secret, step * STEP_MS);
}

async function unsafeHeaders(page: Page): Promise<Record<string, string>> {
  const bootstrap = await page.request.get("/api/v1/session/bootstrap");
  const csrf = ((await bootstrap.json()) as { csrf_token?: string | null }).csrf_token ?? "";
  const origin = new URL(test.info().project.use.baseURL ?? "http://127.0.0.1").origin;
  return { Origin: origin, "X-CSRF-Token": csrf };
}

/** Enrols an authenticator for the signed-in person and confirms it: the session is MFA-verified afterwards. */
export async function enrolAuthenticator(page: Page): Promise<string> {
  const started = await page.request.post("/api/v1/identity/me/mfa/totp", { headers: await unsafeHeaders(page) });
  expect(started.status(), `start authenticator enrolment: ${await started.text()}`).toBe(200);
  const { secret } = (await started.json()) as { secret: string };
  const confirmed = await page.request.post("/api/v1/identity/me/mfa/totp/confirmation", {
    data: { code: await freshCode(page, secret) },
    headers: await unsafeHeaders(page),
  });
  expect(confirmed.status(), `confirm the authenticator: ${await confirmed.text()}`).toBe(200);
  return secret;
}
