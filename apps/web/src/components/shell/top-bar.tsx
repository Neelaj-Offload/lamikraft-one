"use client";

import Link from "next/link";
import { Button as RacButton, Dialog, DialogTrigger, Heading } from "react-aria-components";
import { IconButton } from "@/components/ui/button";
import { PanelRightIcon, SearchIcon } from "@/components/ui/icons";
import { Popover } from "@/components/ui/menu";
import type { ThemePreference } from "@/lib/ui-preferences";
import { shellMessages as m } from "@/messages/shell";
import { UserMenu } from "./user-menu";
import { Wordmark } from "./wordmark";

/** "Demo" label with an explanation on demand (frontend_verification §6, §15). */
export function DemoNotice() {
  return (
    <DialogTrigger>
      <RacButton className="flex min-h-11 items-center rounded-md px-1 outline-hidden focus-visible:focus-ring data-[focus-visible]:focus-ring pointer-fine:min-h-8">
        <span className="rounded-sm bg-warning-bg px-1.5 py-0.5 text-xs font-bold tracking-[0.06em] text-warning-text uppercase">
          {m.demo.label}
        </span>
        <span className="sr-only">: {m.demo.title}</span>
      </RacButton>
      <Popover placement="bottom start" className="max-w-80 p-4">
        <Dialog className="flex flex-col gap-1 outline-hidden">
          <Heading slot="title" className="font-bold text-ink">
            {m.demo.title}
          </Heading>
          <p className="text-sm text-ink-muted">{m.demo.body}</p>
        </Dialog>
      </Popover>
    </DialogTrigger>
  );
}

export interface TopBarProps {
  companyName: string;
  isDemo: boolean;
  userName: string;
  roleLabel: string | null;
  theme: ThemePreference;
  onThemeChange: (theme: ThemePreference) => void;
  onSearch: () => void;
  /** Whether the current screen has context for the rail; without it the toggle is not rendered. */
  hasRailContent: boolean;
  railOpen: boolean;
  onToggleRail: () => void;
  onSignOut: () => void;
}

/** The slim 56 px bar: company, Demo label, search, context panel toggle and account menu. */
export function TopBar(props: TopBarProps) {
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b bg-surface px-3 md:px-6">
      <Link href="/today" aria-label={m.homeLink} className="inline-flex min-h-11 items-center rounded-md md:hidden">
        <Wordmark />
      </Link>
      <p className="hidden min-w-0 truncate font-semibold text-ink md:block">{props.companyName}</p>
      {props.isDemo ? <DemoNotice /> : null}

      <div className="ms-auto flex items-center gap-1 md:gap-2">
        <RacButton
          onPress={props.onSearch}
          aria-keyshortcuts="/ Control+K Meta+K"
          className="hidden min-h-11 w-56 items-center gap-2 rounded-md border border-border-strong bg-canvas px-3 text-ink-muted outline-hidden focus-visible:focus-ring data-[focus-visible]:focus-ring hover:text-ink pointer-fine:min-h-9 md:flex lg:w-72"
        >
          <SearchIcon size={18} />
          <span className="flex-1 text-start">{m.search.trigger}</span>
          <kbd aria-hidden="true" className="rounded-xs border px-1.5 font-mono text-xs">
            {m.search.triggerHint}
          </kbd>
        </RacButton>
        <IconButton label={m.search.trigger} onPress={props.onSearch} className="md:hidden">
          <SearchIcon />
        </IconButton>
        {props.hasRailContent ? (
          <span className="hidden md:inline-flex">
            <IconButton
              label={props.railOpen ? m.rail.hide : m.rail.show}
              onPress={props.onToggleRail}
              aria-expanded={props.railOpen}
            >
              <PanelRightIcon />
            </IconButton>
          </span>
        ) : null}
        <UserMenu
          name={props.userName}
          roleLabel={props.roleLabel}
          theme={props.theme}
          onThemeChange={props.onThemeChange}
          onSignOut={props.onSignOut}
        />
      </div>
    </header>
  );
}
