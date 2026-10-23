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
} as const;

export type InvalidationEvent = keyof typeof invalidationMap;
