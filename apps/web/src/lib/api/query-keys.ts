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
    statusCounts: () => ["sales", "quote-status-counts"] as const,
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
    products: (params: Record<string, string | number | boolean | null | undefined>) => ["catalogue", "products", compact(params)] as const,
    facets: (params: Record<string, string | number | boolean | null | undefined>) => ["catalogue", "facets", compact(params)] as const,
    stats: () => ["catalogue", "stats"] as const,
    completeness: () => ["catalogue", "completeness"] as const,
    product: (productId: string) => ["catalogue", "product", { product_id: productId }] as const,
    categories: (includeInactive = false) => ["catalogue", "categories", compact({ include_inactive: includeInactive })] as const,
    // catalogue lane (Slice 2): media, history, lookups
    media: (productId: string, includeDeleted: boolean) => ["catalogue", "media", { product_id: productId, include_deleted: includeDeleted }] as const,
    history: (productId: string) => ["catalogue", "history", { product_id: productId }] as const,
    lookups: (params: Record<string, string | number | boolean | null | undefined>) => ["catalogue", "lookups", compact(params)] as const,
    lookupTypes: () => ["catalogue", "lookup-types"] as const,
    references: (kind: string, id: string) => ["catalogue", "references", { kind, id }] as const,
  },
  challans: {
    all: () => ["challans"] as const,
    list: (params: Record<string, string | number | boolean | null | undefined>) => ["challans", "list", compact(params)] as const,
    summary: (params: Record<string, string | number | boolean | null | undefined>) => ["challans", "summary", compact(params)] as const,
    challan: (challanId: string) => ["challans", "challan", { challan_id: challanId }] as const,
    print: (challanId: string) => ["challans", "print", { challan_id: challanId }] as const,
    note: (challanId: string) => ["challans", "note", { challan_id: challanId }] as const,
  },
  pricing: {
    all: () => ["pricing"] as const,
    priceLists: (params: Record<string, string | number | boolean | null | undefined>) => ["pricing", "price-lists", compact(params)] as const,
    priceList: (priceListId: string) => ["pricing", "price-list", { price_list_id: priceListId }] as const,
    priceListItems: (priceListId: string, params: Record<string, string | number | boolean | null | undefined>) =>
      ["pricing", "price-list-items", compact({ price_list_id: priceListId, ...params })] as const,
    productPrices: (productId: string) => ["pricing", "product-prices", { product_id: productId }] as const,
    productCosts: (productId: string) => ["pricing", "product-costs", { product_id: productId }] as const,
    // commercial-2 lane (Slice 2): item history, FX rates and policy
    itemHistory: (itemId: string) => ["pricing", "item-history", { item_id: itemId }] as const,
    fxRates: (params: { status?: string | null; offset?: number | null }) =>
      ["pricing", "fx-rates", compact({ status: params.status ?? null, offset: params.offset ?? null })] as const,
    fxPolicy: () => ["pricing", "fx-policy"] as const,
  },
  org: {
    all: () => ["org"] as const,
    settings: () => ["org", "settings"] as const,
    setting: (key: string) => ["org", "setting", { key }] as const,
    settingRevisions: (key: string) => ["org", "setting-revisions", { key }] as const,
    currencies: () => ["org", "currencies"] as const,
    uoms: () => ["org", "uoms"] as const,
    calendar: () => ["org", "calendar"] as const,
  },
  system: {
    all: () => ["system"] as const,
    integrations: () => ["system", "integrations"] as const,
  },
  audit: {
    all: () => ["audit"] as const,
    entries: (params: Record<string, string | number | boolean | null | undefined>) => ["audit", "entries", compact(params)] as const,
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
    receipt: (receiptId: string) => ["agents", "receipt", { receipt_id: receiptId }] as const,
    trace: (correlationId: string) => ["agents", "trace", { correlation_id: correlationId }] as const,
    aiStatus: () => ["agents", "ai-status"] as const,
    aiUsage: (days: number) => ["agents", "ai-usage", { days }] as const,
  },
  // platform-2 (Slice 2): identity administration, self-service security, collaboration, recent searches
  identity: {
    all: () => ["identity"] as const,
    me: () => ["identity", "me"] as const,
    users: (params: { q?: string | null; status?: string | null; role?: string | null; offset?: number | null }) =>
      ["identity", "users", compact({ q: params.q?.trim() ?? null, status: params.status ?? null, role: params.role ?? null, offset: params.offset ?? null })] as const,
    user: (userId: string) => ["identity", "user", { user_id: userId }] as const,
    roles: () => ["identity", "roles"] as const,
    role: (roleId: string) => ["identity", "role", { role_id: roleId }] as const,
    catalogue: () => ["identity", "permissions"] as const,
    effective: (params: { userId?: string | null; roleId?: string | null }) =>
      ["identity", "effective", compact({ user_id: params.userId ?? null, role_id: params.roleId ?? null })] as const,
    check: (params: { userId: string; key: string; scope: string }) =>
      ["identity", "check", compact({ user_id: params.userId, key: params.key, scope: params.scope })] as const,
    mfa: () => ["identity", "mfa"] as const,
    sessions: () => ["identity", "sessions"] as const,
    delegations: (scope: string) => ["identity", "delegations", { scope }] as const,
    absences: (scope: string) => ["identity", "absences", { scope }] as const,
    accessRequests: (scope: string) => ["identity", "access-requests", { scope }] as const,
  },
  collab: {
    all: () => ["collab"] as const,
    note: (resourceType: string, resourceId: string) => ["collab", "note", { resource_type: resourceType, resource_id: resourceId }] as const,
    attachments: (resourceType: string, resourceId: string) =>
      ["collab", "attachments", { resource_type: resourceType, resource_id: resourceId }] as const,
    activity: (params: { resourceType?: string | null; resourceId?: string | null }) =>
      ["collab", "activity", compact({ resource_type: params.resourceType ?? null, resource_id: params.resourceId ?? null })] as const,
  },
  searchRecent: {
    all: () => ["search", "recent"] as const,
  },
  // cutting (Slice 2 wave 2, lane cutting)
  cutting: {
    all: () => ["cutting"] as const,
    allPlans: () => ["cutting", "plans"] as const,
    plans: (params: { q?: string | null; status?: string | null; scope?: string | null; offset?: number | null }) =>
      ["cutting", "plans", compact({ q: params.q?.trim() ?? null, status: params.status ?? null, scope: params.scope ?? null, offset: params.offset ?? null })] as const,
    allPlanDetails: () => ["cutting", "plan"] as const,
    plan: (planId: string) => ["cutting", "plan", { plan_id: planId }] as const,
    grainLocks: () => ["cutting", "grain-locks"] as const,
    products: (q: string) => ["cutting", "products", compact({ q: q.trim() })] as const,
  },
  // orders and inventory (Slice 4)
  orders: {
    all: () => ["orders"] as const,
    list: (params: Record<string, string | number | boolean | null | undefined>) => ["orders", "list", compact(params)] as const,
    order: (orderId: string) => ["orders", "order", { order_id: orderId }] as const,
    forQuote: (quoteId: string) => ["orders", "for-quote", { quote_id: quoteId }] as const,
  },
  inventory: {
    all: () => ["inventory"] as const,
    warehouses: () => ["inventory", "warehouses"] as const,
    stock: (params: Record<string, string | number | boolean | null | undefined>) => ["inventory", "stock", compact(params)] as const,
    movements: (params: Record<string, string | number | boolean | null | undefined>) => ["inventory", "movements", compact(params)] as const,
    reservations: (params: Record<string, string | number | boolean | null | undefined>) => ["inventory", "reservations", compact(params)] as const,
    shortages: () => ["inventory", "shortages"] as const,
    documents: (kind: string) => ["inventory", "documents", { kind }] as const,
    count: (countId: string) => ["inventory", "count", { count_id: countId }] as const,
    pickList: (pickListId: string) => ["inventory", "pick-list", { pick_list_id: pickListId }] as const,
    document: (kind: string, id: string) => ["inventory", "document", { kind, id }] as const,
  },
  // procurement, quality and logistics (Slice 4)
  procurement: {
    all: () => ["procurement"] as const,
    requisitions: (params: Record<string, string | number | boolean | null | undefined>) => ["procurement", "requisitions", compact(params)] as const,
    requisition: (id: string) => ["procurement", "requisition", { requisition_id: id }] as const,
    orders: (params: Record<string, string | number | boolean | null | undefined>) => ["procurement", "orders", compact(params)] as const,
    order: (id: string) => ["procurement", "order", { po_id: id }] as const,
    bills: (poId: string) => ["procurement", "bills", { po_id: poId }] as const,
    receipts: (params: Record<string, string | number | boolean | null | undefined>) => ["procurement", "receipts", compact(params)] as const,
    receipt: (id: string) => ["procurement", "receipt", { grn_id: id }] as const,
    vendorItems: (vendorId: string, history: boolean) => ["procurement", "vendor-items", { vendor_party_id: vendorId, history }] as const,
  },
  quality: {
    all: () => ["quality"] as const,
    inspections: (params: Record<string, string | number | boolean | null | undefined>) => ["quality", "inspections", compact(params)] as const,
    inspection: (id: string) => ["quality", "inspection", { inspection_id: id }] as const,
  },
  logistics: {
    all: () => ["logistics"] as const,
    packingLists: (params: Record<string, string | number | boolean | null | undefined>) => ["logistics", "packing-lists", compact(params)] as const,
    packingList: (id: string) => ["logistics", "packing-list", { packing_list_id: id }] as const,
    shipments: (params: Record<string, string | number | boolean | null | undefined>) => ["logistics", "shipments", compact(params)] as const,
    shipment: (id: string) => ["logistics", "shipment", { shipment_id: id }] as const,
    containers: () => ["logistics", "containers"] as const,
  },
  channels: {
    all: () => ["channels"] as const,
    account: () => ["channels", "account"] as const,
    identities: (scope: "mine" | "all") => ["channels", "identities", { scope }] as const,
    messages: () => ["channels", "messages"] as const,
    templates: () => ["channels", "templates"] as const,
    demoThread: () => ["channels", "demo-thread"] as const,
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
  "challans.challan_changed": [queryKeys.challans.all(), queryKeys.search.all()],
  "challans.challan_transition": [queryKeys.challans.all(), queryKeys.search.all(), queryKeys.tasks.all(), queryKeys.briefings.today(), queryKeys.ui.poll()],
  "parties.party_changed": [queryKeys.parties.all(), queryKeys.sales.all(), queryKeys.search.all()],
  "org.setting_changed": [queryKeys.org.all(), queryKeys.session.bootstrap(), queryKeys.agents.aiStatus()],
  "agents.receipt_undone": [queryKeys.agents.all(), queryKeys.sales.all(), queryKeys.briefings.today()],
  "agents.ai_verified": [queryKeys.agents.aiStatus(), queryKeys.system.integrations()],
  "identity.password_changed": [queryKeys.identity.me()],
  // platform-2: access changes alter navigation and capabilities, so the bootstrap is re-read too
  "identity.access_changed": [queryKeys.identity.all(), queryKeys.session.bootstrap()],
  "collab.changed": [queryKeys.collab.all()],
  // catalogue lane (Slice 2)
  "catalogue.changed": [queryKeys.catalogue.all()],
  "imports.changed": [queryKeys.imports.all(), queryKeys.catalogue.all()],
  "parties.changed": [queryKeys.parties.all(), queryKeys.sales.all()],
  "channels.changed": [queryKeys.channels.all()],
  // orders and inventory (Slice 4): a stock command can change orders, challans, stock, shortages and briefings
  "inventory.changed": [
    queryKeys.inventory.all(),
    queryKeys.orders.all(),
    queryKeys.challans.all(),
    queryKeys.procurement.all(),
    queryKeys.quality.all(),
    queryKeys.logistics.all(),
    queryKeys.tasks.all(),
    queryKeys.briefings.today(),
  ],
} as const;

export type InvalidationEvent = keyof typeof invalidationMap;
