"use client";

import Link from "next/link";
import { useMemo } from "react";
import { Button } from "@/components/ui/button";
import { ChevronRightIcon, SearchIcon, SignOutIcon } from "@/components/ui/icons";
import { RadioGroup } from "@/components/ui/choice";
import { EmptyState } from "@/components/ui/states";
import { sectionLabelClasses } from "@/components/ui/styles";
import { cx } from "@/lib/cx";
import { useSession } from "@/lib/session/context";
import { navRoutesFromBootstrap, routesForMobileTab } from "@/lib/session/nav";
import { THEMES, type ThemePreference } from "@/lib/ui-preferences";
import { shellMessages as m } from "@/messages/shell";
import { AreaIcon } from "./nav-icons";
import { useShell } from "./shell-context";
import { THEME_LABELS } from "./user-menu";

const rowClasses =
  "flex min-h-14 items-center gap-3 border-b px-1 py-3 text-ink last:border-b-0 hover:bg-surface-sunken";

/** Phone "Work" tab: the authorised work areas from the bootstrap nav. */
export function WorkHub() {
  const { bootstrap, permissionKeys } = useSession();
  const areas = useMemo(
    () => routesForMobileTab(navRoutesFromBootstrap(bootstrap.nav, permissionKeys), "work"),
    [bootstrap.nav, permissionKeys],
  );
  return (
    <div className="flex max-w-2xl flex-col gap-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">{m.work.title}</h1>
        <p className="text-ink-muted">{m.work.intro}</p>
      </header>
      {areas.length === 0 ? (
        <EmptyState title={m.work.empty} />
      ) : (
        <ul className="rounded-lg border bg-surface px-3">
          {areas.map((route) => (
            <li key={route.id}>
              <Link href={route.path} className={rowClasses}>
                <AreaIcon id={route.id} size={22} className="shrink-0 text-forest" />
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="font-semibold">{route.label}</span>
                  {m.work.areas[route.id] ? <span className="text-sm text-ink-muted">{m.work.areas[route.id]}</span> : null}
                </span>
                <ChevronRightIcon size={18} className="shrink-0 text-ink-muted" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Phone "More" tab: settings, search, appearance and sign-out. */
export function MoreHub() {
  const { bootstrap, permissionKeys } = useSession();
  const shell = useShell();
  const settings = useMemo(
    () => routesForMobileTab(navRoutesFromBootstrap(bootstrap.nav, permissionKeys), "more"),
    [bootstrap.nav, permissionKeys],
  );

  return (
    <div className="flex max-w-2xl flex-col gap-8">
      <header className="flex flex-col gap-1">
        <h1 className="text-[28px] font-bold tracking-tight md:text-3xl">{m.more.title}</h1>
        <p className="text-ink-muted">
          {bootstrap.company.display_name}
          {bootstrap.company.is_demo ? ` · ${m.demo.title}` : ""}
        </p>
      </header>

      <ul className="rounded-lg border bg-surface px-3">
        {settings.map((route) => (
          <li key={route.id}>
            <Link href={route.path} className={rowClasses}>
              <AreaIcon id={route.id} size={22} className="shrink-0 text-forest" />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="font-semibold">{route.label}</span>
                <span className="text-sm text-ink-muted">{m.more.settingsHint}</span>
              </span>
              <ChevronRightIcon size={18} className="shrink-0 text-ink-muted" />
            </Link>
          </li>
        ))}
        <li>
          <button type="button" onClick={shell.openSearch} className={cx(rowClasses, "w-full text-start")}>
            <SearchIcon size={22} className="shrink-0 text-forest" />
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="font-semibold">{m.more.search}</span>
              <span className="text-sm text-ink-muted">{m.more.searchHint}</span>
            </span>
            <ChevronRightIcon size={18} className="shrink-0 text-ink-muted" />
          </button>
        </li>
      </ul>

      <section aria-labelledby="more-appearance" className="flex flex-col gap-3">
        <h2 id="more-appearance" className={sectionLabelClasses}>
          {m.more.appearance}
        </h2>
        <RadioGroup
          label={m.user.theme}
          value={shell.theme}
          onChange={(value) => {
            const theme = THEMES.find((t) => t === value);
            if (theme) shell.setTheme(theme as ThemePreference);
          }}
          options={THEMES.map((theme) => ({ value: theme, label: THEME_LABELS[theme] }))}
        />
      </section>

      <section aria-labelledby="more-account" className="flex flex-col gap-3">
        <h2 id="more-account" className={sectionLabelClasses}>
          {m.more.account}
        </h2>
        <p className="text-ink-muted">{m.more.signedInAs(bootstrap.user.display_name)}</p>
        <div>
          <Button
            onPress={shell.requestSignOut}
            isPending={shell.signingOut}
            pendingLabel="Signing out…"
            icon={<SignOutIcon size={18} />}
          >
            {m.user.signOut}
          </Button>
        </div>
      </section>
    </div>
  );
}
