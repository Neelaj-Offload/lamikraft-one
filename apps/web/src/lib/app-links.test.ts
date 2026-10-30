import { describe, expect, it } from "vitest";

import { appLinkFor } from "./app-links";

const ID = "01a18baa-80e8-7324-8318-09a76824077e";

describe("appLinkFor", () => {
  it("maps server resource paths to this app's routes", () => {
    expect(appLinkFor(`/approvals/${ID}`)).toBe(`/inbox/approvals/${ID}`);
    expect(appLinkFor(`/inbox/${ID}`)).toBe(`/inbox?task=${ID}`);
    expect(appLinkFor(`/sales/messages/${ID}`)).toBe(`/sales/customer-messages?message=${ID}`);
    expect(appLinkFor(`/sales/quotes/${ID}`)).toBe(`/sales/quotes/${ID}`);
  });

  it("drops paths that would leave the app", () => {
    expect(appLinkFor("https://example.test/x")).toBeNull();
    expect(appLinkFor("//example.test/x")).toBeNull();
  });
});
