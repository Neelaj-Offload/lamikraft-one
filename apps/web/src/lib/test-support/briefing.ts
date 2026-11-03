/**
 * Test-only BriefingView payloads shaped like the canonical fixture world at D0 08:55 IST
 * (docs/architecture/fixtures.md §9.1, Meera: needs 2, plan 1, recommendations 1, changes 1,
 * coming next 1; initial view 5, full list 6). Never imported by product code.
 */

import type { BriefingItem, BriefingView, WireBriefingView, WireItem } from "@/features/briefing/types";

export function testItem(overrides: Partial<BriefingItem> & Pick<BriefingItem, "id" | "section">): BriefingItem {
  return {
    issue_id: `issue-${overrides.id}`,
    display_ordinal: 1,
    priority_band: "P2",
    family: "sales.customer_replies",
    title: `Item ${overrides.id}`,
    summary_text: null,
    due_label: null,
    reasons: [],
    fact_at: "2026-10-11T13:50:00Z",
    due_at: null,
    due_kind: "none",
    overdue: false,
    source_refs: [],
    recommendation: null,
    uncertainty_flags: [],
    allowed_actions: [],
    proposal_ref: null,
    member_count: 1,
    change_kind: "unchanged",
    is_reminder: false,
    fingerprint: `fp-${overrides.id}-1`,
    on_behalf_of: null,
    snoozed_until: null,
    ...overrides,
  };
}

export function meeraBriefing(): BriefingView {
  const items: BriefingItem[] = [
    testItem({
      id: "i1",
      section: "needs_you_now",
      display_ordinal: 1,
      priority_band: "P1",
      family: "sales.quote_expiry",
      title: "Berg & Co AB quote expires today",
      summary_text: "LK-QT-2026-0038 · 600 maple trivets · EUR 5,700.00",
      due_at: "2026-10-12T13:00:00Z",
      due_kind: "hard",
      source_refs: [
        { type: "sales.quote", id: "q38", label: "Quote LK-QT-2026-0038", href: "/sales/quotes/q38", updated_at: "2026-10-12T03:15:00Z" },
      ],
      recommendation: {
        id: "r1",
        action_code: "EXTEND_VALIDITY",
        label: "Extend the validity or confirm the order today.",
        reason_text: "The quote expires at the end of today.",
        effect_text: "Keeps the EUR 5,700.00 offer open.",
        alternatives: ["Mark as lost"],
      },
      allowed_actions: [
        { action: "open", label: "Open quote", primary: true, href: "/sales/quotes/q38", requires_reason: false, via: "briefings", max_until: null },
        { action: "snooze", label: null, primary: false, href: null, requires_reason: false, via: "briefings", max_until: null },
        { action: "mark_handled", label: null, primary: false, href: null, requires_reason: false, via: "briefings", max_until: null },
        { action: "assign", label: null, primary: false, href: null, requires_reason: false, via: "briefings", max_until: null },
        { action: "explain", label: null, primary: false, href: null, requires_reason: false, via: "briefings", max_until: null },
      ],
    }),
    testItem({ id: "i2", section: "needs_you_now", display_ordinal: 2, title: "Reply to Berg & Co AB" }),
    testItem({ id: "i3", section: "plan_for_today", display_ordinal: 3, title: "Reply to Nordhaus Interiors GmbH" }),
    testItem({ id: "i4", section: "recommendations", display_ordinal: 4, family: "sales.samples", title: "Follow up Maison Atelier SARL" }),
    testItem({ id: "i5", section: "changes_since_last_visit", display_ordinal: 5, family: "sales.customer_changes", title: "Maison Atelier SARL address updated" }),
    testItem({ id: "i6", section: "coming_next", display_ordinal: 6, is_reminder: true, title: "Call Maison about finish preferences" }),
  ];
  return {
    briefing_id: "b1",
    work_date: "2026-10-12",
    day_type: "working",
    version: 1,
    status: "ready",
    generated_at: "2026-10-12T03:25:00Z",
    data_as_of: "2026-10-12T03:25:00Z",
    ai_status: "not_used",
    overview: {
      greeting: "Good morning, Meera.",
      text: "Two customer replies need attention, one quote expires today, and yesterday's sample has been delivered.",
      text_source: "template",
      facts: { customer_replies: 2, quotes_expiring_today: 1 },
    },
    sections: [
      { code: "needs_you_now", total: 2, item_ids: ["i1", "i2"] },
      { code: "plan_for_today", total: 1, item_ids: ["i3"] },
      { code: "recommendations", total: 1, item_ids: ["i4"] },
      { code: "changes_since_last_visit", total: 1, item_ids: ["i5"] },
      { code: "coming_next", total: 1, item_ids: ["i6"] },
    ],
    items,
    initial_item_ids: ["i1", "i2", "i3", "i4", "i5"],
    pending_updates: 0,
    latest_version: 1,
    up_to_date: false,
    snoozed: [],
    last_ack: { briefing_id: "b0", version: 1, acknowledged_at: "2026-10-10T12:35:00Z", method: "viewed" },
    partial_families: [],
    fallback: null,
  };
}

// ---------------------------------------------------------------------------------------------
// Wire payloads (briefings/schemas.py), for the parser tests


export function wireItem(overrides: Partial<WireItem> & Pick<WireItem, "issue_id" | "section">): WireItem {
  return {
    ordinal: 1,
    band: "P2",
    score: 50,
    reason_codes: [],
    reasons: [],
    kind: "reply_needed",
    family: "sales.customer_replies",
    title: `Item ${overrides.issue_id}`,
    summary: "",
    facts: {},
    money: [],
    source_refs: [],
    fact_at: "2026-10-11T13:50:00Z",
    owner: null,
    assignee: null,
    due_at: null,
    due_local: null,
    due_label: null,
    due_kind: "none",
    overdue: false,
    recommendation: null,
    uncertainty_flags: [],
    allowed_actions: [],
    proposal_ref: null,
    member_count: 1,
    members: [],
    fingerprint: `fp-${overrides.issue_id}`,
    change_kind: "unchanged",
    changed_since_last_visit: false,
    is_reminder: false,
    blocked: false,
    blocked_by: [],
    state: { acknowledged: false, snoozed_until: null, handled: false, dismissed: false, task_states: {}, issue_state: "open", blocked_now: null },
    ...overrides,
  };
}

const QUOTE_ID = "0192a000-0000-7000-8000-000000000038";
const PROPOSAL_ID = "0192a000-0000-7000-8000-0000000000a5";
const TASK_ID = "0192a000-0000-7000-8000-0000000000f1";

/** Meera's D0 briefing as the server sends it (two needs-you-now items and a decision she requested). */
export function meeraBriefingWire(): WireBriefingView {
  const items: WireItem[] = [
    wireItem({
      issue_id: "w1",
      section: "needs_you_now",
      ordinal: 1,
      band: "P1",
      kind: "quote_expiry",
      family: "sales.quote_expiry",
      title: "Berg & Co AB quote expires today",
      summary: "LK-QT-2026-0006 · EUR 5,700.00",
      due_at: "2026-10-12T18:29:59Z",
      due_label: "Due today, 11:59 pm",
      due_kind: "hard",
      reasons: ["Expires today"],
      source_refs: [{ type: "sales.quote", id: QUOTE_ID, version: 3, label: "LK-QT-2026-0006 · Berg & Co AB", path: `/sales/quotes/${QUOTE_ID}` }],
      recommendation: {
        id: null,
        action_code: "EXTEND_OR_CLOSE",
        label: "Confirm the order or let it lapse today.",
        reason_code: "EXPIRES_TODAY",
        reason: "The quote expires at the end of today.",
        effect_code: "KEEPS_OFFER",
        effect: "Keeps the offer open.",
        alternatives: ["snooze", "dismiss"],
      },
      uncertainty_flags: ["DEMO_DATA"],
      allowed_actions: [
        { action: "open", via: "briefings", path: `/sales/quotes/${QUOTE_ID}`, requires_reason: false, max_until: null, proposal_id: null, proposal_version: null },
        { action: "mark_handled", via: "briefings", path: null, requires_reason: false, max_until: null, proposal_id: null, proposal_version: null },
        { action: "dismiss", via: "briefings", path: null, requires_reason: true, max_until: null, proposal_id: null, proposal_version: null },
        { action: "assign", via: "briefings", path: `/inbox/${TASK_ID}`, requires_reason: false, max_until: null, proposal_id: null, proposal_version: null },
        { action: "snooze", via: "briefings", path: null, requires_reason: false, max_until: "2026-10-12T12:00:00Z", proposal_id: null, proposal_version: null },
        { action: "explain", via: "briefings", path: null, requires_reason: false, max_until: null, proposal_id: null, proposal_version: null },
      ],
    }),
    wireItem({
      issue_id: "w2",
      section: "needs_you_now",
      ordinal: 2,
      kind: "approval_decision",
      family: "common.approvals",
      title: "Decide on LK-QT-2026-0005",
      proposal_ref: { id: PROPOSAL_ID, version: 1 },
      allowed_actions: [
        { action: "open", via: "briefings", path: `/approvals/${PROPOSAL_ID}`, requires_reason: false, max_until: null, proposal_id: null, proposal_version: null },
        { action: "review", via: "briefings", path: `/approvals/${PROPOSAL_ID}`, requires_reason: false, max_until: null, proposal_id: PROPOSAL_ID, proposal_version: 1 },
        { action: "approve", via: "approvals", path: null, requires_reason: false, max_until: null, proposal_id: PROPOSAL_ID, proposal_version: 1 },
        { action: "reject", via: "approvals", path: null, requires_reason: true, max_until: null, proposal_id: PROPOSAL_ID, proposal_version: 1 },
        { action: "explain", via: "briefings", path: null, requires_reason: false, max_until: null, proposal_id: null, proposal_version: null },
      ],
    }),
    wireItem({ issue_id: "w3", section: "plan_for_today", ordinal: 3, title: "Reply to Nordhaus Interiors GmbH" }),
  ];
  return {
    briefing_id: "0192a000-0000-7000-8000-0000000000b9",
    work_date: "2026-10-12",
    day_type: "working",
    time_zone: "Asia/Kolkata",
    status: "ready",
    fallback: false,
    ai_status: "not_used",
    version: 2,
    latest_version: 3,
    generated_at: "2026-10-12T03:25:00Z",
    data_as_of: "2026-10-12T03:25:00Z",
    trigger: "first_open",
    first_opened_at: "2026-10-12T03:25:00Z",
    overview: {
      greeting: "Good morning, Meera.",
      sentence: "Two customer replies need attention and one quote expires today.",
      text_source: "template",
      standard_sentence: "Two customer replies need attention and one quote expires today.",
      template_code: "S1_SALES",
      facts: { customer_replies: 2, quotes_expiring_today: 1 },
    },
    sections: [
      { code: "needs_you_now", title: "Needs you now", total: 2, issue_ids: ["w1", "w2"] },
      { code: "plan_for_today", title: "Plan for today", total: 1, issue_ids: ["w3"] },
    ],
    items,
    initial_view: ["w1", "w2", "w3"],
    snoozed: [],
    updates_available: 1,
    up_to_date: false,
    last_ack: {
      briefing_id: "0192a000-0000-7000-8000-0000000000b8",
      version: 4,
      method: "explicit",
      channel: "web",
      acknowledged_at: "2026-10-10T12:35:00Z",
      accepted: true,
    },
    pin: null,
    fallback_detail: null,
  };
}
