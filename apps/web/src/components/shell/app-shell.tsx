"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Drawer } from "@/components/ui/dialog";
import { toast } from "@/components/ui/toast";
import { SearchDialog } from "@/features/search/search-dialog";
import { cx } from "@/lib/cx";
import { useMediaQuery } from "@/lib/hooks";
import { useSession } from "@/lib/session/context";
import { navRoutesFromBootstrap } from "@/lib/session/nav";
import { applyThemeLocally, saveUiPreferences } from "@/lib/session/preferences";
import { signOut } from "@/lib/session/sign-out";
import { useUiPoll } from "@/lib/session/use-ui-poll";
import { isSearchShortcut } from "@/lib/shortcuts";
import type { ThemePreference } from "@/lib/ui-preferences";
import { shellMessages as m } from "@/messages/shell";
import { BottomNav } from "./bottom-nav";
import { RailBody, RailContext, type RailSlot } from "./context-rail";
import { PrimaryNav } from "./primary-nav";
import { RouteGate } from "./route-gate";
import { ShellContext, type ShellContextValue } from "./shell-context";
import { SkipLink } from "./skip-link";
import { TopBar } from "./top-bar";
import { Wordmark } from "./wordmark";

const WIDE_QUERY = "(min-width: 1280px)";

/** Moves focus to the new page's h1 after client-side navigation (frontend_verification §16). */
function useFocusHeadingOnNavigate(): void {
  const pathname = usePathname();
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    const heading = document.querySelector<HTMLElement>("#main h1");
    if (!heading) return;
    if (!heading.hasAttribute("tabindex")) heading.setAttribute("tabindex", "-1");
    heading.focus();
  }, [pathname]);
}

/**
 * The signed-in frame (build brief <design_direction>): 208 px sidebar from 768 px, a slim
 * top bar, the main canvas and an optional 300 px context rail at ≥1280 px (an overlay drawer
 * on tablets); below 768 px a bottom navigation (Today, Inbox, Work, More) replaces the
 * sidebar. Landmarks: banner, navigation "Primary", main, complementary "Context".
 */
export function AppShell({ children }: { children: ReactNode }) {
  const { bootstrap, permissionKeys, zone } = useSession();
  const queryClient = useQueryClient();
  const navRoutes = useMemo(() => navRoutesFromBootstrap(bootstrap.nav, permissionKeys), [bootstrap.nav, permissionKeys]);

  const poll = useUiPoll();
  const polledCounts = poll.data?.inbox_counts;
  const inboxCount =
    polledCounts?.status === "ok"
      ? polledCounts.value.total
      : bootstrap.inbox_counts.status === "ok"
        ? bootstrap.inbox_counts.value.total
        : null;

  const [searchOpen, setSearchOpen] = useState(false);
  const [theme, setThemeState] = useState<ThemePreference>(bootstrap.ui.theme);
  const [railOpen, setRailOpen] = useState(bootstrap.ui.context_rail_open);
  const [railDrawerOpen, setRailDrawerOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const isWide = useMediaQuery(WIDE_QUERY, true);

  const [railTarget, setRailTarget] = useState<HTMLElement | null>(null);
  const [railItems, setRailItems] = useState(0);
  const register = useCallback(() => {
    setRailItems((count) => count + 1);
    return () => setRailItems((count) => count - 1);
  }, []);
  const railSlot = useMemo<RailSlot>(() => ({ target: railTarget, register }), [railTarget, register]);

  useFocusHeadingOnNavigate();

  const shortcutsEnabled = bootstrap.ui.shortcuts_enabled;
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (isSearchShortcut(event, { shortcutsEnabled })) {
        event.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [shortcutsEnabled]);

  const setTheme = useCallback((next: ThemePreference) => {
    setThemeState(next);
    applyThemeLocally(next);
    saveUiPreferences({ theme: next }).catch(() => toast.warning(m.user.themeSaveFailed));
  }, []);

  const toggleRail = useCallback(() => {
    if (!isWide) {
      setRailDrawerOpen(true);
      return;
    }
    const next = !railOpen;
    setRailOpen(next);
    saveUiPreferences({ context_rail_open: next }).catch(() => toast.warning(m.user.railSaveFailed));
  }, [isWide, railOpen]);

  const requestSignOut = useCallback(async () => {
    setSigningOut(true);
    const result = await signOut();
    if (result.ok) {
      queryClient.clear();
      // A full load drops every cached query and component state of the old session.
      window.location.replace("/login");
      return;
    }
    setSigningOut(false);
    toast.error(m.user.signOutFailed);
  }, [queryClient]);

  const shell = useMemo<ShellContextValue>(
    () => ({
      openSearch: () => setSearchOpen(true),
      theme,
      setTheme,
      requestSignOut: () => void requestSignOut(),
      signingOut,
    }),
    [theme, setTheme, requestSignOut, signingOut],
  );

  const roleLabel = bootstrap.membership.role_names.join(", ") || null;
  const railInline = railOpen;

  return (
    <ShellContext value={shell}>
      <RailContext value={railSlot}>
        <div
          className={cx(
            "min-h-dvh md:grid md:grid-cols-[208px_minmax(0,1fr)]",
            railInline && "xl:grid-cols-[208px_minmax(0,1fr)_300px]",
          )}
        >
          <SkipLink />
          <div className="sticky top-0 hidden h-dvh flex-col gap-6 border-e bg-surface px-3 py-4 md:flex">
            <Link href="/today" aria-label={m.homeLink} className="inline-flex min-h-11 items-center self-start rounded-md px-3">
              <Wordmark />
            </Link>
            <PrimaryNav routes={navRoutes} inboxCount={inboxCount} locale={zone.locale} />
            <div className="mt-auto flex flex-col gap-0.5 border-t px-3 pt-4 text-sm">
              <span className="font-semibold text-ink">{bootstrap.user.display_name}</span>
              {roleLabel ? <span className="text-ink-muted">{roleLabel}</span> : null}
            </div>
          </div>

          <div className="flex min-w-0 flex-col">
            <TopBar
              companyName={bootstrap.company.display_name}
              isDemo={bootstrap.company.is_demo || bootstrap.membership.is_demo}
              userName={bootstrap.user.display_name}
              roleLabel={roleLabel}
              theme={theme}
              onThemeChange={setTheme}
              onSearch={() => setSearchOpen(true)}
              railOpen={isWide ? railOpen : railDrawerOpen}
              onToggleRail={toggleRail}
              onSignOut={() => void requestSignOut()}
            />
            <main
              id="main"
              tabIndex={-1}
              className={cx(
                "@container min-w-0 flex-1 px-4 py-6 outline-none md:px-8 lg:px-10 lg:py-8",
                "max-md:pb-[calc(3.5rem+env(safe-area-inset-bottom)+1.5rem)]",
                "max-md:has-[[data-composer-dock]]:pb-[calc(3.5rem+env(safe-area-inset-bottom)+10rem)]",
              )}
            >
              <RouteGate permissionKeys={permissionKeys}>{children}</RouteGate>
            </main>
          </div>

          {railInline ? (
            <aside
              id="lk-context-rail"
              aria-label={m.contextRail}
              className="sticky top-0 hidden h-dvh flex-col gap-4 overflow-y-auto border-s bg-surface px-4 py-4 xl:flex"
            >
              {isWide ? <RailBody hasContent={railItems > 0} setTarget={setRailTarget} /> : null}
            </aside>
          ) : null}

          <Drawer
            title={m.contextRail}
            isOpen={railDrawerOpen && !isWide}
            onOpenChange={setRailDrawerOpen}
          >
            <RailBody hasContent={railItems > 0} setTarget={setRailTarget} />
          </Drawer>

          <BottomNav navRoutes={navRoutes} inboxCount={inboxCount} locale={zone.locale} />
          <SearchDialog isOpen={searchOpen} onOpenChange={setSearchOpen} />
        </div>
      </RailContext>
    </ShellContext>
  );
}
