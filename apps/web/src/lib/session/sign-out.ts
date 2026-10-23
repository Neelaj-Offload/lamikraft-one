import { api, requestUntyped, type ApiClient } from "@/lib/api/client";
import { ProblemError } from "@/lib/api/errors";

export const SESSION_PATH = "/api/v1/identity/session";

/**
 * Revokes the current session (`DELETE /api/v1/identity/session`, api-conventions §7.1).
 * A 401 means the session had already ended, which is the outcome the user asked for.
 * Anything else (offline, 5xx) is reported: the user is still signed in and must know it.
 */
export async function signOut(client: ApiClient = api): Promise<{ ok: true } | { ok: false; error: unknown }> {
  try {
    await requestUntyped<unknown>(client, "delete", SESSION_PATH);
    return { ok: true };
  } catch (error) {
    if (error instanceof ProblemError && error.status === 401) return { ok: true };
    return { ok: false, error };
  }
}
