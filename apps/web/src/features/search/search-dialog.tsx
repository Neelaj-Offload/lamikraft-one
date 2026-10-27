"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { useState } from "react";
import {
  Autocomplete,
  Dialog,
  Header,
  Menu,
  MenuItem,
  MenuSection,
  Modal,
  ModalOverlay,
  Heading,
} from "react-aria-components";
import { IconButton } from "@/components/ui/button";
import { CloseIcon } from "@/components/ui/icons";
import { SearchField } from "@/components/ui/search-field";
import { ErrorState } from "@/components/ui/states";
import { listItemClasses, sectionLabelClasses } from "@/components/ui/styles";
import { api, requestUntyped } from "@/lib/api/client";
import { isEndpointUnavailable } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { cx } from "@/lib/cx";
import { useDebouncedValue } from "@/lib/hooks";
import { shellMessages as m } from "@/messages/shell";
import { parseSearchResponse } from "./parse";
import type { SearchResponse } from "./types";

export const SEARCH_MIN_CHARS = 2;
export const SEARCH_DEBOUNCE_MS = 250;

export async function fetchSearch(q: string, signal?: AbortSignal): Promise<SearchResponse> {
  const raw = await requestUntyped<unknown>(api, "get", "/api/v1/search", {
    params: { query: { q, per_group: 5 } },
    signal,
  });
  return parseSearchResponse(raw, q);
}

function hitId(group: string, path: string): string {
  return `${group}|${path}`;
}

/** The status line under the field (also the live region announcing results). */
export function searchStatus(
  q: string,
  state: { isFetching: boolean; data: SearchResponse | undefined; isError: boolean },
): string {
  if (q.length < SEARCH_MIN_CHARS) return m.search.tooShort;
  if (state.isError) return "";
  if (state.isFetching && !state.data) return m.search.searching;
  if (!state.data) return "";
  const count = state.data.groups.reduce((sum, group) => sum + group.items.length, 0);
  return count === 0 ? m.search.noResults(q) : m.search.resultsAnnouncement(count);
}

/**
 * Global search (frontend_verification §12): opened by "/" or Ctrl/Cmd+K, debounced 250 ms,
 * at least 2 characters, stale requests aborted (TanStack Query passes an AbortSignal),
 * results grouped by type and permission-filtered by the server. Arrow keys move through
 * results while typing; Enter opens the canonical URL.
 */
export function SearchDialog({ isOpen, onOpenChange }: { isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const router = useRouter();
  const [text, setText] = useState("");
  const q = useDebouncedValue(text.trim(), SEARCH_DEBOUNCE_MS);
  const enabled = isOpen && q.length >= SEARCH_MIN_CHARS;

  const query = useQuery({
    queryKey: queryKeys.search.query(q),
    queryFn: ({ signal }) => fetchSearch(q, signal),
    enabled,
    staleTime: 30_000,
    placeholderData: (previous) => previous,
  });

  const unavailable = query.isError && isEndpointUnavailable(query.error);
  const groups = enabled && query.data ? query.data.groups : [];
  const pathById = new Map(groups.flatMap((group) => group.items.map((hit) => [hitId(group.group, hit.path), hit.path] as const)));
  const status = searchStatus(q, { isFetching: query.isFetching, data: enabled ? query.data : undefined, isError: query.isError });

  const close = () => {
    onOpenChange(false);
    setText("");
  };

  return (
    <ModalOverlay
      isOpen={isOpen}
      onOpenChange={(open) => (open ? onOpenChange(true) : close())}
      isDismissable
      className="fixed inset-0 z-50 flex items-start justify-center bg-scrim p-0 entering:animate-overlay-in exiting:animate-overlay-out md:p-6 md:pt-[12vh]"
    >
      <Modal className="flex max-h-dvh w-full flex-col overflow-hidden bg-surface shadow-lg outline-hidden entering:animate-pop-in exiting:animate-pop-out md:max-h-[70vh] md:max-w-xl md:rounded-xl md:border">
        <Dialog aria-labelledby="lk-search-title" className="flex min-h-0 flex-1 flex-col outline-hidden">
          <div className="flex items-center justify-between gap-2 px-4 pt-3">
            <Heading id="lk-search-title" slot="title" className="text-base font-bold">
              {m.search.dialogTitle}
            </Heading>
            <IconButton label="Close search" onPress={close}>
              <CloseIcon size={18} />
            </IconButton>
          </div>
          <Autocomplete inputValue={text} onInputChange={setText}>
            <div className="px-4 pt-1 pb-2">
              <SearchField label={m.search.fieldLabel} hideLabel placeholder={m.search.placeholder} autoFocus />
              <p className="mt-2 min-h-5 text-sm text-ink-muted" role="status" aria-live="polite">
                {status}
              </p>
            </div>
            {unavailable ? (
              <div className="px-4 pb-4">
                <p className="font-semibold text-ink">{m.search.unavailableTitle}</p>
                <p className="text-sm text-ink-muted">{m.search.unavailableBody}</p>
              </div>
            ) : query.isError && enabled ? (
              <div className="px-4 pb-4">
                <ErrorState error={query.error} what="search results" onRetry={() => void query.refetch()} compact headingLevel={3} />
              </div>
            ) : (
              <Menu
                aria-label="Search results"
                className={cx("min-h-0 flex-1 overflow-y-auto px-2 pb-3 outline-hidden", groups.length === 0 && "hidden")}
                onAction={(key) => {
                  const path = pathById.get(String(key));
                  if (!path) return;
                  close();
                  router.push(path as Route);
                }}
              >
                {groups.map((group) => (
                  <MenuSection key={group.group} id={group.group} className="pt-2">
                    <Header className={cx(sectionLabelClasses, "flex justify-between px-3 pb-1")}>
                      <span>{group.group}</span>
                      {group.total > group.items.length ? <span className="normal-case tracking-normal">{group.total}</span> : null}
                    </Header>
                    {group.items.map((hit) => (
                      <MenuItem key={hit.path} id={hitId(group.group, hit.path)} textValue={hit.title} className={cx(listItemClasses, "flex-col items-start justify-center gap-0 py-1.5")}>
                        <span className="font-medium text-ink">{hit.title}</span>
                        {hit.subtitle ? <span className="text-sm text-ink-muted">{hit.subtitle}</span> : null}
                      </MenuItem>
                    ))}
                  </MenuSection>
                ))}
              </Menu>
            )}
          </Autocomplete>
          <p className="hidden border-t px-4 py-2 text-xs text-ink-muted md:block">{m.search.shortcutHint}</p>
        </Dialog>
      </Modal>
    </ModalOverlay>
  );
}
