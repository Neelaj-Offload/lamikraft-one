import type { ReactNode } from "react";
import { cx } from "@/lib/cx";
import { IconButton } from "./button";
import { Icon, type IconName } from "./icon";

export type BannerTone = "neutral" | "leaf" | "amber" | "ember" | "cobalt" | "gold";

const toneIcon: Record<BannerTone, IconName> = {
  leaf: "checkCircle",
  amber: "alert",
  ember: "alert",
  cobalt: "info",
  gold: "sparkles",
  neutral: "info",
};

export interface BannerProps {
  tone?: BannerTone;
  /** A short lead-in, set in bold before the message. */
  title?: ReactNode;
  /** Replaces the tone's default icon. */
  icon?: IconName;
  /** One follow-up (a small button or a link) at the end of the row. */
  action?: ReactNode;
  /** Renders a Dismiss button. Only pass it from a client component. */
  onClose?: () => void;
  className?: string;
  children?: ReactNode;
}

/**
 * An inline message about the screen it sits on. Ember and amber are announced at once
 * (role="alert"); the others politely (role="status"). No directive: it renders on the server
 * unless it is given `onClose`.
 */
export function Banner({ tone = "neutral", title, icon, action, onClose, className, children }: BannerProps) {
  return (
    <div
      className={cx("lk-banner", tone !== "neutral" && `lk-banner-${tone}`, className)}
      role={tone === "ember" || tone === "amber" ? "alert" : "status"}
    >
      <Icon name={icon ?? toneIcon[tone]} size={18} />
      <div className="lk-banner-body">
        {title ? <b>{title} </b> : null}
        {children}
      </div>
      {action ? <div className="lk-banner-action">{action}</div> : null}
      {onClose ? (
        <IconButton icon="x" label="Dismiss" variant="ghost" size="sm" className="lk-banner-close" onPress={onClose} />
      ) : null}
    </div>
  );
}
