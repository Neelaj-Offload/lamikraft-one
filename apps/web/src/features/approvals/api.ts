/**
 * Approvals (backend/app/modules/approvals/router.py): read a proposal and decide it with the
 * exact `content_hash` and `expected_version` the person reviewed. The shapes mirror
 * `ProposalOut`, `TargetOut` and `DecideIn`. INTERIM(api-generate): the endpoints are in the
 * regenerated schema on main; switch to `api.GET/POST` once this branch carries it.
 */

import { api, idempotencyHeaders, requestUntyped, type ApiClient } from "@/lib/api/client";
import { isStalenessConflict, ProblemError } from "@/lib/api/errors";

export interface ProposalTarget {
  target_type: string;
  target_id: string;
  target_version: number | null;
}

export interface ProposalCapability {
  allowed: boolean;
  reason_code: string | null;
}

export interface Proposal {
  id: string;
  kind: string;
  status: "pending" | "approved" | "rejected" | "expired" | "invalidated" | "superseded" | "withdrawn" | (string & {});
  title: string;
  summary: string | null;
  facts: Readonly<Record<string, unknown>>;
  content_hash: string;
  requested_by: string;
  requested_by_name: string | null;
  requested_at: string;
  expires_at: string | null;
  decided_at: string | null;
  decision_reason: string | null;
  version: number;
  targets: ProposalTarget[];
  capabilities: Readonly<Record<string, ProposalCapability>>;
}

export class ProposalShapeError extends Error {
  override readonly name = "ProposalShapeError";
}

type Json = Record<string, unknown>;
const isObject = (value: unknown): value is Json => value !== null && typeof value === "object" && !Array.isArray(value);
const str = (value: unknown): string | null => (typeof value === "string" && value !== "" ? value : null);
const int = (value: unknown): number | null => (typeof value === "number" && Number.isInteger(value) ? value : null);

export function parseProposal(raw: unknown): Proposal {
  if (!isObject(raw) || !str(raw.id) || !str(raw.content_hash) || int(raw.version) === null) {
    throw new ProposalShapeError("The approval request could not be read.");
  }
  const capabilities: Record<string, ProposalCapability> = {};
  if (isObject(raw.capabilities)) {
    for (const [key, cap] of Object.entries(raw.capabilities)) {
      if (isObject(cap) && typeof cap.allowed === "boolean") capabilities[key] = { allowed: cap.allowed, reason_code: str(cap.reason_code) };
    }
  }
  return {
    id: str(raw.id)!,
    kind: str(raw.kind) ?? "",
    status: str(raw.status) ?? "pending",
    title: str(raw.title) ?? "",
    summary: str(raw.summary),
    facts: isObject(raw.facts) ? raw.facts : {},
    content_hash: str(raw.content_hash)!,
    requested_by: str(raw.requested_by) ?? "",
    requested_by_name: str(raw.requested_by_name),
    requested_at: str(raw.requested_at) ?? "",
    expires_at: str(raw.expires_at),
    decided_at: str(raw.decided_at),
    decision_reason: str(raw.decision_reason),
    version: int(raw.version)!,
    targets: (Array.isArray(raw.targets) ? raw.targets : []).flatMap((target) =>
      isObject(target) && str(target.target_id)
        ? [{ target_type: str(target.target_type) ?? "", target_id: str(target.target_id)!, target_version: int(target.target_version) }]
        : [],
    ),
    capabilities,
  };
}

const proposalPath = (id: string): `/api/v1/${string}` => `/api/v1/approvals/proposals/${encodeURIComponent(id)}`;

export async function fetchProposal(id: string, signal?: AbortSignal, client: ApiClient = api): Promise<Proposal> {
  return parseProposal(await requestUntyped<unknown>(client, "get", proposalPath(id), { signal }));
}

/** `DecideIn` built only from what the person reviewed: the hash and version on screen. */
export function decideBody(proposal: Pick<Proposal, "content_hash" | "version">, decision: "approve" | "reject", reason: string | null) {
  const body: { decision: "approve" | "reject"; content_hash: string; expected_version: number; reason?: string } = {
    decision,
    content_hash: proposal.content_hash,
    expected_version: proposal.version,
  };
  const text = reason?.trim();
  if (text) body.reason = text;
  return body;
}

export async function decideProposal(
  proposal: Pick<Proposal, "id" | "content_hash" | "version">,
  decision: "approve" | "reject",
  reason: string | null,
  idempotencyKey: string,
  client: ApiClient = api,
): Promise<Proposal> {
  const raw = await requestUntyped<unknown>(client, "post", `${proposalPath(proposal.id)}/decide`, {
    body: decideBody(proposal, decision, reason),
    headers: idempotencyHeaders(idempotencyKey),
  });
  return parseProposal(raw);
}

export async function withdrawProposal(proposal: Pick<Proposal, "id">, idempotencyKey: string, client: ApiClient = api): Promise<Proposal> {
  return parseProposal(
    await requestUntyped<unknown>(client, "post", `${proposalPath(proposal.id)}/withdraw`, { headers: idempotencyHeaders(idempotencyKey) }),
  );
}

/**
 * 409s that mean "what you reviewed is no longer what would be decided": the request or its
 * document changed, went stale, expired or was already decided. The page reloads and says so.
 */
const REVIEW_CONFLICTS = new Set([
  "proposal_changed",
  "proposal_stale",
  "approval_stale",
  "proposal_content_mismatch",
  "proposal_expired",
  "version_conflict",
]);

export function isReviewConflict(error: unknown): error is ProblemError {
  if (isStalenessConflict(error)) return true;
  return error instanceof ProblemError && error.status === 409 && (REVIEW_CONFLICTS.has(error.code) || error.code.startsWith("proposal_"));
}
