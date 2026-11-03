/**
 * Query-key convention.
 *
 * Every key starts with the backend module that owns the data, then the resource, then an
 * optional parameter object: `[module, resource, params?]`. Invalidating a prefix such as
 * `["tasks"]` or `["tasks", "inbox"]` therefore refreshes exactly that module's or resource's
 * queries. Parameter objects hold only defined, serialisable values so equal filters produce
 * equal keys. Keys are built only through the factories below, never written inline.
 */

type Params = Record<string, string | number | boolean | null>;

function compact(params: Record<string, string | number | boolean | null | undefined>): Params {
  const out: Params = {};
  for (const key of Object.keys(params).sort()) {
    const value = params[key];
    if (value !== undefined && value !== "") out[key] = value;
  }
  return out;
}

export const queryKeys = {
  session: {
    all: () => ["session"] as const,
    bootstrap: () => ["session", "bootstrap"] as const,
  },
  ui: {
    all: () => ["ui"] as const,
    poll: () => ["ui", "poll"] as const,
  },
  briefings: {
    all: () => ["briefings"] as const,
    today: () => ["briefings", "today"] as const,
    explain: (issueId: string) => ["briefings", "explain", { issue_id: issueId }] as const,
  },
  tasks: {
    all: () => ["tasks"] as const,
    inbox: (params: { tab: string; cursor?: string | null }) =>
      ["tasks", "inbox", compact({ tab: params.tab, cursor: params.cursor ?? null })] as const,
    counts: () => ["tasks", "counts"] as const,
    task: (taskId: string) => ["tasks", "task", { task_id: taskId }] as const,
  },
  approvals: {
    all: () => ["approvals"] as const,
    proposal: (proposalId: string) => ["approvals", "proposal", { proposal_id: proposalId }] as const,
  },
  sales: {
    all: () => ["sales"] as const,
    quotes: (params: { q?: string | null; status?: string | null; scope?: string | null; offset?: number | null }) =>
      ["sales", "quotes", compact({ q: params.q?.trim() ?? null, status: params.status ?? null, scope: params.scope ?? null, offset: params.offset ?? null })] as const,
    quote: (quoteId: string) => ["sales", "quote", { quote_id: quoteId }] as const,
    quoteHistory: (quoteId: string) => ["sales", "quote-history", { quote_id: quoteId }] as const,
    quoteRevisions: (quoteId: string) => ["sales", "quote-revisions", { quote_id: quoteId }] as const,
    quotePreview: (quoteId: string, signature: string) => ["sales", "quote-preview", { quote_id: quoteId, signature }] as const,
    enquiries: (params: { q?: string | null; status?: string | null; offset?: number | null }) =>
      ["sales", "enquiries", compact({ q: params.q?.trim() ?? null, status: params.status ?? null, offset: params.offset ?? null })] as const,
    enquiry: (enquiryId: string) => ["sales", "enquiry", { enquiry_id: enquiryId }] as const,
    messages: (params: { status?: string | null; offset?: number | null }) =>
      ["sales", "customer-messages", compact({ status: params.status ?? null, offset: params.offset ?? null })] as const,
    // commercial-2 lane (Slice 2): revisions compare, currency preview, settings, custom products, samples
    quoteCompare: (quoteId: string, from: number, to: number | null) =>
      ["sales", "quote-compare", compact({ quote_id: quoteId, from, to })] as const,
    currencyPreview: (quoteId: string, currency: string) => ["sales", "currency-preview", { quote_id: quoteId, currency }] as const,
    quoteSettings: () => ["sales", "quote-settings"] as const,
    customProducts: (params: { q?: string | null; status?: string | null; scope?: string | null; offset?: number | null }) =>
      ["sales", "custom-products", compact({ q: params.q?.trim() ?? null, status: params.status ?? null, scope: params.scope ?? null, offset: params.offset ?? null })] as const,
    customProduct: (customProductId: string) => ["sales", "custom-product", { custom_product_id: customProductId }] as const,
    customProductHistory: (customProductId: string) => ["sales", "custom-product-history", { custom_product_id: customProductId }] as const,
    customProductCosting: (customProductId: string) => ["sales", "custom-product-costing", { custom_product_id: customProductId }] as const,
    samples: (params: { q?: string | null; status?: string | null; offset?: number | null }) =>
      ["sales", "samples", compact({ q: params.q?.trim() ?? null, status: params.status ?? null, offset: params.offset ?? null })] as const,
    sample: (sampleId: string) => ["sales", "sample", { sample_id: sampleId }] as const,
    // configurator follow-up (Slice 2): one page of the quote configurator, keyed by its whole request body
    configurator: (body: object) => ["sales", "configurator", body] as const,
  },
  // commercial-2 lane (Slice 2): price lists, item history, FX rates and policy
  pricing: {
    all: () => ["pricing"] as const,
    priceLists: (params: { q?: string | null; status?: string | null; offset?: number | null }) =>
      ["pricing", "price-lists", compact({ q: params.q?.trim() ?? null, status: params.status ?? null, offset: params.offset ?? null })] as const,
    priceList: (priceListId: string) => ["pricing", "price-list", { price_list_id: priceListId }] as const,
    priceListItems: (priceListId: string, params: { q?: string | null; offset?: number | null; history?: boolean | null }) =>
      ["pricing", "price-list-items", compact({ price_list_id: priceListId, q: params.q?.trim() ?? null, offset: params.offset ?? null, history: params.history ?? null })] as const,
    itemHistory: (itemId: string) => ["pricing", "item-history", { item_id: itemId }] as const,
    fxRates: (params: { status?: string | null; offset?: number | null }) =>
      ["pricing", "fx-rates", compact({ status: params.status ?? null, offset: params.offset ?? null })] as const,
    fxPolicy: () => ["pricing", "fx-policy"] as const,
  },
  parties: {
    all: () => ["parties"] as const,
    search: (q: string) => ["parties", "search", compact({ q: q.trim() })] as const,
  },
  catalogue: {
    all: () => ["catalogue"] as const,
    productSearch: (q: string) => ["catalogue", "product-search", compact({ q: q.trim() })] as const,
  },
  search: {
    all: () => ["search"] as const,
    query: (q: string) => ["search", "results", compact({ q: q.trim() })] as const,
  },
  agents: {
    all: () => ["agents"] as const,
    run: (runId: string) => ["agents", "run", { run_id: runId }] as const,
  },
} as const;

/** Prefixes a mutation invalidates; one table so screens never guess (frontend_verification §5). */
export const invalidationMap = {
  "briefings.item_action": [queryKeys.briefings.today(), queryKeys.tasks.all(), queryKeys.ui.poll()],
  "briefings.snooze": [queryKeys.briefings.today(), queryKeys.tasks.all(), queryKeys.ui.poll()],
  "identity.preferences": [queryKeys.session.bootstrap()],
  "tasks.task_command": [queryKeys.tasks.all(), queryKeys.briefings.today(), queryKeys.ui.poll()],
  "approvals.decide": [queryKeys.approvals.all(), queryKeys.tasks.all(), queryKeys.sales.all(), queryKeys.briefings.today(), queryKeys.ui.poll()],
  "sales.quote_changed": [queryKeys.sales.all(), queryKeys.briefings.today()],
  "sales.quote_transition": [queryKeys.sales.all(), queryKeys.approvals.all(), queryKeys.tasks.all(), queryKeys.briefings.today(), queryKeys.ui.poll()],
  "sales.message_replied": [queryKeys.sales.all(), queryKeys.tasks.all(), queryKeys.briefings.today(), queryKeys.ui.poll()],
} as const;

export type InvalidationEvent = keyof typeof invalidationMap;
