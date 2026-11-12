import type { Route } from "next";
import Link from "next/link";
import { useId, type ReactNode } from "react";
import { cx } from "@/lib/cx";
import { EmptyState } from "~/ui/empty-state";
import { Skeleton, SkeletonRows } from "~/ui/skeleton";
import { Icon, type IconName } from "./icon";

/*
 * The list workhorse. A semantic <table> from 768px; below that each row becomes a stacked card in
 * one list (or the table scrolls sideways with `mobile="scroll"`). Sorting, filtering and paging
 * are the caller's: this component renders state and reports intent.
 *
 * It has no "use client" directive on purpose. A server page can render it with `rowHref` and
 * `sortHref` (plain links, state in the URL); a client screen can also pass `onSort` and
 * `onRowAction`.
 */

export interface Column<Row> {
  /** Stable id; also what `sort.key`, `sortHref` and `onSort` refer to. */
  key: string;
  header: ReactNode;
  cell: (row: Row) => ReactNode;
  /** Money, quantities and counts: right-aligned with tabular figures. */
  numeric?: boolean;
  /** The cell that names the row. It carries the row's link and is the card title on phones. Defaults to the first column. */
  primary?: boolean;
  /** A CSS width for the column ("120px", "20%"). */
  width?: string;
  sortable?: boolean;
  /** Leave this column out of the phone card. */
  hideOnMobile?: boolean;
  /** Label for the value on the phone card, when `header` is not plain text or is too long. */
  mobileLabel?: string;
}

export interface SortState {
  key: string;
  dir: "asc" | "desc";
}

export interface DataTableProps<Row> {
  /** Names the table for screen readers ("Quotations"). */
  label: string;
  columns: readonly Column<Row>[];
  rows: readonly Row[];
  rowKey: (row: Row) => string;
  /** Where a row leads. The whole row (or card) becomes the link target. */
  rowHref?: (row: Row) => Route;
  /** Called when a row is activated, for rows that open a drawer instead of navigating. */
  onRowAction?: (row: Row) => void;
  sort?: SortState;
  /** Sort as a link, keeping the state in the URL. Returns the URL that sorts by this column. */
  sortHref?: (key: string) => Route;
  /** Sort as a handler. */
  onSort?: (key: string) => void;
  dense?: boolean;
  /** Shows placeholder rows shaped like the columns instead of `rows`. */
  loading?: boolean;
  skeletonRows?: number;
  /** Shown instead of the table when there are no rows. Say why it is empty and what to do next. */
  empty?: ReactNode;
  /** Under the table: counts on one side, paging on the other (see `TableFooter`). */
  footer?: ReactNode;
  /** `rowKey` of the row that is open in a side panel. */
  selectedKey?: string;
  /** Under 768px: `cards` (default) stacks each row as a card, `scroll` keeps the table and scrolls sideways. */
  mobile?: "cards" | "scroll";
  /** Caps the height ("480px"); the body then scrolls under a sticky header. */
  maxHeight?: string;
  className?: string;
}

const BAR_WIDTHS = ["72%", "48%", "64%", "40%", "56%"] as const;

function SortControl({
  column,
  active,
  href,
  onSort,
}: {
  column: { key: string; header: ReactNode };
  active: SortState["dir"] | null;
  href?: Route;
  onSort?: (key: string) => void;
}) {
  const body = (
    <>
      {column.header}
      <Icon name={active === "asc" ? "chevronUp" : active === "desc" ? "chevronDown" : "sort"} size={12} />
    </>
  );
  if (href) {
    return (
      <Link href={href} className="lk-th-sort" scroll={false}>
        {body}
      </Link>
    );
  }
  return (
    <button type="button" className="lk-th-sort" onClick={onSort ? () => onSort(column.key) : undefined}>
      {body}
    </button>
  );
}

/** The single control stretched over a row or card. It is named by the row's primary cell. */
function RowControl({
  href,
  onAction,
  labelledBy,
}: {
  href?: Route;
  onAction?: () => void;
  labelledBy: string;
}) {
  if (href) return <Link href={href} className="lk-row-link" aria-labelledby={labelledBy} />;
  if (onAction) return <button type="button" className="lk-row-link" aria-labelledby={labelledBy} onClick={onAction} />;
  return null;
}

export function DataTable<Row>({
  label,
  columns,
  rows,
  rowKey,
  rowHref,
  onRowAction,
  sort,
  sortHref,
  onSort,
  dense = false,
  loading = false,
  skeletonRows = 6,
  empty,
  footer,
  selectedKey,
  mobile = "cards",
  maxHeight,
  className,
}: DataTableProps<Row>) {
  const baseId = useId();
  const primaryKey = (columns.find((column) => column.primary) ?? columns[0])?.key;
  const interactive = Boolean(rowHref || onRowAction);
  const cardFacts = columns.filter((column) => column.key !== primaryKey && !column.hideOnMobile);
  const primaryColumn = columns.find((column) => column.key === primaryKey);

  if (!loading && rows.length === 0) {
    return (
      <div className={cx("lk-table-wrap", className)}>
        <div className="lk-table-empty">
          {empty ?? <EmptyState compact title="Nothing to show" text="There are no rows here yet." />}
        </div>
        {footer ? <div className="lk-table-foot">{footer}</div> : null}
      </div>
    );
  }

  // A region that can scroll must be reachable by keyboard; cards on phones never scroll sideways.
  const scrolls = mobile === "scroll" || Boolean(maxHeight);

  return (
    <div
      className={cx("lk-table-wrap", className)}
      data-mobile={mobile}
      style={maxHeight ? { maxHeight } : undefined}
      {...(scrolls ? { tabIndex: 0, role: "region", "aria-label": `${label}, scrollable` } : {})}
    >
      {loading ? (
        <span className="sr-only" role="status">
          Loading {label}
        </span>
      ) : null}
      <table
        className={cx("lk-table", dense && "lk-table-dense", maxHeight ? "lk-table-sticky" : null)}
        aria-label={label}
        aria-busy={loading || undefined}
      >
        <thead>
          <tr>
            {columns.map((column) => {
              const active = sort && sort.key === column.key ? sort.dir : null;
              const canSort = column.sortable && Boolean(sortHref || onSort);
              return (
                <th
                  key={column.key}
                  scope="col"
                  className={cx(column.numeric && "lk-th-num")}
                  aria-sort={active ? (active === "asc" ? "ascending" : "descending") : undefined}
                  style={column.width ? { width: column.width } : undefined}
                >
                  {canSort ? (
                    <SortControl column={column} active={active} href={sortHref?.(column.key)} onSort={onSort} />
                  ) : (
                    column.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {loading
            ? Array.from({ length: skeletonRows }, (_, rowIndex) => (
                <tr key={rowIndex} aria-hidden="true">
                  {columns.map((column, columnIndex) => (
                    <td key={column.key} className={cx(column.numeric && "lk-td-num")}>
                      <Skeleton
                        width={column.numeric ? "56px" : BAR_WIDTHS[(rowIndex + columnIndex * 2) % BAR_WIDTHS.length]}
                        height={12}
                        style={{ marginBlock: 4 }}
                      />
                    </td>
                  ))}
                </tr>
              ))
            : rows.map((row, rowIndex) => {
                const key = rowKey(row);
                const nameId = `${baseId}-t${rowIndex}`;
                return (
                  <tr key={key} aria-selected={selectedKey === key || undefined}>
                    {columns.map((column) => {
                      const isPrimary = column.key === primaryKey;
                      return (
                        <td key={column.key} className={cx(isPrimary && "lk-td-primary", column.numeric && "lk-td-num")}>
                          {isPrimary && interactive ? (
                            <>
                              <div id={nameId}>{column.cell(row)}</div>
                              <RowControl
                                href={rowHref?.(row)}
                                onAction={onRowAction ? () => onRowAction(row) : undefined}
                                labelledBy={nameId}
                              />
                            </>
                          ) : (
                            column.cell(row)
                          )}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
        </tbody>
      </table>

      {mobile === "cards" ? (
        loading ? (
          <div className="lk-cardlist lk-table-empty">
            <SkeletonRows rows={Math.min(skeletonRows, 4)} columns={2} />
          </div>
        ) : (
          <ul className="lk-cardlist" aria-label={label}>
            {rows.map((row, rowIndex) => {
              const key = rowKey(row);
              const nameId = `${baseId}-c${rowIndex}`;
              return (
                <li key={key} className="lk-cardlist-item" aria-current={selectedKey === key ? "true" : undefined}>
                  <div className="lk-cardlist-title">
                    <div id={nameId}>{primaryColumn?.cell(row)}</div>
                    {interactive ? (
                      <RowControl
                        href={rowHref?.(row)}
                        onAction={onRowAction ? () => onRowAction(row) : undefined}
                        labelledBy={nameId}
                      />
                    ) : null}
                  </div>
                  {cardFacts.length > 0 ? (
                    <dl className="lk-cardlist-facts">
                      {cardFacts.map((column) => (
                        <div key={column.key}>
                          <dt>{column.mobileLabel ?? column.header}</dt>
                          <dd className={cx(column.numeric && "lk-td-num")}>{column.cell(row)}</dd>
                        </div>
                      ))}
                    </dl>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )
      ) : null}

      {footer ? <div className="lk-table-foot">{footer}</div> : null}
    </div>
  );
}

export interface MediaCellProps {
  title: ReactNode;
  subtitle?: ReactNode;
  /** A thumbnail URL (a decor swatch, a product photo). */
  src?: string;
  /** Shown in the thumbnail square when there is no image. */
  icon?: IconName;
  className?: string;
}

/** A table cell with a thumbnail, a title and a quieter second line. */
export function MediaCell({ title, subtitle, src, icon, className }: MediaCellProps) {
  return (
    <div className={cx("lk-table-cell-media", className)}>
      {src ? (
        // Thumbnails come from the API at arbitrary sizes; the 44px square does not need the image optimiser.
        // eslint-disable-next-line @next/next/no-img-element
        <img className="lk-table-thumb" src={src} alt="" loading="lazy" decoding="async" width={44} height={44} />
      ) : icon ? (
        <span className="lk-table-thumb lk-table-thumb-icon" aria-hidden="true">
          <Icon name={icon} size={20} />
        </span>
      ) : null}
      <div>
        {title}
        {subtitle ? <small>{subtitle}</small> : null}
      </div>
    </div>
  );
}

/** Content for a table's `footer`: one slot at each end (a row count, paging). */
export function TableFooter({ left, right, className }: { left?: ReactNode; right?: ReactNode; className?: string }) {
  return (
    <div className={cx("lk-table-foot-slots", className)}>
      <div>{left}</div>
      <div>{right}</div>
    </div>
  );
}
