/**
 * Collaboration on any record: the internal note, attachments and the activity timeline (platform-2 item 4).
 * INTERIM(api-generate): untyped calls with hand-written types until the integrator regenerates the schema.
 */

import { api, requestUntyped } from "@/lib/api/client";

export interface Capability {
  allowed: boolean;
  reason_code: string | null;
}

export interface NoteRead {
  resource_type: string;
  resource_id: string;
  note_id: string | null;
  body: string;
  version: number;
  updated_at: string | null;
  updated_by: string | null;
  updated_by_name: string | null;
  capabilities: { update: Capability };
}

export interface AttachmentRead {
  id: string;
  resource_type: string;
  resource_id: string;
  file_id: string;
  title: string;
  role: "general" | "document" | "image";
  kind: string;
  content_type: string;
  size_bytes: number;
  content_url: string;
  thumbnail_url: string | null;
  created_at: string;
  created_by_name: string | null;
  version: number;
  capabilities: { update: Capability };
}

export interface AttachmentList {
  items: AttachmentRead[];
  capabilities: { add: Capability };
}

export interface ActivityItem {
  id: string;
  occurred_at: string;
  event_type: string;
  verb: string;
  summary: string;
  actor_name: string | null;
  actor_type: string;
  resource_type: string;
  resource_id: string | null;
  resource_label: string | null;
  path: string | null;
  changed_fields: string[];
}

export interface ActivityPage {
  items: ActivityItem[];
  next_cursor: string | null;
}

const C = "/api/v1/collab";

export const fetchNote = (type: string, id: string, signal?: AbortSignal) =>
  requestUntyped<NoteRead>(api, "get", `${C}/notes`, { params: { query: { resource_type: type, resource_id: id } }, signal });
export const saveNote = (type: string, id: string, body: string, expectedVersion: number) =>
  requestUntyped<NoteRead>(api, "put", `${C}/notes`, { params: { query: { resource_type: type, resource_id: id } }, body: { body, expected_version: expectedVersion } });

export const fetchAttachments = (type: string, id: string, signal?: AbortSignal) =>
  requestUntyped<AttachmentList>(api, "get", `${C}/attachments`, { params: { query: { resource_type: type, resource_id: id } }, signal });
export const addAttachment = (type: string, id: string, fileId: string, title: string | null) =>
  requestUntyped<AttachmentRead>(api, "post", `${C}/attachments`, { body: { resource_type: type, resource_id: id, file_id: fileId, title } });
export const removeAttachment = (attachmentId: string) => requestUntyped<void>(api, "delete", `${C}/attachments/${attachmentId}`);

export const fetchActivity = (params: { resourceType?: string | null; resourceId?: string | null; before?: string | null }, signal?: AbortSignal) =>
  requestUntyped<ActivityPage>(api, "get", `${C}/activity`, {
    params: { query: { resource_type: params.resourceType, resource_id: params.resourceId, before: params.before, limit: 30 } },
    signal,
  });

/** Uploads one file through platform/files (sniffed, size-limited, deduplicated); returns the file id. */
export async function uploadFile(file: File, purpose: "image" | "document"): Promise<string> {
  const form = new FormData();
  form.append("file", file, file.name);
  const result = await requestUntyped<{ id: string }>(api, "post", `/api/v1/files`, { params: { query: { purpose } }, body: form });
  return result.id;
}

export function purposeFor(file: File): "image" | "document" {
  return /^image\/(png|jpeg|gif|webp)$/.test(file.type) ? "image" : "document";
}

export function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}
