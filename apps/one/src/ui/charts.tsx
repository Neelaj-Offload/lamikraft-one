import { useId, type ReactNode } from "react";
import { cx } from "@/lib/cx";
import { DEFAULT_LOCALE } from "@/lib/format/money";

/*
 * Charts are plain SVG with a viewBox, so they scale with their container and render on the server.
 * They take plain numbers for plotting only: money and quantities stay decimal strings everywhere
 * else, and the labels people read come from `formatValue`.
 *
 * Colour order: series 1 gold (--chart-1), series 2 ink (--chart-2), then chart-3 to chart-6.
 * Every chart has an accessible name (`label`) and a text alternative for its data.
 */

type Point = readonly [number, number];

const round = (value: number) => Math.round(value * 100) / 100;

function plainNumber(locale: string): (value: number) => string {
  const formatter = new Intl.NumberFormat(locale, { maximumFractionDigits: 2 });
  return (value) => formatter.format(value);
}

/** A smooth path through the points (horizontal control handles, so the line never overshoots sideways). */
function smoothPath(points: readonly Point[]): string {
  const first = points[0];
  if (!first) return "";
  let d = `M${round(first[0])},${round(first[1])}`;
  for (let index = 1; index < points.length; index += 1) {
    const from = points[index - 1]!;
    const to = points[index]!;
    const mid = round((from[0] + to[0]) / 2);
    d += ` C${mid},${round(from[1])} ${mid},${round(to[1])} ${round(to[0])},${round(to[1])}`;
  }
  return d;
}

/** The smallest "round" number at or above the value (1, 2, 2.5, 5 or 10 times a power of ten). */
function niceCeil(value: number): number {
  if (!(value > 0)) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  const fraction = value / power;
  const step = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 2.5 ? 2.5 : fraction <= 5 ? 5 : 10;
  return step * power;
}

export interface SparklineProps {
  data: readonly number[];
  /** What the line measures ("Enquiries, last 8 weeks"). */
  label: string;
  width?: number;
  height?: number;
  color?: string;
  area?: boolean;
  /** Fill the container's width instead of the fixed 96 by 32 tile size. */
  fluid?: boolean;
  /** The surrounding text already states the trend (a stat tile): hide the line from screen readers. */
  decorative?: boolean;
  className?: string;
}

/** A small trend line with a dot on the latest value. */
export function Sparkline({
  data,
  label,
  width = 96,
  height = 32,
  color = "var(--chart-1)",
  area = true,
  fluid = false,
  decorative = false,
  className,
}: SparklineProps) {
  if (data.length === 0) return null;
  const pad = 3;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const points: Point[] = data.map((value, index) => [
    data.length === 1 ? width / 2 : pad + (index / (data.length - 1)) * (width - pad * 2),
    pad + (1 - (value - min) / range) * (height - pad * 2),
  ]);
  const d = smoothPath(points);
  const first = points[0]!;
  const last = points[points.length - 1]!;
  const format = plainNumber(DEFAULT_LOCALE);
  const summary = `${label}: from ${format(data[0]!)} to ${format(data[data.length - 1]!)}, low ${format(min)}, high ${format(max)}.`;
  return (
    <svg
      className={cx("lk-stat-spark", fluid && "lk-spark-fluid", className)}
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      {...(decorative ? { "aria-hidden": true } : { role: "img", "aria-label": summary })}
    >
      {area ? (
        <path
          d={`${d} L${round(last[0])},${height} L${round(first[0])},${height} Z`}
          fill={color}
          className="lk-chart-area lk-chart-fade"
        />
      ) : null}
      <path d={d} className="lk-chart-line lk-chart-draw" stroke={color} pathLength={1} />
      <circle cx={round(last[0])} cy={round(last[1])} r="3" fill={color} className="lk-chart-dot lk-chart-after" />
    </svg>
  );
}

export interface ChartSeries {
  name: string;
  data: readonly number[];
  /** Overrides the series colour; by default series take --chart-1, --chart-2 and so on. */
  color?: string;
  /** A dashed line for a target, forecast or comparison period. */
  dashed?: boolean;
}

export interface LineChartProps {
  /** What the chart shows ("Quotations sent per week"). */
  label: string;
  series: readonly ChartSeries[];
  /** One label per point along the x axis. */
  labels?: readonly string[];
  /** Size of the drawing in viewBox units; the chart scales to its container. */
  width?: number;
  height?: number;
  /** Soft fill under the first series. */
  area?: boolean;
  /** Mark one point of the first series with its value: `true` for the latest, or a point index. */
  callout?: boolean | number;
  legend?: boolean;
  /** Text for axis ticks, the callout and the data table. */
  formatValue?: (value: number) => string;
  className?: string;
}

/** One or more lines over a shared zero-based scale. The lines draw from left to right once. */
export function LineChart({
  label,
  series,
  labels,
  width = 480,
  height = 180,
  area = true,
  callout,
  legend = false,
  formatValue = plainNumber(DEFAULT_LOCALE),
  className,
}: LineChartProps) {
  const top = niceCeil(Math.max(0, ...series.flatMap((entry) => entry.data)));
  const ticks = [0, top / 2, top];
  const tickText = ticks.map(formatValue);
  const padLeft = Math.max(32, 12 + Math.max(...tickText.map((text) => text.length)) * 6.5);
  const padRight = 12;
  const padTop = 16;
  const padBottom = labels ? 24 : 8;
  const plotWidth = width - padLeft - padRight;
  const plotHeight = height - padTop - padBottom;
  const count = Math.max(1, ...series.map((entry) => entry.data.length));
  const x = (index: number) => (count === 1 ? padLeft + plotWidth / 2 : padLeft + (index / (count - 1)) * plotWidth);
  const y = (value: number) => padTop + (1 - Math.max(0, value) / top) * plotHeight;
  const baseline = y(0);
  const lines = series.map((entry) => {
    const points: Point[] = entry.data.map((value, index) => [x(index), y(value)]);
    return { points, d: smoothPath(points) };
  });
  const colorOf = (index: number) => series[index]?.color ?? `var(--chart-${(index % 6) + 1})`;

  const lead = lines[0];
  const calloutIndex =
    callout === undefined || callout === false || !lead || lead.points.length === 0
      ? null
      : callout === true
        ? lead.points.length - 1
        : Math.min(Math.max(0, callout), lead.points.length - 1);
  const calloutPoint = calloutIndex === null ? undefined : lead?.points[calloutIndex];
  const calloutValue = calloutIndex === null ? undefined : series[0]?.data[calloutIndex];

  const columns = Array.from({ length: count }, (_, index) => labels?.[index] ?? String(index + 1));

  return (
    <figure className={cx("lk-chart-wrap", className)}>
      <svg className="lk-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
        {ticks.map((tick, index) => (
          <g key={tick}>
            <line className="lk-chart-grid" x1={padLeft} x2={width - padRight} y1={round(y(tick))} y2={round(y(tick))} />
            <text className="lk-chart-axis" x={padLeft - 8} y={round(y(tick)) + 4} textAnchor="end">
              {tickText[index]}
            </text>
          </g>
        ))}
        {labels?.slice(0, count).map((text, index) => (
          <text
            key={index}
            className="lk-chart-axis"
            x={round(x(index))}
            y={height - 6}
            textAnchor={count > 1 && index === count - 1 ? "end" : "middle"}
          >
            {text}
          </text>
        ))}
        {lines.map((line, index) => {
          const start = line.points[0];
          const end = line.points[line.points.length - 1];
          if (!start || !end) return null;
          const dashed = series[index]?.dashed;
          return (
            <g key={index}>
              {area && index === 0 ? (
                <path
                  d={`${line.d} L${round(end[0])},${round(baseline)} L${round(start[0])},${round(baseline)} Z`}
                  fill={colorOf(index)}
                  className="lk-chart-area lk-chart-fade"
                />
              ) : null}
              {dashed ? (
                <path d={line.d} className="lk-chart-line lk-chart-fade" stroke={colorOf(index)} strokeDasharray="4 6" />
              ) : (
                <path d={line.d} className="lk-chart-line lk-chart-draw" stroke={colorOf(index)} pathLength={1} />
              )}
            </g>
          );
        })}
        {calloutPoint && calloutValue !== undefined
          ? (() => {
              const text = formatValue(calloutValue);
              const boxWidth = 16 + text.length * 6.5;
              const boxX = Math.min(Math.max(calloutPoint[0] - boxWidth / 2, 0), width - boxWidth);
              const boxY = Math.max(calloutPoint[1] - 30, 0);
              return (
                <g className="lk-chart-after">
                  <line
                    className="lk-chart-grid"
                    x1={round(calloutPoint[0])}
                    x2={round(calloutPoint[0])}
                    y1={padTop}
                    y2={round(baseline)}
                    strokeDasharray="3 4"
                  />
                  <circle cx={round(calloutPoint[0])} cy={round(calloutPoint[1])} r="4.5" fill={colorOf(0)} className="lk-chart-dot" />
                  <rect className="lk-chart-callout-bg" x={round(boxX)} y={round(boxY)} width={round(boxWidth)} height={20} rx="10" />
                  <text className="lk-chart-callout" x={round(boxX + boxWidth / 2)} y={round(boxY) + 14} textAnchor="middle">
                    {text}
                  </text>
                </g>
              );
            })()
          : null}
      </svg>
      {legend ? (
        <div className="lk-chart-legend" aria-hidden="true">
          {series.map((entry, index) => (
            <span key={entry.name}>
              <i style={{ background: colorOf(index) }} />
              {entry.name}
            </span>
          ))}
        </div>
      ) : null}
      <table className="sr-only">
        <caption>{label}</caption>
        <thead>
          <tr>
            <td />
            {columns.map((column, index) => (
              <th key={index} scope="col">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {series.map((entry) => (
            <tr key={entry.name}>
              <th scope="row">{entry.name}</th>
              {columns.map((_, index) => {
                const value = entry.data[index];
                return <td key={index}>{value === undefined ? "" : formatValue(value)}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}

export interface BarChartProps {
  /** What the bars measure ("Dispatches per day"). */
  label: string;
  data: readonly number[];
  labels?: readonly string[];
  width?: number;
  height?: number;
  /** Index of the bar to bring forward in gold; the others step back. */
  highlight?: number;
  color?: string;
  highlightColor?: string;
  formatValue?: (value: number) => string;
  className?: string;
}

/** Vertical bars on a zero baseline. Ink by default, with one bar optionally highlighted in gold. */
export function BarChart({
  label,
  data,
  labels,
  width = 480,
  height = 160,
  highlight,
  color = "var(--chart-2)",
  highlightColor = "var(--chart-1)",
  formatValue = plainNumber(DEFAULT_LOCALE),
  className,
}: BarChartProps) {
  const padSide = 8;
  const padTop = 8;
  const padBottom = labels ? 22 : 8;
  const plotHeight = height - padTop - padBottom;
  const plotWidth = width - padSide * 2;
  const max = Math.max(0, ...data) || 1;
  const count = Math.max(1, data.length);
  const gap = 6;
  const barWidth = Math.max(1, (plotWidth - gap * (count - 1)) / count);
  const nameOf = (index: number) => labels?.[index] ?? String(index + 1);
  return (
    <figure className={cx("lk-chart-wrap", className)}>
      <svg className="lk-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
        {data.map((value, index) => {
          const barHeight = (Math.max(0, value) / max) * plotHeight;
          const left = padSide + index * (barWidth + gap);
          const lit = highlight === index;
          return (
            <g key={index}>
              <rect
                className="lk-chart-bar"
                x={round(left)}
                y={round(padTop + plotHeight - barHeight)}
                width={round(barWidth)}
                height={round(barHeight)}
                fill={lit ? highlightColor : color}
                opacity={highlight !== undefined && !lit ? 0.35 : 1}
              >
                <title>{`${nameOf(index)}: ${formatValue(value)}`}</title>
              </rect>
              {labels ? (
                <text className="lk-chart-axis" x={round(left + barWidth / 2)} y={height - 6} textAnchor="middle">
                  {labels[index]}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
      <ul className="sr-only" aria-label={`${label}, values`}>
        {data.map((value, index) => (
          <li key={index}>
            {nameOf(index)}: {formatValue(value)}
            {highlight === index ? " (highlighted)" : ""}
          </li>
        ))}
      </ul>
    </figure>
  );
}

const clampPercent = (value: number) => Math.min(100, Math.max(0, Number.isFinite(value) ? value : 0));

export interface ProgressRingProps {
  /** 0 to 100. */
  value: number;
  /** What is progressing ("Order packed"). Read by screen readers; not shown. */
  label: string;
  size?: number;
  stroke?: number;
  /** Gold by default. */
  tone?: "ink" | "leaf" | "cobalt";
  /** Short text under the percentage. */
  caption?: ReactNode;
  className?: string;
}

/** A circular progress meter with the percentage in the middle. */
export function ProgressRing({ value, label, size = 96, stroke = 8, tone, caption, className }: ProgressRingProps) {
  const percent = clampPercent(value);
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  return (
    <div
      className={cx("lk-ring", tone && `lk-ring-${tone}`, className)}
      role="progressbar"
      aria-valuenow={Math.round(percent)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle className="lk-ring-track" cx={size / 2} cy={size / 2} r={radius} strokeWidth={stroke} />
        <circle
          className="lk-ring-bar"
          cx={size / 2}
          cy={size / 2}
          r={radius}
          strokeWidth={stroke}
          strokeDasharray={round(circumference)}
          strokeDashoffset={round(circumference * (1 - percent / 100))}
        />
      </svg>
      <div className="lk-ring-label">
        <span className="lk-ring-value" style={{ fontSize: Math.round(size * 0.22) }}>
          {Math.round(percent)}%
        </span>
        {caption ? <span className="lk-ring-caption">{caption}</span> : null}
      </div>
    </div>
  );
}

export interface ProgressBarProps {
  /** 0 to 100. */
  value: number;
  /** What is progressing; shown above the track unless `hideLabel`. */
  label: string;
  hideLabel?: boolean;
  /** Text at the end of the label row; defaults to the percentage ("8 of 12 rolls"). */
  detail?: ReactNode;
  /** Gold by default. */
  tone?: "ink" | "leaf" | "ember";
  thick?: boolean;
  /** Draw this many discrete steps instead of a continuous fill. */
  segments?: number;
  className?: string;
}

/** A horizontal progress meter, continuous or in steps. */
export function ProgressBar({ value, label, hideLabel, detail, tone, thick, segments, className }: ProgressBarProps) {
  const percent = clampPercent(value);
  const id = useId();
  return (
    <div
      className={cx(
        "lk-progress",
        tone && `lk-progress-${tone}`,
        thick && "lk-progress-thick",
        segments ? "lk-progress-segmented" : null,
        className,
      )}
      role="progressbar"
      aria-valuenow={Math.round(percent)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-labelledby={id}
    >
      <div className={cx("lk-progress-head", hideLabel && "sr-only")}>
        <span id={id}>{label}</span>
        <b>{detail !== undefined ? detail : `${Math.round(percent)}%`}</b>
      </div>
      <div className="lk-progress-track">
        {segments ? (
          Array.from({ length: segments }, (_, index) => (
            <span
              key={index}
              className={cx("lk-progress-seg", index < Math.round((percent / 100) * segments) && "lk-progress-seg-on")}
            />
          ))
        ) : (
          <div className="lk-progress-fill" style={{ width: `${percent}%` }} />
        )}
      </div>
    </div>
  );
}
