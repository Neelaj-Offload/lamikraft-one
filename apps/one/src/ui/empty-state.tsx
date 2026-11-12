import type { ReactNode } from "react";
import { cx } from "@/lib/cx";
import { Icon, type IconName } from "./icon";

export interface EmptyStateProps {
  icon?: IconName;
  /** What is (not) here, in the serif display face: "No quotations yet". */
  title: ReactNode;
  /** One sentence on why, or what to do next. */
  text?: ReactNode;
  /** The way forward: usually one primary button, at most two controls. */
  actions?: ReactNode;
  /** A smaller version for panels and table bodies. */
  compact?: boolean;
  className?: string;
}

/** Shown where a list or panel has nothing to show; it always offers the next step when there is one. */
export function EmptyState({ icon = "box", title, text, actions, compact = false, className }: EmptyStateProps) {
  return (
    <div className={cx("lk-empty", compact && "lk-empty-compact", className)}>
      <div className="lk-empty-art">
        <Icon name={icon} size={24} />
      </div>
      <h3 className="lk-empty-title">{title}</h3>
      {text ? <p className="lk-empty-text">{text}</p> : null}
      {actions ? <div className="lk-empty-actions">{actions}</div> : null}
    </div>
  );
}
