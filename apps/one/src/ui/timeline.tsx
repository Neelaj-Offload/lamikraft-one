import type { ReactNode } from "react";
import { cx } from "@/lib/cx";
import type { Tone } from "~/ui/badge";
import { Icon, type IconName } from "./icon";

export interface TimelineItem {
  id: string;
  /** What happened, with who did it: "Meera sent quotation LK-QT-2026-0041". */
  title: ReactNode;
  /** When, and any short context: a `<DateText>`, a channel. */
  meta?: ReactNode;
  /** Detail under the title: a note, a changed value, a quoted message. */
  body?: ReactNode;
  icon?: IconName;
  /** Colours the marker. The title carries the meaning; the tone only reinforces it. */
  tone?: Tone;
}

export interface TimelineProps {
  /** Names the list ("Quotation activity"). */
  label: string;
  /** In the order they should be read, usually newest first. */
  items: readonly TimelineItem[];
  className?: string;
}

/** A vertical activity list: one marker per event on a hairline rail. */
export function Timeline({ label, items, className }: TimelineProps) {
  return (
    <ol className={cx("lk-timeline", className)} aria-label={label}>
      {items.map((item) => (
        <li key={item.id} className="lk-timeline-item">
          <span
            className={cx(
              "lk-timeline-marker",
              item.tone && item.tone !== "neutral" && `lk-timeline-marker-${item.tone}`,
              !item.icon && "lk-timeline-marker-dot",
            )}
            aria-hidden="true"
          >
            {item.icon ? <Icon name={item.icon} size={14} /> : null}
          </span>
          <div className="lk-timeline-content">
            <div className="lk-timeline-head">
              <span className="lk-timeline-title">{item.title}</span>
              {item.meta ? <span className="lk-timeline-meta">{item.meta}</span> : null}
            </div>
            {item.body ? <div className="lk-timeline-body">{item.body}</div> : null}
          </div>
        </li>
      ))}
    </ol>
  );
}
