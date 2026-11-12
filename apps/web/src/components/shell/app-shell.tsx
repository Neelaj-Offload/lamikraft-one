"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { IconButton } from "@/components/ui/button";
import { Drawer } from "@/components/ui/dialog";
import { toast } from "@/components/ui/toast";
import { SearchDialog } from "@/features/search/search-dialog";
import { cx } from "@/lib/cx";
import { ChevronLeftIcon, ChevronRightIcon, OfflineIcon } from "@/components/ui/icons";
import { useMediaQuery, useOnline } from "@/lib/hooks";
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
import { PrimaryNav, sidebarClasses, type SidebarMode } from "./primary-nav";
import { RouteGate } from "./route-gate";
import { ShellContext, type ShellContextValue } from "./shell-context";
import { SkipLink } from "./skip-link";
import { TopBar } from "./top-bar";
import { Wordmark } from "./wordmark";

const WIDE_QUERY = "(min-width: 1280px)";

/**
 * Grid columns from 768 px: the sidebar (64 px icon rail on tablets and when collapsed,
 * otherwise 208 px from 1280 px), the canvas, and the optional 300 px context rail at 1280 px.
 * One literal string per case, so exactly one `xl:grid-cols-*` class applies.
 */
export function shellGridClasses(mode: SidebarMode, railInline: boolean): string {
  if (mode === "rail") {
    return railInline ? "md:grid-cols-[64px_minmax(0,1fr)] xl:grid-cols-[64px_minmax(0,1fr)_300px]" : "md:grid-cols-[64px_minmax(0,1fr)]";
  }
  return railInline
    ? "md:grid-cols-[64px_minmax(0,1fr)] xl:grid-cols-[208px_minmax(0,1fr)_300px]"
    : "md:grid-cols-[64px_minmax(0,1fr)] xl:grid-cols-[208px_minmax(0,1fr)]";
}

/** Moves focus to the new page's h1 after client-side navigation (frontend_verification §16). */
function useFocusHeadingOnNavigate(): void {
  const pathname = usePathname();
  // Compare with the last path (not a "first run" flag) so Strict Mode's repeated effects and
  // the initial load never steal focus; only a real route change moves it.
  const previous = useRef(pathname);
  useEffect(() => {
    if (previous.current === pathname) return;
    previous.current = pathname;
    const heading = document.querySelector<HTMLElement>("#main h1");
    if (!heading) return;
    if (!heading.hasAttribute("tabindex")) heading.setAttribute("tabindex", "-1");
    heading.focus();
  }, [pathname]);
}

/**
 * The signed-in frame (build brief <design_direction>): a 208 px sidebar from 1280 px that the
 * person can collapse to a 64 px icon rail (always the rail on tablets, 768-1279 px), a slim
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
  const [sidebarCollapsed, setSidebarCollapsed] = useState(bootstrap.ui.sidebar_collapsed);
  const [railDrawerOpen, setRailDrawerOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const isWide = useMediaQuery(WIDE_QUERY, true);
  const online = useOnline();

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

  const toggleSidebar = useCallback(() => {
    const next = !sidebarCollapsed;
    setSidebarCollapsed(next);
    saveUiPreferences({ sidebar_collapsed: next }).catch(() => toast.warning(m.user.sidebarSaveFailed));
  }, [sidebarCollapsed]);

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
  // The rail only exists on screens that put record context into it (<RailContent>); elsewhere
  // there is nothing to show, so neither the column nor its toggle is rendered.
  const hasRailContent = railItems > 0;
  const railInline = railOpen && hasRailContent;
  const sidebarMode: SidebarMode = sidebarCollapsed ? "rail" : "auto";
  const sidebar = sidebarClasses[sidebarMode];
  const navId = "lk-primary-nav";

  return (
    <ShellContext value={shell}>
      <RailContext value={railSlot}>
        <div className={cx("min-h-dvh md:grid", shellGridClasses(sidebarMode, railInline))}>
          <SkipLink />
          <div
            className={cx(
              "sticky top-0 hidden h-dvh flex-col gap-6 border-e bg-surface py-4 md:flex",
              sidebarMode === "rail" ? "px-2" : "px-2 xl:px-3",
            )}
          >
            <Link
              href="/today"
              aria-label={m.homeLink}
              className={cx(
                "inline-flex min-h-11 items-center rounded-md",
                sidebarMode === "rail" ? "self-center px-2" : "self-start px-3 md:max-xl:self-center md:max-xl:px-2",
              )}
            >
              <Wordmark labelClassName={sidebar.label} />
            </Link>
            <PrimaryNav
              id={navId}
              routes={navRoutes}
              inboxCount={inboxCount}
              locale={zone.locale}
              mode={sidebarMode}
              showTooltips={sidebarCollapsed || !isWide}
            />
            <div className="mt-auto flex flex-col gap-3 border-t pt-4 text-sm">
              <div className={cx("flex flex-col gap-0.5 px-3", sidebar.wide)}>
                <span className="font-semibold text-ink">{bootstrap.user.display_name}</span>
                {roleLabel ? <span className="text-ink-muted">{roleLabel}</span> : null}
              </div>
              {/* Tablets always show the icon rail; the choice applies from 1280 px. */}
              <div className={cx("hidden xl:flex", sidebarMode === "rail" ? "justify-center" : "px-1")}>
                <IconButton
                  label={sidebarCollapsed ? m.sidebar.expand : m.sidebar.collapse}
                  onPress={toggleSidebar}
                  aria-controls={navId}
                >
                  {sidebarCollapsed ? <ChevronRightIcon /> : <ChevronLeftIcon />}
                </IconButton>
              </div>
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
              hasRailContent={hasRailContent}
              railOpen={isWide ? railInline : railDrawerOpen}
              onToggleRail={toggleRail}
              onSignOut={() => void requestSignOut()}
            />
            {online ? null : (
              <p role="status" className="flex items-center gap-2 border-b bg-warning-bg px-4 py-2 text-sm text-warning-text md:px-6">
                <OfflineIcon size={18} className="shrink-0" />
                {m.offline}
              </p>
            )}
            <main
              id="main"
              tabIndex={-1}
              className={cx(
                "@container min-w-0 flex-1 px-4 py-6 outline-hidden md:px-8 lg:px-10 lg:py-8",
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
            isOpen={railDrawerOpen && !isWide && hasRailContent}
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
