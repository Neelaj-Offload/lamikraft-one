"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { RelativeTime } from "@/components/ui/format";
import { ErrorState, Loading } from "@/components/ui/states";
import { TextArea } from "@/components/ui/text-field";
import { conflictFromError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { fetchNote, saveNote, type NoteRead } from "./api";

export const AUTOSAVE_MS = 1000;

export type SaveState = "idle" | "dirty" | "saving" | "saved" | "conflict" | "error";

export function statusLine(state: SaveState, note: NoteRead | undefined): string {
  switch (state) {
    case "dirty":
      return "Unsaved changes…";
    case "saving":
      return "Saving…";
    case "saved":
      return "Saved.";
    case "conflict":
      return "Someone else changed this note while you were typing.";
    case "error":
      return "Not saved. Check your connection; your text is kept here.";
    default:
      return note?.updated_by_name ? `Last changed by ${note.updated_by_name}.` : "";
  }
}

/**
 * The internal note of a record (PARITY UI-66 / LM-99): autosaves a second after typing stops, with an optimistic
 * version; a 409 shows both texts so nothing typed is lost. Read-only when the record cannot be edited.
 */
export function RecordNote({ resourceType, resourceId }: { resourceType: string; resourceId: string }) {
  const client = useQueryClient();
  const key = queryKeys.collab.note(resourceType, resourceId);
  const query = useQuery({ queryKey: key, queryFn: ({ signal }) => fetchNote(resourceType, resourceId, signal) });
  const [text, setText] = useState<string | null>(null);
  const [state, setState] = useState<SaveState>("idle");
  const [theirs, setTheirs] = useState<NoteRead | null>(null);
  const timer = useRef<number | null>(null);
  const version = useRef<number>(0);

  useEffect(() => {
    if (query.data && text === null) version.current = query.data.version;
  }, [query.data, text]);
  useEffect(() => () => {
    if (timer.current) window.clearTimeout(timer.current);
  }, []);

  async function save(body: string) {
    setState("saving");
    try {
      const saved = await saveNote(resourceType, resourceId, body, version.current);
      version.current = saved.version;
      client.setQueryData(key, saved);
      setState("saved");
    } catch (err) {
      const conflict = conflictFromError(err);
      if (conflict && conflict.current && typeof conflict.current === "object") {
        setTheirs(conflict.current as NoteRead);
        setState("conflict");
      } else setState("error");
    }
  }

  if (query.isPending) return <Loading label="the internal note" variant="inline" />;
  if (query.isError) return <ErrorState error={query.error} what="the internal note" onRetry={() => void query.refetch()} compact headingLevel={3} />;
  const editable = query.data.capabilities.update.allowed;
  const value = text ?? query.data.body;

  return (
    <div className="flex flex-col gap-2">
      <TextArea
        label="Internal note"
        description="Only people who can open this record see it; it is never printed."
        value={value}
        rows={5}
        isReadOnly={!editable}
        onChange={(next) => {
          setText(next);
          setState("dirty");
          if (timer.current) window.clearTimeout(timer.current);
          timer.current = window.setTimeout(() => void save(next), AUTOSAVE_MS);
        }}
      />
      <p className="text-sm text-ink-muted" role="status" aria-live="polite">
        {editable ? statusLine(state, query.data) : "Read only: you cannot edit this record."}
        {state === "idle" && query.data.updated_at ? (
          <>
            {" "}
            <RelativeTime value={query.data.updated_at} />
          </>
        ) : null}
      </p>
      {state === "conflict" && theirs ? (
        <div role="alert" className="flex flex-col gap-2 rounded-lg border border-warning/50 bg-warning/5 p-3">
          <p className="font-semibold">{theirs.updated_by_name ?? "Someone"} saved a different version.</p>
          <p className="text-sm">Their text:</p>
          <pre className="max-h-40 overflow-auto rounded bg-surface p-2 text-sm whitespace-pre-wrap">{theirs.body}</pre>
          <div className="flex flex-wrap gap-2">
            <Button
              onPress={() => {
                version.current = theirs.version;
                setText(theirs.body);
                client.setQueryData(key, theirs);
                setTheirs(null);
                setState("idle");
              }}
            >
              Use their text
            </Button>
            <Button
              variant="primary"
              onPress={() => {
                version.current = theirs.version;
                setTheirs(null);
                void save(value);
              }}
            >
              Keep mine
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
