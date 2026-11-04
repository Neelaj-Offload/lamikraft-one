/**
 * Reading the reconciliation report (`RunDetail.report`, a JSON object the API types as a free-form record) into
 * the shapes the run screen shows. Unknown or missing parts read as empty; figures stay as the server sent them.
 */

type Json = Record<string, unknown>;

function obj(value: unknown): Json {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Json) : {};
}

function num(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function str(value: unknown): string | null {
  return typeof value === "string" ? value : typeof value === "number" ? String(value) : null;
}

export interface EntityRow {
  entity: string;
  rows: number;
  accepted: number;
  quarantined: number;
  rejected: number;
  repeats: number;
  balanced: boolean;
}

export interface CurrencyTotals {
  currency: string;
  sourceQuotes: number;
  sourceTotal: string | null;
  acceptedTotal: string | null;
  recomputedTotal: string | null;
  difference: string | null;
  discrepant: number;
}

export interface Discrepancy {
  key: string;
  quoteNumber: string | null;
  currency: string;
  legacy: string | null;
  lines: string | null;
  difference: string | null;
}

export interface LinkRow {
  link: string;
  linked: number | null;
  orphans: number | null;
  unresolved: number | null;
}

export interface FileRow {
  file: string;
  entity: string;
  format: string;
  rows: number;
  sha256: string;
}

export interface MediaFacts {
  accessible: number;
  notFetched: number;
  inaccessible: { key: string; location: string; reason: string }[];
}

export interface RunReport {
  reconciled: boolean;
  entities: EntityRow[];
  totals: CurrencyTotals[];
  discrepancies: Discrepancy[];
  links: LinkRow[];
  files: FileRow[];
  ignored: string[];
  authorised: boolean;
  manifest: { authorisedBy: string | null; exportedAt: string | null };
  media: MediaFacts | null;
  challans: { documents: number; stockMovements: number } | null;
  users: { invitations: number; historical: number; existing: number; credentialsDropped: number } | null;
  idMaps: { total: number; new: number; changed: number; unchanged: number };
  openingLines: number | null;
}

/** The legacy collections in migration order (the report is a JSON object, whose key order is not kept). */
export const ENTITY_ORDER = [
  "category_taxonomy", "products_master", "pricing", "packaging", "specifications", "media", "lookup_reference", "users",
  "quote_settings", "custom_products", "quotes", "quote_lines", "quote_revisions", "grain_locked_decors",
  "delivery_challans", "delivery_challan_lines", "opening_balances",
];

function byOrder(a: string, b: string): number {
  const ia = ENTITY_ORDER.indexOf(a);
  const ib = ENTITY_ORDER.indexOf(b);
  return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib) || a.localeCompare(b);
}

export function readReport(raw: unknown): RunReport {
  const r = obj(raw);
  const entities = Object.entries(obj(r.entities)).sort(([a], [b]) => byOrder(a, b)).map(([entity, value]) => {
    const v = obj(value);
    return {
      entity,
      rows: num(v.source_rows),
      accepted: num(v.accepted),
      quarantined: num(v.quarantined),
      rejected: num(v.rejected),
      repeats: num(v.duplicate_identical),
      balanced: v.balanced === true,
    };
  });
  const quotes = obj(r.quotes);
  const totals = Object.entries(obj(quotes.totals_by_currency)).map(([currency, value]) => {
    const v = obj(value);
    return {
      currency,
      sourceQuotes: num(v.source_quotes),
      sourceTotal: str(v.source_total),
      acceptedTotal: str(v.accepted_total),
      recomputedTotal: str(v.recomputed_total),
      difference: str(v.discrepancy_total),
      discrepant: num(v.discrepant_quotes),
    };
  });
  const discrepancies = (Array.isArray(quotes.discrepancies) ? quotes.discrepancies : []).map((value) => {
    const v = obj(value);
    return {
      key: str(v.source_key) ?? "",
      quoteNumber: str(v.quote_number),
      currency: str(v.currency) ?? "",
      legacy: str(v.legacy_total),
      lines: str(v.recomputed_total),
      difference: str(v.difference),
    };
  });
  const links = Object.entries(obj(r.links)).map(([link, value]) => {
    const v = obj(value);
    const opt = (k: string) => (typeof v[k] === "number" ? (v[k] as number) : null);
    return { link, linked: opt("linked"), orphans: opt("orphans") ?? opt("unknown"), unresolved: opt("unresolved") };
  });
  const source = obj(r.source);
  const files = (Array.isArray(source.files) ? source.files : [])
    .map((value) => {
      const v = obj(value);
      return { file: str(v.file) ?? "", entity: str(v.entity) ?? "", format: str(v.format) ?? "", rows: num(v.rows), sha256: str(v.sha256) ?? "" };
    })
    .sort((a, b) => byOrder(a.entity, b.entity));
  const manifest = obj(source.export_manifest);
  const media = r.media ? obj(r.media) : null;
  const challans = r.challans ? obj(r.challans) : null;
  const users = r.users ? obj(r.users) : null;
  const ids = obj(r.id_maps);
  const opening = r.opening_balances ? obj(r.opening_balances) : null;
  return {
    reconciled: r.reconciled === true,
    entities,
    totals,
    discrepancies,
    links,
    files,
    ignored: (Array.isArray(source.ignored_files) ? source.ignored_files : []).filter((x): x is string => typeof x === "string"),
    authorised: source.authorised === true,
    manifest: { authorisedBy: str(manifest.authorised_by), exportedAt: str(manifest.exported_at) },
    media: media
      ? {
          accessible: num(media.accessible),
          notFetched: num(media.not_fetched),
          inaccessible: (Array.isArray(media.inaccessible) ? media.inaccessible : []).map((value) => {
            const v = obj(value);
            return { key: str(v.source_key) ?? "", location: str(v.location) ?? "", reason: str(v.reason) ?? "" };
          }),
        }
      : null,
    challans: challans ? { documents: num(challans.documents), stockMovements: num(challans.stock_movements) } : null,
    users: users
      ? { invitations: num(users.invitation), historical: num(users.historical), existing: num(users.existing_member), credentialsDropped: num(users.credentials_dropped) }
      : null,
    idMaps: { total: num(ids.total), new: num(ids.new), changed: num(ids.changed), unchanged: num(ids.unchanged) },
    openingLines: opening ? num(opening.lines) : null,
  };
}
