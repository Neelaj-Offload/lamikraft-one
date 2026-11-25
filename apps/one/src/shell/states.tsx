"use client";

import type { ReactNode } from "react";
import { isEndpointUnavailable, isNetworkError, isProblemError, ProblemError } from "@/lib/api/errors";
import { Banner } from "~/ui/banner";
import { Button } from "~/ui/button";
import { EmptyState } from "~/ui/empty-state";
import { SkeletonText } from "~/ui/skeleton";
import type { IconName } from "~/ui/icon";

/**
 * Loading, error and empty states. Rules: skeletons shaped like the content (never a page
 * spinner); errors appear in place, say what happened and offer the way forward; empty states
 * lead with the next action.
 */

/** A plain-language title and body for any failed request. */
export function describeError(error: unknown, what: string): { title: string; body: string; requestId: string | null } {
  if (isNetworkError(error)) {
    return { title: `${what} could not load`, body: "The connection dropped before the server answered. Check your network, then try again.", requestId: null };
  }
  if (isEndpointUnavailable(error)) {
    return { title: `${what} is not switched on yet`, body: "This part of Lamikraft One has not been enabled for your workspace.", requestId: null };
  }
  if (isProblemError(error)) {
    const problem = error as ProblemError;
    if (problem.status === 403) {
      return { title: `You do not have access to ${what.toLowerCase()}`, body: "Your role does not include this. Ask a workspace admin if you need it.", requestId: problem.request_id ?? null };
    }
    if (problem.status === 404) {
      return { title: `${what} was not found`, body: "It may have been removed, or the link is out of date.", requestId: problem.request_id ?? null };
    }
    return {
      title: `${what} could not load`,
      body: problem.detail || problem.title || "The server could not complete the request. Try again; if it keeps happening, share the reference below.",
      requestId: problem.request_id ?? null,
    };
  }
  return { title: `${what} could not load`, body: "Something unexpected happened. Try again.", requestId: null };
}

/** An in-place error with a retry. `what` names the thing in sentence case: "Quotations", "This order". */
export function ErrorBlock({ error, what, onRetry, className }: { error: unknown; what: string; onRetry?: () => void; className?: string }) {
  const { title, body, requestId } = describeError(error, what);
  return (
    <Banner
      tone="ember"
      title={title}
      className={className}
      action={
        onRetry ? (
          <Button variant="secondary" size="sm" iconLeft="refresh" onPress={onRetry}>
            Try again
          </Button>
        ) : undefined
      }
    >
      {body}
      {requestId ? (
        <>
          {" "}
          <span className="t-code-sm lk-mono select-all">Reference {requestId}</span>
        </>
      ) : null}
    </Banner>
  );
}

/** A placeholder panel while a block loads. Prefer DataTable's own `loading` for tables. */
export function LoadingBlock({ lines = 4, label = "Loading", className }: { lines?: number; label?: string; className?: string }) {
  return (
    <div className={`lk-glass lk-glass-pad-md ${className ?? ""}`} role="status" aria-label={label}>
      <SkeletonText lines={lines} />
    </div>
  );
}

interface QueryLike<T> {
  data: T | undefined;
  error: unknown;
  isPending: boolean;
  isError: boolean;
  refetch: () => unknown;
}

/**
 * Renders a query's three states with one call:
 *   <QueryView query={q} what="Quotations" isEmpty={(d) => d.items.length === 0} empty={<EmptyState … />}>
 *     {(data) => …}
 *   </QueryView>
 */
export function QueryView<T>({
  query,
  what,
  children,
  loading,
  isEmpty,
  empty,
}: {
  query: QueryLike<T>;
  what: string;
  children: (data: T) => ReactNode;
  loading?: ReactNode;
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode;
}) {
  if (query.isPending) return <>{loading ?? <LoadingBlock label={`Loading ${what.toLowerCase()}`} />}</>;
  if (query.isError || query.data === undefined) return <ErrorBlock error={query.error} what={what} onRetry={() => void query.refetch()} />;
  if (isEmpty?.(query.data)) return <>{empty ?? null}</>;
  return <>{children(query.data)}</>;
}

/** Shown when a screen exists but the person lacks one specific capability inside it. */
export function NotPermitted({ what, icon = "lock" }: { what: string; icon?: IconName }) {
  return <EmptyState icon={icon} title={`${what} is not part of your role`} text="Ask a workspace admin if you need it." compact />;
}
