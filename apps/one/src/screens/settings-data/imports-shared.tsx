import type { Route } from "next";
import type { ImportType } from "@/features/imports/api";
import type { Crumb } from "~/shell/page";
import { lookOf, SETTINGS_CRUMBS, StatusBadge, type StatusLook } from "./shared";

/** Names, statuses and links the import screens share. No directive: usable from server and client files. */

export const IMPORT_PAGE_SIZE = 25;

export const IMPORTS_CRUMBS: readonly Crumb[] = [...SETTINGS_CRUMBS, { label: "Imports", href: "/settings/imports" }];

export const IMPORT_TYPE_LABEL: Record<ImportType, string> = {
  category_taxonomy: "Categories",
  products_master: "Products",
  pricing: "Prices",
  packaging: "Packaging",
  specifications: "Specifications",
  media: "Media",
  lookup_reference: "Lookup reference",
};

export const importTypeLabel = (type: string) => IMPORT_TYPE_LABEL[type as ImportType] ?? type.replace(/_/g, " ");

const STATUS: Record<string, StatusLook> = {
  parsed: { label: "Waiting for mapping", tone: "amber" },
  validated: { label: "Ready to review", tone: "cobalt" },
  committing: { label: "Writing", tone: "cobalt" },
  committed: { label: "Written", tone: "leaf" },
  commit_failed: { label: "Writing stopped", tone: "ember" },
  cancelled: { label: "Cancelled", tone: "neutral" },
  rolled_back: { label: "Rolled back", tone: "neutral" },
  partially_rolled_back: { label: "Partly rolled back", tone: "amber" },
};

export function ImportStatus({ status, size }: { status: string; size?: "sm" }) {
  return <StatusBadge look={lookOf(STATUS, status)} size={size} />;
}

/** The history list's URL: type filter and page offset; the defaults stay out of it. */
export function importsHref(importType: string | null, offset = 0): Route {
  const query = new URLSearchParams();
  if (importType) query.set("type", importType);
  if (offset > 0) query.set("offset", String(offset));
  const text = query.toString();
  return (text ? `/settings/imports?${text}` : "/settings/imports") as Route;
}

export const importHref = (jobId: string) => `/settings/imports/${encodeURIComponent(jobId)}` as Route;

/** Read from the URL on the server: an unknown type is passed through (the server answers with nothing), offsets snap to pages. */
export function importsStateFrom(search: Record<string, string | string[] | undefined>): { importType: string | null; offset: number } {
  const type = typeof search.type === "string" ? search.type.slice(0, 40) : "";
  const raw = Number.parseInt(typeof search.offset === "string" ? search.offset : "0", 10);
  const offset = Number.isFinite(raw) && raw > 0 ? raw - (raw % IMPORT_PAGE_SIZE) : 0;
  return { importType: type || null, offset };
}
