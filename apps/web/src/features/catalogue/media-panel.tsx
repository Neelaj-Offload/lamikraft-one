"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useRef, useState, type DragEvent } from "react";
import { Button, unavailableWhen } from "@/components/ui/button";
import { LocalDateTime } from "@/components/ui/format";
import { ReasonDialog } from "@/components/ui/reason-dialog";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Loading } from "@/components/ui/states";
import { toast } from "@/components/ui/toast";
import { ProblemError } from "@/lib/api/errors";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { cx } from "@/lib/cx";
import { deleteMedia, fetchMedia, mediaCommand, uploadMedia } from "./api";
import type { MediaRead } from "./types";

const GROUPS: readonly { key: "image" | "packaging_photo" | "document"; label: string }[] = [
  { key: "image", label: "Images" },
  { key: "packaging_photo", label: "Packaging photos" },
  { key: "document", label: "Documents" },
];

export function uploadErrorText(error: unknown): string {
  if (error instanceof ProblemError) {
    if (error.status === 413) return "The file is too large (images 15 MB, documents 25 MB).";
    if (error.status === 415) return "This file type is not accepted (JPEG, PNG, GIF, WebP, PDF, Office files).";
    if (error.code === "media_duplicate") return "This file is already attached to the product.";
    if (error.code === "not_an_image") return "Images and packaging photos must be image files.";
  }
  return "The upload failed.";
}

function MediaItem({
  item,
  onPrimary,
  onDelete,
  onRestore,
  busy,
}: {
  item: MediaRead;
  onPrimary: () => void;
  onDelete: () => void;
  onRestore: () => void;
  busy: boolean;
}) {
  const isImage = item.content_type?.startsWith("image/") && item.content_url;
  return (
    <li className={cx("flex flex-col gap-2 rounded-md border p-3", item.deleted_at && "opacity-70")}>
      {isImage ? (
        // eslint-disable-next-line @next/next/no-img-element -- same-origin authenticated original (no variants yet)
        <img src={item.content_url!} alt={item.alt_text ?? item.file_name ?? ""} className="h-32 w-full rounded-sm object-contain" loading="lazy" />
      ) : null}
      <div className="flex flex-col gap-0.5 text-sm">
        <span className="truncate font-semibold">{item.file_name ?? item.source_url_key ?? "File"}</span>
        <span className="text-ink-muted">
          {item.is_primary ? "Primary · " : ""}
          {item.ingest_status === "external_only" ? "Reference only (not stored) · " : ""}
          {item.uploaded_by_name ?? "Import"} · <LocalDateTime value={item.uploaded_at} />
        </span>
        {item.deleted_at ? <span className="text-ink-muted">Deleted: {item.delete_reason}</span> : null}
      </div>
      <div className="flex flex-wrap gap-2">
        {item.content_url ? (
          <a href={item.content_url} className="text-sm underline" target={item.previewable ? "_blank" : undefined} rel="noreferrer">
            {item.previewable ? "Preview" : "Download"}
          </a>
        ) : null}
        {item.capabilities.make_primary?.allowed ? (
          <Button size="sm" onPress={onPrimary} {...unavailableWhen(busy ? "Working…" : null)}>
            Make primary
          </Button>
        ) : null}
        {item.capabilities.delete?.allowed ? (
          <Button size="sm" variant="danger" onPress={onDelete} {...unavailableWhen(busy ? "Working…" : null)}>
            Delete
          </Button>
        ) : null}
        {item.capabilities.restore?.allowed ? (
          <Button size="sm" onPress={onRestore} {...unavailableWhen(busy ? "Working…" : null)}>
            Restore
          </Button>
        ) : null}
      </div>
    </li>
  );
}

/** Media tab (UI-43, LM-23..26): button and drag-and-drop upload, groups, primary toggle, preview, download, delete
 * with a reason and restore. Uploads go to the platform files store first (sniffed, size limited). */
export function MediaPanel({ productId, canManage }: { productId: string; canManage: boolean }) {
  const queryClient = useQueryClient();
  const [showDeleted, setShowDeleted] = useState(false);
  const [mediaType, setMediaType] = useState<MediaRead["media_type"]>("image");
  const [deleting, setDeleting] = useState<MediaRead | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const inputId = useId();
  const media = useQuery({
    queryKey: queryKeys.catalogue.media(productId, showDeleted),
    queryFn: ({ signal }) => fetchMedia(productId, showDeleted, signal),
  });
  const refresh = () => {
    for (const key of invalidationMap["catalogue.changed"]) void queryClient.invalidateQueries({ queryKey: key });
  };
  const upload = useMutation({
    mutationFn: (files: File[]) => Promise.all(files.map((file) => uploadMedia(productId, file, mediaType))),
    onSuccess: (items) => {
      refresh();
      toast.success(items.length === 1 ? "File attached" : `${items.length} files attached`);
    },
    onError: (error) => toast.error(uploadErrorText(error)),
  });
  const command = useMutation({
    mutationFn: ({ item, action, reason }: { item: MediaRead; action: "make-primary" | "restore" | "delete"; reason?: string }) =>
      action === "delete" ? deleteMedia(item, reason ?? "") : mediaCommand(item, action),
    onSuccess: () => {
      setDeleting(null);
      refresh();
    },
    onError: () => toast.error("The change was not saved; reload and try again"),
  });
  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    const files = [...event.dataTransfer.files];
    if (files.length && canManage) upload.mutate(files);
  };

  return (
    <div className="flex flex-col gap-6">
      {canManage ? (
        <div
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cx("flex flex-col gap-3 rounded-md border border-dashed p-4 md:flex-row md:items-end", dragging && "border-forest bg-forest-tint")}
        >
          <Select
            label="Upload as"
            options={[
              { id: "image", label: "Image" },
              { id: "packaging_photo", label: "Packaging photo" },
              { id: "document", label: "Document" },
            ]}
            value={mediaType}
            onChange={(v) => setMediaType((v as MediaRead["media_type"]) ?? "image")}
          />
          <div className="flex flex-col gap-1.5">
            <label htmlFor={inputId} className="text-sm font-semibold">
              Files
            </label>
            <input
              ref={inputRef}
              id={inputId}
              type="file"
              multiple
              className="text-sm"
              onChange={(event) => {
                const files = [...(event.target.files ?? [])];
                if (files.length) upload.mutate(files);
                event.target.value = "";
              }}
            />
          </div>
          <p className="text-sm text-ink-muted md:ms-auto">{upload.isPending ? "Uploading…" : "Or drop files here."}</p>
        </div>
      ) : null}
      {media.isPending ? (
        <Loading label="media" />
      ) : media.isError ? (
        <ErrorState error={media.error} what="the media" onRetry={() => void media.refetch()} compact />
      ) : (
        <>
          {GROUPS.map((group) => {
            const items = media.data[group.key];
            return (
              <section key={group.key} aria-label={group.label} className="flex flex-col gap-3">
                <h2 className="text-base font-semibold">
                  {group.label} <span className="text-sm font-normal text-ink-muted tabular">{items.length}</span>
                </h2>
                {items.length ? (
                  <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    {items.map((item) => (
                      <MediaItem
                        key={item.id}
                        item={item}
                        busy={command.isPending}
                        onPrimary={() => command.mutate({ item, action: "make-primary" })}
                        onDelete={() => setDeleting(item)}
                        onRestore={() => command.mutate({ item, action: "restore" })}
                      />
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-ink-muted">None.</p>
                )}
              </section>
            );
          })}
          <div>
            <Button size="sm" variant="quiet" onPress={() => setShowDeleted((v) => !v)}>
              {showDeleted ? "Hide deleted" : "Show deleted"}
            </Button>
          </div>
          {showDeleted ? (
            media.data.deleted.length ? (
              <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-label="Deleted media">
                {media.data.deleted.map((item) => (
                  <MediaItem key={item.id} item={item} busy={command.isPending} onPrimary={() => undefined} onDelete={() => undefined}
                    onRestore={() => command.mutate({ item, action: "restore" })} />
                ))}
              </ul>
            ) : (
              <EmptyState title="Nothing deleted" />
            )
          ) : null}
        </>
      )}
      <ReasonDialog
        title="Delete media"
        description={deleting?.file_name ?? undefined}
        requireNote
        noteLabel="Reason"
        confirmLabel="Delete"
        isOpen={deleting !== null}
        isPending={command.isPending}
        onOpenChange={(open) => (open ? undefined : setDeleting(null))}
        onConfirm={(_code, note) => deleting && command.mutate({ item: deleting, action: "delete", reason: note.trim() })}
      />
    </div>
  );
}
