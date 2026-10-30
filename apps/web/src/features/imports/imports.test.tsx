import { describe, expect, it, vi } from "vitest";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { renderWithQueries, seedQueryError, textOf } from "@/lib/test-support/render";
import { testBootstrap } from "@/lib/test-support/session";
import { isBusy, stepOf, type JobDetail } from "./api";
import { DemoResetPanel } from "./demo-reset";
import { ImportHistory, ImportJobView, NewImport } from "./workbench";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/settings/imports",
  useSearchParams: () => new URLSearchParams(),
}));

const JOB = "0192a000-0000-7000-8000-0000000000a9";
const importer = () =>
  testBootstrap({
    permissions: ["imports.job.read", "imports.job.run", "imports.rollback.execute", "system.demo_data.delete"].map((key) => ({ key, scope: "company" })),
  });
const sales = () => testBootstrap();

function job(overrides: Partial<JobDetail> = {}): JobDetail {
  return {
    id: JOB,
    import_type: "packaging",
    status: "validated",
    file_name: "packaging.csv",
    file_sha256: "a".repeat(64),
    file_format: "csv",
    row_count: 3,
    counts: { valid: 1, quarantined: 1, rejected: 1, to_update: 1 },
    progress: { state: "idle" },
    parent_job_id: null,
    created_at: "2026-10-12T03:25:00Z",
    created_by_name: "Priya Nair",
    committed_at: null,
    rolled_back_at: null,
    path: `/settings/imports/${JOB}`,
    sheet_name: null,
    mapping: { product_key: "product_key" },
    options: { blank_cells: "ignore", decor_float_artefact_rule: true, default_price_type: null, default_currency: null, date_order: "DMY" },
    error_code: null,
    error_detail: null,
    source_file_id: "0192a000-0000-7000-8000-0000000000b9",
    source_url: "/api/v1/files/0192a000-0000-7000-8000-0000000000b9/content",
    report_url: `/api/v1/imports/jobs/${JOB}/issues/report.csv`,
    version: 3,
    capabilities: {
      commit: { allowed: true, reason_code: null },
      validate: { allowed: true, reason_code: null },
      recheck: { allowed: true, reason_code: null },
      rollback: { allowed: false, reason_code: "not_committed" },
    },
    ...overrides,
  };
}

describe("import job steps", () => {
  it("derive the stepper position and polling from status and progress", () => {
    expect(stepOf(job({ status: "parsed" }))).toBe("mapping");
    expect(stepOf(job({ status: "parsed", progress: { state: "validating" } }))).toBe("validating");
    expect(stepOf(job())).toBe("review");
    expect(stepOf(job({ status: "commit_failed" }))).toBe("review");
    expect(stepOf(job({ status: "committing" }))).toBe("committing");
    expect(stepOf(job({ status: "committed" }))).toBe("result");
    expect(isBusy(job({ progress: { state: "validating" } }))).toBe(true);
    expect(isBusy(job({ status: "committed" }))).toBe(false);
  });
});

describe("import screens", () => {
  it("history lists durable jobs and offers New import only to importers", () => {
    const seed = (c: import("@tanstack/react-query").QueryClient) =>
      c.setQueryData(queryKeys.imports.jobs({ import_type: null, offset: 0 }), { items: [job({ status: "committed", counts: { committed: 2 } })], total: 1, limit: 25, offset: 0 });
    const text = textOf(renderWithQueries(<ImportHistory importType={null} offset={0} />, seed, importer()));
    expect(text).toContain("packaging.csv");
    expect(text).toContain("Committed");
    expect(text).toContain("New import");
    expect(textOf(renderWithQueries(<ImportHistory importType={null} offset={0} />, seed, sales()))).not.toContain("packaging.csv");
  });

  it("review shows counts, the full report link, recheck and the acknowledgement for excluded rows", () => {
    const html = renderWithQueries(
      <ImportJobView jobId={JOB} />,
      (c) => {
        c.setQueryData(queryKeys.imports.job(JOB), job());
        c.setQueryData(queryKeys.imports.issues(JOB, { severity: null, offset: 0 }), {
          items: [{ id: "i1", row_number: 2, column: "carton_qty", field: "carton_qty", code: "ALIAS_CONFLICT", severity: "quarantine", message: "Alias values disagree", raw_value: "carton_qty=24, master_carton_qty=12" }],
          total: 1, limit: 50, offset: 0,
        });
        c.setQueryData(queryKeys.imports.rows(JOB, { status: null, offset: 0 }), { items: [], total: 0, limit: 50, offset: 0 });
      },
      importer(),
    );
    const text = textOf(html);
    expect(text).toContain("ALIAS_CONFLICT");
    expect(text).toContain("2 rejected or quarantined rows will not be imported");
    expect(text).toContain("Recheck quarantined rows");
    expect(text).not.toContain("Roll back");
    expect(html).toContain(`href="/api/v1/imports/jobs/${JOB}/issues/report.csv"`);
    expect(text).toContain("Acknowledge the excluded rows"); // the commit button says why it is disabled
  });

  it("offers rollback only when the server allows it and reports a failed job", () => {
    const html = renderWithQueries(
      <ImportJobView jobId={JOB} />,
      (c) => {
        c.setQueryData(queryKeys.imports.job(JOB), job({ status: "committed", capabilities: { rollback: { allowed: true, reason_code: null } } }));
        c.setQueryData(queryKeys.imports.issues(JOB, { severity: null, offset: 0 }), { items: [], total: 0, limit: 50, offset: 0 });
        c.setQueryData(queryKeys.imports.rows(JOB, { status: null, offset: 0 }), { items: [], total: 0, limit: 50, offset: 0 });
      },
      importer(),
    );
    expect(textOf(html)).toContain("Roll back");
    const failed = renderWithQueries(
      <ImportJobView jobId={JOB} />,
      (c) => seedQueryError(c, queryKeys.imports.job(JOB), new ProblemError({ type: "about:blank", title: "Not found", status: 404, code: "not_found" })),
      importer(),
    );
    expect(textOf(failed)).not.toContain("packaging.csv");
  });

  it("the upload step lists the types in dependency order with templates", () => {
    const html = renderWithQueries(
      <NewImport />,
      (c) =>
        c.setQueryData(queryKeys.imports.types(), [
          { import_type: "category_taxonomy", label: "Category taxonomy", description: "Import this first.", fields: [{ name: "category", required: true, aliases: [] }], depends_on: [], dependency_status: { categories: 2 }, template_path: "/api/v1/imports/types/category_taxonomy/template.csv" },
          { import_type: "products_master", label: "Products master", description: "Needs taxonomy.", fields: [], depends_on: ["category_taxonomy"], dependency_status: { products: 4 }, template_path: "/api/v1/imports/types/products_master/template.csv" },
        ]),
      importer(),
    );
    const text = textOf(html);
    expect(text).toContain("1. Category taxonomy");
    expect(text).toContain("Needs: Category taxonomy");
    expect(text).toContain("2 categories now");
    expect(html).toContain('href="/api/v1/imports/types/category_taxonomy/template.csv"');
    expect(text).toContain("Choose a file");
  });

  it("the demo reset needs the phrase, and explains a refusal", () => {
    const allowed = renderWithQueries(
      <DemoResetPanel />,
      (c) => c.setQueryData(queryKeys.imports.demoReset(), { company_name: "Crown Decor (Demo)", is_demo: true, counts: { catalogue_product: 4 }, blocking_references: {}, allowed: true, reason_code: null, phrase: "RESET Crown Decor (Demo)", token: "1.sig" }),
      importer(),
    );
    expect(textOf(allowed)).toContain("Type “RESET Crown Decor (Demo)” to confirm");
    expect(textOf(allowed)).toContain("Type the phrase exactly");
    const refused = renderWithQueries(
      <DemoResetPanel />,
      (c) => c.setQueryData(queryKeys.imports.demoReset(), { company_name: "Crown", is_demo: true, counts: {}, blocking_references: { pricing_price_list_item: 3 }, allowed: false, reason_code: "demo_data_referenced", phrase: "RESET Crown", token: null }),
      importer(),
    );
    expect(textOf(refused)).toContain("Price lists, quotes or other records use the demo products");
    expect(renderWithQueries(<DemoResetPanel />, () => undefined, sales())).toBe("");
  });
});
