import { describe, expect, it } from "vitest";
import { announce, getAnnouncerState, subscribeAnnouncer } from "@/lib/a11y/announcer";
import { createApiClient } from "@/lib/api/client";
import { navRoutesFromBootstrap } from "@/lib/session/nav";
import { signOut } from "@/lib/session/sign-out";
import { controlsWithoutVisibleFocus, countTags, render, renderInSession, textOf } from "@/lib/test-support/render";
import { testBootstrap } from "@/lib/test-support/session";
import { shellGridClasses } from "./app-shell";
import { phoneTabs } from "./bottom-nav";
import { ComposerDock } from "./composer-dock";
import { DemoNotice, TopBar, type TopBarProps } from "./top-bar";
import { deniedRoute } from "./route-gate";
import { initials } from "./user-menu";
import { PrimaryNav } from "./primary-nav";
import { WorkHub } from "./hubs";

describe("phone tabs", () => {
  it("are Today, Inbox, Work and More when the bootstrap lists Today and Inbox", () => {
    const session = testBootstrap();
    const routes = navRoutesFromBootstrap(session.nav, session.permissions.map((p) => p.key));
    expect(phoneTabs(routes).map((tab) => [tab.label, tab.href])).toEqual([
      ["Today", "/today"],
      ["Inbox", "/inbox"],
      ["Work", "/work"],
      ["More", "/more"],
    ]);
  });

  it("omit areas the bootstrap does not list", () => {
    const routes = navRoutesFromBootstrap([{ key: "today" }], []);
    expect(phoneTabs(routes).map((tab) => tab.id)).toEqual(["today", "work", "more"]);
  });
});

describe("route gate", () => {
  it("denies areas outside the user's permissions and allows the rest", () => {
    const sales = ["sales.quote.read", "tasks.task.read"];
    expect(deniedRoute("/finance", sales)?.id).toBe("finance");
    expect(deniedRoute("/operations", sales)?.id).toBe("operations");
    expect(deniedRoute("/sales", sales)).toBeNull();
    expect(deniedRoute("/today", [])).toBeNull();
    expect(deniedRoute("/login", [])).toBeNull();
    expect(deniedRoute("/no-such-page", [])).toBeNull();
  });
});

describe("shell pieces", () => {
  it("initials for the account button", () => {
    expect(initials("Meera Iyer")).toBe("MI");
    expect(initials("Priya")).toBe("P");
    expect(initials("  ")).toBe("?");
    expect(initials("Sahil Kumar Mehta")).toBe("SM");
  });

  it("demo label is a real control that explains itself", () => {
    const html = render(<DemoNotice />);
    expect(countTags(html, "button")).toBe(1);
    expect(textOf(html)).toBe("Demo : Demo workspace");
  });

  it("composer dock pins above the phone navigation", () => {
    const html = render(
      <ComposerDock>
        <p>composer</p>
      </ComposerDock>,
    );
    expect(html).toContain("data-composer-dock");
    expect(html).toContain("max-md:fixed");
  });

  it("work hub lists only the bootstrap's work areas", () => {
    const html = renderInSession(<WorkHub />);
    expect(html).toContain('href="/sales"');
    expect(html).toContain('href="/products"');
    expect(html).not.toContain('href="/finance"');
    expect(html).toMatch(/<h1[^>]*>Work<\/h1>/);
  });
});

describe("sign-out", () => {
  const client = (status: number) =>
    createApiClient({
      baseUrl: "http://127.0.0.1:3050",
      onUnauthorized: () => undefined,
      fetch: async (request) => {
        expect(request.method).toBe("DELETE");
        expect(new URL(request.url).pathname).toBe("/api/v1/identity/session");
        return status === 204
          ? new Response(null, { status: 204 })
          : new Response(JSON.stringify({ title: "x", status, code: status === 401 ? "unauthenticated" : "internal_error" }), {
              status,
              headers: { "Content-Type": "application/problem+json" },
            });
      },
    });

  it("succeeds on 204 and when the session had already ended", async () => {
    expect(await signOut(client(204))).toEqual({ ok: true });
    expect(await signOut(client(401))).toEqual({ ok: true });
  });

  it("reports a failure so the person knows they are still signed in", async () => {
    const result = await signOut(client(500));
    expect(result.ok).toBe(false);
  });
});

describe("live announcer", () => {
  it("re-announces identical messages and ignores blanks", () => {
    const seen: number[] = [];
    const unsubscribe = subscribeAnnouncer(() => seen.push(getAnnouncerState().polite.id));
    announce("3 updates");
    announce("3 updates");
    announce("   ");
    announce("Saved", "assertive");
    unsubscribe();
    expect(seen).toHaveLength(3);
    expect(seen[0]).not.toBe(seen[1]);
    expect(getAnnouncerState().polite.message).toBe("3 updates");
    expect(getAnnouncerState().assertive.message).toBe("Saved");
  });
});

describe("collapsible sidebar (PARITY UI-07)", () => {
  const routes = navRoutesFromBootstrap(testBootstrap().nav, testBootstrap().permissions.map((p) => p.key));

  it("uses the 64 px icon rail when collapsed and on tablets, 208 px from 1280 px otherwise", () => {
    expect(shellGridClasses("rail", false)).toBe("md:grid-cols-[64px_minmax(0,1fr)]");
    expect(shellGridClasses("rail", true)).toContain("xl:grid-cols-[64px_minmax(0,1fr)_300px]");
    expect(shellGridClasses("auto", false)).toBe("md:grid-cols-[64px_minmax(0,1fr)] xl:grid-cols-[208px_minmax(0,1fr)]");
    expect(shellGridClasses("auto", true)).toContain("xl:grid-cols-[208px_minmax(0,1fr)_300px]");
  });

  it("keeps every link's name in the icon rail (visually hidden) and a visible focus ring", () => {
    const html = renderInSession(<PrimaryNav routes={routes} inboxCount={3} locale="en-IN" mode="rail" showTooltips />);
    expect(html).toMatch(/<span class="[^"]*\bsr-only\b[^"]*">Today<\/span>/);
    expect(html).toMatch(/<span class="[^"]*\bsr-only\b[^"]*">Inbox<\/span>/);
    expect(controlsWithoutVisibleFocus(html)).toEqual([]);
    const wide = renderInSession(<PrimaryNav routes={routes} inboxCount={null} locale="en-IN" mode="auto" />);
    expect(wide).toMatch(/<span class="[^"]*md:max-xl:sr-only[^"]*">Today<\/span>/);
  });
});

describe("context rail toggle", () => {
  const noop = () => {};
  const props: TopBarProps = {
    companyName: "Crown Decor (Demo)",
    isDemo: true,
    userName: "Sahil Mehta",
    roleLabel: "Management",
    theme: "system",
    onThemeChange: noop,
    onSearch: noop,
    hasRailContent: false,
    railOpen: true,
    onToggleRail: noop,
    onSignOut: noop,
  };

  it("is not rendered on screens without rail content, even when the preference is open", () => {
    const html = renderInSession(<TopBar {...props} />);
    expect(html).not.toContain("context panel");
  });

  it("is rendered with its state when the screen has rail content", () => {
    expect(renderInSession(<TopBar {...props} hasRailContent />)).toContain('aria-label="Hide context panel"');
    expect(renderInSession(<TopBar {...props} hasRailContent railOpen={false} />)).toContain('aria-label="Show context panel"');
  });
});
