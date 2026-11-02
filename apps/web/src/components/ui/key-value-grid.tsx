import type { ReactNode } from "react";
import { cx } from "@/lib/cx";

export interface KeyValue {
  term: string;
  description: ReactNode;
  numeric?: boolean;
  /** Mono for identifiers and codes. */
  mono?: boolean;
}

/**
 * Many short facts (specification, packaging, addresses) as a responsive <dl> grid: one
 * column on phones, two from tablet, three from desktop. Callers drop empty values first.
 */
export function KeyValueGrid({ items, columns = 3, className }: { items: readonly KeyValue[]; columns?: 2 | 3; className?: string }) {
  return (
    <dl className={cx("grid grid-cols-1 gap-x-8 gap-y-3 sm:grid-cols-2", columns === 3 && "lg:grid-cols-3", className)}>
      {items.map((item) => (
        <div key={item.term} className="flex min-w-0 flex-col gap-0.5 border-b pb-3">
          <dt className="text-sm text-ink-muted">{item.term}</dt>
          <dd className={cx("min-w-0 text-ink [overflow-wrap:anywhere]", item.numeric && "tabular", item.mono && "font-mono text-sm")}>{item.description}</dd>
        </div>
      ))}
    </dl>
  );
}
