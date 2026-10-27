"use client";

import { createElement, type ReactNode } from "react";
import { isEndpointUnavailable, isNetworkError, ProblemError, type ConflictInfo } from "@/lib/api/errors";
import { cx } from "@/lib/cx";
import { stateMessages as m } from "@/messages/states";
import { Button } from "./button";
import {
  AlertIcon,
  ConflictIcon,
  ErrorIcon,
  InfoIcon,
  LockIcon,
  OfflineIcon,
  RefreshIcon,
  SuccessIcon,
} from "./icons";
import { LinkButton } from "./link";
import { Skeleton, SkeletonText } from "./skeleton";

/**
 * The state catalogue (frontend_verification §15): every state has real copy and a real
 * next step. Headings default to h2 because these render inside a page that owns the h1.
 */

type HeadingLevel = 1 | 2 | 3;

interface StateViewProps {
  icon: ReactNode;
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
  headingLevel?: HeadingLevel;
  tone?: "neutral" | "danger" | "warning";
  role?: "alert" | "status";
  compact?: boolean;
  className?: string;
}

export function StateView({
  icon,
  title,
  children,
  actions,
  headingLevel = 2,
  tone = "neutral",
  role,
  compact = false,
  className,
}: StateViewProps) {
  return (
    <section
      role={role}
      className={cx(
        "flex flex-col items-start gap-3 rounded-lg border bg-surface",
        compact ? "p-4" : "px-5 py-6 md:px-6",
        className,
      )}
    >
      <div className="flex items-start gap-3">
        <span
          aria-hidden="true"
          className={cx(
            "mt-0.5 shrink-0",
            tone === "danger" ? "text-danger" : tone === "warning" ? "text-warning-text" : "text-ink-muted",
          )}
        >
          {icon}
        </span>
        <div className="flex min-w-0 flex-col gap-1">
          {createElement(`h${headingLevel}`, { className: "text-base font-bold text-ink" }, title)}
          {children ? <div className="text-[15px] text-ink-muted">{children}</div> : null}
        </div>
      </div>
      {actions ? <div className="flex flex-wrap gap-2 ps-8">{actions}</div> : null}
    </section>
  );
}

export function EmptyState({
  title,
  children,
  action,
  headingLevel,
  className,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  headingLevel?: HeadingLevel;
  className?: string;
}) {
  return (
    <StateView icon={<InfoIcon />} title={title} actions={action} headingLevel={headingLevel} className={className}>
      {children}
    </StateView>
  );
}

/** Busy region with a layout-shaped skeleton that appears after 150 ms. */
export function Loading({
  label,
  variant = "list",
  rows = 4,
  className,
}: {
  label: string;
  variant?: "list" | "detail" | "inline";
  rows?: number;
  className?: string;
}) {
  return (
    <div role="status" aria-busy="true" className={cx("flex flex-col gap-4", className)}>
      <span className="sr-only">{m.loading(label)}</span>
      <div className="animate-appear-late flex flex-col gap-4">
        {variant === "inline" ? (
          <Skeleton className="h-4 w-40" />
        ) : variant === "detail" ? (
          <>
            <Skeleton className="h-7 w-2/3" />
            <SkeletonText lines={4} />
          </>
        ) : (
          Array.from({ length: rows }, (_, index) => (
            <div key={index} className="flex flex-col gap-2 border-b pb-4">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-5 w-3/4" />
              <Skeleton className="h-3.5 w-1/2" />
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function errorBody(error: unknown): string {
  if (error instanceof ProblemError) {
    if (error.status === 429) return error.detail ?? m.error.rateLimited;
    if (error.status === 502 || error.status === 503 || error.status === 504) return m.error.unavailable;
    if (error.status >= 500) return m.error.server;
    return error.detail ?? error.title;
  }
  return m.error.generic;
}

/**
 * Problem+json-aware error state: what failed, the server's explanation, the request id to
 * quote to support, and Retry. A network failure renders the Offline state; an endpoint that
 * does not exist yet renders a calm "not available yet" state instead of an error.
 */
export function ErrorState({
  error,
  what,
  onRetry,
  backToToday = true,
  headingLevel,
  compact,
  className,
}: {
  error: unknown;
  /** Lower-case noun phrase: "your briefing", "the Inbox". */
  what: string;
  onRetry?: () => void;
  /**
   * Offer "Back to Today" when the endpoint is not available yet. Pass false on Today itself
   * (and inside dialogs), where the link would lead to the page already shown.
   */
  backToToday?: boolean;
  headingLevel?: HeadingLevel;
  compact?: boolean;
  className?: string;
}) {
  if (isNetworkError(error)) return <Offline onRetry={onRetry} headingLevel={headingLevel} compact={compact} className={className} />;
  if (isEndpointUnavailable(error)) {
    const actions = (
      <>
        {onRetry ? (
          <Button onPress={onRetry} icon={<RefreshIcon size={18} />}>
            {m.retry}
          </Button>
        ) : null}
        {backToToday ? <LinkButton href="/today">{m.backToToday}</LinkButton> : null}
      </>
    );
    return (
      <StateView
        icon={<InfoIcon />}
        title={m.notYetAvailable.title(what)}
        headingLevel={headingLevel}
        compact={compact}
        className={className}
        actions={onRetry || backToToday ? actions : null}
      >
        {m.notYetAvailable.body}
      </StateView>
    );
  }
  const requestId = error instanceof ProblemError ? error.request_id : null;
  return (
    <StateView
      icon={<ErrorIcon />}
      title={m.error.title(what)}
      tone="danger"
      role="alert"
      headingLevel={headingLevel}
      compact={compact}
      className={className}
      actions={
        onRetry ? (
          <Button onPress={onRetry} icon={<RefreshIcon size={18} />}>
            {m.retry}
          </Button>
        ) : null
      }
    >
      <p>{errorBody(error)}</p>
      {requestId ? (
        <p className="mt-1 text-sm">
          {m.requestId}: <span className="font-mono text-ink select-all">{requestId}</span>
        </p>
      ) : null}
    </StateView>
  );
}

/**
 * No connection to the server. With `asOf` (already formatted in the user's zone) it labels
 * cached content that stays on screen: "Offline · as of 09:02", actions disabled
 * (briefing.md §11).
 */
export function Offline({
  onRetry,
  asOf,
  headingLevel,
  compact,
  className,
}: {
  onRetry?: () => void;
  asOf?: string | null;
  headingLevel?: HeadingLevel;
  compact?: boolean;
  className?: string;
}) {
  return (
    <StateView
      icon={<OfflineIcon />}
      title={asOf ? m.offline.asOfTitle(asOf) : m.offline.title}
      tone="warning"
      role="status"
      headingLevel={headingLevel}
      compact={compact}
      className={className}
      actions={onRetry ? <Button onPress={onRetry}>{m.retry}</Button> : null}
    >
      {asOf ? m.offline.asOfBody : m.offline.body}
    </StateView>
  );
}

/** Data older than the user should rely on; `asOf` is already formatted in the user's zone. */
export function Stale({ asOf, onRefresh, className }: { asOf: string; onRefresh: () => void; className?: string }) {
  return (
    <StateView
      icon={<AlertIcon />}
      title={m.stale.title}
      tone="warning"
      role="status"
      compact
      className={className}
      actions={
        <Button size="sm" onPress={onRefresh} icon={<RefreshIcon size={16} />}>
          {m.stale.action}
        </Button>
      }
    >
      {m.stale.body(asOf)}
    </StateView>
  );
}

/**
 * 409 version conflict with the three-way hint (base → mine vs theirs). The screen owns the
 * merge (src/lib/merge.ts); this explains what happened and offers the two safe next steps.
 */
export function Conflict({
  conflict,
  changedAtLabel,
  onReview,
  onKeepMine,
  className,
}: {
  conflict: ConflictInfo;
  /** `conflict.changedAt` formatted in the user's zone. */
  changedAtLabel?: string | null;
  onReview: () => void;
  onKeepMine?: () => void;
  className?: string;
}) {
  return (
    <StateView
      icon={<ConflictIcon />}
      title={m.conflict.title}
      tone="warning"
      role="alert"
      compact
      className={className}
      actions={
        <>
          <Button variant="primary" onPress={onReview}>
            {m.conflict.reload}
          </Button>
          {onKeepMine ? <Button onPress={onKeepMine}>{m.conflict.keepMine}</Button> : null}
        </>
      }
    >
      <p>{m.conflict.body(conflict.changedBy, changedAtLabel ?? null)}</p>
      <p className="mt-1 text-sm">{m.conflict.hint}</p>
      {conflict.request_id ? (
        <p className="mt-1 text-sm">
          {m.requestId}: <span className="font-mono text-ink select-all">{conflict.request_id}</span>
        </p>
      ) : null}
    </StateView>
  );
}

/** An area the user's role does not include; shows no data, names the missing capability. */
export function PermissionDenied({ area, headingLevel = 1, className }: { area: string; headingLevel?: HeadingLevel; className?: string }) {
  return (
    <StateView
      icon={<LockIcon />}
      title={m.permissionDenied.title(area)}
      headingLevel={headingLevel}
      className={className}
      actions={<LinkButton href="/today">{m.backToToday}</LinkButton>}
    >
      {m.permissionDenied.body}
    </StateView>
  );
}

/** A record that does not exist or is out of scope; the two are indistinguishable on purpose. */
export function NotAvailable({ headingLevel = 1, className }: { headingLevel?: HeadingLevel; className?: string }) {
  return (
    <StateView
      icon={<InfoIcon />}
      title={m.notAvailable.title}
      headingLevel={headingLevel}
      className={className}
      actions={<LinkButton href="/today">{m.backToToday}</LinkButton>}
    >
      {m.notAvailable.body}
    </StateView>
  );
}

/** A completed command with a persistent receipt link. */
export function Success({
  title,
  children,
  receipt,
  headingLevel,
  className,
}: {
  title: string;
  children?: ReactNode;
  receipt?: { label: string; href: string };
  headingLevel?: HeadingLevel;
  className?: string;
}) {
  return (
    <StateView
      icon={<SuccessIcon className="text-success" />}
      title={title}
      role="status"
      headingLevel={headingLevel}
      compact
      className={className}
      actions={receipt ? <LinkButton href={receipt.href}>{receipt.label}</LinkButton> : null}
    >
      {children}
    </StateView>
  );
}
