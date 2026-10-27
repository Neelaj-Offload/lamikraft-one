import type { ReactNode } from "react";
import { cx } from "@/lib/cx";

export interface DescriptionItem {
  term: string;
  description: ReactNode;
  /** Right-align numeric values (money, quantities) with tabular figures. */
  numeric?: boolean;
}

/** Key facts as a semantic <dl>: two columns from tablet up, stacked on phones. */
export function DescriptionList({ items, className }: { items: readonly DescriptionItem[]; className?: string }) {
  return (
    <dl className={cx("grid grid-cols-1 gap-x-6 sm:grid-cols-[minmax(8rem,max-content)_1fr]", className)}>
      {items.map((item) => (
        <div key={item.term} className="contents">
          <dt className="pt-2 text-sm font-medium text-ink-muted sm:border-b sm:pb-2">{item.term}</dt>
          <dd className={cx("border-b pb-2 text-ink sm:pt-2", item.numeric && "tabular sm:text-end")}>{item.description}</dd>
        </div>
      ))}
    </dl>
  );
}
