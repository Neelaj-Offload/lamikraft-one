"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { SectionCard } from "@/components/ui/section-card";
import { ErrorState, Loading } from "@/components/ui/states";
import { descriptionClasses, fieldErrorClasses } from "@/components/ui/styles";
import { TextArea } from "@/components/ui/text-field";
import { conflictFromError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { challansMessages as m } from "@/messages/challans";
import { fetchChallanNote, saveChallanNote } from "./api";
import type { InternalNote } from "./types";
import { saveFailureText, useDebouncedSaver } from "./use-line-saver";

const w = m.workspace;

/**
 * The internal note (legacy autosave, LM-95): a collab note on the challan, editable after issue by whoever may update
 * the challan, never printed or exported. Saves 800 ms after the last keystroke; a 409 shows the other person's
 * version and keeps the typed text to copy, never overwriting either.
 */
export function InternalNotePanel({ challanId }: { challanId: string }) {
  const query = useQuery({ queryKey: queryKeys.challans.note(challanId), queryFn: ({ signal }) => fetchChallanNote(challanId, signal) });
  return (
    <SectionCard title={w.note} description={w.noteHint}>
      {query.isPending ? (
        <Loading label={w.note} variant="inline" />
      ) : query.isError ? (
        <ErrorState error={query.error} what={w.note} onRetry={() => void query.refetch()} headingLevel={3} compact backToToday={false} />
      ) : (
        <NoteEditor key={challanId} challanId={challanId} note={query.data} />
      )}
    </SectionCard>
  );
}

function NoteEditor({ challanId, note }: { challanId: string; note: InternalNote }) {
  const queryClient = useQueryClient();
  const [text, setText] = useState(note.body);
  const [lost, setLost] = useState<string | null>(null);
  const version = useRef(note.version);
  const saver = useDebouncedSaver<string>(
    async (body) => {
      try {
        const saved = await saveChallanNote(challanId, body, version.current);
        version.current = saved.version;
        queryClient.setQueryData(queryKeys.challans.note(challanId), saved);
      } catch (error) {
        if (conflictFromError(error)) {
          const latest = await fetchChallanNote(challanId);
          version.current = latest.version;
          setLost(body);
          setText(latest.body);
          queryClient.setQueryData(queryKeys.challans.note(challanId), latest);
        }
        throw error;
      }
    },
    { delayMs: 800 },
  );
  const state = saver.state;

  if (!note.canUpdate) {
    return (
      <div className="flex flex-col gap-1">
        <p className="whitespace-pre-line text-ink [overflow-wrap:anywhere]">{note.body || "—"}</p>
        <p className={descriptionClasses}>{w.noteReadOnly}</p>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      <TextArea
        label={w.note}
        value={text}
        onChange={(value) => {
          setText(value);
          setLost(null);
          saver.change(value);
        }}
        onBlur={() => void saver.flush()}
        rows={4}
      />
      <div aria-live="polite" className="min-h-6">
        {state.status === "failed" ? (
          <span className="flex flex-wrap items-center gap-2" data-save="failed">
            <span className={fieldErrorClasses}>
              {w.noteFailed}: {lost !== null ? w.noteConflict : saveFailureText(state.error)}
            </span>
            {lost === null ? (
              <Button size="sm" onPress={() => void saver.retry()}>
                {w.save.retry}
              </Button>
            ) : null}
          </span>
        ) : state.status === "saving" || state.status === "pending" ? (
          <span className={descriptionClasses}>{w.noteSaving}</span>
        ) : state.status === "saved" ? (
          <span className={descriptionClasses} data-save="saved">
            {w.noteSaved}
          </span>
        ) : null}
      </div>
      {lost !== null ? <TextArea label={w.noteYourText} value={lost} onChange={() => undefined} isReadOnly rows={3} /> : null}
    </div>
  );
}
