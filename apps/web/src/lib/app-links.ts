/**
 * Maps the in-app paths that backend modules put in payloads (`SourceRef.path`, `ActionView.path`)
 * to this app's routes. The server names some screens by their resource, not by the page that
 * shows them:
 * - `/approvals/{proposal_id}` is the review page `/inbox/approvals/{proposal_id}`;
 * - `/inbox/{task_id}` is the Inbox task drawer, `/inbox?task={task_id}`.
 * Everything else must already be an in-app path (`safeAppPath`); anything that would leave
 * the app is dropped.
 */

import { safeAppPath } from "./safe-path";

export const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function reviewHref(proposalId: string): string {
  return `/inbox/approvals/${encodeURIComponent(proposalId)}`;
}

export function taskHref(taskId: string, base = "/inbox"): string {
  return `${base}?${new URLSearchParams({ task: taskId }).toString()}`;
}

export function appLinkFor(raw: unknown): string | null {
  const path = safeAppPath(raw);
  if (!path) return null;
  const cut = path.search(/[?#]/);
  const pathname = cut === -1 ? path : path.slice(0, cut);
  const approval = /^\/approvals\/([^/]+)\/?$/.exec(pathname);
  if (approval && UUID_PATTERN.test(approval[1]!)) return reviewHref(approval[1]!);
  const task = /^\/inbox\/([^/]+)\/?$/.exec(pathname);
  if (task && UUID_PATTERN.test(task[1]!)) return taskHref(task[1]!);
  return path;
}
