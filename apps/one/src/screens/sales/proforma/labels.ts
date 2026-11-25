import type { ProformaStatus } from "~/data/proforma";
import type { Tone } from "~/ui/badge";

export const PROFORMA_STATUSES: readonly ProformaStatus[] = ["draft", "issued", "cancelled"];

export const PROFORMA_STATUS_LABEL: Record<ProformaStatus, string> = { draft: "Draft", issued: "Issued", cancelled: "Cancelled" };
export const PROFORMA_STATUS_TONE: Record<ProformaStatus, Tone> = { draft: "amber", issued: "leaf", cancelled: "neutral" };
