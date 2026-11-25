"use client";

/**
 * Data hooks for the sales CRM screens (leads, customers, enquiries, messages, samples) that the
 * old app kept inside its view files, plus the few reads the rebuilt screens add on top of the same
 * endpoints (one customer's samples and orders, counts for the pipeline filters).
 *
 * Everything here calls an endpoint that already exists and reuses the old query-key prefixes
 * (`["sales", …]`, `["orders", …]`, `["collab", …]`), so every command's invalidation still reaches it.
 */

import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  addAttachment,
  fetchActivity,
  fetchAttachments,
  fetchNote,
  purposeFor,
  removeAttachment,
  saveNote,
  uploadFile,
  type NoteRead,
} from "@/features/collab/api";
import type { OrderPage } from "@/features/orders/api";
import { fetchPartyQuotes, partyQuotesParams } from "@/features/parties/api";
import { ENQUIRIES_PATH, fetchQuoteStatusCounts } from "@/features/sales/api";
import { pageFrom } from "@/features/sales/resource-command";
import { SAMPLES_PATH, type Sample } from "@/features/samples/api";
import { api, requestUntyped, unwrap } from "@/lib/api/client";
import { conflictFromError, isProblemError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";

// ---- one customer's history ---------------------------------------------------------------------

/** How many rows a customer's record asks for in each of its history views. */
export const CUSTOMER_HISTORY_LIMIT = 25;

/** The customer's quotations, newest first, across everyone's the person may see (same key as the old record). */
export function useCustomerQuotes(partyId: string, enabled = true) {
  const params = partyQuotesParams(partyId);
  return useQuery({
    queryKey: ["sales", "quotes", { party_id: partyId, scope: params.scope }] as const,
    queryFn: ({ signal }) => fetchPartyQuotes(partyId, signal),
    enabled,
  });
}

/** Samples sent to one customer (`GET /sales/samples?party_id=`). */
export function useCustomerSamples(partyId: string, enabled = true) {
  return useQuery({
    queryKey: ["sales", "samples", { party_id: partyId }] as const,
    queryFn: async ({ signal }) => {
      const raw = await requestUntyped<unknown>(api, "get", SAMPLES_PATH, {
        params: { query: { party_id: partyId, offset: 0, limit: CUSTOMER_HISTORY_LIMIT } },
        signal,
      });
      return pageFrom<Sample>(raw, "samples");
    },
    enabled,
  });
}

/** Orders placed by one customer (`GET /orders/sales-orders?party_id=`). */
export function useCustomerOrders(partyId: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.orders.list({ party_id: partyId }),
    queryFn: ({ signal }): Promise<OrderPage> =>
      unwrap(api.GET("/api/v1/orders/sales-orders", { params: { query: { party_id: partyId, limit: CUSTOMER_HISTORY_LIMIT, offset: 0 } }, signal })),
    enabled,
  });
}

// ---- counts for pipelines and the hub ------------------------------------------------------------

/** One integer per sample status (`GET /sales/samples/status-counts`), for everyone or for one customer. */
export function useSampleStatusCounts(enabled = true, partyId: string | null = null) {
  return useQuery({
    queryKey: ["sales", "sample-status-counts", { party_id: partyId }] as const,
    queryFn: ({ signal }): Promise<Record<string, number>> =>
      unwrap(api.GET("/api/v1/sales/samples/status-counts", { params: { query: { party_id: partyId ?? undefined } }, signal })),
    enabled,
  });
}

/** One integer per quotation status for one customer (`GET /sales/quotes/status-counts?party_id=`). */
export function useCustomerQuoteCounts(partyId: string, enabled = true) {
  return useQuery({
    queryKey: ["sales", "quote-status-counts", { party_id: partyId }] as const,
    queryFn: ({ signal }) => fetchQuoteStatusCounts({ scope: "all", party_id: partyId }, signal),
    enabled,
  });
}

/** How many enquiries sit in one status: the list endpoint's `total`, asked for with a one-row page. */
export function useEnquiryCount(status: string, enabled = true) {
  return useQuery({
    queryKey: ["sales", "enquiry-count", { status }] as const,
    queryFn: async ({ signal }) => {
      const raw = await requestUntyped<unknown>(api, "get", ENQUIRIES_PATH, { params: { query: { status, offset: 0, limit: 1 } }, signal });
      return pageFrom<{ id: string }>(raw, "enquiries").total;
    },
    enabled,
  });
}

/** How many sales orders are in one status: the list endpoint's `total`, asked for with a one-row page. */
export function useOrderCount(status: "draft" | "confirmed" | "on_hold" | "completed" | "cancelled", enabled = true) {
  return useQuery({
    queryKey: queryKeys.orders.list({ status, count_only: true }),
    queryFn: async ({ signal }) => (await unwrap(api.GET("/api/v1/orders/sales-orders", { params: { query: { status: [status], limit: 1, offset: 0 } }, signal }))).total,
    enabled,
  });
}

// ---- notes, files and activity on a record ---------------------------------------------------------

export const NOTE_AUTOSAVE_MS = 1000;
export type NoteSaveState = "idle" | "dirty" | "saving" | "saved" | "conflict" | "error";

/**
 * The internal note of a record: saves a second after typing stops with the version the person
 * saw; on a 409 both texts are kept so nothing typed is lost (the old `RecordNote` behaviour).
 */
export function useRecordNote(resourceType: string, resourceId: string) {
  const client = useQueryClient();
  const key = queryKeys.collab.note(resourceType, resourceId);
  const query = useQuery({ queryKey: key, queryFn: ({ signal }) => fetchNote(resourceType, resourceId, signal) });
  const [text, setText] = useState<string | null>(null);
  const [state, setState] = useState<NoteSaveState>("idle");
  const [theirs, setTheirs] = useState<NoteRead | null>(null);
  const timer = useRef<number | null>(null);
  const version = useRef(0);

  useEffect(() => {
    if (query.data && text === null) version.current = query.data.version;
  }, [query.data, text]);
  useEffect(
    () => () => {
      if (timer.current) window.clearTimeout(timer.current);
    },
    [],
  );

  const save = useCallback(
    async (body: string) => {
      setState("saving");
      try {
        const saved = await saveNote(resourceType, resourceId, body, version.current);
        version.current = saved.version;
        client.setQueryData(key, saved);
        setState("saved");
      } catch (error) {
        const conflict = conflictFromError(error);
        if (conflict && conflict.current && typeof conflict.current === "object") {
          setTheirs(conflict.current as NoteRead);
          setState("conflict");
        } else setState("error");
      }
    },
    // `key` is derived from the two ids.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [client, resourceId, resourceType],
  );

  const value = text ?? query.data?.body ?? "";
  const change = (next: string) => {
    setText(next);
    setState("dirty");
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void save(next), NOTE_AUTOSAVE_MS);
  };
  const useTheirs = () => {
    if (!theirs) return;
    version.current = theirs.version;
    setText(theirs.body);
    client.setQueryData(key, theirs);
    setTheirs(null);
    setState("idle");
  };
  const keepMine = () => {
    if (!theirs) return;
    version.current = theirs.version;
    setTheirs(null);
    void save(value);
  };

  return { query, value, state, theirs, change, useTheirs, keepMine, retry: () => void save(value) };
}

export const ATTACHMENT_MAX_BYTES = { image: 15 * 1024 * 1024, document: 25 * 1024 * 1024 } as const;

/** Why a chosen file is refused before upload (the server checks again). */
export function attachmentRefusal(file: File): string | null {
  const purpose = purposeFor(file);
  if (file.size > ATTACHMENT_MAX_BYTES[purpose]) return `${file.name} is larger than ${ATTACHMENT_MAX_BYTES[purpose] / (1024 * 1024)} MB. Choose a smaller file.`;
  if (/\.svg$/i.test(file.name) || file.type === "image/svg+xml") return "SVG files cannot be attached. Export it as PNG or PDF first.";
  return null;
}

export function attachmentProblem(error: unknown): string {
  if (isProblemError(error)) {
    if (error.status === 413) return "That file is too large to attach.";
    if (error.status === 415) return error.detail ?? "That kind of file cannot be attached.";
    if (error.status === 429) return "Too many uploads in a short time. Wait a moment, then try again.";
    if (error.code === "already_attached") return "That file is already attached here.";
    return error.detail ?? error.title;
  }
  return "The upload did not finish. Check your connection, then try again.";
}

/** Files attached to a record: list, add (upload then attach) and remove. */
export function useRecordAttachments(resourceType: string, resourceId: string) {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: queryKeys.collab.attachments(resourceType, resourceId),
    queryFn: ({ signal }) => fetchAttachments(resourceType, resourceId, signal),
  });
  const [busy, setBusy] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);

  /** Uploads and attaches each file; returns the problems to show (an empty list when all went through). */
  const add = async (files: readonly File[]): Promise<string[]> => {
    if (files.length === 0) return [];
    const problems: string[] = [];
    setBusy(true);
    try {
      for (const file of files) {
        const refusal = attachmentRefusal(file);
        if (refusal) {
          problems.push(refusal);
          continue;
        }
        try {
          const fileId = await uploadFile(file, purposeFor(file));
          await addAttachment(resourceType, resourceId, fileId, null);
        } catch (error) {
          problems.push(attachmentProblem(error));
        }
      }
      await client.invalidateQueries({ queryKey: queryKeys.collab.all() });
    } finally {
      setBusy(false);
    }
    return problems;
  };

  const remove = async (attachmentId: string): Promise<void> => {
    setRemoving(attachmentId);
    try {
      await removeAttachment(attachmentId);
      await client.invalidateQueries({ queryKey: queryKeys.collab.all() });
    } finally {
      setRemoving(null);
    }
  };

  return { query, add, remove, busy, removing };
}

/** A record's activity, newest first, 30 at a time. */
export function useRecordActivity(resourceType: string, resourceId: string) {
  return useInfiniteQuery({
    queryKey: queryKeys.collab.activity({ resourceType, resourceId }),
    queryFn: ({ pageParam, signal }) => fetchActivity({ resourceType, resourceId, before: pageParam }, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });
}
