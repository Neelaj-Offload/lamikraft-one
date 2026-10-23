import { describe, expect, it } from "vitest";
import { digits, forAllSeeds, int } from "@/lib/test-support/random";
import { compareDecimalStr, isDecimalStr, normaliseDecimalInput } from "./decimal";
import { formatCount, formatDecimal, formatMoney, formatQuantity } from "./money";
import {
  calendarDaysFrom,
  formatBusinessDate,
  formatDayTime,
  formatLongDate,
  formatRelative,
  parseBusinessDate,
  parseInstant,
  zonedDateKey,
} from "./time";

const D0 = new Date("2026-10-12T03:25:00Z"); // Monday 08:55 IST, the fixture clock
const IST = { timeZone: "Asia/Kolkata", locale: "en-IN" };
const BERLIN = { timeZone: "Europe/Berlin", locale: "en-GB" };

describe("DecimalStr input", () => {
  it.each([
    ["240", "240"],
    [" 5,760.00 ", "5760.00"],
    ["1,23,456.5", "123456.5"],
    ["+24", "24"],
    ["0024.50", "24.50"],
    [".5", "0.5"],
    ["7.", "7"],
    ["-0", "0"],
    ["12 345", "12345"],
  ])("normalises %j to %j", (raw, expected) => {
    expect(normaliseDecimalInput(raw, { maxFractionDigits: 4 })).toEqual({ ok: true, value: expected });
  });

  it("treats an empty field as no value", () => {
    expect(normaliseDecimalInput("   ")).toEqual({ ok: true, value: null });
  });

  it.each([
    ["abc", "invalid"],
    ["1e5", "invalid"],
    ["1.2.3", "invalid"],
    ["NaN", "invalid"],
    ["123456789012345", "too_many_integer_digits"],
    ["1.23456", "too_many_fraction_digits"],
    ["-5", "negative"],
  ])("rejects %j as %s", (raw, reason) => {
    expect(normaliseDecimalInput(raw, { maxFractionDigits: 4 })).toEqual({ ok: false, reason });
  });

  it("accepts negatives only when allowed and integers only when asked", () => {
    expect(normaliseDecimalInput("-5.25", { allowNegative: true })).toEqual({ ok: true, value: "-5.25" });
    expect(normaliseDecimalInput("2.5", { maxFractionDigits: 0 })).toEqual({ ok: false, reason: "too_many_fraction_digits" });
  });

  it("always yields a DecimalStr that survives a second pass unchanged (property)", () => {
    forAllSeeds(400, (random) => {
      const integer = digits(random, int(random, 1, 14));
      const fraction = digits(random, int(random, 0, 4));
      const raw = `${integer}${fraction ? `.${fraction}` : ""}`;
      const first = normaliseDecimalInput(raw, { maxFractionDigits: 4 });
      if (!first.ok || first.value === null) throw new Error(`rejected ${raw}`);
      expect(isDecimalStr(first.value)).toBe(true);
      expect(normaliseDecimalInput(first.value, { maxFractionDigits: 4 })).toEqual(first);
      expect(compareDecimalStr(first.value, raw)).toBe(0);
    });
  });

  it("compares without floats", () => {
    expect(compareDecimalStr("99999999999999.999999", "99999999999999.999998")).toBe(1);
    expect(compareDecimalStr("24.0000", "24")).toBe(0);
    expect(compareDecimalStr("-1", "0.5")).toBe(-1);
    expect(compareDecimalStr("-2", "-10")).toBe(1);
    expect(compareDecimalStr("0.10", "0.09")).toBe(1);
    expect(() => compareDecimalStr("1e3", "1")).toThrow(TypeError);
  });
});

describe("money and quantities", () => {
  it("formats server amounts exactly with the currency's minor unit", () => {
    expect(formatMoney({ amount: "5760.0000", currency: "EUR" }, { locale: "en-GB" })).toBe("€5,760.00");
    expect(formatMoney({ amount: "24.0000", currency: "EUR" }, { locale: "en-GB" })).toBe("€24.00");
    expect(formatMoney({ amount: "123456.5", currency: "INR" }, { locale: "en-IN" })).toBe("₹1,23,456.50");
    expect(formatMoney({ amount: "5850.0000", currency: "GBP" }, { locale: "en-GB", display: "code" })).toMatch(/^GBP\s5,850\.00$/);
  });

  it("keeps precision a float would lose", () => {
    expect(formatMoney({ amount: "99999999999999.99", currency: "USD" }, { locale: "en-US" })).toBe("$99,999,999,999,999.99");
    expect(formatDecimal("12345678901234.567891", { locale: "en-US" })).toBe("12,345,678,901,234.567891");
  });

  it("shows unit prices to four places when asked", () => {
    expect(formatMoney({ amount: "9.4950", currency: "EUR" }, { locale: "en-GB", maxFractionDigits: 4 })).toBe("€9.495");
  });

  it("refuses invalid values instead of guessing", () => {
    expect(formatMoney({ amount: "5760.5.1", currency: "EUR" })).toBeNull();
    expect(formatMoney({ amount: "12", currency: "eur" })).toBeNull();
    expect(formatMoney({ amount: 5760 as unknown as string, currency: "EUR" })).toBeNull();
    expect(formatMoney(null)).toBeNull();
    expect(formatQuantity({ value: "", uom: "pcs" })).toBeNull();
  });

  it("formats quantities with their unit", () => {
    expect(formatQuantity({ value: "240", uom: "pcs" }, { locale: "en-IN" })).toBe("240 pcs");
    expect(formatQuantity({ value: "1200.500000", uom: "sqm" }, { locale: "en-IN" })).toBe("1,200.5 sqm");
    expect(formatQuantity({ value: "24", uom: "carton" }, { unitLabel: "cartons" })).toBe("24 cartons");
  });

  it("formats counts", () => {
    expect(formatCount(1234, "en-IN")).toBe("1,234");
  });
});

describe("zone-aware time", () => {
  it("parses only RFC 3339 instants and real business dates", () => {
    expect(parseInstant("2026-10-12T13:00:00Z")?.toISOString()).toBe("2026-10-12T13:00:00.000Z");
    expect(parseInstant("2026-10-12 13:00")).toBeNull();
    expect(parseInstant("2026-10-12")).toBeNull();
    expect(parseBusinessDate("2026-02-30")).toBeNull();
    expect(parseBusinessDate("2026-10-12")?.toISOString()).toBe("2026-10-12T00:00:00.000Z");
  });

  it("labels the same instant in the user's zone, not the browser's", () => {
    // fixtures A-05: the Berg reply is due 13:00Z: "Today 18:30" in Kolkata, "Today 15:00" in Berlin.
    expect(formatDayTime("2026-10-12T13:00:00Z", D0, IST)).toMatch(/^Today, 6:30\spm$/i);
    expect(formatDayTime("2026-10-12T13:00:00Z", D0, BERLIN)).toBe("Today, 15:00");
  });

  it("uses tomorrow, yesterday and dated labels across midnight in the zone", () => {
    // 19:00Z on the 12th is 00:30 on the 13th in Kolkata: tomorrow there, still today in Berlin.
    expect(formatDayTime("2026-10-12T19:00:00Z", D0, IST)).toMatch(/^Tomorrow, 12:30\sam$/i);
    expect(formatDayTime("2026-10-12T19:00:00Z", D0, BERLIN)).toBe("Today, 21:00");
    expect(formatDayTime("2026-10-11T10:42:00Z", D0, IST)).toMatch(/^Yesterday, 4:12\spm$/i);
    expect(formatDayTime("2026-10-15T03:30:00Z", D0, BERLIN)).toBe("Thu 15 Oct, 5:30");
    expect(formatDayTime("2025-12-31T06:30:00Z", D0, BERLIN)).toBe("31 Dec 2025, 7:30");
    expect(formatDayTime("nonsense", D0, IST)).toBeNull();
  });

  it("computes calendar days in the zone", () => {
    expect(zonedDateKey(new Date("2026-10-11T19:00:00Z"), "Asia/Kolkata")).toBe("2026-10-12");
    expect(calendarDaysFrom(new Date("2026-10-11T19:00:00Z"), D0, "Asia/Kolkata")).toBe(0);
    expect(calendarDaysFrom(new Date("2026-10-11T19:00:00Z"), D0, "Europe/Berlin")).toBe(-1);
  });

  it("formats long and business dates without shifting them", () => {
    expect(formatLongDate(D0, IST)).toBe("Monday, 12 October");
    expect(formatBusinessDate("2026-10-12", "en-GB")).toBe("12 Oct 2026");
    expect(formatBusinessDate("2026-10-12", "en-GB", "long")).toBe("Monday 12 October");
    expect(formatBusinessDate("12/10/2026", "en-GB")).toBeNull();
  });

  it("describes freshness relative to the server's now", () => {
    expect(formatRelative("2026-10-12T03:20:00Z", D0, "en")).toBe("5 minutes ago");
    expect(formatRelative("2026-10-12T05:25:00Z", D0, "en")).toBe("in 2 hours");
    expect(formatRelative("2026-10-12T03:24:50Z", D0, "en")).toBe("now");
    expect(formatRelative("2026-10-10T03:25:00Z", D0, "en")).toBe("2 days ago");
  });
});
