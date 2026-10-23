/**
 * INTERIM hand-written types for `GET /api/v1/search?q=` (platform search; contract in
 * backend/app/platform/search/defs.py: SearchHit and SearchProvider, grouped per provider).
 * The search endpoint is built by another lane; the web derives this shape from the provider
 * dataclasses. INTERIM(api-generate): replace with the generated schema types when it merges.
 */

export interface SearchHit {
  /** e.g. "catalogue.product", "sales.quote". */
  resource_type: string;
  resource_id: string;
  /** "LK-OT-0450 · Oak serving tray 450" */
  title: string;
  subtitle: string | null;
  /** Canonical web route, e.g. "/products/<id>". */
  path: string;
}

export interface SearchGroup {
  /** Display group: "Products", "Parties", "Quotes", ... */
  group: string;
  resource_type: string;
  /** Visible matches in this group (permission-filtered on the server). */
  total: number;
  items: SearchHit[];
}

export interface SearchResponse {
  q: string;
  groups: SearchGroup[];
}
