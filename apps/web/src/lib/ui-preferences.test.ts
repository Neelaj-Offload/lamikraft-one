import { describe, expect, it } from "vitest";
import {
  DEFAULT_UI_PREFERENCES,
  htmlThemeAttributes,
  parseUiPreferences,
  serializeUiPreferences,
} from "./ui-preferences";

describe("parseUiPreferences", () => {
  it("returns defaults when the cookie is absent or empty", () => {
    expect(parseUiPreferences(undefined)).toEqual(DEFAULT_UI_PREFERENCES);
    expect(parseUiPreferences(null)).toEqual(DEFAULT_UI_PREFERENCES);
    expect(parseUiPreferences("")).toEqual(DEFAULT_UI_PREFERENCES);
  });

  it("reads theme and motion", () => {
    expect(parseUiPreferences("theme=dark&motion=reduced")).toEqual({ theme: "dark", motion: "reduced" });
    expect(parseUiPreferences("motion=full&theme=light")).toEqual({ theme: "light", motion: "full" });
  });

  it("accepts the quoted and percent-encoded forms servers emit", () => {
    expect(parseUiPreferences('"theme=dark&motion=reduced"')).toEqual({ theme: "dark", motion: "reduced" });
    expect(parseUiPreferences("theme%3Ddark%26motion%3Dreduced")).toEqual({ theme: "dark", motion: "reduced" });
  });

  it("falls back per field for invalid or malformed values", () => {
    expect(parseUiPreferences("theme=purple&motion=reduced")).toEqual({ theme: "system", motion: "reduced" });
    expect(parseUiPreferences("theme=dark&motion=wild")).toEqual({ theme: "dark", motion: "full" });
    expect(parseUiPreferences("%E0%A4%A")).toEqual(DEFAULT_UI_PREFERENCES);
  });

  it("round-trips through serializeUiPreferences", () => {
    const prefs = { theme: "dark", motion: "reduced" } as const;
    expect(parseUiPreferences(serializeUiPreferences(prefs))).toEqual(prefs);
  });
});

describe("htmlThemeAttributes", () => {
  it("omits data-theme for system so the media query decides", () => {
    expect(htmlThemeAttributes({ theme: "system", motion: "full" })).toEqual({ "data-motion": "full" });
  });

  it("sets an explicit theme", () => {
    expect(htmlThemeAttributes({ theme: "dark", motion: "reduced" })).toEqual({
      "data-theme": "dark",
      "data-motion": "reduced",
    });
  });
});
