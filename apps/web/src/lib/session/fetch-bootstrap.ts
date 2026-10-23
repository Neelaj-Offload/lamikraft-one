/**
 * Server-side bootstrap call used by the (app) layout (api-conventions §8). Kept free of
 * Next imports so it is unit-testable; `server.ts` supplies the request's cookies.
 */

import { BOOTSTRAP_PATH } from "@/lib/api/client";
import { ProblemError, type ProblemDetails } from "@/lib/api/errors";
import { BootstrapShapeError, parseBootstrap } from "./parse";
import type { SessionBootstrap } from "./types";

export type BootstrapResult =
  | { status: "ok"; bootstrap: SessionBootstrap }
  | { status: "unauthenticated" }
  | { status: "error"; problem: ProblemDetails };

export interface ServerFetchOptions {
  /** Origin of FastAPI as seen from the Next server (LK_API_INTERNAL_URL). */
  baseUrl: string;
  /** The incoming request's Cookie header, forwarded verbatim. */
  cookieHeader: string | null;
  requestId?: string | null;
  fetchImpl?: typeof fetch;
}

/** Problem used when the API cannot be reached at all; no internal detail is exposed. */
export function unreachableProblem(): ProblemDetails {
  return {
    code: "service_unavailable",
    title: "Lamikraft One could not reach its server",
    status: 503,
    detail: "Check that the API is running, then reload the page.",
    request_id: null,
  };
}

export function forwardedHeaders(options: ServerFetchOptions): Headers {
  const headers = new Headers({ accept: "application/json" });
  if (options.cookieHeader) headers.set("cookie", options.cookieHeader);
  if (options.requestId) headers.set("x-request-id", options.requestId);
  return headers;
}

/** GET a JSON resource from FastAPI on behalf of the signed-in browser. Never cached. */
export async function serverGet(
  path: `/api/v1/${string}`,
  options: ServerFetchOptions,
): Promise<{ ok: true; data: unknown; response: Response } | { ok: false; response: Response | null; problem: ProblemDetails }> {
  const fetchImpl = options.fetchImpl ?? fetch;
  let response: Response;
  try {
    response = await fetchImpl(`${options.baseUrl.replace(/\/+$/, "")}${path}`, {
      method: "GET",
      headers: forwardedHeaders(options),
      cache: "no-store",
      redirect: "manual",
    });
  } catch {
    return { ok: false, response: null, problem: unreachableProblem() };
  }
  let body: unknown = null;
  const text = await response.text();
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (!response.ok) return { ok: false, response, problem: ProblemError.fromResponse(response, body).problem };
  return { ok: true, data: body, response };
}

export async function fetchBootstrap(options: ServerFetchOptions): Promise<BootstrapResult> {
  if (!options.cookieHeader) return { status: "unauthenticated" };
  const result = await serverGet(BOOTSTRAP_PATH as `/api/v1/${string}`, options);
  if (!result.ok) {
    if (result.response?.status === 401) return { status: "unauthenticated" };
    return { status: "error", problem: result.problem };
  }
  try {
    return { status: "ok", bootstrap: parseBootstrap(result.data) };
  } catch (error) {
    const detail = error instanceof BootstrapShapeError ? error.message : "The session response could not be read.";
    return {
      status: "error",
      problem: {
        code: "bootstrap_unreadable",
        title: "Your session details could not be read",
        status: 502,
        detail,
        request_id: result.response.headers.get("x-request-id"),
      },
    };
  }
}
