"use client";

import { useState } from "react";
import { ProblemError } from "@/lib/api/errors";
import { useMediaCommand, useProductMedia, useUploadMedia, type MediaRead } from "~/data/products";
import { PageSection } from "~/shell/page";
import { ErrorBlock, LoadingBlock } from "~/shell/states";
import { Badge, ButtonLink, DateText, FileField, GlassPanel, Icon, IconButton, Menu, ReasonDialog, SegmentedControl, Switch, toast, type MenuItem } from "~/ui";
import { riseStyle } from "./motion";

/** Photos, packaging photos and documents of one product: add, pick the main photo, remove with a reason, bring back. */

type MediaType = MediaRead["media_type"];

const GROUPS: readonly { key: MediaType; title: string; empty: string }[] = [
  { key: "image", title: "Photos", empty: "No photos yet. The first one you add becomes the picture in the catalogue." },
  { key: "packaging_photo", title: "Packaging photos", empty: "No packaging photos yet." },
  { key: "document", title: "Documents", empty: "No documents yet. Data sheets and certificates go here." },
];

const UPLOAD_AS: { value: MediaType; label: string }[] = [
  { value: "image", label: "Photo" },
  { value: "packaging_photo", label: "Packaging photo" },
  { value: "document", label: "Document" },
];

function uploadProblem(error: unknown): string {
  if (error instanceof ProblemError) {
    if (error.status === 413) return "That file is too large. Photos can be up to 15 MB and documents up to 25 MB.";
    if (error.status === 415) return "That file type is not accepted. Use JPEG, PNG, GIF, WebP, PDF or an Office file.";
    if (error.code === "media_duplicate") return "That file is already attached to this product.";
    if (error.code === "not_an_image") return "Photos and packaging photos must be image files. Add this one as a document instead.";
  }
  return "The upload did not finish. Check your connection, then add the file again.";
}

function MediaCard({
  item,
  busy,
  index,
  onPrimary,
  onDelete,
  onRestore,
}: {
  item: MediaRead;
  busy: boolean;
  index: number;
  onPrimary: () => void;
  onDelete: () => void;
  onRestore: () => void;
}) {
  const isImage = Boolean(item.content_type?.startsWith("image/") && item.content_url);
  const name = item.file_name ?? item.original_filename ?? item.source_url_key ?? "File";
  const actions: MenuItem[] = [];
  if (item.capabilities.make_primary?.allowed) actions.push({ id: "primary", label: "Make this the main photo", icon: "star", onAction: onPrimary, isDisabled: busy });
  if (item.capabilities.restore?.allowed) actions.push({ id: "restore", label: "Bring it back", icon: "undo", onAction: onRestore, isDisabled: busy });
  if (item.capabilities.delete?.allowed) {
    if (actions.length > 0) actions.push({ id: "sep", separator: true });
    actions.push({ id: "delete", label: "Remove", icon: "trash", tone: "danger", onAction: onDelete, isDisabled: busy });
  }
  return (
    <GlassPanel as="li" padding="none" className="rise-plain flex flex-col overflow-hidden" style={{ ...riseStyle(index), opacity: item.deleted_at ? 0.72 : undefined }}>
      <div className="relative aspect-[4/3] w-full bg-sand-soft">
        {isImage ? (
          // eslint-disable-next-line @next/next/no-img-element -- the signed-in original from the API; there are no resized variants yet
          <img src={item.content_url!} alt={item.alt_text ?? name} loading="lazy" decoding="async" className="h-full w-full object-contain" />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-ink-3">
            <Icon name={item.media_type === "document" ? "fileText" : "image"} size={28} />
          </div>
        )}
        {item.is_primary ? (
          <span className="absolute left-3 top-3 rounded-pill bg-surface">
            <Badge tone="gold" size="sm" icon="star">
              Main photo
            </Badge>
          </span>
        ) : null}
      </div>
      <div className="flex flex-1 flex-col gap-3 p-4">
        <div className="flex min-w-0 items-start justify-between gap-2">
          <div className="flex min-w-0 flex-col gap-1">
            <p className="t-label m-0 truncate text-ink" title={name}>
              {name}
            </p>
            <p className="t-caption m-0 text-ink-3">
              {item.uploaded_by_name ?? "Imported"} · <DateText value={item.uploaded_at} style="relative" />
            </p>
          </div>
          {actions.length > 0 ? <Menu label={`Actions for ${name}`} items={actions} placement="bottom end" trigger={<IconButton icon="more" label={`Actions for ${name}`} variant="ghost" size="sm" />} /> : null}
        </div>
        {item.ingest_status === "external_only" ? <p className="t-caption m-0 text-ink-3">A reference only. The file itself is not stored here.</p> : null}
        {item.deleted_at ? <p className="t-caption m-0 text-ink-2">Removed: {item.delete_reason ?? "no reason given"}</p> : null}
        {item.content_url ? (
          <div className="mt-auto">
            <ButtonLink
              external
              href={item.content_url}
              variant="secondary"
              size="sm"
              iconLeft={item.previewable ? "eye" : "download"}
              target={item.previewable ? "_blank" : undefined}
              rel="noreferrer"
            >
              {item.previewable ? "Open" : "Download"}
            </ButtonLink>
          </div>
        ) : null}
      </div>
    </GlassPanel>
  );
}

export function ProductMedia({ productId, canManage }: { productId: string; canManage: boolean }) {
  const [showRemoved, setShowRemoved] = useState(false);
  const [mediaType, setMediaType] = useState<MediaType>("image");
  const [deleting, setDeleting] = useState<MediaRead | null>(null);
  const media = useProductMedia(productId, showRemoved);
  const upload = useUploadMedia(productId);
  const command = useMediaCommand();

  const add = (files: File[]) => {
    if (files.length === 0) return;
    upload.mutate(
      { files, mediaType },
      {
        onSuccess: (items) => toast.success(items.length === 1 ? "File added" : `${items.length} files added`),
        onError: (error) => toast.error("The file was not added", { description: uploadProblem(error) }),
      },
    );
  };
  const run = (item: MediaRead, action: "make-primary" | "restore") =>
    command.mutate(
      { item, action },
      {
        onSuccess: () => toast.success(action === "restore" ? "File brought back" : "Main photo changed"),
        onError: () => toast.error("That did not save", { description: "The file may have changed. Reload the page, then try again." }),
      },
    );

  return (
    <>
      <PageSection
        title="Media"
        description="Photos, packaging photos and documents. The main photo is the one the catalogue shows."
        action={<Switch label="Show removed files" isSelected={showRemoved} onChange={setShowRemoved} />}
      >
        {canManage ? (
          <GlassPanel padding="lg" className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h3 className="t-h4 m-0">Add files</h3>
              <SegmentedControl label="Add as" size="sm" value={mediaType} onChange={(value) => setMediaType(UPLOAD_AS.find((option) => option.value === value)?.value ?? "image")} options={UPLOAD_AS} />
            </div>
            <FileField
              label={mediaType === "document" ? "Documents to add" : "Photos to add"}
              multiple
              accept={mediaType === "document" ? undefined : ["image/*"]}
              maxBytes={(mediaType === "document" ? 25 : 15) * 1024 * 1024}
              onSelect={add}
              isDisabled={upload.isPending}
              help={
                upload.isPending
                  ? "Uploading…"
                  : mediaType === "document"
                    ? "PDF or Office files, up to 25 MB each."
                    : "JPEG, PNG, GIF or WebP, up to 15 MB each."
              }
            />
          </GlassPanel>
        ) : null}

        {media.isPending ? (
          <LoadingBlock label="Loading media" lines={5} />
        ) : media.isError || !media.data ? (
          <ErrorBlock error={media.error} what="Media" onRetry={() => void media.refetch()} />
        ) : (
          <>
            {GROUPS.map((group) => {
              const items = media.data[group.key];
              return (
                <section key={group.key} className="stack" aria-label={group.title}>
                  <h3 className="t-h4 m-0 flex items-baseline gap-2">
                    {group.title}
                    <span className="t-body-sm lk-tnum text-ink-3">{items.length}</span>
                  </h3>
                  {items.length > 0 ? (
                    <ul className="m-0 grid list-none grid-cols-1 gap-4 p-0 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                      {items.map((item, index) => (
                        <MediaCard
                          key={item.id}
                          item={item}
                          index={index}
                          busy={command.isPending}
                          onPrimary={() => run(item, "make-primary")}
                          onDelete={() => setDeleting(item)}
                          onRestore={() => run(item, "restore")}
                        />
                      ))}
                    </ul>
                  ) : (
                    <p className="t-body-sm m-0 text-ink-3">{group.empty}</p>
                  )}
                </section>
              );
            })}
            {showRemoved ? (
              <section className="stack" aria-label="Removed files">
                <h3 className="t-h4 m-0 flex items-baseline gap-2">
                  Removed
                  <span className="t-body-sm lk-tnum text-ink-3">{media.data.deleted.length}</span>
                </h3>
                {media.data.deleted.length > 0 ? (
                  <ul className="m-0 grid list-none grid-cols-1 gap-4 p-0 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                    {media.data.deleted.map((item, index) => (
                      <MediaCard key={item.id} item={item} index={index} busy={command.isPending} onPrimary={() => undefined} onDelete={() => undefined} onRestore={() => run(item, "restore")} />
                    ))}
                  </ul>
                ) : (
                  <p className="t-body-sm m-0 text-ink-3">Nothing has been removed from this product.</p>
                )}
              </section>
            ) : null}
          </>
        )}
      </PageSection>

      <ReasonDialog
        isOpen={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        tone="danger"
        title="Remove this file"
        description={deleting ? `${deleting.file_name ?? "The file"} leaves the product. It can be brought back from the removed files.` : undefined}
        confirmLabel="Remove file"
        reasonLabel="Why are you removing it?"
        reasonHelp="Kept with the file in the product's history."
        onConfirm={async (reason) => {
          if (!deleting) return;
          try {
            await command.mutateAsync({ item: deleting, action: "delete", reason });
            toast.success("File removed");
          } catch (error) {
            toast.error("The file was not removed", { description: "It may have changed. Reload the page, then try again." });
            throw error;
          }
        }}
      />
    </>
  );
}
