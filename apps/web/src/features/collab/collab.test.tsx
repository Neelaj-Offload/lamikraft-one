import { describe, expect, it } from "vitest";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { renderWithQueries, seedQueryError, textOf } from "@/lib/test-support/render";
import { ActivityFeed } from "./activity";
import { formatBytes, purposeFor } from "./api";
import { preflight, RecordAttachments, uploadProblem } from "./attachments";
import { RecordNote, statusLine } from "./notes";

const Q = "0192a000-0000-7000-8000-000000000009";
const cap = (allowed: boolean) => ({ allowed, reason_code: allowed ? null : "permission_denied" });

describe("internal note", () => {
  it("is read-only when the record cannot be edited, and describes its save state", () => {
    const html = renderWithQueries(<RecordNote resourceType="sales.quote" resourceId={Q} />, (c) =>
      c.setQueryData(queryKeys.collab.note("sales.quote", Q), {
        resource_type: "sales.quote",
        resource_id: Q,
        note_id: "n",
        body: "Call back Friday",
        version: 2,
        updated_at: "2026-10-12T03:00:00Z",
        updated_by: "u",
        updated_by_name: "Meera Iyer",
        capabilities: { update: cap(false) },
      }),
    );
    expect(textOf(html)).toContain("Read only");
    expect(html).toContain("readOnly");
    expect(statusLine("conflict", undefined)).toMatch(/Someone else changed/);
    expect(statusLine("idle", { updated_by_name: "Neha" } as never)).toBe("Last changed by Neha.");
  });

  it("shows nothing of a record that is not visible (404)", () => {
    const html = renderWithQueries(<RecordNote resourceType="sales.quote" resourceId={Q} />, (c) =>
      seedQueryError(c, queryKeys.collab.note("sales.quote", Q), new ProblemError({ title: "Not found", status: 404, code: "not_found" })),
    );
    expect(textOf(html)).not.toContain("Internal note");
  });
});

describe("attachments", () => {
  it("lists files with download links and offers add/remove only when allowed", () => {
    const list = {
      items: [
        {
          id: "a1",
          resource_type: "sales.quote",
          resource_id: Q,
          file_id: "f1",
          title: "Drawing",
          role: "document",
          kind: "pdf",
          content_type: "application/pdf",
          size_bytes: 2048,
          content_url: "/api/v1/files/f1/content",
          thumbnail_url: null,
          created_at: "2026-10-12T03:00:00Z",
          created_by_name: "Meera Iyer",
          version: 1,
          capabilities: { update: cap(false) },
        },
      ],
      capabilities: { add: cap(false) },
    };
    const html = renderWithQueries(<RecordAttachments resourceType="sales.quote" resourceId={Q} />, (c) => c.setQueryData(queryKeys.collab.attachments("sales.quote", Q), list));
    expect(html).toContain('href="/api/v1/files/f1/content"');
    expect(textOf(html)).not.toContain("Attach files");
    expect(textOf(html)).not.toContain("Remove");
    const editable = renderWithQueries(<RecordAttachments resourceType="sales.quote" resourceId={Q} />, (c) =>
      c.setQueryData(queryKeys.collab.attachments("sales.quote", Q), { items: [], capabilities: { add: cap(true) } }),
    );
    expect(textOf(editable)).toContain("Attach files");
    expect(textOf(editable)).toContain("No attachments");
  });

  it("refuses oversized and SVG files before uploading and explains server refusals", () => {
    expect(preflight({ name: "a.pdf", size: 30 * 1024 * 1024, type: "application/pdf" } as File)).toMatch(/larger than 25 MB/);
    expect(preflight({ name: "x.svg", size: 10, type: "image/svg+xml" } as File)).toMatch(/SVG/);
    expect(preflight({ name: "x.png", size: 10, type: "image/png" } as File)).toBeNull();
    expect(purposeFor({ type: "image/webp" } as File)).toBe("image");
    expect(uploadProblem(new ProblemError({ title: "x", status: 413, code: "payload_too_large" }))).toMatch(/too large/);
    expect(formatBytes(1536)).toBe("2 KB");
  });
});

describe("activity feed", () => {
  it("renders items with in-app links only, and empty and forbidden states", () => {
    const key = queryKeys.collab.activity({ resourceType: null, resourceId: null });
    const html = renderWithQueries(<ActivityFeed />, (c) =>
      c.setQueryData(key, {
        pages: [
          {
            items: [
              {
                id: "e1",
                occurred_at: "2026-10-12T03:00:00Z",
                event_type: "sales.quote.created",
                verb: "created",
                summary: "Quote created",
                actor_name: "Meera Iyer",
                actor_type: "user",
                resource_type: "sales.quote",
                resource_id: Q,
                resource_label: "LK-QT-2026-0008",
                path: "/sales/quotes/" + Q,
                changed_fields: [],
              },
              {
                id: "e2",
                occurred_at: "2026-10-12T02:00:00Z",
                event_type: "x.y.updated",
                verb: "updated",
                summary: "Y updated",
                actor_name: null,
                actor_type: "system",
                resource_type: "x.y",
                resource_id: null,
                resource_label: "Evil",
                path: "https://evil.example",
                changed_fields: ["status"],
              },
            ],
            next_cursor: null,
          },
        ],
        pageParams: [null],
      }),
    );
    expect(textOf(html)).toContain("Meera Iyer · Quote created");
    expect(html).toContain('href="/sales/quotes/' + Q + '"');
    expect(html).not.toContain("evil.example");
    expect(textOf(html)).toContain("changed status");
    const empty = renderWithQueries(<ActivityFeed />, (c) => c.setQueryData(key, { pages: [{ items: [], next_cursor: null }], pageParams: [null] }));
    expect(textOf(empty)).toContain("No activity yet");
    const forbidden = renderWithQueries(<ActivityFeed />, (c) => seedQueryError(c, key, new ProblemError({ title: "x", status: 403, code: "permission_denied" })));
    expect(textOf(forbidden)).not.toContain("Quote created");
  });
});
