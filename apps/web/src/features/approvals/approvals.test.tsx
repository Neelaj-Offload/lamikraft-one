import { describe, expect, it } from "vitest";
import { createApiClient } from "@/lib/api/client";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { renderWithQueries, textOf } from "@/lib/test-support/render";
import { testQuoteWire } from "@/lib/test-support/sales";
import { parseQuoteDetail } from "@/features/sales/parse";
import { decideBody, decideProposal, isReviewConflict, parseProposal } from "./api";
import { decisionState, quoteChanges, ReviewView } from "./review-view";

const ME = "0192a000-0000-7000-8000-00000000000a";
const PROPOSAL = "0192a000-0000-7000-8000-0000000000a5";
const QUOTE = "0192a000-0000-7000-8000-000000000005";
const HASH = "a".repeat(64);

function rawProposal(overrides: Record<string, unknown> = {}) {
  return {
    id: PROPOSAL,
    kind: "sales.quote.review",
    status: "pending",
    title: "Review LK-QT-2026-0005 · Maison Atelier SARL",
    summary: "Price override on one line.",
    facts: { price_override: true, discount: false, below_minimum: false, grand_total: "4560.00", currency: "EUR" },
    content_hash: HASH,
    requested_by: "0192a000-0000-7000-8000-0000000000b2",
    requested_by_name: "Meera Iyer",
    requested_at: "2026-10-12T02:50:00Z",
    expires_at: null,
    decided_at: null,
    decision_reason: null,
    version: 1,
    targets: [{ target_type: "sales.quote", target_id: QUOTE, target_version: 4 }],
    capabilities: { decide: { allowed: true, reason_code: null }, withdraw: { allowed: false, reason_code: "only_requester_can_withdraw" } },
    ...overrides,
  };
}

const problem = (status: number, code: string) => new ProblemError({ code, title: "Conflict", status, detail: null, request_id: "req-1" });

describe("approval decisions", () => {
  it("send exactly the content hash and version on screen", async () => {
    const proposal = parseProposal(rawProposal());
    expect(decideBody(proposal, "approve", null)).toEqual({ decision: "approve", content_hash: HASH, expected_version: 1 });
    expect(decideBody(proposal, "reject", "  price too low ")).toEqual({ decision: "reject", content_hash: HASH, expected_version: 1, reason: "price too low" });
    const seen: Request[] = [];
    const client = createApiClient({
      baseUrl: "http://127.0.0.1:3050",
      getCsrfToken: () => "csrf",
      fetch: async (request) => {
        seen.push(request.clone());
        return Response.json(rawProposal({ status: "approved", version: 2 }));
      },
    });
    const decided = await decideProposal(proposal, "approve", null, "k-1", client);
    expect(new URL(seen[0]!.url).pathname).toBe(`/api/v1/approvals/proposals/${PROPOSAL}/decide`);
    expect(decided.status).toBe("approved");
  });

  it("treats every staleness 409 as 'reload and review again'", () => {
    for (const code of ["proposal_changed", "proposal_stale", "approval_stale", "proposal_content_mismatch", "proposal_expired", "proposal_approved", "version_conflict"]) {
      expect(isReviewConflict(problem(409, code))).toBe(true);
    }
    expect(isReviewConflict(problem(403, "separation_of_duties"))).toBe(false);
    expect(isReviewConflict(new Error("x"))).toBe(false);
  });

  it("derives the controls from capabilities, with separation of duties explained", () => {
    const proposal = parseProposal(rawProposal());
    expect(decisionState(proposal, ME)).toEqual({ canDecide: true, canWithdraw: false, explanation: null });
    const own = parseProposal(
      rawProposal({
        requested_by: ME,
        capabilities: { decide: { allowed: false, reason_code: "not_an_eligible_approver" }, withdraw: { allowed: true, reason_code: null } },
      }),
    );
    expect(decisionState(own, ME)).toMatchObject({ canDecide: false, canWithdraw: true, explanation: expect.stringMatching(/separation of duties/) });
    expect(decisionState({ ...proposal, status: "approved" }, ME)).toMatchObject({ canDecide: false, canWithdraw: false });
  });

  it("lists what changed from the list price", () => {
    const quote = parseQuoteDetail(testQuoteWire({ overridden: true }));
    const changes = quoteChanges(quote, "en-IN");
    expect(changes[0]).toMatch(/LK-OT-0450.*list price €24\.00, quoted €22\.00 · Reason: Long-standing customer/);
  });
});

describe("ReviewView (server render)", () => {
  it("shows facts, the quote with persisted totals, and Approve / Reject for an eligible approver", () => {
    const html = renderWithQueries(<ReviewView proposalId={PROPOSAL} />, (client) => {
      client.setQueryData(queryKeys.approvals.proposal(PROPOSAL), parseProposal(rawProposal()));
      client.setQueryData(queryKeys.sales.quote(QUOTE), parseQuoteDetail(testQuoteWire({ id: QUOTE, overridden: true, version: 4 })));
    });
    const text = textOf(html);
    expect(html).toMatch(/<h1[^>]*>Review LK-QT-2026-0005/);
    expect(text).toContain("Price differs from the list Yes");
    expect(text).toContain("€4,560.00");
    expect(text).toMatch(/Grand total \(excl\. taxes\) €5,280\.00/);
    expect(text).toContain("Approve");
    expect(text).toContain("Reject");
    expect(text).not.toContain("The quote has changed since this request");
  });

  it("warns when the quote moved on since the request, and explains when the viewer cannot decide", () => {
    const html = renderWithQueries(<ReviewView proposalId={PROPOSAL} />, (client) => {
      client.setQueryData(
        queryKeys.approvals.proposal(PROPOSAL),
        parseProposal(rawProposal({ requested_by: ME, capabilities: { decide: { allowed: false, reason_code: "not_an_eligible_approver" } } })),
      );
      client.setQueryData(queryKeys.sales.quote(QUOTE), parseQuoteDetail(testQuoteWire({ id: QUOTE, version: 5 })));
    });
    const text = textOf(html);
    expect(text).toContain("The quote has changed since this request");
    expect(text).toContain("separation of duties");
    expect(text).not.toMatch(/\bApprove\b/);
  });
});
