"use client";

import {
  now as zonedNow,
  parseAbsolute,
  parseDate,
  toZoned,
  type CalendarDate,
  type DateValue,
  type ZonedDateTime,
} from "@internationalized/date";
import { useMemo, type ReactNode } from "react";
import {
  Button as RacButton,
  Calendar,
  CalendarCell,
  CalendarGrid,
  DateInput,
  DatePicker as RacDatePicker,
  DateSegment,
  Dialog,
  FieldError,
  Group,
  Heading,
  Label,
  Popover,
  Text,
} from "react-aria-components";
import { cx } from "@/lib/cx";
import { useZone } from "@/lib/session/context";
import { CalendarIcon, ChevronLeftIcon, ChevronRightIcon } from "./icons";
import { descriptionClasses, fieldErrorClasses, iconButtonClasses, labelClasses, popoverClasses } from "./styles";

/** `"2026-10-12"` → CalendarDate, or null when empty or malformed. */
export function toCalendarDate(value: string | null): CalendarDate | null {
  if (!value) return null;
  try {
    return parseDate(value);
  } catch {
    return null;
  }
}

/** RFC 3339 instant → ZonedDateTime in the user's zone, so the picker shows local wall time. */
export function toZonedDateTime(value: string | null, timeZone: string): ZonedDateTime | null {
  if (!value) return null;
  try {
    return parseAbsolute(value, timeZone);
  } catch {
    return null;
  }
}

/** ZonedDateTime → `2026-10-12T13:00:00Z` (api-conventions §14: instants travel as UTC). */
export function zonedToUtcIso(value: ZonedDateTime): string {
  return value.toDate().toISOString().replace(/\.\d{3}Z$/, "Z");
}

/**
 * Any picker value → UTC instant. A value without a zone (a CalendarDateTime, which the picker
 * produces when it starts empty without a zoned placeholder) is wall time in `timeZone`, the
 * session zone, never the browser's.
 */
export function dateValueToUtcIso(value: DateValue, timeZone: string): string {
  return zonedToUtcIso("timeZone" in value ? value : toZoned(value, timeZone));
}

/** Placeholder for an empty instant field: the current hour in the session zone, so the zone segment shows. */
export function zonedPlaceholder(timeZone: string): ZonedDateTime {
  return zonedNow(timeZone).set({ minute: 0, second: 0, millisecond: 0 });
}

interface CommonProps {
  label: string;
  description?: ReactNode;
  errorMessage?: string;
  isRequired?: boolean;
  isDisabled?: boolean;
  name?: string;
  className?: string;
}

export type DatePickerProps = CommonProps &
  (
    | {
        /** A business date (`YYYY-MM-DD`) in the documented local zone; no conversion. */
        granularity?: "day";
        value: string | null;
        onChange: (value: string | null) => void;
      }
    | {
        /** An instant, edited as wall time in the user's zone and returned as UTC. */
        granularity: "minute";
        value: string | null;
        onChange: (value: string | null) => void;
      }
  );

function PickerChrome({ label, description, errorMessage }: Pick<CommonProps, "label" | "description" | "errorMessage">) {
  return (
    <>
      <Label className={labelClasses}>{label}</Label>
      <Group className="flex min-h-11 items-center rounded-md border border-border-strong bg-surface ps-3 pointer-fine:min-h-10 invalid:border-danger focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-focus">
        <DateInput className="flex flex-1 flex-wrap items-center tabular text-[15px] text-ink">
          {(segment) => (
            <DateSegment
              segment={segment}
              className="inline-block min-w-6 rounded-xs px-0.5 py-0.5 text-center outline-hidden placeholder-shown:text-ink-muted focus:bg-forest focus:text-on-forest data-[type=literal]:min-w-0 data-[type=literal]:px-0"
            />
          )}
        </DateInput>
        <RacButton aria-label="Open calendar" className={iconButtonClasses("quiet")}>
          <CalendarIcon size={18} />
        </RacButton>
      </Group>
      {description ? (
        <Text slot="description" className={descriptionClasses}>
          {description}
        </Text>
      ) : null}
      <FieldError className={fieldErrorClasses}>{errorMessage}</FieldError>
      <Popover className={cx(popoverClasses, "p-3")} offset={4}>
        <Dialog className="outline-hidden" aria-label={`${label}: choose a date`}>
          <Calendar>
            <header className="mb-2 flex items-center justify-between gap-2">
              <RacButton slot="previous" aria-label="Previous month" className={iconButtonClasses("quiet")}>
                <ChevronLeftIcon size={18} />
              </RacButton>
              <Heading className="text-[15px] font-semibold" />
              <RacButton slot="next" aria-label="Next month" className={iconButtonClasses("quiet")}>
                <ChevronRightIcon size={18} />
              </RacButton>
            </header>
            <CalendarGrid className="border-separate border-spacing-0.5 text-sm">
              {(date) => (
                <CalendarCell
                  date={date}
                  className={cx(
                    "flex size-11 items-center justify-center rounded-md tabular outline-hidden focus-visible:focus-ring-inset data-[focus-visible]:focus-ring-inset pointer-fine:size-9",
                    "hover:bg-surface-sunken outside-month:invisible selected:bg-forest selected:text-on-forest",
                    "disabled:opacity-40 unavailable:text-ink-muted unavailable:line-through",
                  )}
                />
              )}
            </CalendarGrid>
          </Calendar>
        </Dialog>
      </Popover>
    </>
  );
}

/**
 * Date picker with zone-aware display: business dates stay calendar dates; instants are shown
 * and edited in the signed-in user's zone (with the zone name visible) and saved as UTC.
 */
export function DatePicker(props: DatePickerProps) {
  const zone = useZone();
  const { label, description, errorMessage, isRequired, isDisabled, name, className } = props;
  // Without a zoned placeholder an empty picker produces zone-less values (read in the
  // browser's zone) and shows no zone segment.
  const placeholder = useMemo(() => zonedPlaceholder(zone.timeZone), [zone.timeZone]);
  const shared = {
    isRequired,
    isDisabled,
    name,
    isInvalid: Boolean(errorMessage),
    className: cx("flex flex-col gap-1.5", className),
  };

  if (props.granularity === "minute") {
    return (
      <RacDatePicker<ZonedDateTime>
        {...shared}
        granularity="minute"
        value={toZonedDateTime(props.value, zone.timeZone)}
        placeholderValue={placeholder}
        // Typed as ZonedDateTime, but converted defensively in case a zone-less value arrives.
        onChange={(next: DateValue | null) => props.onChange(next ? dateValueToUtcIso(next, zone.timeZone) : null)}
      >
        <PickerChrome label={label} description={description} errorMessage={errorMessage} />
      </RacDatePicker>
    );
  }
  return (
    <RacDatePicker<CalendarDate>
      {...shared}
      value={toCalendarDate(props.value)}
      onChange={(next) => props.onChange(next ? next.toString() : null)}
    >
      <PickerChrome label={label} description={description} errorMessage={errorMessage} />
    </RacDatePicker>
  );
}
