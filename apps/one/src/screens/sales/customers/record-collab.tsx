"use client";

import { useRef, useState } from "react";
import { formatBytes } from "@/features/collab/api";
import { isProblemError } from "@/lib/api/errors";
import { useRecordActivity, useRecordAttachments, useRecordNote, type NoteSaveState } from "~/data/sales-crm";
import { ErrorBlock, LoadingBlock, NotPermitted } from "~/shell/states";
import { Banner, Button, ConfirmDialog, DateText, EmptyState, GlassPanel, Icon, IconButton, Textarea, Timeline, toast } from "~/ui";
import { humanise, stagger } from "./labels";

/**
 * Notes, files and activity for any record whose type the server knows (`parties.party`,
 * `sales.enquiry`, `sales.sample`). The server authorises each through the record itself, so the
 * panels only render controls the response allows.
 */

function noteStatus(state: NoteSaveState, changedBy: string | null): string {
  switch (state) {
    case "dirty":
      return "Unsaved changes";
    case "saving":
      return "Saving";
    case "saved":
      return "Saved";
    case "conflict":
      return "Someone else changed this note while you were typing.";
    case "error":
      return "Not saved. Check your connection; your text is kept here.";
    default:
      return changedBy ? `Last changed by ${changedBy}` : "Saves as you type";
  }
}

export function RecordNote({ resourceType, resourceId, subject }: { resourceType: string; resourceId: string; subject: string }) {
  const note = useRecordNote(resourceType, resourceId);
  if (note.query.isPending) return <LoadingBlock label="Loading the note" lines={5} />;
  if (note.query.isError) return <ErrorBlock error={note.query.error} what="The note" onRetry={() => void note.query.refetch()} />;
  const data = note.query.data;
  const editable = data.capabilities.update.allowed;
  return (
    <GlassPanel as="section" padding="lg" title="Internal note" titleAs="h2" className="flex flex-col gap-4">
      <Textarea
        label="Internal note"
        hideLabel
        rows={6}
        value={note.value}
        onChange={note.change}
        isReadOnly={!editable}
        placeholder={editable ? `What the team should know about ${subject}: how they like to be reached, what was agreed, what to avoid.` : "No note yet."}
        help="Only people who can open this record see it. It never prints on a document."
      />
      <p className="t-caption flex flex-wrap items-center gap-2 text-ink-3" role="status" aria-live="polite">
        {editable ? (
          <>
            <Icon name={note.state === "error" || note.state === "conflict" ? "alert" : note.state === "saved" ? "check" : "clock"} size={14} />
            <span>{noteStatus(note.state, data.updated_by_name)}</span>
            {note.state === "idle" && data.updated_at ? <DateText value={data.updated_at} style="relative" /> : null}
            {note.state === "error" ? (
              <Button variant="secondary" size="sm" onPress={note.retry}>
                Save again
              </Button>
            ) : null}
          </>
        ) : (
          <>
            <Icon name="lock" size={14} />
            <span>Read only. Your role cannot edit this record.</span>
          </>
        )}
      </p>
      {note.state === "conflict" && note.theirs ? (
        <Banner tone="amber" title={`${note.theirs.updated_by_name ?? "Someone"} saved a different version.`}>
          <span className="mt-2 block whitespace-pre-wrap rounded-md border border-line bg-surface p-3 text-ink">{note.theirs.body}</span>
          <span className="mt-3 flex flex-wrap gap-2">
            <Button variant="secondary" size="sm" onPress={note.useTheirs}>
              Use their text
            </Button>
            <Button variant="inverse" size="sm" onPress={note.keepMine}>
              Keep mine
            </Button>
          </span>
        </Banner>
      ) : null}
    </GlassPanel>
  );
}

export function RecordFiles({ resourceType, resourceId }: { resourceType: string; resourceId: string }) {
  const files = useRecordAttachments(resourceType, resourceId);
  const input = useRef<HTMLInputElement>(null);
  const [toRemove, setToRemove] = useState<{ id: string; title: string } | null>(null);

  if (files.query.isPending) return <LoadingBlock label="Loading files" lines={4} />;
  if (files.query.isError) return <ErrorBlock error={files.query.error} what="Files" onRetry={() => void files.query.refetch()} />;
  const data = files.query.data;
  const canAdd = data.capabilities.add.allowed;

  const choose = async (list: FileList | null) => {
    const chosen = list ? Array.from(list) : [];
    const problems = await files.add(chosen);
    if (input.current) input.current.value = "";
    for (const problem of problems) toast.error("A file was not attached", { description: problem });
    const added = chosen.length - problems.length;
    if (added > 0) toast.success(added === 1 ? "File attached" : `${added} files attached`);
  };

  const attach = canAdd ? (
    <>
      <input ref={input} type="file" multiple className="lk-sr-only" tabIndex={-1} aria-label="Choose files to attach" onChange={(event) => void choose(event.target.files)} />
      <Button variant="secondary" size="sm" iconLeft="paperclip" loading={files.busy} onPress={() => input.current?.click()}>
        Attach files
      </Button>
    </>
  ) : undefined;

  return (
    <GlassPanel as="section" padding="lg" title="Files" titleAs="h2" action={data.items.length > 0 ? attach : undefined} className="flex flex-col gap-4">
      {data.items.length === 0 ? (
        <EmptyState
          compact
          icon="paperclip"
          title="No files yet"
          text={canAdd ? "Attach drawings, photos or signed documents. Images up to 15 MB, documents up to 25 MB." : "Nothing has been attached to this record."}
          actions={attach}
        />
      ) : (
        <ul className="m-0 flex list-none flex-col p-0">
          {data.items.map((file, index) => (
            <li key={file.id} className="rise-plain flex min-w-0 items-center gap-3 border-line py-3 [&:not(:first-child)]:border-t" style={stagger(index)}>
              {file.thumbnail_url ? (
                // eslint-disable-next-line @next/next/no-img-element -- same-origin, cookie-authenticated thumbnail
                <img src={file.thumbnail_url} alt="" className="size-11 flex-none rounded-md object-cover" />
              ) : (
                <span className="grid size-11 flex-none place-items-center rounded-md bg-gold-soft text-gold-strong">
                  <Icon name="fileText" size={18} />
                </span>
              )}
              <span className="flex min-w-0 flex-1 flex-col">
                <a href={file.content_url} className="lk-link t-label truncate" title={file.title}>
                  {file.title}
                </a>
                <span className="t-caption text-ink-3">
                  {file.kind.toUpperCase()} · {formatBytes(file.size_bytes)} · {file.created_by_name ?? "Someone"}, <DateText value={file.created_at} style="relative" />
                </span>
              </span>
              {file.capabilities.update.allowed ? (
                <IconButton icon="trash" label={`Remove ${file.title}`} variant="ghost" size="sm" onPress={() => setToRemove({ id: file.id, title: file.title })} />
              ) : null}
            </li>
          ))}
        </ul>
      )}
      <ConfirmDialog
        isOpen={toRemove !== null}
        onOpenChange={(open) => {
          if (!open) setToRemove(null);
        }}
        tone="danger"
        title="Remove this file"
        description={toRemove ? `${toRemove.title} is taken off this record. The team can no longer open it from here.` : undefined}
        confirmLabel="Remove file"
        onConfirm={async () => {
          if (!toRemove) return;
          try {
            await files.remove(toRemove.id);
            toast.success("File removed");
          } catch (error) {
            toast.error("The file was not removed", { description: isProblemError(error) ? (error.detail ?? error.title) : "Check your connection, then try again." });
            throw error;
          }
        }}
      />
    </GlassPanel>
  );
}

export function RecordActivity({ resourceType, resourceId }: { resourceType: string; resourceId: string }) {
  const query = useRecordActivity(resourceType, resourceId);
  if (query.isPending) return <LoadingBlock label="Loading activity" lines={6} />;
  if (query.isError) {
    if (isProblemError(query.error) && query.error.status === 403) {
      return (
        <GlassPanel padding="lg">
          <NotPermitted what="Activity" icon="history" />
        </GlassPanel>
      );
    }
    return <ErrorBlock error={query.error} what="Activity" onRetry={() => void query.refetch()} />;
  }
  const items = query.data.pages.flatMap((page) => page.items);
  return (
    <GlassPanel as="section" padding="lg" title="Activity" titleAs="h2" className="flex flex-col gap-5">
      {items.length === 0 ? (
        <EmptyState compact icon="history" title="Nothing recorded yet" text="Changes to this record appear here as the team makes them." />
      ) : (
        <Timeline
          label="Activity on this record"
          items={items.map((item) => ({
            id: item.id,
            title: item.summary,
            meta: <DateText value={item.occurred_at} style="dayTime" />,
            body: [item.actor_name ?? "Someone", item.changed_fields.length ? `changed ${item.changed_fields.map((field) => humanise(field).toLowerCase()).join(", ")}` : null].filter(Boolean).join(" · "),
          }))}
        />
      )}
      {query.hasNextPage ? (
        <div>
          <Button variant="secondary" size="sm" loading={query.isFetchingNextPage} onPress={() => void query.fetchNextPage()}>
            Show older activity
          </Button>
        </div>
      ) : null}
    </GlassPanel>
  );
}
