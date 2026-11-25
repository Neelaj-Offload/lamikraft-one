/**
 * Entering sample history (module 2, spec 2026-11-25-customers-samples-design.md): a sample recorded as already
 * sent (`sent_on`) and steps dated when they really happened (`occurred_on`). The old app's request builders do not
 * know these fields, so this module adds them on top of the same endpoints.
 */

import { recordFrom } from "@/features/sales/resource-command";
import { SAMPLES_PATH, sampleTransitionBody, type Sample, type SampleTransitionRequest } from "@/features/samples/api";
import { api, idempotencyHeaders, requestUntyped, type ApiClient } from "@/lib/api/client";

export interface DatedTransition extends SampleTransitionRequest {
  /** `YYYY-MM-DD`; omitted means now. Only dispatch, deliver and record_feedback take a date. */
  occurred_on?: string | null;
}

export const DATED_ACTIONS = new Set(["dispatch", "deliver", "record_feedback"]);

export function datedTransitionBody(sample: Pick<Sample, "version">, request: DatedTransition): Record<string, unknown> {
  const body = sampleTransitionBody(sample, request);
  if (request.occurred_on && DATED_ACTIONS.has(request.action)) body.occurred_on = request.occurred_on;
  return body;
}

export async function transitionSampleDated(
  sample: Pick<Sample, "id" | "version">,
  request: DatedTransition,
  key: string,
  client: ApiClient = api,
): Promise<Sample> {
  const path = `${SAMPLES_PATH}/${encodeURIComponent(sample.id)}/transitions` as `/api/v1/${string}`;
  return recordFrom<Sample>(
    await requestUntyped<unknown>(client, "post", path, { body: datedTransitionBody(sample, request), headers: idempotencyHeaders(key) }),
    "sample",
  );
}
