import { cx } from "@/lib/cx";

export type AvatarSize = "sm" | "md" | "lg" | "xl";

export interface AvatarProps {
  /** The person's name: the accessible name, and the source of the initials. */
  name?: string;
  /** A photo; initials show when there is none. */
  src?: string;
  size?: AvatarSize;
  status?: "online" | "away" | "off";
  className?: string;
}

const statusLabel = { online: "online", away: "away", off: "offline" } as const;

/** Up to two initials, by code point so non-Latin names work. */
function initialsOf(name: string): string {
  return name
    .trim()
    .split(/\s+/)
    .map((part) => Array.from(part)[0] ?? "")
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

function sizeClass(size: AvatarSize | undefined): string | false {
  return size !== undefined && size !== "md" && `lk-avatar-${size}`;
}

/** A person: their photo, or their initials on sand. */
export function Avatar({ name = "", src, size, status, className }: AvatarProps) {
  const label = [name.trim(), status ? statusLabel[status] : ""].filter(Boolean).join(", ");
  return (
    <span
      className={cx("lk-avatar", sizeClass(size), className)}
      role={label ? "img" : undefined}
      aria-label={label || undefined}
      aria-hidden={label ? undefined : true}
    >
      {src ? (
        // Profile photos come from the API at unknown origins and sizes; next/image needs both configured.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src} alt="" loading="lazy" decoding="async" />
      ) : (
        initialsOf(name)
      )}
      {status ? <span className={cx("lk-avatar-status", status !== "online" && `lk-avatar-status-${status}`)} /> : null}
    </span>
  );
}

export interface AvatarGroupProps {
  people: AvatarProps[];
  /** How many faces to show before "+N". */
  max?: number;
  size?: AvatarSize;
  className?: string;
}

/** An overlapping stack of people, with a count for the rest. */
export function AvatarGroup({ people, max = 4, size, className }: AvatarGroupProps) {
  const shown = people.slice(0, Math.max(0, max));
  const extra = people.length - shown.length;
  return (
    <span className={cx("lk-avatar-group", className)}>
      {shown.map((person, index) => (
        <Avatar key={index} size={size} {...person} />
      ))}
      {extra > 0 ? (
        <span className={cx("lk-avatar", "lk-avatar-more", sizeClass(size))} role="img" aria-label={`${extra} more`}>
          +{extra}
        </span>
      ) : null}
    </span>
  );
}
