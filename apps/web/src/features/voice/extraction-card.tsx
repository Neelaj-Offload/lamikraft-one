"use client";

import { useState } from "react";
import { Badge, DemoBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/text-field";
import { assistantProblem } from "@/features/assistant/use-assistant";
import { confirmExtraction, type ExtractionCard, type ExtractionField } from "@/lib/voice/api";
import { voiceMessages } from "@/messages/voice";

const m = voiceMessages.photo;

/** One value per field: confirmed, read with confidence, or a confirmation field (empty until answered). */
function FieldRow({ field, value, onChange, idPrefix }: { field: ExtractionField; value: string; onChange: (v: string) => void; idPrefix: string }) {
  if (!field.needs_confirmation) {
    return (
      <div className="flex flex-wrap justify-between gap-x-3 text-sm">
        <dt className="text-ink-muted">{field.label}</dt>
        <dd className="font-medium text-ink">{field.value ?? "—"}</dd>
      </div>
    );
  }
  return (
    <TextField
      id={`${idPrefix}-${field.key}`}
      label={`${field.label} · ${m.confirmField}`}
      description={field.suggestion ? m.suggestion(field.suggestion) : undefined}
      value={value}
      onChange={onChange}
      className="rounded-sm border border-warning-text/40 bg-warning-bg p-2"
    />
  );
}

/**
 * The structured confirmation card for a photo or document (ai-routing §3 `visual_extraction`).
 * Values the model read with confidence are shown; uncertain or missing ones are empty inputs
 * that the person must answer — the model's reading is a hint, never a default. Confirming
 * records the values only; nothing is created.
 */
export function ExtractionCardView({ card, onChange, onUse }: { card: ExtractionCard; onChange: (card: ExtractionCard) => void; onUse: (summary: string) => void }) {
  const [header, setHeader] = useState<Record<string, string>>({});
  const [lines, setLines] = useState<Record<string, string>[]>(() => card.lines.map(() => ({})));
  const [problem, setProblem] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const kind = m.kinds[card.extraction_kind] ?? card.extraction_kind;
  const confirmed = card.status === "confirmed";

  const submit = async () => {
    setSaving(true);
    setProblem(null);
    const pick = (fields: ExtractionField[], values: Record<string, string>) =>
      Object.fromEntries(fields.filter((f) => f.needs_confirmation).map((f) => [f.key, values[f.key]?.trim() || null]));
    try {
      const next = await confirmExtraction(card.request_id, {
        expected_version: card.version,
        header: pick(card.header, header),
        lines: card.lines.map((line, index) => pick(line.fields, lines[index] ?? {})),
      });
      onChange(next);
    } catch (error) {
      setProblem(assistantProblem(error));
    } finally {
      setSaving(false);
    }
  };

  const summary = () => {
    const head = card.header.filter((f) => f.value).map((f) => `${f.label}: ${f.value}`);
    const rows = card.lines.map((line, index) => `${m.line(index + 1)}: ${line.fields.filter((f) => f.value).map((f) => f.value).join(", ")}`);
    return [`${m.title(kind)} (confirmed)`, ...head, ...rows].join("; ");
  };

  return (
    <section aria-label={m.title(kind)} className="flex flex-col gap-3 rounded-sm border bg-surface p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-ink">{m.title(kind)}</h3>
        {card.provider_label === "Demo" ? <DemoBadge /> : <Badge>{card.provider_label}</Badge>}
      </div>
      {card.status === "unavailable" ? <p className="text-sm text-warning-text">{m.unavailable}</p> : null}
      <p className="text-xs text-ink-muted">{m.untrusted}</p>
      <dl className="flex flex-col gap-2">
        {card.header.map((field) => (
          <FieldRow key={field.key} idPrefix={`${card.request_id}-h`} field={field} value={header[field.key] ?? ""} onChange={(v) => setHeader((h) => ({ ...h, [field.key]: v }))} />
        ))}
      </dl>
      {card.lines.map((line) => (
        <fieldset key={line.index} className="flex flex-col gap-2 border-t pt-2">
          <legend className="text-xs font-semibold text-ink-muted">{m.line(line.index + 1)}</legend>
          <dl className="flex flex-col gap-2">
            {line.fields.map((field) => (
              <FieldRow
                key={field.key}
                idPrefix={`${card.request_id}-l${line.index}`}
                field={field}
                value={lines[line.index]?.[field.key] ?? ""}
                onChange={(v) => setLines((all) => all.map((row, i) => (i === line.index ? { ...row, [field.key]: v } : row)))}
              />
            ))}
          </dl>
        </fieldset>
      ))}
      {problem ? (
        <p role="alert" className="text-sm text-warning-text">
          {problem}
        </p>
      ) : null}
      {confirmed ? (
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm text-ink">{m.confirmed}</p>
          <Button variant="secondary" onPress={() => onUse(summary())}>
            {m.useInAssistant}
          </Button>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {card.pending_confirmations > 0 ? <p className="text-sm text-ink-muted">{m.pending(card.pending_confirmations)}</p> : null}
          <Button variant="primary" onPress={() => void submit()} isPending={saving}>
            {m.confirm}
          </Button>
        </div>
      )}
    </section>
  );
}
