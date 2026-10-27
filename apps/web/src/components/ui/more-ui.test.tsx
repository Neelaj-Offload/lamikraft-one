import { CalendarDateTime } from "@internationalized/date";
import { Button as RacButton } from "react-aria-components";
import { describe, expect, it } from "vitest";
import { countTags, render, renderInSession, textOf } from "@/lib/test-support/render";
import { testBootstrap } from "@/lib/test-support/session";
import { DatePicker, dateValueToUtcIso, toCalendarDate, toZonedDateTime, zonedPlaceholder, zonedToUtcIso } from "./date-picker";
import { Dialog, Drawer } from "./dialog";
import { Menu, MenuItem, MenuTrigger } from "./menu";
import { ComboBox } from "./select";
import { SearchField } from "./search-field";
import { LiveAnnouncer, ToastRegion } from "./toast";
import { Tooltip } from "./tooltip";

const noop = () => {};

describe("DatePicker", () => {
  it("keeps business dates as calendar dates", () => {
    expect(toCalendarDate("2026-10-12")?.toString()).toBe("2026-10-12");
    expect(toCalendarDate("12/10/2026")).toBeNull();
    expect(toCalendarDate(null)).toBeNull();
  });

  it("edits instants as wall time in the user's zone and saves UTC", () => {
    const zoned = toZonedDateTime("2026-10-12T13:00:00Z", "Asia/Kolkata")!;
    expect(zoned.hour).toBe(18);
    expect(zoned.minute).toBe(30);
    expect(zonedToUtcIso(zoned)).toBe("2026-10-12T13:00:00Z");
    const berlin = toZonedDateTime("2026-10-12T13:00:00Z", "Europe/Berlin")!;
    expect(berlin.hour).toBe(15);
    expect(toZonedDateTime("not a date", "Asia/Kolkata")).toBeNull();
  });

  it("renders a labelled group with a calendar button", () => {
    const html = renderInSession(<DatePicker label="Valid until" value="2026-10-12" onChange={noop} />);
    expect(textOf(html)).toContain("Valid until");
    expect(html).toContain('role="group"');
    expect(html).toContain('aria-label="Open calendar"');
  });

  it("shows the zone for date-times (zone-aware display)", () => {
    const html = renderInSession(
      <DatePicker label="Remind me" granularity="minute" value="2026-10-12T13:00:00Z" onChange={noop} />,
      testBootstrap({ time_zone: "Asia/Kolkata" }),
    );
    expect(html).toMatch(/IST|GMT\+5:30|India/);
  });

  it("starts an empty date-time field in the session zone and saves the wall time there", () => {
    const html = renderInSession(
      <DatePicker label="Remind me" granularity="minute" value={null} onChange={noop} />,
      testBootstrap({ time_zone: "Asia/Kolkata" }),
    );
    // The zone segment shows even before a value is chosen.
    expect(html).toMatch(/IST|GMT\+5:30|India/);
    expect(zonedPlaceholder("Asia/Kolkata").timeZone).toBe("Asia/Kolkata");
    // A zone-less value (what an empty picker used to produce) is wall time in the session zone.
    expect(dateValueToUtcIso(new CalendarDateTime(2026, 10, 23, 10, 0), "Asia/Kolkata")).toBe("2026-10-23T04:30:00Z");
    expect(dateValueToUtcIso(toZonedDateTime("2026-10-23T04:30:00Z", "Europe/Berlin")!, "Asia/Kolkata")).toBe("2026-10-23T04:30:00Z");
  });
});

describe("fields with popovers", () => {
  it("SearchField has a label (visually hidden when asked) and a clear button", () => {
    const html = render(<SearchField label="Search the Inbox" hideLabel />);
    expect(html).toMatch(/<label[^>]*class="[^"]*sr-only/);
    expect(html).toContain('aria-label="Clear search"');
    expect(html).toContain('type="search"');
  });

  it("ComboBox is a labelled combobox with an options button", () => {
    const html = render(
      <ComboBox label="Assign to" options={[{ id: "u1", label: "Meera Iyer" }]} value={null} onChange={noop} />,
    );
    expect(html).toContain('role="combobox"');
    expect(html).toContain('aria-label="Show Assign to options"');
  });
});

describe("overlays", () => {
  it("render nothing while closed", () => {
    expect(render(<Dialog title="Snooze" isOpen={false} onOpenChange={noop}>body</Dialog>)).toBe("");
    expect(render(<Drawer title="Context" isOpen={false} onOpenChange={noop}>body</Drawer>)).toBe("");
  });

  it("menus render only their trigger until opened", () => {
    const html = render(
      <MenuTrigger>
        <RacButton aria-label="More actions">⋯</RacButton>
        <Menu aria-label="More actions">
          <MenuItem id="snooze">Snooze</MenuItem>
        </Menu>
      </MenuTrigger>,
    );
    expect(countTags(html, "button")).toBe(1);
    expect(html).toContain('aria-haspopup="true"');
    expect(html).not.toContain("Snooze");
  });

  it("tooltips never replace the trigger's own name", () => {
    const html = render(
      <Tooltip content="Search (/)">
        <RacButton aria-label="Search">s</RacButton>
      </Tooltip>,
    );
    expect(html).toContain('aria-label="Search"');
  });

  it("live regions exist from the first render, empty", () => {
    const html = render(<LiveAnnouncer />);
    expect(html).toContain('role="status" aria-live="polite"');
    expect(html).toContain('role="alert" aria-live="assertive"');
    expect(textOf(html)).toBe("");
    expect(render(<ToastRegion />)).toBe("");
  });
});
