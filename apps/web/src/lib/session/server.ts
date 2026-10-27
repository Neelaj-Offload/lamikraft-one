/**
 * Request-scoped server helpers: forward the browser's cookies to FastAPI at
 * LK_API_INTERNAL_URL (api-conventions §1). Import only from server components.
 */

import { headers } from "next/headers";
import { fetchBootstrap, serverGet, type BootstrapResult, type ServerFetchOptions } from "./fetch-bootstrap";

/** Set by src/proxy.ts so server layouts know the requested path (for `/login?next=`). */
export const PATH_HEADER = "x-lk-path";

export function apiInternalUrl(): string {
  return (process.env.LK_API_INTERNAL_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
}

async function requestOptions(): Promise<ServerFetchOptions> {
  const incoming = await headers();
  return {
    baseUrl: apiInternalUrl(),
    cookieHeader: incoming.get("cookie"),
    requestId: incoming.get("x-request-id"),
    // Next fills this with the socket's remote address when no proxy in front of it set one.
    forwardedFor: incoming.get("x-forwarded-for"),
  };
}

export async function loadSession(): Promise<BootstrapResult> {
  return fetchBootstrap(await requestOptions());
}

export async function requestedPath(): Promise<string | null> {
  return (await headers()).get(PATH_HEADER);
}

/** Prefetch helper for pages: resolves to the JSON body, or null when the call fails. */
export async function serverGetJson(path: `/api/v1/${string}`): Promise<unknown | null> {
  const result = await serverGet(path, await requestOptions());
  return result.ok ? result.data : null;
}
