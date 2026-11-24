"use client";

import Link from "next/link";
import { useId, useMemo, type CSSProperties } from "react";
import { useSession } from "@/lib/session/context";
import { riseIndex } from "~/lib/motion";
import { Page, PageHeader } from "~/shell/page";
import { visibleAreas, type NavArea, type NavItem } from "~/shell/nav";
import { ButtonLink, EmptyState, GlassPanel, Icon } from "~/ui";

/** The areas that are "work" (the phone's Work tab): Today, Inbox and Settings have their own tabs. */
const WORK_AREAS: ReadonlySet<NavArea["id"]> = new Set(["sales", "products", "operations", "finance"]);

/**
 * Work: every screen this person may open, as one flat list under plain area headings. It is the
 * phone's way into the areas (the dock has no room for them) and a site map on larger screens.
 * Nothing expands or nests: a heading, its one-line purpose, then the screens.
 */
export function WorkScreen() {
  const { bootstrap, permissionKeys } = useSession();
  const areas = useMemo(
    () => visibleAreas(bootstrap.nav, permissionKeys).filter((area) => WORK_AREAS.has(area.id)),
    [bootstrap.nav, permissionKeys],
  );

  return (
    <Page>
      <PageHeader
        display
        title="Work"
        lead="Every screen your role can open, by area."
      />
      {areas.length === 0 ? (
        <GlassPanel padding="lg" className="rise" style={riseIndex(1) as CSSProperties}>
          <EmptyState
            icon="grid"
            title="No work areas yet"
            text="Your role does not open Sales, Products, Operations or Finance. Today and Inbox still show what needs you."
            actions={
              <ButtonLink href="/today" variant="inverse">
                Go to Today
              </ButtonLink>
            }
          />
        </GlassPanel>
      ) : (
        <div className="grid grid-cols-1 items-start gap-5 xl:grid-cols-2">
          {areas.map((area, index) => (
            <AreaGroup key={area.id} area={area} index={index} />
          ))}
        </div>
      )}
    </Page>
  );
}

function AreaGroup({ area, index }: { area: NavArea; index: number }) {
  const headingId = useId();
  // An area whose screens are all outside this role still has its own landing screen.
  const items: readonly NavItem[] = area.items.length > 0 ? area.items : [{ label: area.label, icon: area.icon, href: area.href }];
  return (
    <GlassPanel as="section" padding="md" className="rise" style={riseIndex(index + 1) as CSSProperties} aria-labelledby={headingId}>
      <div className="flex items-center gap-4 px-1 pb-4">
        <span className="grid size-11 flex-none place-items-center rounded-md bg-sand-soft text-ink" aria-hidden>
          <Icon name={area.icon} size={22} />
        </span>
        <div className="flex min-w-0 flex-col gap-0.5">
          <h2 id={headingId} className="t-h3">
            {area.label}
          </h2>
          <p className="t-body-sm text-ink-3">{area.blurb}</p>
        </div>
      </div>
      <ul className="hairline-top m-0 grid list-none grid-cols-1 gap-x-3 p-0 pt-2 sm:grid-cols-2">
        {items.map((item) => (
          <li key={item.label}>
            <Link
              href={item.href}
              className="flex min-h-12 items-center gap-3 rounded-sm px-2 text-ink no-underline transition-colors hover:bg-sand-soft"
            >
              <Icon name={item.icon} size={18} className="flex-none text-ink-3" />
              <span className="t-body min-w-0 flex-1 truncate font-medium">{item.label}</span>
              <Icon name="chevronRight" size={16} className="flex-none text-ink-4" />
            </Link>
          </li>
        ))}
      </ul>
    </GlassPanel>
  );
}
