/**
 * The assistant (agents module) as the web uses it.
 *
 * INTERIM(api-generate): the agents module (backend/app/modules/agents, lane `agents`) is being
 * built in the same wave and has no router or schemas yet. The wire shapes below follow the
 * lane brief (scratchpad/s1w1/agents-brief.md §2-§3) and docs/architecture/ai-routing.md §4.1
 * and §5; `parse.ts` is the only reader of them, so after `npm run api:generate` only that
 * adapter changes. Endpoints (operationIds):
 * - `POST /api/v1/agents/conversations` (agents_create_conversation) → `{id}`
 * - `POST /api/v1/agents/conversations/{id}/turns` (agents_create_turn) → 202 `{run_id}`
 * - `GET  /api/v1/agents/runs/{run_id}?after_seq=N` (agents_get_run) → run status + steps
 * - `POST /api/v1/agents/runs/{run_id}/cancel` (agents_cancel_run)
 */

// ---------------------------------------------------------------------------------------------
// Screen context (ai-routing.md §4.1): sent with every turn

export interface ScreenRecordRef {
  type: string;
  id: string;
  version: number | null;
}

export interface ScreenVisibleItem extends ScreenRecordRef {
  /** Stable within the list the person sees: "i2" is the second row of the primary list. */
  ref: string;
  list_key: string;
  ordinal: number;
}

export interface ScreenDraft {
  form_key: string;
  record_ref: string | null;
  dirty_fields: string[];
  /** The person's own unsaved input; restricted fields are never included. */
  values: Record<string, string | number | boolean | null>;
}

export type ScreenFilterValue = string | number | boolean | string[];

export interface ScreenContext {
  schema_version: 1;
  captured_at: string;
  route: { path: string; params: Record<string, string>; area: string };
  focus: ScreenRecordRef | null;
  records: (ScreenRecordRef & { role: "primary" | "related" })[];
  visible_items: ScreenVisibleItem[];
  selection: string[];
  filters: Record<string, ScreenFilterValue>;
  draft: ScreenDraft | null;
  briefing_pin: { pin_id: string; version: number } | null;
  viewport: { width: number; height: number } | null;
}

// ---------------------------------------------------------------------------------------------
// Runs and steps

export type RunStatus = "queued" | "running" | "succeeded" | "failed" | "budget_exceeded" | "cancelled";
export type StepKind = "route" | "tool_call" | "tool_result" | "card" | "text" | "handoff";

export interface RunStep {
  seq: number;
  kind: StepKind | (string & {});
  name: string | null;
  is_error: boolean;
  /** Assistant text (kind `text`), after the server's numeric-claim check. */
  text: string | null;
  card: AssistantCard | null;
}

export interface AgentRun {
  id: string;
  status: RunStatus | (string & {});
  error_code: string | null;
  /** The run read external text (customer messages): proposals need explicit confirmation. */
  tainted: boolean;
  steps: RunStep[];
}

// ---------------------------------------------------------------------------------------------
// Cards (server-built from tool outputs; the client never computes their figures)

export interface CardMoney {
  amount: string;
  currency: string;
}

export interface CardLink {
  label: string;
  href: string;
}

export interface QuoteDraftCardLine {
  line_no: number;
  label: string;
  product_key: string | null;
  quantity: string;
  unit_code: string;
  unit_price: CardMoney | null;
  line_total: CardMoney | null;
}

export interface QuoteDraftCard {
  kind: "quote_draft";
  demo: boolean;
  quote_id: string;
  quote_number: string;
  status: string;
  party_name: string | null;
  lines: QuoteDraftCardLine[];
  subtotal: CardMoney | null;
  surcharge: CardMoney | null;
  grand_total: CardMoney | null;
  /** The engine's recommended quantity note ("216 pcs reach the order minimum"), when sent. */
  notes: string[];
  open_href: string;
  review_href: string;
}

export interface ClarificationOption {
  id: string;
  label: string;
  detail: string | null;
  /** Posted back as the next turn's `selected_option`; opaque to the client. */
  value: unknown;
}

export interface ClarificationCard {
  kind: "clarification";
  demo: boolean;
  question: string;
  options: ClarificationOption[];
}

export interface ErrorCard {
  kind: "error";
  demo: boolean;
  code: string;
  message: string;
  recoverable: CardLink | null;
}

export interface RecordLinkCard {
  kind: "record_link";
  demo: boolean;
  label: string;
  detail: string | null;
  href: string;
}

export interface ReceiptCard {
  kind: "receipt";
  demo: boolean;
  title: string;
  detail: string | null;
  link: CardLink | null;
}

export type AssistantCard = QuoteDraftCard | ClarificationCard | ErrorCard | RecordLinkCard | ReceiptCard;
