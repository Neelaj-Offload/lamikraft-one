import { describe, expect, it } from "vitest";
import { ProblemError, NetworkError } from "@/lib/api/errors";
import { countTags, nestedInteractive, render, renderInSession, textOf } from "@/lib/test-support/render";
import { Badge, DemoBadge, NotConnectedBadge, StatusPill } from "./badge";
import { Button, IconButton } from "./button";
import { Checkbox, RadioGroup, Switch } from "./choice";
import { DataTable, KeysetPagination, OffsetPagination, type DataTableColumn } from "./data-table";
import {
  ariaSortFor,
  nextSortState,
  offsetRange,
  selectionSummary,
  sortFromParam,
  sortToParam,
  toggleAllRows,
  toggleRow,
} from "./data-table-model";
import { DescriptionList } from "./description-list";
import { LocalDate, LocalDateTime, Money, Quantity, RelativeTime } from "./format";
import { Link, LinkButton } from "./link";
import { NumberField } from "./number-field";
import { Select } from "./select";
import { NavTabs } from "./tabs";
import { TextArea, TextField } from "./text-field";
import {
  Conflict,
  EmptyState,
  ErrorState,
  Loading,
  NotAvailable,
  Offline,
  PermissionDenied,
  Stale,
  Success,
} from "./states";

const noop = () => {};

describe("Button", () => {
  it("renders a real button with a 44 px touch target and no spinner while pending", () => {
    const html = render(
      <Button variant="primary" onPress={noop} isPending pendingLabel="Signing in…">
        Sign in
      </Button>,
    );
    expect(countTags(html, "button")).toBe(1);
    expect(html).toContain("min-h-11");
    expect(textOf(html)).toBe("Signing in…");
    expect(html).not.toMatch(/animate-spin/);
  });

  it("describes why it is disabled", () => {
    const html = render(
      <Button onPress={noop} isDisabled disabledReason="The assistant is not available yet.">
        Send
      </Button>,
    );
    const describedBy = /aria-describedby="([^"]+)"/.exec(html)?.[1];
    expect(describedBy).toBeTruthy();
    expect(html).toContain(`id="${describedBy}"`);
    expect(textOf(html)).toContain("The assistant is not available yet.");
    expect(html).toContain("disabled");
  });

  it("supports submit buttons and each variant", () => {
    for (const variant of ["primary", "secondary", "quiet", "danger"] as const) {
      const html = render(
        <Button type="submit" variant={variant}>
          Save
        </Button>,
      );
      expect(html).toContain('type="submit"');
    }
    expect(render(<Button variant="danger" onPress={noop}>Delete</Button>)).toContain("bg-danger text-on-danger");
  });

  it("names icon-only buttons", () => {
    const html = render(
      <IconButton label="Close" onPress={noop}>
        <svg />
      </IconButton>,
    );
    expect(html).toContain('aria-label="Close"');
    expect(html).toContain("size-11");
  });
});

describe("links", () => {
  it("render anchors that work without JavaScript", () => {
    expect(render(<Link href="/today">Back to Today</Link>)).toMatch(/<a [^>]*href="\/today"/);
    const html = render(
      <LinkButton href="/sales/quotes/1" variant="primary">
        Review quote
      </LinkButton>,
    );
    expect(html).toMatch(/<a [^>]*href="\/sales\/quotes\/1"/);
    expect(html).toContain("bg-forest");
  });
});

describe("fields", () => {
  it("label every input and surface server errors", () => {
    const html = render(<TextField label="Email" type="email" isInvalid errorMessage="Enter a valid email" />);
    const inputId = /<input[^>]*\sid="([^"]+)"/.exec(html)?.[1];
    expect(html).toMatch(new RegExp(`<label[^>]*for="${inputId}"`));
    expect(textOf(html)).toContain("Enter a valid email");
    expect(html).toContain('aria-invalid="true"');
  });

  it("render text areas, selects and choices with labels", () => {
    expect(render(<TextArea label="Note" />)).toContain("<textarea");
    const select = render(<Select label="Reason" options={[{ id: "a", label: "Duplicate" }]} value={null} onChange={noop} />);
    expect(textOf(select)).toContain("Reason");
    expect(select).toContain('aria-haspopup="listbox"');
    expect(render(<Checkbox aria-label="Select row">{null}</Checkbox>)).toContain('type="checkbox"');
    expect(render(<Switch>Shortcuts</Switch>)).toContain('role="switch"');
    const radios = render(
      <RadioGroup label="Theme" value="light" onChange={noop} options={[{ value: "light", label: "Light" }, { value: "dark", label: "Dark" }]} />,
    );
    expect(countTags(radios, "input", 'type="radio"')).toBe(2);
  });

  it("keeps decimal fields as text with a decimal keypad and a formatted preview", () => {
    const html = renderInSession(<NumberField label="Unit price" value="24.0000" onChange={noop} currency="EUR" />);
    expect(html).toContain('inputMode="decimal"');
    expect(html).toContain('value="24.0000"');
    expect(textOf(html)).toContain("€24.00");
    expect(renderInSession(<NumberField label="Quantity" value="240" onChange={noop} maxFractionDigits={0} uom="pcs" />)).toContain(
      'inputMode="numeric"',
    );
  });
});

describe("badges", () => {
  it("pair colour with text", () => {
    expect(textOf(render(<StatusPill tone="warning">Due today</StatusPill>))).toBe("Due today");
    expect(textOf(render(<DemoBadge />))).toBe("Demo");
    expect(textOf(render(<NotConnectedBadge />))).toBe("Not connected");
    expect(render(<Badge tone="danger">Overdue</Badge>)).toContain("text-danger");
  });
});

describe("formatters", () => {
  it("render money and quantities with tabular figures in the session locale", () => {
    const html = renderInSession(
      <>
        <Money value={{ amount: "5760.0000", currency: "EUR" }} />
        <Quantity value={{ value: "240", uom: "pcs" }} />
      </>,
    );
    expect(textOf(html)).toBe("€5,760.00 240 pcs");
    expect(countTags(html, "span", "tabular")).toBe(2);
  });

  it("mark unavailable values instead of inventing zeros", () => {
    const html = renderInSession(<Money value={{ amount: "abc", currency: "EUR" }} />);
    expect(textOf(html)).toBe("— Amount unavailable");
  });

  it("render times in the user's zone from the server clock", () => {
    const html = renderInSession(
      <>
        <LocalDateTime value="2026-10-12T13:00:00Z" />
        <RelativeTime value="2026-10-12T03:20:00Z" />
        <LocalDate value="2026-10-12" />
      </>,
    );
    expect(html).toContain('dateTime="2026-10-12T13:00:00Z"');
    expect(textOf(html)).toMatch(/^Today, 6:30\spm 5 minutes ago 12 Oct 2026$/i);
  });
});

describe("DataTable", () => {
  interface Row {
    id: string;
    number: string;
    party: string;
    total: { amount: string; currency: string };
  }
  const rows: Row[] = [
    { id: "q1", number: "LK-QT-2026-0041", party: "Nordhaus Interiors GmbH", total: { amount: "5760.0000", currency: "EUR" } },
    { id: "q2", number: "LK-QT-2026-0038", party: "Berg & Co AB", total: { amount: "5700.0000", currency: "EUR" } },
  ];
  const columns: DataTableColumn<Row>[] = [
    { id: "number", header: "Quote", cell: (r) => r.number, isRowHeader: true, sortable: true, mobile: "key" },
    { id: "party", header: "Customer", cell: (r) => r.party, mobile: "title" },
    { id: "total", header: "Total", cell: (r) => <Money value={r.total} />, numeric: true, sortable: true, mobile: "amount" },
  ];

  it("is a semantic table with caption, scoped headers and aria-sort", () => {
    const html = renderInSession(
      <DataTable
        caption="Open quotes"
        columns={columns}
        rows={rows}
        rowId={(r) => r.id}
        rowHref={(r) => `/sales/quotes/${r.id}`}
        sort={{ column: "total", direction: "descending" }}
        onSortChange={noop}
      />,
    );
    expect(html).toContain("<caption");
    expect(countTags(html, "th", 'scope="col"')).toBe(3);
    expect(countTags(html, "th", 'scope="row"')).toBe(2);
    expect(html).toContain('aria-sort="descending"');
    expect(html).toContain('aria-sort="none"');
    // Customer is not sortable: no aria-sort on it.
    expect(countTags(html, "th", "aria-sort")).toBe(2);
    expect(html).toMatch(/text-end tabular/);
  });

  it("offers a linked phone list built from column priorities", () => {
    const html = renderInSession(
      <DataTable caption="Open quotes" columns={columns} rows={rows} rowId={(r) => r.id} rowHref={(r) => `/sales/quotes/${r.id}`} />,
    );
    expect(html).toMatch(/<ul aria-label="Open quotes" class="[^"]*md:hidden/);
    expect(html).toContain('href="/sales/quotes/q1"');
  });

  it("uses plain mobile cells inside linked rows, so links never nest", () => {
    const linked: DataTableColumn<Row>[] = [
      {
        id: "number",
        header: "Quote",
        isRowHeader: true,
        mobile: "title",
        cell: (r) => <Link href={`/sales/quotes/${r.id}`}>{r.number}</Link>,
        mobileCell: (r) => r.number,
      },
    ];
    const html = renderInSession(
      <DataTable caption="Open quotes" columns={linked} rows={rows} rowId={(r) => r.id} rowHref={(r) => `/sales/quotes/${r.id}`} />,
    );
    expect(nestedInteractive(html)).toEqual([]);
    // Without rowHref the phone list keeps the interactive cell.
    const unlinked = renderInSession(<DataTable caption="Open quotes" columns={linked} rows={rows} rowId={(r) => r.id} />);
    expect(countTags(unlinked, "a")).toBe(4);
  });

  it("labels selection checkboxes per row and for the page", () => {
    const html = renderInSession(
      <DataTable
        caption="Open quotes"
        columns={columns}
        rows={rows}
        rowId={(r) => r.id}
        selection={{ selected: new Set(["q1"]), onChange: noop, rowLabel: (r) => r.number }}
      />,
    );
    expect(html).toContain('aria-label="Select all rows on this page"');
    expect(html).toContain('aria-label="Select LK-QT-2026-0041"');
  });

  it("renders the empty state instead of an empty table", () => {
    const html = renderInSession(
      <DataTable caption="Open quotes" columns={columns} rows={[]} rowId={(r) => r.id} empty={<EmptyState title="No open quotes" />} />,
    );
    expect(html).not.toContain("<table");
    expect(textOf(html)).toContain("No open quotes");
  });

  it("paginates with real totals", () => {
    const offset = renderInSession(
      <OffsetPagination total={312} limit={50} offset={50} shown={50} control={(o) => ({ href: `/x?offset=${o}` })} />,
    );
    expect(textOf(offset)).toContain("Showing 51–100 of 312");
    expect(offset).toContain('href="/x?offset=0"');
    expect(offset).toContain('href="/x?offset=100"');
    const keyset = render(<KeysetPagination next={{ href: "/inbox?cursor=abc" }} first={null} />);
    expect(textOf(keyset)).toBe("Next page");
    expect(render(<KeysetPagination next={null} first={null} />)).toBe("");
  });
});

describe("DataTable model", () => {
  it("cycles sort direction per column", () => {
    const first = nextSortState(null, "total");
    expect(first).toEqual({ column: "total", direction: "ascending" });
    expect(nextSortState(first, "total")).toEqual({ column: "total", direction: "descending" });
    expect(nextSortState(first, "number")).toEqual({ column: "number", direction: "ascending" });
    expect(ariaSortFor(first, "number")).toBe("none");
    expect(sortToParam({ column: "total", direction: "descending" })).toBe("-total");
    expect(sortFromParam("-total", ["total"])).toEqual({ column: "total", direction: "descending" });
    expect(sortFromParam("-secret", ["total"])).toBeNull();
  });

  it("selects and clears the visible page", () => {
    const selected = new Set(["a"]);
    expect(selectionSummary(["a", "b"], selected)).toBe("some");
    const all = toggleAllRows(["a", "b"], selected);
    expect([...all].sort()).toEqual(["a", "b"]);
    expect(selectionSummary(["a", "b"], all)).toBe("all");
    expect([...toggleAllRows(["a", "b"], all)]).toEqual([]);
    expect([...toggleRow("c", selected)].sort()).toEqual(["a", "c"]);
    expect(selectionSummary([], selected)).toBe("none");
  });

  it("computes offset ranges", () => {
    expect(offsetRange(312, 50, 300, 12)).toEqual({ first: 301, last: 312, total: 312, previousOffset: 250, nextOffset: null });
    expect(offsetRange(0, 50, 0, 0)).toEqual({ first: 0, last: 0, total: 0, previousOffset: null, nextOffset: null });
  });
});

describe("tabs and lists", () => {
  it("renders URL tabs as a nav with aria-current and real counts only", () => {
    const html = render(
      <NavTabs
        label="Inbox views"
        currentId="approvals"
        tabs={[
          { id: "tasks", label: "Tasks", href: "/inbox", count: 3 },
          { id: "approvals", label: "Approvals", href: "/inbox?tab=approvals", count: null },
        ]}
      />,
    );
    expect(html).toContain('<nav aria-label="Inbox views"');
    expect(html).toMatch(/href="\/inbox\?tab=approvals"[^>]*aria-current="page"|aria-current="page"[^>]*href="\/inbox\?tab=approvals"/);
    expect(textOf(html)).toBe("Tasks 3 Approvals");
  });

  it("renders description lists semantically", () => {
    const html = render(<DescriptionList items={[{ term: "Incoterm", description: "FOB" }]} />);
    expect(html).toMatch(/<dl[^>]*>.*<dt[^>]*>Incoterm<\/dt><dd[^>]*>FOB<\/dd>/s);
  });
});

describe("states", () => {
  it("shows what failed, the server's reason and the request id, with Retry", () => {
    const error = new ProblemError({
      code: "permission_denied",
      title: "You can't do that",
      status: 403,
      detail: "Your role cannot read quotes owned by others.",
      request_id: "0192-req",
    });
    const html = renderInSession(<ErrorState error={error} what="your briefing" onRetry={noop} />);
    expect(textOf(html)).toContain("Your briefing couldn't be loaded");
    expect(textOf(html)).toContain("Your role cannot read quotes owned by others.");
    expect(textOf(html)).toContain("0192-req");
    expect(html).toContain('role="alert"');
    expect(textOf(html)).toContain("Try again");
  });

  it("hides server internals on 5xx and calls a missing endpoint 'not available yet'", () => {
    const server = renderInSession(
      <ErrorState error={new ProblemError({ code: "internal_error", title: "Boom", status: 500, detail: "trace" })} what="the Inbox" />,
    );
    expect(textOf(server)).toContain("The server ran into a problem");
    expect(textOf(server)).not.toContain("trace");
    const missing = renderInSession(
      <ErrorState error={new ProblemError({ code: "not_found", title: "Not Found", status: 404, detail: "Not Found" })} what="the Inbox" />,
    );
    expect(textOf(missing)).toContain("The Inbox isn't available yet");
    expect(missing).not.toContain('role="alert"');
  });

  it("renders the offline, stale, conflict, permission, not-available, loading and success states", () => {
    expect(textOf(renderInSession(<ErrorState error={new NetworkError(new TypeError("x"))} what="x" />))).toContain("You're offline");
    expect(textOf(renderInSession(<Offline />))).toContain("changes can't be sent");
    expect(textOf(renderInSession(<Stale asOf="9:02 am" onRefresh={noop} />))).toContain("as of 9:02 am");
    const conflict = renderInSession(
      <Conflict
        conflict={{
          code: "version_conflict",
          title: "Changed",
          detail: null,
          request_id: "r1",
          currentVersion: 4,
          current: {},
          changedBy: "Meera Iyer",
          changedAt: "2026-10-12T05:12:00Z",
          allowedTransitions: [],
          remaining: [],
        }}
        changedAtLabel="10:42 am"
        onReview={noop}
        onKeepMine={noop}
      />,
    );
    expect(textOf(conflict)).toContain("Meera Iyer saved a newer version at 10:42 am");
    expect(textOf(conflict)).toContain("fields you both changed need your choice");
    const denied = renderInSession(<PermissionDenied area="Finance" />);
    expect(denied).toMatch(/<h1[^>]*>You don(&#x27;|')t have access to Finance<\/h1>/);
    expect(denied).toContain('href="/today"');
    expect(textOf(renderInSession(<NotAvailable />))).toContain("Not found or not available to you");
    const loading = render(<Loading label="your briefing" />);
    expect(loading).toContain('aria-busy="true"');
    expect(textOf(loading)).toBe("Loading your briefing…");
    expect(loading).toContain("animate-appear-late");
    const success = renderInSession(<Success title="Snoozed until 2:00 pm" receipt={{ label: "View task", href: "/inbox" }} />);
    expect(success).toContain('href="/inbox"');
  });
});
