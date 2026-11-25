import { Fragment, type ReactNode } from "react";
import { cx } from "@/lib/cx";
import { Dash } from "./format";
import { Icon, type IconName } from "./icon";

const isMissing = (value: ReactNode) => value === null || value === undefined || value === "" || value === false;

export interface KeyValueItem {
  label: ReactNode;
  /** Null, undefined or an empty string renders the "not set" dash. */
  value: ReactNode;
  /** The closing line of a summary: heavier, with a larger figure. */
  total?: boolean;
  /** Monospace, for identifiers and codes. */
  mono?: boolean;
}

export interface KeyValueProps {
  items: readonly KeyValueItem[];
  /** Ledger layout: each pair on its own ruled line, value at the right edge (totals, summaries). */
  rows?: boolean;
  /** Pairs side by side from 768px; always one column on phones. */
  columns?: 1 | 2 | 3;
  className?: string;
}

/** Facts as a definition list: label on the left, value beside it. */
export function KeyValue({ items, rows = false, columns = 1, className }: KeyValueProps) {
  const classes = cx("lk-kv", rows && "lk-kv-rows", columns > 1 && `lk-kv-cols-${columns}`, className);
  const valueOf = (item: KeyValueItem) => (isMissing(item.value) ? <Dash /> : item.value);
  if (rows) {
    return (
      <dl className={classes}>
        {items.map((item, index) => (
          <div key={index} className={cx(item.total && "lk-kv-total")}>
            <dt>{item.label}</dt>
            <dd className={cx(item.mono && "lk-mono")}>{valueOf(item)}</dd>
          </div>
        ))}
      </dl>
    );
  }
  return (
    <dl className={classes}>
      {items.map((item, index) => (
        <Fragment key={index}>
          <dt className={cx(item.total && "lk-kv-total")}>{item.label}</dt>
          <dd className={cx(item.total && "lk-kv-total", item.mono && "lk-mono")}>{valueOf(item)}</dd>
        </Fragment>
      ))}
    </dl>
  );
}

export interface Fact {
  label: string;
  value: ReactNode;
  icon?: IconName;
}

/** Three to five key facts in a strip under a record's title; a two-column grid on phones. */
export function FactStrip({ items, className }: { items: readonly Fact[]; className?: string }) {
  return (
    <dl className={cx("lk-facts", className)}>
      {items.map((item) => (
        <div key={item.label} className="lk-fact">
          <dt>
            {item.icon ? <Icon name={item.icon} size={14} /> : null}
            {item.label}
          </dt>
          <dd>{isMissing(item.value) ? <Dash /> : item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
