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
  },
  parties: {
    all: () => ["parties"] as const,
    search: (q: string) => ["parties", "search", compact({ q: q.trim() })] as const,
    // catalogue lane (Slice 2): party list/detail and customer types
    list: (params: Record<string, string | number | boolean | null | undefined>) => ["parties", "list", compact(params)] as const,
    party: (partyId: string) => ["parties", "party", { party_id: partyId }] as const,
    customerTypes: () => ["parties", "customer-types"] as const,
  },
  catalogue: {
    all: () => ["catalogue"] as const,
    productSearch: (q: string) => ["catalogue", "product-search", compact({ q: q.trim() })] as const,
    // catalogue lane (Slice 2): products, taxonomy, media, completeness, lookups
    products: (params: Record<string, string | number | boolean | null | undefined>) => ["catalogue", "products", compact(params)] as const,
    facets: (params: Record<string, string | number | boolean | null | undefined>) => ["catalogue", "facets", compact(params)] as const,
    stats: () => ["catalogue", "stats"] as const,
    product: (productId: string) => ["catalogue", "product", { product_id: productId }] as const,
    media: (productId: string, includeDeleted: boolean) => ["catalogue", "media", { product_id: productId, include_deleted: includeDeleted }] as const,
    history: (productId: string) => ["catalogue", "history", { product_id: productId }] as const,
    categories: (includeInactive: boolean) => ["catalogue", "categories", { include_inactive: includeInactive }] as const,
    completeness: () => ["catalogue", "completeness"] as const,
    lookups: (params: Record<string, string | number | boolean | null | undefined>) => ["catalogue", "lookups", compact(params)] as const,
    lookupTypes: () => ["catalogue", "lookup-types"] as const,
  },
  // catalogue lane (Slice 2): import workbench
  imports: {
    all: () => ["imports"] as const,
    types: () => ["imports", "types"] as const,
    jobs: (params: Record<string, string | number | boolean | null | undefined>) => ["imports", "jobs", compact(params)] as const,
    job: (jobId: string) => ["imports", "job", { job_id: jobId }] as const,
    preview: (jobId: string) => ["imports", "preview", { job_id: jobId }] as const,
    rows: (jobId: string, params: Record<string, string | number | boolean | null | undefined>) => ["imports", "rows", { job_id: jobId, ...compact(params) }] as const,
    issues: (jobId: string, params: Record<string, string | number | boolean | null | undefined>) => ["imports", "issues", { job_id: jobId, ...compact(params) }] as const,
    demoReset: () => ["imports", "demo-reset"] as const,
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
  // catalogue lane (Slice 2)
  "catalogue.changed": [queryKeys.catalogue.all()],
  "imports.changed": [queryKeys.imports.all(), queryKeys.catalogue.all()],
  "parties.changed": [queryKeys.parties.all(), queryKeys.sales.all()],
} as const;

export type InvalidationEvent = keyof typeof invalidationMap;
