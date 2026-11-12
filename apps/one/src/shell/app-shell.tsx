"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useOnline } from "@/lib/hooks";
import { canAccessRoute, matchRoute } from "@/lib/routes";
import { useSession } from "@/lib/session/context";
import { saveUiPreferences } from "@/lib/session/preferences";
import { useUiPoll } from "@/lib/session/use-ui-poll";
import { Banner } from "~/ui/banner";
import { ButtonLink } from "~/ui/button";
import { EmptyState } from "~/ui/empty-state";
import { LiveAnnouncer, toast, ToastRegion } from "~/ui/toast";
import { Dock } from "./dock";
import { areaOf, currentItem, visibleAreas, type NavArea } from "./nav";
import { Sidebar } from "./sidebar";
import { TopBar } from "./top-bar";

/** Moves focus to the new page's h1 after a client-side navigation, so screen readers announce it. */
function useFocusHeadingOnNavigate(): void {
  const pathname = usePathname();
  const previous = useRef(pathname);
  useEffect(() => {
    if (previous.current === pathname) return;
    previous.current = pathname;
    const heading = document.querySelector<HTMLElement>("#main h1");
    if (!heading) return;
    if (!heading.hasAttribute("tabindex")) heading.setAttribute("tabindex", "-1");
    heading.focus({ preventScroll: true });
    window.scrollTo({ top: 0 });
  }, [pathname]);
}

/** The area's screens as a pill row: shown when the sidebar is a rail, and on phones. */
function AreaNav({ areas }: { areas: readonly NavArea[] }) {
  const pathname = usePathname();
  const search = useSearchParams();
  const area = areas.find((candidate) => candidate.id === areaOf(pathname));
  if (!area || area.items.length === 0) return null;
  const current = currentItem(area, pathname, search);
  return (
    <nav className="area-nav" aria-label={`${area.label} screens`}>
      <Link href={area.href} aria-current={pathname === String(area.href) ? "page" : undefined}>
        Overview
      </Link>
      {area.items.map((item) => (
        <Link key={item.label} href={item.href} aria-current={current === item ? "page" : undefined}>
          {item.label}
        </Link>
      ))}
    </nav>
  );
}

/**
 * The signed-in frame. Desktop: a labelled left-side menu (collapsible to an icon rail) beside a
 * floating top bar and the page. Tablet: the rail. Phone: a top bar and a four-tab dock.
 * Landmarks: banner, navigation "Primary", main.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const { bootstrap, permissionKeys } = useSession();
  const pathname = usePathname();
  const online = useOnline();
  useFocusHeadingOnNavigate();

  const areas = useMemo(() => visibleAreas(bootstrap.nav, permissionKeys), [bootstrap.nav, permissionKeys]);

  const poll = useUiPoll();
  const polled = poll.data?.inbox_counts;
  const inboxCount =
    polled?.status === "ok" ? polled.value.total : bootstrap.inbox_counts.status === "ok" ? bootstrap.inbox_counts.value.total : 0;

  const [collapsed, setCollapsed] = useState(bootstrap.ui.sidebar_collapsed);
  const toggleSidebar = useCallback(() => {
    setCollapsed((current) => {
      const next = !current;
      saveUiPreferences({ sidebar_collapsed: next }).catch(() => {
        toast.warning("The menu setting applies until you reload", {
          description: "It could not be saved to your profile. Try again in a moment.",
        });
      });
      return next;
    });
  }, []);

  const route = matchRoute(pathname);
  const denied = route !== null && !canAccessRoute(route, permissionKeys);
  const canOpen = (path: string) => {
    const target = matchRoute(path);
    return target !== null && canAccessRoute(target, permissionKeys);
  };
  const canSearch = canOpen("/search");
  const roleLine = bootstrap.membership.role_names.join(", ") || "Member";

  return (
    <>
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[1200] lk-btn lk-btn-inverse">
        Skip to main content
      </a>
      <div className="app-scene" aria-hidden />
      <div className="app" data-side={collapsed ? "rail" : "full"}>
        <Suspense fallback={<aside className="side" />}>
          <Sidebar
            areas={areas}
            inboxCount={inboxCount}
            collapsed={collapsed}
            onToggle={toggleSidebar}
            companyName={bootstrap.company.display_name}
            showActivity={canOpen("/activity")}
          />
        </Suspense>
        <div className="app-main">
          <TopBar
            userName={bootstrap.user.display_name}
            userEmail={bootstrap.user.email}
            roleLine={roleLine}
            isDemo={bootstrap.company.is_demo}
            inboxCount={inboxCount}
            canSearch={canSearch}
            shortcutsEnabled={bootstrap.ui.shortcuts_enabled}
          />
          <main id="main" className="app-content" tabIndex={-1}>
            {!online ? (
              <Banner tone="amber" title="You are offline" className="mb-5">
                What you see may be out of date, and changes will not send until the connection is back.
              </Banner>
            ) : null}
            <Suspense fallback={null}>
              <AreaNav areas={areas} />
            </Suspense>
            {denied ? (
              <EmptyState
                icon="lock"
                title="This screen is not part of your role"
                text={`${route.label} needs a permission you do not have. Ask a workspace admin to add it, or head back to today's work.`}
                actions={
                  <ButtonLink href="/today" variant="inverse">
                    Back to Today
                  </ButtonLink>
                }
              />
            ) : (
              children
            )}
          </main>
        </div>
        <Dock inboxCount={inboxCount} />
      </div>
      <ToastRegion />
      <LiveAnnouncer />
    </>
  );
}
