"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { RelativeTime } from "@/components/ui/format";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { toast } from "@/components/ui/toast";
import { isProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { addAttachment, fetchAttachments, formatBytes, purposeFor, removeAttachment, uploadFile } from "./api";

export const MAX_BYTES = { image: 15 * 1024 * 1024, document: 25 * 1024 * 1024 } as const;

/** Why a chosen file is refused before upload (the server checks again: type sniffing, limits, no SVG). */
export function preflight(file: File): string | null {
  const purpose = purposeFor(file);
  if (file.size > MAX_BYTES[purpose]) return `${file.name} is larger than ${MAX_BYTES[purpose] / (1024 * 1024)} MB.`;
  if (/\.svg$/i.test(file.name) || file.type === "image/svg+xml") return "SVG files cannot be attached.";
  return null;
}

export function uploadProblem(error: unknown): string {
  if (isProblemError(error)) {
    if (error.status === 413) return "That file is too large.";
    if (error.status === 415) return error.detail ?? "That kind of file cannot be attached.";
    if (error.status === 429) return "Too many uploads in a short time; try again shortly.";
    if (error.code === "already_attached") return "That file is already attached here.";
    return error.detail ?? error.title;
  }
  return "Upload failed. Try again.";
}

/** Files attached to a record: download (authorised by the record), add and remove when the record is editable. */
export function RecordAttachments({ resourceType, resourceId }: { resourceType: string; resourceId: string }) {
  const client = useQueryClient();
  const key = queryKeys.collab.attachments(resourceType, resourceId);
  const query = useQuery({ queryKey: key, queryFn: ({ signal }) => fetchAttachments(resourceType, resourceId, signal) });
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

  async function add(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true);
    try {
      for (const file of Array.from(files)) {
        const refusal = preflight(file);
        if (refusal) {
          toast.error(refusal);
          continue;
        }
        const fileId = await uploadFile(file, purposeFor(file));
        await addAttachment(resourceType, resourceId, fileId, null);
      }
      await client.invalidateQueries({ queryKey: queryKeys.collab.all() });
    } catch (err) {
      toast.error(uploadProblem(err));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  if (query.isPending) return <Loading label="attachments" variant="inline" />;
  if (query.isError) return <ErrorState error={query.error} what="attachments" onRetry={() => void query.refetch()} compact headingLevel={3} />;
  const canAdd = query.data.capabilities.add.allowed;
  return (
    <div className="flex flex-col gap-3">
      {query.data.items.length === 0 ? (
        <EmptyState title="No attachments" headingLevel={3}>
          {canAdd ? "Add drawings, photos or documents." : null}
        </EmptyState>
      ) : (
        <ul className="divide-y rounded-lg border">
          {query.data.items.map((a) => (
            <li key={a.id} className="flex items-center gap-3 px-3 py-2">
              {a.thumbnail_url ? (
                // eslint-disable-next-line @next/next/no-img-element -- same-origin, cookie-authenticated thumbnail
                <img src={a.thumbnail_url} alt="" className="size-12 rounded object-cover" />
              ) : null}
              <div className="flex min-w-0 flex-1 flex-col">
                <a href={a.content_url} className="focus-ring truncate rounded font-medium underline underline-offset-2">
                  {a.title}
                </a>
                <span className="text-sm text-ink-muted">
                  {a.kind.toUpperCase()} · {formatBytes(a.size_bytes)} · {a.created_by_name ?? "someone"} <RelativeTime value={a.created_at} />
                </span>
              </div>
              {a.capabilities.update.allowed ? (
                <Button
                  size="sm"
                  variant="quiet"
                  onPress={() =>
                    void removeAttachment(a.id)
                      .then(() => client.invalidateQueries({ queryKey: queryKeys.collab.all() }))
                      .catch((err: unknown) => toast.error(uploadProblem(err)))
                  }
                >
                  Remove
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {canAdd ? (
        <div>
          <input ref={input} type="file" multiple className="sr-only" id={`attach-${resourceId}`} aria-label="Choose files to attach" onChange={(e) => void add(e.target.files)} />
          <Button isPending={busy} pendingLabel="Uploading…" onPress={() => input.current?.click()}>
            Attach files
          </Button>
        </div>
      ) : null}
    </div>
  );
}
