import type { HTMLAttributes, ReactNode, Ref } from "react";
import { cx } from "@/lib/cx";

export interface GlassPanelProps extends Omit<HTMLAttributes<HTMLElement>, "title"> {
  as?: "section" | "div" | "article" | "aside" | "li" | "form";
  /** glass (default) for panels on the ground, strong over imagery, solid for dense data, inverse for emphasis. */
  variant?: "glass" | "strong" | "solid" | "inverse" | "outline";
  padding?: "none" | "sm" | "md" | "lg";
  /** Lifts 2px on hover. The panel itself is not a control: put a link or button inside it. */
  interactive?: boolean;
  /** Gold glow: the one selected panel in a set. */
  selected?: boolean;
  eyebrow?: ReactNode;
  title?: ReactNode;
  titleAs?: "h2" | "h3" | "h4";
  /** Sits at the end of the header row (a button, a segmented control, a link). */
  action?: ReactNode;
  className?: string;
  children?: ReactNode;
  ref?: Ref<HTMLElement>;
}

/** The frosted panel every screen is built from. */
export function GlassPanel({
  as = "div",
  variant = "glass",
  padding = "md",
  interactive = false,
  selected = false,
  eyebrow,
  title,
  titleAs = "h3",
  action,
  className,
  children,
  ...rest
}: GlassPanelProps) {
  // Typed as one concrete tag on purpose: the six tags share these attributes (and `ref` is typed to
  // their common base), while a bare `ElementType` resolves its props to `never` under these React types.
  const Tag = as as "div";
  const Title = titleAs as "h3";
  const hasHead = Boolean(eyebrow) || Boolean(title) || Boolean(action);
  return (
    <Tag
      {...(rest as HTMLAttributes<HTMLDivElement>)}
      className={cx(
        "lk-glass",
        variant !== "glass" && `lk-glass-${variant}`,
        `lk-glass-pad-${padding}`,
        interactive && "lk-glass-interactive",
        selected && "lk-glass-selected",
        className,
      )}
    >
      {hasHead ? (
        <div className="lk-glass-head">
          <div>
            {eyebrow ? <div className="lk-glass-eyebrow">{eyebrow}</div> : null}
            {title ? <Title className="lk-glass-title">{title}</Title> : null}
          </div>
          {action}
        </div>
      ) : null}
      {children}
    </Tag>
  );
}
