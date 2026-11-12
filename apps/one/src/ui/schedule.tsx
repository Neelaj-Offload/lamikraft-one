import { Fragment } from "react";
import { cx } from "@/lib/cx";

export interface ScheduleBlock {
  /** Start and end in hours on the day's clock; fractions are minutes (9.5 is 9:30). */
  start: number;
  end: number;
  label: string;
  /** Ink by default; gold for the block that matters now, glass for tentative ones. */
  tone?: "gold" | "glass";
  /** A person's name: their initials ride on the block. */
  avatar?: string;
}

export interface ScheduleNote {
  /** Where the note sits, in hours. */
  at: number;
  note: string;
}

export interface ScheduleLane {
  label: string;
  blocks: readonly (ScheduleBlock | ScheduleNote)[];
}

export interface ScheduleProps {
  /** Names the schedule ("Press line, Monday"). */
  label: string;
  lanes: readonly ScheduleLane[];
  /** First and last hour shown. */
  start?: number;
  end?: number;
  hourLabel?: (hour: number) => string;
  className?: string;
}

/** `9` is "9 AM", `13.5` is "1:30 PM". */
function defaultHourLabel(hour: number): string {
  const whole = Math.floor(hour);
  const minutes = Math.round((hour - whole) * 60);
  const onClock = ((whole + 11) % 12) + 1;
  const suffix = whole % 24 >= 12 ? "PM" : "AM";
  return `${onClock}${minutes ? `:${String(minutes).padStart(2, "0")}` : ""} ${suffix}`;
}

/** At most seven axis labels, on a step that divides the day evenly when one exists. */
function axisHours(start: number, end: number): number[] {
  const span = end - start;
  const step = [1, 2, 3, 4, 6].find((size) => span / size <= 6 && span % size === 0) ?? Math.max(1, Math.ceil(span / 6));
  const hours: number[] = [];
  for (let hour = start; hour <= end; hour += step) hours.push(hour);
  return hours;
}

const isNote = (block: ScheduleBlock | ScheduleNote): block is ScheduleNote => "note" in block;

const initialsOf = (name: string) =>
  name
    .split(" ")
    .map((part) => part[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();

/**
 * Lanes of timed blocks across one day. The drawing scrolls sideways on narrow screens; the same
 * information is also given as a list for screen readers, lane by lane in time order.
 */
export function Schedule({ label, lanes, start = 9, end = 18, hourLabel = defaultHourLabel, className }: ScheduleProps) {
  const span = Math.max(1, end - start);
  const position = (hour: number) => Math.min(100, Math.max(0, ((hour - start) / span) * 100));
  return (
    <div className={className}>
      <div className="lk-schedule-scroll" tabIndex={0} role="group" aria-label={`${label}, timeline. Scroll sideways to see the whole day.`}>
        <div className="lk-schedule" aria-hidden="true">
          {lanes.map((lane, laneIndex) => (
            <Fragment key={laneIndex}>
              <div className="lk-schedule-label">{lane.label}</div>
              <div className="lk-schedule-lane">
                {lane.blocks.map((block, blockIndex) =>
                  isNote(block) ? (
                    <span key={blockIndex} className="lk-schedule-note" style={{ left: `${position(block.at)}%` }}>
                      {block.note}
                    </span>
                  ) : (
                    <span
                      key={blockIndex}
                      className={cx("lk-schedule-block", block.tone && `lk-schedule-block-${block.tone}`)}
                      style={{
                        left: `${position(block.start)}%`,
                        width: `${Math.max(4, position(block.end) - position(block.start))}%`,
                      }}
                      title={`${block.label}, ${hourLabel(block.start)} to ${hourLabel(block.end)}`}
                    >
                      {block.label}
                      {block.avatar ? <span className="lk-avatar lk-avatar-sm">{initialsOf(block.avatar)}</span> : null}
                    </span>
                  ),
                )}
              </div>
            </Fragment>
          ))}
          <div className="lk-schedule-axis">
            {axisHours(start, end).map((hour) => (
              <span key={hour}>{hourLabel(hour)}</span>
            ))}
          </div>
        </div>
      </div>
      <ul className="sr-only" aria-label={label}>
        {lanes.map((lane, laneIndex) => (
          <li key={laneIndex}>
            {lane.label}
            <ul>
              {lane.blocks.map((block, blockIndex) => (
                <li key={blockIndex}>
                  {isNote(block)
                    ? `${hourLabel(block.at)}: ${block.note}`
                    : `${hourLabel(block.start)} to ${hourLabel(block.end)}: ${block.label}${block.avatar ? `, ${block.avatar}` : ""}`}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </div>
  );
}
