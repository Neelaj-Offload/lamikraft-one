/**
 * Test-only BriefingView payloads shaped like the canonical fixture world at D0 08:55 IST
 * (docs/architecture/fixtures.md §9.1, Meera: needs 2, plan 1, recommendations 1, changes 1,
 * coming next 1; initial view 5, full list 6). Never imported by product code.
 */

import type { BriefingItem, BriefingView } from "@/features/briefing/types";

export function testItem(overrides: Partial<BriefingItem> & Pick<BriefingItem, "id" | "section">): BriefingItem {
  return {
    issue_id: `issue-${overrides.id}`,
    display_ordinal: 1,
    priority_band: "P2",
    family: "sales.customer_replies",
    title: `Item ${overrides.id}`,
    summary_text: null,
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
        { action: "open", label: "Open quote", primary: true, href: "/sales/quotes/q38", requires_reason: false },
        { action: "snooze", label: null, primary: false, href: null, requires_reason: false },
        { action: "mark_handled", label: null, primary: false, href: null, requires_reason: false },
        { action: "assign", label: null, primary: false, href: null, requires_reason: false },
        { action: "explain", label: null, primary: false, href: null, requires_reason: false },
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
    ai_status: "unavailable",
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
    last_ack: { version: 1, acknowledged_at: "2026-10-10T12:35:00Z", method: "viewed" },
    partial_families: [],
    fallback: null,
  };
}
