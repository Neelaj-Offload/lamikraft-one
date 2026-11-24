"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { fetchChallanNote, saveChallanNote } from "@/features/challans/api";
import type { InternalNote } from "@/features/challans/types";
import { useDebouncedSaver } from "@/features/challans/use-line-saver";
import { conflictFromError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { QueryView } from "~/shell/states";
import { Banner, Button, DateText, GlassPanel, Textarea } from "~/ui";
import { saveFailureText } from "./save-text";

/**
 * The internal note: for the team only, never printed or exported. Whoever may change the challan
 * can write it, even after issue. It saves 800 ms after the last keystroke; if someone else saved
 * first, their version is shown and the typed text is kept beside it to copy, never overwritten.
 */
export function NoteView({ challanId }: { challanId: string }) {
  const query = useQuery({ queryKey: queryKeys.challans.note(challanId), queryFn: ({ signal }) => fetchChallanNote(challanId, signal) });
  return (
    <GlassPanel padding="lg" className="rise flex flex-col gap-5" title="Internal note" titleAs="h2">
      <p className="t-body-sm -mt-2 text-ink-3">For the team only. It is never printed, exported or sent with the challan.</p>
      <QueryView query={query} what="The internal note">
        {(note) => <NoteEditor key={challanId} challanId={challanId} note={note} />}
      </QueryView>
    </GlassPanel>
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
  const saved = queryClient.getQueryData<InternalNote>(queryKeys.challans.note(challanId)) ?? note;

  if (!note.canUpdate) {
    return (
      <div className="flex flex-col gap-2">
        {note.body ? (
          <p className="t-body whitespace-pre-line text-ink [overflow-wrap:anywhere]">{note.body}</p>
        ) : (
          <p className="t-body text-ink-3">Nobody has written a note yet.</p>
        )}
        <p className="t-caption text-ink-3">You can read this note. Changing it is not part of your role.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {lost !== null ? (
        <Banner tone="amber" title="Someone else changed the note.">
          Their version is in the box. What you typed is kept below so you can copy it back in.
        </Banner>
      ) : null}
      <Textarea
        label="Note"
        hideLabel
        placeholder="Who to call at the gate, what was promised, anything the next person should know"
        rows={6}
        value={text}
        onChange={(value) => {
          setText(value);
          setLost(null);
          saver.change(value);
        }}
        onBlur={() => void saver.flush()}
      />
      <div aria-live="polite" className="flex min-h-6 flex-wrap items-center gap-3">
        {state.status === "failed" ? (
          <>
            <span className="t-caption text-ember-text">{lost !== null ? "Your text was not saved." : saveFailureText(state.error)}</span>
            {lost === null ? (
              <Button size="sm" variant="secondary" iconLeft="refresh" onPress={() => void saver.retry()}>
                Save again
              </Button>
            ) : null}
          </>
        ) : state.status === "saving" || state.status === "pending" ? (
          <span className="t-caption text-ink-3">Saving</span>
        ) : saved.updated_at ? (
          <span className="t-caption text-ink-3" data-save={state.status === "saved" ? "saved" : undefined}>
            Saved <DateText value={saved.updated_at} style="relative" />
            {saved.updated_by?.display_name ? ` by ${saved.updated_by.display_name}` : ""}
          </span>
        ) : (
          <span className="t-caption text-ink-3">Saves on its own as you type.</span>
        )}
      </div>
      {lost !== null ? <Textarea label="What you typed" isReadOnly rows={3} value={lost} /> : null}
    </div>
  );
}
