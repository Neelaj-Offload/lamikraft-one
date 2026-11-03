/**
 * Types for `GET /api/v1/search?q=&types=&limit=&offset=` and `GET|POST|DELETE /api/v1/search/recent`
 * (backend/app/platform/search/schemas.py). INTERIM(api-generate): replace with the generated schema types.
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
  /** More hits after this page (the "See all results" page pages one group). */
  hasMore?: boolean;
  offset?: number;
}

export interface SearchResponse {
  q: string;
  groups: SearchGroup[];
  /** Groups whose provider failed this time (shown as unavailable, never as "no results"). */
  unavailable?: string[];
}

export interface RecentSearch {
  id: string;
  query: string;
  searched_at: string;
}
