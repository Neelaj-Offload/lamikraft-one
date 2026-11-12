"use client";

import { parseDate, type CalendarDate } from "@internationalized/date";
import {
  Button as RacButton,
  Calendar,
  CalendarCell,
  CalendarGrid,
  CalendarGridBody,
  CalendarGridHeader,
  CalendarHeaderCell,
  DateInput,
  DatePicker as RacDatePicker,
  DateRangePicker as RacDateRangePicker,
  DateSegment,
  Dialog,
  Group,
  Heading,
  Popover,
  RangeCalendar,
} from "react-aria-components";
import { cx } from "@/lib/cx";
import { FieldLabel, FieldMessage, hasError, inputClass, type FieldChromeProps, type FieldSize } from "./field";
import { Icon } from "./icon";

/** `"2026-10-12"` to a calendar date; null when empty or malformed. Business dates carry no zone. */
function toCalendarDate(value: string | null | undefined): CalendarDate | null {
  if (!value) return null;
  try {
    return parseDate(value);
  } catch {
    return null;
  }
}

interface DateFieldChrome extends FieldChromeProps {
  /** Earliest selectable day, ISO `YYYY-MM-DD`. */
  minValue?: string;
  /** Latest selectable day, ISO `YYYY-MM-DD`. */
  maxValue?: string;
  isRequired?: boolean;
  isDisabled?: boolean;
  size?: FieldSize;
  glass?: boolean;
  className?: string;
}

export interface DatePickerProps extends DateFieldChrome {
  /** ISO `YYYY-MM-DD`, or null when empty. */
  value: string | null;
  onChange: (value: string | null) => void;
  name?: string;
}

export interface DateRange {
  start: string;
  end: string;
}

export interface DateRangePickerProps extends DateFieldChrome {
  /** Both ends as ISO `YYYY-MM-DD`, or null when empty. */
  value: DateRange | null;
  onChange: (value: DateRange | null) => void;
  startName?: string;
  endName?: string;
}

function Segments({ slot, className }: { slot?: "start" | "end"; className?: string }) {
  return (
    <DateInput slot={slot} className={cx("lk-date-input", className)}>
      {(segment) => <DateSegment segment={segment} className="lk-date-segment" />}
    </DateInput>
  );
}

function CalendarButton() {
  return (
    <RacButton className="lk-date-btn">
      <Icon name="calendar" />
    </RacButton>
  );
}

/** Month heading, previous / next, and the day grid; shared by the single and the range calendar. */
function CalendarBody() {
  return (
    <>
      <header className="lk-calendar-head">
        <RacButton slot="previous" className="lk-calendar-nav">
          <Icon name="chevronLeft" />
        </RacButton>
        <Heading className="lk-calendar-title" />
        <RacButton slot="next" className="lk-calendar-nav">
          <Icon name="chevronRight" />
        </RacButton>
      </header>
      <CalendarGrid className="lk-calendar-grid" weekdayStyle="short">
        <CalendarGridHeader>
          {(day) => <CalendarHeaderCell className="lk-calendar-weekday">{day}</CalendarHeaderCell>}
        </CalendarGridHeader>
        <CalendarGridBody>
          {(date) => (
            <CalendarCell date={date} className="lk-calendar-cell">
              {({ formattedDate }) => <span className="lk-calendar-day">{formattedDate}</span>}
            </CalendarCell>
          )}
        </CalendarGridBody>
      </CalendarGrid>
    </>
  );
}

/**
 * A business date. Type it segment by segment (arrow keys step a segment) or open the calendar.
 * The value is an ISO `YYYY-MM-DD` string with no time or zone, so nothing shifts across zones.
 */
export function DatePicker({
  label,
  optional,
  hideLabel,
  help,
  error,
  value,
  onChange,
  minValue,
  maxValue,
  isRequired,
  isDisabled,
  size = "md",
  glass,
  name,
  className,
}: DatePickerProps) {
  const invalid = hasError(error);
  return (
    <RacDatePicker<CalendarDate>
      value={toCalendarDate(value)}
      onChange={(next) => onChange(next ? next.toString() : null)}
      minValue={toCalendarDate(minValue) ?? undefined}
      maxValue={toCalendarDate(maxValue) ?? undefined}
      isInvalid={invalid || undefined}
      validationBehavior="aria"
      isRequired={isRequired}
      isDisabled={isDisabled}
      name={name}
      className={cx("lk-field", className)}
    >
      <FieldLabel optional={optional} hidden={hideLabel}>
        {label}
      </FieldLabel>
      <Group className={inputClass({ size, glass, invalid, disabled: isDisabled })}>
        <Segments />
        <CalendarButton />
      </Group>
      <FieldMessage help={help} error={error} />
      <Popover className="lk-picker-popover lk-calendar-popover" offset={6}>
        <Dialog className="lk-calendar-dialog">
          <Calendar className="lk-calendar">
            <CalendarBody />
          </Calendar>
        </Dialog>
      </Popover>
    </RacDatePicker>
  );
}

/** A span of business dates: two typed dates sharing one range calendar. */
export function DateRangePicker({
  label,
  optional,
  hideLabel,
  help,
  error,
  value,
  onChange,
  minValue,
  maxValue,
  isRequired,
  isDisabled,
  size = "md",
  glass,
  startName,
  endName,
  className,
}: DateRangePickerProps) {
  const invalid = hasError(error);
  const start = toCalendarDate(value?.start);
  const end = toCalendarDate(value?.end);
  return (
    <RacDateRangePicker<CalendarDate>
      value={start && end ? { start, end } : null}
      onChange={(next) => onChange(next ? { start: next.start.toString(), end: next.end.toString() } : null)}
      minValue={toCalendarDate(minValue) ?? undefined}
      maxValue={toCalendarDate(maxValue) ?? undefined}
      isInvalid={invalid || undefined}
      validationBehavior="aria"
      isRequired={isRequired}
      isDisabled={isDisabled}
      startName={startName}
      endName={endName}
      className={cx("lk-field", className)}
    >
      <FieldLabel optional={optional} hidden={hideLabel}>
        {label}
      </FieldLabel>
      <Group className={inputClass({ size, glass, invalid, disabled: isDisabled })}>
        <Segments slot="start" className="lk-date-input-start" />
        <span className="lk-date-sep" aria-hidden="true">
          –
        </span>
        <Segments slot="end" />
        <CalendarButton />
      </Group>
      <FieldMessage help={help} error={error} />
      <Popover className="lk-picker-popover lk-calendar-popover" offset={6}>
        <Dialog className="lk-calendar-dialog">
          <RangeCalendar className="lk-calendar lk-calendar-range">
            <CalendarBody />
          </RangeCalendar>
        </Dialog>
      </Popover>
    </RacDateRangePicker>
  );
}
