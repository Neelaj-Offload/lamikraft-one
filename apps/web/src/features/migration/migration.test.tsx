import { describe, expect, it, vi } from "vitest";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { getRoute } from "@/lib/routes";
import { controlsWithoutVisibleFocus, nestedInteractive, renderWithQueries, seedQueryError, textOf } from "@/lib/test-support/render";
import { testBootstrap } from "@/lib/test-support/session";
import { issueFiltersFrom, issueFiltersHref, parseRunId, type BackupFacts, type Candidate, type Issue, type RunDetail, type RunSummary } from "./api";
import { BackupsPage } from "./backups-page";
import { MigrationPage } from "./migration-page";
import { readReport } from "./report";
import { RunDetailView } from "./run-detail";
import { bytesText, entityLabel, shortSha } from "./shared";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: () => undefined, replace: () => undefined, refresh: () => undefined }),
  usePathname: () => "/settings/migration",
  useSearchParams: () => new URLSearchParams(),
}));

const RUN_ID = "01a1a418-72b3-75ba-b46e-bfe951172f7c";
const SHA = "dce3c0f365044fa8b707a8d434d6eefaed842fba0a41fcb4a7f28842a5fb77ae";
const SUMMARY: RunSummary = {
  id: RUN_ID, kind: "dry_run", status: "completed", source_label: "legacy_export", source_digest: SHA, issue_count: 61,
  quarantined_count: 30, error_count: 3, started_at: "2026-11-04T01:00:00Z", finished_at: "2026-11-04T01:00:04Z",
  started_by_name: "Priya Nair", backup_id: null, error_code: null, path: `/settings/migration/runs/${RUN_ID}`,
};
const REPORT = {
  reconciled: true,
  source: {
    label: "legacy_export", digest: SHA, authorised: true, ignored_files: ["notes.txt"],
    export_manifest: { authorised_by: "Synthetic test fixture", exported_at: "2026-11-04T06:00:00Z" },
    files: [{ file: "packaging.xlsx", entity: "packaging", format: "xlsx", sha256: SHA, bytes: 5175, rows: 4 }],
  },
  entities: {
    packaging: { source_rows: 4, accepted: 2, quarantined: 2, rejected: 0, duplicate_identical: 0, balanced: true },
    quotes: { source_rows: 8, accepted: 4, quarantined: 4, rejected: 0, duplicate_identical: 0, balanced: true },
  },
  links: { "pricing->products": { linked: 3, orphans: 1 }, "quote_lines->products": { unresolved: 1 } },
  quotes: {
    totals_by_currency: { EUR: { source_quotes: 5, source_total: "5750.00", accepted_total: "4250.00", recomputed_total: "3850.00", discrepancy_total: "400.00", discrepant_quotes: 1 } },
    discrepancies: [{ source_key: "q-2", quote_number: "LK-QT-2025-0002", currency: "EUR", legacy_total: "2400.00", recomputed_total: "2000.00", difference: "400.00" }],
  },
  media: { accessible: 2, not_fetched: 2, inaccessible: [{ source_key: "LKX-1002|image|missing_large.png", location: "missing_large.png", reason: "missing" }] },
  challans: { documents: 2, lines: 3, inventory_effect: "none", stock_movements: 0 },
  users: { invitation: 2, historical: 1, credentials_dropped: 6, candidates: [] },
  id_maps: { total: 82, new: 82, changed: 0, unchanged: 0 },
  opening_balances: { lines: 2 },
};
const DETAIL: RunDetail = {
  ...SUMMARY, export_manifest: {}, files: [], options: {}, counts: {}, report: REPORT, error_detail: null,
  issues_csv_path: `/api/v1/migration/runs/${RUN_ID}/issues.csv`,
};
const ISSUE: Issue = {
  id: "01a1a418-0000-7000-8000-000000000001", entity: "packaging", source_file: "packaging.xlsx", row_number: 3,
  source_key: "LKX-1002", code: "ALIAS_CONFLICT", severity: "quarantine", message: "Alias values disagree: carton_qty=12, master_carton_qty=10",
  field: "carton_qty", raw_value: "carton_qty=12, master_carton_qty=10", raw: { product_key: "LKX-1002", carton_qty: "12", master_carton_qty: "10" },
};
const PARTY = { id: "01a1a418-0000-7000-8000-0000000000aa", party_number: "P-00001", display_name: "Nordhaus Interiors GmbH", country_code: "DE", path: "/sales/parties/01a1a418-0000-7000-8000-0000000000aa" };
const CANDIDATE: Candidate = {
  id: "01a1a418-0000-7000-8000-0000000000c1", legacy_name: "Nordhaus GmbH", legacy_country: "Germany", name_key: "nordhaus",
  country_key: "DE", variants: [{ name: "Nordhaus GmbH", count: 1 }, { name: "NORDHAUS GMBH.", count: 1 }], occurrences: 2,
  sources: [], match_kind: "name_tokens", score: "0.700", status: "proposed", suggested_party: PARTY, linked_party: null,
  decided_by_name: null, decided_at: null, decision_note: null, version: 1,
  capabilities: { decide: { allowed: true, reason_code: null }, reopen: { allowed: false, reason_code: "not_decided" } },
};
const page = <T,>(items: T[]) => ({ items, total: items.length, limit: 25, offset: 0 });
const admin = testBootstrap({ permissions: ["migration.run.read", "migration.party_candidate.update", "system.backup.read"] });

describe("migration helpers", () => {
  it("reads the reconciliation report defensively", () => {
    const report = readReport(REPORT);
    expect(report.reconciled).toBe(true);
    expect(report.entities.map((e) => e.entity)).toEqual(["packaging", "quotes"]);
    expect(report.totals[0]).toMatchObject({ currency: "EUR", acceptedTotal: "4250.00", recomputedTotal: "3850.00", difference: "400.00" });
    expect(report.links.find((l) => l.link === "quote_lines->products")?.unresolved).toBe(1);
    expect(report.challans).toEqual({ documents: 2, stockMovements: 0 });
    expect(report.users?.credentialsDropped).toBe(6);
    expect(readReport(null).entities).toEqual([]);
    expect(readReport({ entities: { x: "nonsense" } }).entities[0]?.rows).toBe(0);
  });

  it("keeps filters in the URL and refuses odd route values", () => {
    expect(parseRunId(RUN_ID)).toBe(RUN_ID);
    expect(parseRunId("../../etc")).toBeNull();
    const filters = issueFiltersFrom({ severity: "quarantine", entity: "packaging", code: "ALIAS_CONFLICT", offset: "60" });
    expect(filters).toEqual({ severity: "quarantine", entity: "packaging", code: "ALIAS_CONFLICT", offset: 50 });
    expect(issueFiltersFrom({ severity: "bogus", entity: "DROP TABLE", code: "x;y" })).toEqual({ severity: null, entity: null, code: null, offset: 0 });
    expect(issueFiltersHref(RUN_ID, filters)).toBe(`/settings/migration/runs/${RUN_ID}?severity=quarantine&entity=packaging&code=ALIAS_CONFLICT&offset=50#issues`);
    expect(entityLabel("delivery_challan_lines")).toBe("Delivery challan lines");
    expect(shortSha(SHA)).toBe("dce3c0f36504…");
    expect(bytesText(1037584, "en-IN")).toBe("1,013.3 KB");
    expect(bytesText(51, "en-IN")).toBe("51 B");
  });

  it("registers the settings routes under the migration and backup permissions", () => {
    expect(getRoute("settings-migration")).toMatchObject({ path: "/settings/migration", navGroup: "context", requiredPermission: "migration." });
    expect(getRoute("settings-migration-run").path).toBe("/settings/migration/runs/[runId]");
    expect(getRoute("settings-backups")).toMatchObject({ path: "/settings/backups", requiredPermission: "system." });
  });
});

describe("Settings › Migration", () => {
  it("shows the latest run, the history and candidate customers with their decisions", () => {
    const html = renderWithQueries(<MigrationPage offset={0} />, (client) => {
      client.setQueryData(queryKeys.migration.runs(0), page([SUMMARY]));
      client.setQueryData(queryKeys.migration.candidates({ status: "proposed", offset: 0 }), page([CANDIDATE]));
      client.setQueryData(queryKeys.migration.opening(), page([]));
    }, admin);
    const text = textOf(html);
    expect(text).toContain("Latest run");
    expect(text).toContain("legacy_export");
    expect(text).toContain("Nordhaus GmbH");
    expect(text).toContain("2 spellings");
    expect(text).toContain("Link to Nordhaus Interiors GmbH");
    expect(text).toContain("similar name");
    expect(text).toContain("No opening-balance batch staged");
    expect(html).toContain(`href="/settings/migration/runs/${RUN_ID}"`);
    expect(nestedInteractive(html)).toEqual([]);
    expect(controlsWithoutVisibleFocus(html)).toEqual([]);
  });

  it("asks for an authenticator confirmation instead of failing on mfa_required", () => {
    const html = renderWithQueries(<MigrationPage offset={0} />, (client) => {
      seedQueryError(client, queryKeys.migration.runs(0), new ProblemError({ title: "x", status: 401, code: "mfa_required" }));
      client.setQueryData(queryKeys.migration.candidates({ status: "proposed", offset: 0 }), page([]));
      client.setQueryData(queryKeys.migration.opening(), page([]));
    }, admin);
    expect(textOf(html)).toContain("Confirm and show");
  });

  it("is refused without migration.run.read", () => {
    const html = renderWithQueries(<MigrationPage offset={0} />, () => undefined, testBootstrap({ permissions: [] }));
    expect(textOf(html)).not.toContain("Run history");
  });

  it("renders a run's reconciliation and its quarantine with row references and original values", () => {
    const filters = { severity: null, entity: null, code: null, offset: 0 };
    const html = renderWithQueries(<RunDetailView runId={RUN_ID} filters={filters} />, (client) => {
      client.setQueryData(queryKeys.migration.run(RUN_ID), DETAIL);
      client.setQueryData(queryKeys.migration.facets(RUN_ID), { severity: [{ value: "quarantine", count: 30 }], entity: [], code: [] });
      client.setQueryData(queryKeys.migration.issues(RUN_ID, { ...filters }), page([ISSUE]));
    }, admin);
    const text = textOf(html);
    expect(text).toContain("Reconciliation by collection");
    expect(text).toContain("LK-QT-2025-0002");
    expect(text).toContain("4250.00");
    expect(text).toContain("Stock movements planned from legacy challans");
    expect(text).toContain("packaging.xlsx · row 3 · LKX-1002");
    expect(text).toContain("ALIAS_CONFLICT");
    expect(text).toContain("master_carton_qty");
    expect(text).toContain("Not read (not a legacy collection): notes.txt");
    expect(html).toContain(`/api/v1/migration/runs/${RUN_ID}/issues.csv`);
    expect(nestedInteractive(html)).toEqual([]);
  });
});

describe("Settings › Backups", () => {
  const FACTS: BackupFacts = {
    last_backup: {
      backup_id: "bk-20261104T011425Z-00b502", status: "completed", database: "lk_wt6", alembic_revision: "0050",
      started_at: "2026-11-04T01:14:25Z", finished_at: "2026-11-04T01:14:30Z", dump_bytes: 1037584, dump_sha256: SHA,
      storage_files: 1, storage_bytes: 51, storage_sha256: SHA, manifest_sha256: SHA, table_count: 159, row_total: 2136,
      error_code: null, rehearsal_outcome: "passed", rehearsed_at: "2026-11-04T01:14:40Z", rehearsal_seconds: "9.76",
      rehearsal_checks: [{ check: "row_counts", passed: true, detail: "2136 rows in 159 tables" }, { check: "temporary_database_dropped", passed: true, detail: "lk_rehearsal_a221eb6b" }],
    },
    last_rehearsal: null,
    history: [],
    max_age_hours_for_apply: 24,
  };

  it("shows the last backup and its rehearsal checks, read-only", () => {
    const html = renderWithQueries(<BackupsPage />, (client) => {
      client.setQueryData(queryKeys.migration.backups(), { ...FACTS, last_rehearsal: FACTS.last_backup, history: [FACTS.last_backup] });
    }, admin);
    const text = textOf(html);
    expect(text).toContain("bk-20261104T011425Z-00b502");
    expect(text).toContain("Row counts");
    expect(text).toContain("Temporary database dropped");
    expect(text).toContain("needs a backup from the last 24 hours");
    expect(html).not.toContain("<button");
  });

  it("says when nothing has been backed up yet", () => {
    const html = renderWithQueries(<BackupsPage />, (client) => {
      client.setQueryData(queryKeys.migration.backups(), { ...FACTS, last_backup: null });
    }, admin);
    expect(textOf(html)).toContain("No backup recorded yet");
  });
});
