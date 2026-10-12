# Lamikraft One

Your working day, understood. Your business, in conversation.

Product proposal for Crown / Lamikraft · 12 October 2026

## The idea

Give every employee a personal AI workspace that understands their responsibilities, prepares their day, and helps finish their work. They can speak, type, or send a WhatsApp message. Their agent brings together customer, product, stock, production and financial information, proposes the next action, and executes within their authority.

The home screen is a living daily briefing. Conversation opens real working surfaces: an editable quote, a stock movement, a cutting plan, an approval comparison, or a customer timeline. People can inspect and adjust the work directly. Voice remains available throughout, but a noisy factory, a complex table, or a weak connection never forces someone to use it.

“Lamikraft One” is a proposed working name. Start with Crown Decor Pvt. Ltd. as one company and Crown / Lamikraft as brands; confirm the actual legal structure before production setup. Nothing in the supplied specification establishes that these are separate legal companies.

## The daily briefing is the product's front door

On the first opening of each local working day, generate a briefing for that employee. On later visits, show what has changed since they last checked. An optional spoken version takes about a minute; the visual version stays scannable.

The briefing answers six questions:

1. **What needs me today?** Prioritised commitments, due work, overdue items and approvals, with owners and due times.
2. **What changed?** New orders, customer replies, supplier updates, production progress and decisions since the employee's last acknowledged briefing.
3. **What should I do?** A recommended action for each issue, a short reason, the expected effect, and alternatives when a tradeoff matters.
4. **What is at risk?** Shortages, delivery conflicts, missing information, expiring quotes, returns and financial exceptions that the person is allowed to see.
5. **What is already handled?** Work completed by people and authorised automations, linked to the resulting records.
6. **What comes next?** Tomorrow's dependencies and upcoming commitments worth preparing for today.

Each item is an actionable card with a source record, timestamp, owner, priority reason and one primary action. Actions include Review, Prepare, Assign, Approve, Ask for information, Snooze and Mark handled. An item only becomes “handled” when the underlying task is complete or an authorised person dismisses it with a reason. Dismissing a warning does not resolve the business problem.

Use three priority groups: **Needs you now**, **Plan for today**, and **Keep in view**. Rank using due dates, blockers, business impact and role responsibility. Do not let the language model invent urgency or calculate money. Cap the opening screen at a handful of important items; the complete queue remains accessible.

### Example: sales employee

> Good morning, Meera. Two customer replies need attention, one quote expires today, and yesterday's sample has been delivered.
>
> **Nordhaus quote:** Their approved oak tray configuration is available at the current export price. Prepare a repeat quote using their last quantities, then review the current terms.
>
> **Maison sample:** Delivery is recorded. Suggested next step: prepare a short follow-up asking for finish approval. Review the message before sending.
>
> **Berg & Co:** Their quote expires today. The price list changed yesterday. Compare the impact before extending validity.

Illustrative names and events only; these are not claims about live business data.

### Example: operations employee

> Two dispatches are due today. One production order is missing material, and a returnable sample is due tomorrow. Review the shortage first because it blocks the afternoon work order. A matching offcut may cover part of the requirement; dimensions and grain direction still need verification.

### Example: management

> Three approvals need your decision. One order may miss its promised date. Two teams have competing claims on the same stock. Compare the proposed allocation and its delivery impact before releasing either reservation.

### Make the briefing trustworthy

Every fact links to a record and its last update. Distinguish facts, estimates and recommendations. Say “No warehouse update since yesterday” instead of pretending stock is current. A missing integration appears as “Not connected,” not a healthy metric.

Use a saved per-user briefing and event-driven updates. Refresh impacted items after relevant changes rather than rewriting the entire page continually. Keep a stable reading order while someone is using it and offer a small “3 updates” control. Remember acknowledged updates, snoozes and resolved items across web and WhatsApp. Run deduplication so one late supplier delivery does not produce ten almost-identical alerts.

Respect working days, time zones, shift schedules, leave, quiet hours and temporary delegation. Initial assumptions: Asia/Kolkata, configurable workweek and shift times. Deliver WhatsApp briefings only when the employee opts in and messaging rules permit. Personal preferences can change language, detail and notification frequency; they cannot weaken company policy or access controls.

## A personal agent, supported by specialist skills

Employees should not have to choose between ten bots. Each has one familiar assistant with access to the specialist capabilities needed for their job.

| Employee / specialist | What their workspace prepares |
|---|---|
| Sales | Enquiries, repeat quotes, customer context, follow-ups, sample status and commercial exceptions |
| Operations / warehouse | Reservations, material receipts, pick lists, challans, dispatches, returns and stock discrepancies |
| Production | Material requirements, cutting plans, grain constraints, work orders, offcuts and yield exceptions |
| Procurement | Shortages, supplier comparisons, purchase drafts, expected receipts and late supplies |
| Finance | Invoice drafts, recorded receipts, matching exceptions, ageing and accounting handoff |
| Management | Cross-team blockers, margin exceptions, approval decisions, capacity and cash visibility |
| Catalogue / admin | Missing product data, duplicate candidates, imports, price-list changes and access management |

Agent memory has separate scopes: personal preferences, authorised team context and company policy. Customer-specific pricing and negotiations stay attached to that customer. Sales agents cannot gain access to hidden costing through management summaries or another agent.

## The interaction model

**Say the outcome → inspect the work → act.**

For example: “Prepare a quote for Nordhaus's usual oak trays, and tell me whether we can deliver by the end of the month.”

The assistant resolves the customer and previous configuration, checks the current price list and packaging, reads available stock and capacity, and opens a quote alongside a delivery assessment. If two customers match, it asks a short clarifying question. If capacity is unknown, the date remains an estimate. It does not treat a successful search as a delivery promise.

“Change that to 240, keep the walnut items out, and send it to review” updates the visible draft and routes it to the right approver. The audit record connects the original request, changes, approval and resulting document.

Routine reads and permitted reversible drafts happen immediately. Commercial commitments, external messages, stock posting and financial posting follow configured authority and approval rules. Higher-risk changes can require a second person or re-authentication. The AI never approves its own request. Approved routine automations should run without repeatedly asking the same question.

## Better ideas beyond a conversational ERP

| Capability | Why it matters | Delivery |
|---|---|---|
| **Daily decision briefing** | Turns every employee's data into a manageable plan with suggested actions | First release |
| **Change radar** | Shows what changed since the last visit and which existing plans are affected | First release |
| **Commitment check** | Compares requested delivery dates with stock, material lead times and capacity before a promise is made | With inventory and production |
| **What-if workspace** | Shows the effects of an order, price change or production priority without posting transactions | After operational core |
| **Offcut library** | Saves reusable remnants by dimensions, decor, thickness, grain and location; proposes them in future plans | With production |
| **Sample-to-order memory** | Connects samples, feedback, custom development, approvals and eventual commercial orders | With sales and returns |
| **Return radar** | Reconciles outward returnable challans with partial receipts and outstanding quantities | With inventory |
| **Photo and voice capture** | Extracts a draft enquiry, receipt or damage report from a message; asks people to confirm uncertain fields | After text workflows |
| **Customer-specific product passports** | Keeps approved finish, packaging, specifications and sample history together | With custom products |
| **Commercial coach** | Suggests carton-aligned quantities, alternative materials or consolidation to improve the proposed order | With verified pricing and stock |
| **Capacity-aware handoffs** | Assigns work to available authorised people, with explicit delegation and an owner | After basic tasks |
| **Business replay** | Explains who changed a price, approved a quote, reserved stock or recorded a return | First release foundation |

Avoid a predictive sales score until enough reliable historical data exists. Begin with rules that people can understand and inspect.

## Preserve every useful existing capability

The supplied current-state document is evidence of existing functionality, not an instruction to reuse the old architecture or bugs. The build prompt requires a detailed coverage matrix against it.

| Existing capability | New home and improvement |
|---|---|
| Product master; immutable product key; variants; taxonomy; filters; specs; packaging; images/documents | Product workspace with full field preservation, canonical units, real pagination, a pricing editor and authorised field visibility |
| Seven CSV/XLSX importers; preview; validation; aliases; row errors | Import workbench with staging, orphan quarantine, repeat-safe imports, downloadable error reports and controlled demo reset |
| Quotes; three line types; configurator; defaults; overrides; revisions; duplication; statuses; ownership | Sales workspace with snapshots, validated transitions, revision comparison, approval routing and one consistent totals engine |
| EUR 5,000 minimum; EUR 400 optional surcharge; carton-rounded recommended MOQ | Versioned commercial rules retaining these defaults and advisory MOQ, with explicit currency handling |
| Custom-product library and lifecycle | Customer-linked product development with duplicate/export, protected costing and an implemented promotion-to-catalogue flow |
| Sheet nesting; decor/thickness grouping; grain locks; oversize; layouts; efficiency | Saved production plans using a validated packer, configurable machine constraints and traceable remnants |
| Challans; six types; destinations; returnable flags; PDFs; filters; summaries; duplication | Linked material documents with authorised stock effects, return reconciliation and printable signatures |
| Four roles; 14 permissions; per-user overrides; profile/password management | Server-enforced module/action/scope permissions, field redaction, reliable sessions, configurable role templates and a role simulator |
| Global search; recent searches; activity; completeness; autosaved notes; CSV/PDF/print; dark mode | Shared contextual search, truthful completeness checks, linked activity, accessible themes and consistent document outputs |

Preserve quote and challan numbering formats through safe atomic counters. Old activity and revisions remain discoverable after migration. Historical challans must not silently manufacture opening stock.

## Make it a real ERP in connected releases

**Release 1 — daily workspace and complete old-system parity.** Build the personalised briefing, tasks, permissions, products/imports, customers, quotations, custom products, nesting and challans. Provide text commands, then voice and WhatsApp adapters, with an explicit demo mode while credentials are absent. Retain every required feature before replacing the old app.

**Release 2 — operations.** Connect accepted quotes to sales orders, reservations, stock ledgers, purchasing, receipts, BOMs, work orders, QC, picking, dispatch and return reconciliation. Add packing lists and carton/weight/CBM calculations. The optimiser produces saved production plans.

**Release 3 — finance and planning.** Add operational invoices, credit notes, receipts, payment matching and an accounting connector. Select the statutory accounting system with the business's accountant; the default proposal is an adapter to the chosen accounting platform, not an unverified new statutory ledger. Add verified tax/e-invoice/e-way-bill integrations only after scope and provider decisions. Add simulation, capacity scheduling and forecasting as data quality permits.

Employee identities and responsibilities are necessary from the start. Payroll, attendance, full HR and a native general ledger are separately scoped expansions; the old system has none of them. Do not display them as completed modules.

## WhatsApp is another entrance to the same business

An employee can ask “What do I need to handle today?”, send a voice note, request a quote, upload a purchase order, or check a dispatch. The same identity, permissions, records, tasks and approvals apply in the web app and WhatsApp. Link an employee's account through authenticated enrolment; do not grant access because a message claims to be from management. Keep customer-facing conversations separate from employee conversations.

For consequential or sensitive actions, WhatsApp can open the exact review screen through a secure link. Routine permitted drafts and status checks should work in the conversation itself. A notification being sent does not mean it was read, approved or completed.

Meta requires opt-in for proactive contact, approved templates outside the 24-hour service window, and a clear escalation path for automated replies. Build those constraints into the channel adapter. [WhatsApp Business Messaging Policy](https://whatsappbusiness.com/policy/)

## Visual direction

Think of a calm architectural materials studio: warm mineral white, forest green, dark ink and small sand accents. Use real material swatches, precise tables and clear document previews. A large daily greeting and short briefing set the tone; the command bar sits directly below. An expandable specialist rail shows prepared work and blockers. Dense tasks open in a larger canvas instead of being squeezed into chat bubbles.

Palette: canvas `#F6F5F0`, surfaces `#FFFFFF`, ink `#202723`, primary forest `#214C3C`, sand `#C8A064`, borders `#E0E4DC`. Use accessible darker text for amber warnings. Body typography: a clean sans such as Manrope; numeric tables use tabular figures. Keep decorative type out of operational tables.

The generated inspiration image is an illustrative direction with fictional data, not a finished application. It shows the management morning workspace and a companion WhatsApp quote interaction. The build must add full briefing detail, all user roles and responsive states.

## How to use the build prompt

Open a coding environment with Claude Opus 5.5 selected. Add `OPUS_5_5_BUILD_PROMPT.md`, `CURRENT_STATE_SPEC.md`, this concept and the inspiration image to the project. Paste the build prompt, or ask the agent to read it and execute it. The prompt contains a complete product contract, implementation order and acceptance scenarios. Model settings belong in the coding environment; writing a model name in a prompt does not select it.

Start at medium effort, then raise it selectively for difficult architecture or correctness work. The prompt explicitly requires visible progress, concrete design choices and durable completion tracking, reflecting Anthropic's Opus 5.5 guidance. [Official Opus 5.5 prompting guide](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5-5)

A large ERP needs successive implemented and verified slices. This package provides the direction and build contract; it does not establish that generated code is ready for live inventory, financial posting or external messaging without validation.
