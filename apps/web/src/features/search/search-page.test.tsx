import { describe, expect, it, vi } from "vitest";
import { ProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { renderWithQueries, seedQueryError, textOf } from "@/lib/test-support/render";
import { parseRecent, parseSearchResponse } from "./parse";
import { seeAllHref } from "./search-dialog";
import { SearchPage, searchPageHref, searchPageStateFrom } from "./search-page";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), usePathname: () => "/search", useSearchParams: () => new URLSearchParams() }));

const key = (q: string, type: string | null = null, offset = 0) => [...queryKeys.search.query(q), { type, offset }];

describe("platform search shape (platform-2)", () => {
  it("reads hits, has_more, offset and unavailable groups from the platform response", () => {
    const response = parseSearchResponse(
      {
        query: "nordhaus",
        terms: ["nordhaus"],
        groups: [
          {
            resource_type: "parties.party",
            group: "Parties",
            hits: [{ resource_type: "parties.party", resource_id: "p1", title: "Nordhaus Interiors GmbH", subtitle: "DE", path: "/sales/parties/p1" }],
            has_more: true,
            offset: 0,
            total: null,
          },
        ],
        unavailable_groups: ["Quotes"],
      },
      "nordhaus",
    );
    expect(response.groups[0]).toMatchObject({ group: "Parties", hasMore: true, offset: 0, total: 2 });
    expect(response.unavailable).toEqual(["Quotes"]);
    expect(parseRecent([{ id: "r1", query: "oak", searched_at: "2026-10-12T03:00:00Z" }, { nope: 1 }])).toEqual([
      { id: "r1", query: "oak", searched_at: "2026-10-12T03:00:00Z" },
    ]);
  });

  it("keeps the results page state in the URL (one group pages; offsets are bounded)", () => {
    expect(searchPageStateFrom({ q: " oak tray ", type: "catalogue.product", offset: "20" })).toEqual({ q: "oak tray", type: "catalogue.product", offset: 20 });
    expect(searchPageStateFrom({ q: "oak", type: "bad type", offset: "999" })).toEqual({ q: "oak", type: null, offset: 0 });
    expect(searchPageStateFrom({ q: "oak", type: "catalogue.product", offset: "999" }).offset).toBe(200);
    expect(searchPageHref({ q: "100% oak", type: null, offset: 0 })).toBe("/search?q=100%25+oak");
    expect(seeAllHref(" a&b ")).toBe("/search?q=a%26b");
  });
});

describe("search results page", () => {
  it("asks for two characters before searching", () => {
    expect(textOf(renderWithQueries(<SearchPage state={{ q: "o", type: null, offset: 0 }} />, () => undefined))).toContain("Type at least 2 characters");
  });

  it("groups results with totals and a see-all link per group", () => {
    const html = renderWithQueries(<SearchPage state={{ q: "oak", type: null, offset: 0 }} />, (c) =>
      c.setQueryData(key("oak"), {
        q: "oak",
        groups: [
          {
            group: "Products",
            resource_type: "catalogue.product",
            total: 12,
            hasMore: true,
            offset: 0,
            items: [{ resource_type: "catalogue.product", resource_id: "p1", title: "LK-OT-0450 · Oak tray", subtitle: null, path: "/products/p1" }],
          },
        ],
      }),
    );
    expect(textOf(html)).toContain("12 found");
    expect(html).toContain('href="/search?q=oak&amp;type=catalogue.product"');
  });

  it("shows an empty and an error state", () => {
    expect(textOf(renderWithQueries(<SearchPage state={{ q: "zzz", type: null, offset: 0 }} />, (c) => c.setQueryData(key("zzz"), { q: "zzz", groups: [] })))).toContain(
      "Nothing matches",
    );
    const failed = renderWithQueries(<SearchPage state={{ q: "oak", type: null, offset: 0 }} />, (c) =>
      seedQueryError(c, key("oak"), new ProblemError({ title: "x", status: 500, code: "internal" })),
    );
    expect(textOf(failed)).toMatch(/Try again|Retry/i);
  });
});
