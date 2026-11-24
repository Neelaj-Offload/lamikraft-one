/**
 * Words for autosave: why a typed quantity cannot be sent, and why a save failed. A plain module
 * (no hooks) shared by the lines and the internal note.
 */

import { conflictFromError, isNetworkError, ProblemError } from "@/lib/api/errors";
import { quantityProblem } from "@/features/challans/line-save";

const QUANTITY_PROBLEM: Record<string, string> = {
  required: "Enter a quantity. To drop the line, remove it instead.",
  invalid: "Enter a number with up to 4 decimal places, for example 12 or 2.5.",
  not_positive: "Enter more than zero. To drop the line, remove it instead.",
};

/** Why a typed quantity is not sent, or null when it can be. */
export function quantityText(raw: string): string | null {
  const problem = quantityProblem(raw);
  return problem ? (QUANTITY_PROBLEM[problem] ?? null) : null;
}

/** The inline message for a failed save: the server's field message, a conflict, offline, or the problem itself. */
export function saveFailureText(error: unknown): string {
  if (error instanceof ProblemError && error.status === 422) return error.validationIssues[0]?.msg ?? error.detail ?? error.title;
  if (conflictFromError(error)) return "Someone changed this challan while you typed. The latest version is shown. Enter your value again.";
  if (isNetworkError(error)) return "You are offline, so this was not saved. It is sent again when you retry.";
  if (error instanceof ProblemError) return [error.detail ?? error.title, error.request_id ? `Reference ${error.request_id}.` : null].filter(Boolean).join(" ");
  return "This was not saved. Try again.";
}
