"use client";

import { useId, type ReactNode } from "react";
import { cx } from "@/lib/cx";

/**
 * A titled region on a detail screen. Cards are reserved for documents, proposals and distinct
 * sections (build brief); lists and tables stay on the canvas with separators.
 */
export function SectionCard({
  title,
  description,
  actions,
  children,
  headingLevel = 2,
  className,
  bodyClassName,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  headingLevel?: 2 | 3;
  className?: string;
  bodyClassName?: string;
}) {
  const id = useId();
  const Heading = headingLevel === 2 ? "h2" : "h3";
  return (
    <section aria-labelledby={id} className={cx("flex flex-col gap-4 rounded-lg border bg-surface p-4 md:p-5", className)}>
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="flex min-w-0 flex-col gap-0.5">
          <Heading id={id} className="text-lg font-[650] text-ink">
            {title}
          </Heading>
          {description ? <p className="text-sm text-ink-muted">{description}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      <div className={cx("flex flex-col gap-4", bodyClassName)}>{children}</div>
    </section>
  );
}
