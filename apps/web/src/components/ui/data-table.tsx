"use client";

import { useEffect, useId, useRef, useState, type ReactNode, type RefObject } from "react";
import { Button as RacButton, Link as RacLink } from "react-aria-components";
import { cx } from "@/lib/cx";
import { formatCount } from "@/lib/format/money";
import { useZone } from "@/lib/session/context";
import { Checkbox } from "./choice";
import {
  ariaSortFor,
  nextSortState,
  offsetRange,
  selectionSummary,
  toggleAllRows,
  toggleRow,
  type SortState,
} from "./data-table-model";
import { ArrowDownIcon, ArrowUpIcon, ChevronLeftIcon, ChevronRightIcon, SortIcon } from "./icons";
import { buttonClasses } from "./styles";

/**
 * Native semantic table (frontend_verification §13; ADR-044): <caption>, <th scope>, sortable
 * header buttons with aria-sort, right-aligned tabular numbers. Sorting, filtering and
 * pagination are server-side; this component only renders state and reports intents.
 *
 * Below 768 px the table is replaced by a purposeful list built from column priorities
 * (title, key, status, amount) whose rows link to the record, instead of sideways scrolling.
 */

export type MobileRole = "title" | "key" | "status" | "amount" | "meta";

export interface DataTableColumn<Row> {
  id: string;
  header: string;
  cell: (row: Row) => ReactNode;
  /** Money, quantities and counts: end-aligned with tabular figures. */
  numeric?: boolean;
  sortable?: boolean;
  /** Render this column's cells as row headers (<th scope="row">); usually the title column. */
  isRowHeader?: boolean;
  /** Role in the phone list; columns without one are omitted there. */
  mobile?: MobileRole;
  /**
   * Phone-list content when the whole row is a link (`rowHref`): must not contain links or
   * buttons, since interactive content cannot nest inside the row's <a>. Defaults to `cell`.
   */
  mobileCell?: (row: Row) => ReactNode;
  className?: string;
}

export interface DataTableSelection<Row> {
  selected: ReadonlySet<string>;
  onChange: (next: Set<string>) => void;
  /** Names the row in the checkbox label: "Select LK-QT-2026-0041". */
  rowLabel: (row: Row) => string;
}

export interface DataTableProps<Row> {
  caption: string;
  /** Keep the caption for screen readers only when a visible heading already names the table. */
  hideCaption?: boolean;
  columns: readonly DataTableColumn<Row>[];
  rows: readonly Row[];
  rowId: (row: Row) => string;
  /** Canonical detail URL for the row (phone list link and title cell link). */
  rowHref?: (row: Row) => string | null;
  sort?: SortState | null;
  onSortChange?: (sort: SortState) => void;
  selection?: DataTableSelection<Row>;
  /** Rendered instead of the table when there are no rows. */
  empty?: ReactNode;
  footer?: ReactNode;
  className?: string;
}

export function DataTable<Row>({
  caption,
  hideCaption = false,
  columns,
  rows,
  rowId,
  rowHref,
  sort = null,
  onSortChange,
  selection,
  empty,
  footer,
  className,
}: DataTableProps<Row>) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const overflows = useHorizontalScroll(scrollRef);
  const captionId = useId();
  if (rows.length === 0 && empty) return <div className={className}>{empty}</div>;
  const ids = rows.map(rowId);
  const summary = selection ? selectionSummary(ids, selection.selected) : "none";

  return (
    <div className={cx("flex flex-col gap-3", className)}>
      {/* A wide table that scrolls sideways is reachable by keyboard (WCAG 2.1.1; axe scrollable-region-focusable):
          the wrapper takes focus only while it actually overflows, so narrow tables add no tab stop. */}
      <div
        ref={scrollRef}
        className="hidden overflow-x-auto rounded-lg border bg-surface focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus md:block"
        {...(overflows ? { tabIndex: 0, role: "region", "aria-labelledby": captionId } : {})}
      >
        <table className="w-full border-collapse text-sm">
          <caption id={captionId} className={cx("px-4 pt-3 pb-1 text-start text-[15px] font-semibold text-ink", hideCaption && "sr-only")}>
            {caption}
          </caption>
          <thead>
            <tr className="border-b">
              {selection ? (
                <th scope="col" className="w-12 px-3 py-2 text-start">
                  <Checkbox
                    aria-label="Select all rows on this page"
                    isSelected={summary === "all"}
                    isIndeterminate={summary === "some"}
                    onChange={() => selection.onChange(toggleAllRows(ids, selection.selected))}
                  />
                </th>
              ) : null}
              {columns.map((column) => {
                const sortable = column.sortable && onSortChange;
                const ariaSort = sortable ? ariaSortFor(sort, column.id) : undefined;
                return (
                  <th
                    key={column.id}
                    scope="col"
                    aria-sort={ariaSort}
                    className={cx(
                      "px-4 py-2 text-xs font-semibold tracking-[0.04em] whitespace-nowrap text-ink-muted uppercase",
                      column.numeric ? "text-end" : "text-start",
                    )}
                  >
                    {sortable ? (
                      <RacButton
                        onPress={() => onSortChange(nextSortState(sort, column.id))}
                        className={cx(
                          "-mx-2 inline-flex min-h-11 items-center gap-1 rounded-sm px-2 uppercase hover:text-ink pointer-fine:min-h-9",
                          column.numeric && "flex-row-reverse",
                        )}
                      >
                        {column.header}
                        {ariaSort === "ascending" ? (
                          <ArrowUpIcon size={14} />
                        ) : ariaSort === "descending" ? (
                          <ArrowDownIcon size={14} />
                        ) : (
                          <SortIcon size={14} className="opacity-60" />
                        )}
                      </RacButton>
                    ) : (
                      column.header
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => {
              const id = ids[index]!;
              const isSelected = selection?.selected.has(id) ?? false;
              return (
                <tr key={id} className={cx("border-b last:border-b-0", isSelected && "bg-forest-tint")}>
                  {selection ? (
                    <td className="px-3 py-2 align-top">
                      <Checkbox
                        aria-label={`Select ${selection.rowLabel(row)}`}
                        isSelected={isSelected}
                        onChange={() => selection.onChange(toggleRow(id, selection.selected))}
                      />
                    </td>
                  ) : null}
                  {columns.map((column) => {
                    const content = column.cell(row);
                    const props = {
                      className: cx("px-4 py-3 align-top text-ink", column.numeric && "text-end tabular", column.className),
                    };
                    return column.isRowHeader ? (
                      <th key={column.id} scope="row" {...props} className={cx(props.className, "text-start font-semibold")}>
                        {content}
                      </th>
                    ) : (
                      <td key={column.id} {...props}>
                        {content}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <MobileList caption={caption} columns={columns} rows={rows} ids={ids} rowHref={rowHref} selection={selection} />
      {footer}
    </div>
  );
}

function MobileList<Row>({
  caption,
  columns,
  rows,
  ids,
  rowHref,
  selection,
}: {
  caption: string;
  columns: readonly DataTableColumn<Row>[];
  rows: readonly Row[];
  ids: readonly string[];
  rowHref?: (row: Row) => string | null;
  selection?: DataTableSelection<Row>;
}) {
  const byRole = (role: MobileRole) => columns.filter((column) => column.mobile === role);
  const [title] = byRole("title");
  const keys = byRole("key");
  const statuses = byRole("status");
  const amounts = byRole("amount");
  const metas = byRole("meta");

  return (
    <ul aria-label={caption} className="flex flex-col divide-y rounded-lg border bg-surface md:hidden">
      {rows.map((row, index) => {
        const href = rowHref?.(row) ?? null;
        // Inside a linked row, cells render their plain variant (no nested links).
        const show = (column: DataTableColumn<Row>) => (href && column.mobileCell ? column.mobileCell(row) : column.cell(row));
        const body = (
          <>
            <span className="flex items-start justify-between gap-3">
              <span className="min-w-0 font-semibold text-ink">{title ? show(title) : null}</span>
              {amounts.map((column) => (
                <span key={column.id} className="shrink-0 tabular text-ink">
                  {show(column)}
                </span>
              ))}
            </span>
            <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-muted">
              {keys.map((column) => (
                <span key={column.id} className="font-mono">
                  {show(column)}
                </span>
              ))}
              {statuses.map((column) => (
                <span key={column.id}>{show(column)}</span>
              ))}
              {metas.map((column) => (
                <span key={column.id}>
                  <span className="sr-only">{column.header}: </span>
                  {show(column)}
                </span>
              ))}
            </span>
          </>
        );
        const id = ids[index]!;
        return (
          <li key={id} className="flex items-start gap-2 px-3">
            {selection ? (
              <Checkbox
                aria-label={`Select ${selection.rowLabel(row)}`}
                isSelected={selection.selected.has(id)}
                onChange={() => selection.onChange(toggleRow(id, selection.selected))}
                className="mt-1"
              />
            ) : null}
            {href ? (
              <RacLink href={href} className="flex min-h-14 flex-1 flex-col justify-center gap-1 py-3 outline-hidden focus-visible:focus-ring-inset data-[focus-visible]:focus-ring-inset">
                {body}
              </RacLink>
            ) : (
              <div className="flex min-h-14 flex-1 flex-col justify-center gap-1 py-3">{body}</div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

type PageControl = { href: string } | { onPress: () => void };

function PageButton({ control, label, icon, iconAfter }: { control: PageControl; label: string; icon?: ReactNode; iconAfter?: ReactNode }) {
  const className = buttonClasses("secondary", "sm");
  if ("href" in control) {
    return (
      <RacLink href={control.href} className={className}>
        {icon}
        <span>{label}</span>
        {iconAfter}
      </RacLink>
    );
  }
  return (
    <RacButton onPress={control.onPress} className={className}>
      {icon}
      <span>{label}</span>
      {iconAfter}
    </RacButton>
  );
}

/** Offset pages: "Showing 51–100 of 312" with Previous / Next (real totals only). */
export function OffsetPagination({
  total,
  limit,
  offset,
  shown,
  control,
  label = "Pagination",
}: {
  total: number;
  limit: number;
  offset: number;
  shown: number;
  /** Builds the control for a target offset: a URL (preferred, keeps state in the URL) or a handler. */
  control: (offset: number) => PageControl;
  label?: string;
}) {
  const { locale } = useZone();
  const range = offsetRange(total, limit, offset, shown);
  return (
    <nav aria-label={label} className="flex flex-wrap items-center justify-between gap-3">
      <p className="text-sm text-ink-muted tabular" aria-live="polite">
        {range.total === 0
          ? "No results"
          : `Showing ${formatCount(range.first, locale)}–${formatCount(range.last, locale)} of ${formatCount(range.total, locale)}`}
      </p>
      <div className="flex gap-2">
        {range.previousOffset !== null ? (
          <PageButton control={control(range.previousOffset)} label="Previous" icon={<ChevronLeftIcon size={16} />} />
        ) : null}
        {range.nextOffset !== null ? (
          <PageButton control={control(range.nextOffset)} label="Next" iconAfter={<ChevronRightIcon size={16} />} />
        ) : null}
      </div>
    </nav>
  );
}

/** Keyset pages (`CursorPage{items,next_cursor,limit}`): Next while a cursor exists, plus First page. */
export function KeysetPagination({
  next,
  first,
  label = "Pagination",
}: {
  /** null when there is no next page. */
  next: PageControl | null;
  /** null on the first page. */
  first: PageControl | null;
  label?: string;
}) {
  if (!next && !first) return null;
  return (
    <nav aria-label={label} className="flex flex-wrap items-center justify-end gap-2">
      {first ? <PageButton control={first} label="First page" icon={<ChevronLeftIcon size={16} />} /> : null}
      {next ? <PageButton control={next} label="Next page" iconAfter={<ChevronRightIcon size={16} />} /> : null}
    </nav>
  );
}

/** Whether the element scrolls horizontally (measured after mount and on resize). */
function useHorizontalScroll(ref: RefObject<HTMLDivElement | null>): boolean {
  const [overflows, setOverflows] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setOverflows(el.scrollWidth > el.clientWidth + 1);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    if (el.firstElementChild) observer.observe(el.firstElementChild);
    return () => observer.disconnect();
  }, [ref]);
  return overflows;
}
