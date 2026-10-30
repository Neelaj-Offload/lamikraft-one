"use client";

/**
 * Remembers the detail records the user opens (`POST /api/v1/ui/recent-records`): the server keeps the
 * newest 20 per user, feeds onboarding ("Open a product record") through the `ui.recent_record` reader and
 * stores only records the user can read. Fire-and-forget: a failure never disturbs the page.
 */

import { useEffect } from "react";
import { api, unwrap, type ApiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type RecentRecordType = "sales.quote" | "sales.enquiry" | "catalogue.product";

export async function recordRecentRecord(
  resourceType: RecentRecordType,
  resourceId: string,
  client: ApiClient = api,
): Promise<components["schemas"]["RecentRecordRead"] | null> {
  try {
    return await unwrap(client.POST("/api/v1/ui/recent-records", { body: { resource_type: resourceType, resource_id: resourceId } }));
  } catch {
    return null;
  }
}

/** Records the record once per id, after it has loaded (`ready`), so an invisible or missing one is never sent. */
export function useRecentRecord(resourceType: RecentRecordType, resourceId: string | null | undefined, ready: boolean): void {
  useEffect(() => {
    if (!ready || !resourceId) return;
    void recordRecentRecord(resourceType, resourceId);
  }, [resourceType, resourceId, ready]);
}
