"use client";

/**
 * Data for Settings: AI (status, usage, routing, traces), Integrations and WhatsApp.
 *
 * The wire calls, parsers and query keys are the old app's (`@/features/ai-admin/api`,
 * `@/features/settings/api`, `@/features/channels/api`). The hooks below restate what lived inside
 * the old view files: the same endpoints, bodies, Idempotency-Keys, conflict handling and cache
 * invalidation. Commands raise their own toast, so a screen never shows a second one.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AI_ROUTING_SETTING, fetchAiStatus, fetchAiUsage, fetchTrace, verifyAi } from "@/features/ai-admin/api";
import {
  createEnrolment,
  fetchAccount,
  fetchAttentionMessages,
  fetchDemoThread,
  fetchIdentities,
  fetchTemplates,
  resolveOutbox,
  sendDemoInbound,
  syncTemplates,
  unlinkIdentity,
  updateConsent,
  verifyAccount,
  type ConsentPurpose,
  type DemoInput,
} from "@/features/channels/api";
import { fetchIntegrations, fetchSetting, fetchSettingRevisions, updateSetting } from "@/features/settings/api";
import { fieldPathFromLoc } from "@/features/settings/setting-model";
import type { Json, SettingRead } from "@/features/settings/types";
import { createIdempotencyKey } from "@/lib/api/client";
import { conflictFromError, ProblemError, type ConflictInfo } from "@/lib/api/errors";
import { invalidationMap, queryKeys } from "@/lib/api/query-keys";
import { useOnline } from "@/lib/hooks";
import { toast } from "~/ui/toast";

export { AI_ROUTING_SETTING };

export const OFFLINE_NOTE = "You are offline. Changes wait until the connection is back.";

/** The server's own words for a failed command, with the reference support will ask for. */
export function problemText(error: unknown): string | undefined {
  if (!(error instanceof ProblemError)) return error instanceof Error ? error.message : undefined;
  const text = [error.detail ?? error.title, error.request_id ? `Reference ${error.request_id}` : null].filter(Boolean).join(" ");
  return text || undefined;
}

// ---- AI: status, usage, verification, traces ----

/** `GET /admin/ai/status` (agents.ai_usage.read). */
export function useAiStatus(enabled: boolean) {
  return useQuery({ queryKey: queryKeys.agents.aiStatus(), queryFn: ({ signal }) => fetchAiStatus(signal), enabled });
}

/** `GET /admin/ai/usage?days=N` (agents.ai_usage.read). */
export function useAiUsage(days: number, enabled = true) {
  return useQuery({ queryKey: queryKeys.agents.aiUsage(days), queryFn: ({ signal }) => fetchAiUsage(days, signal), enabled });
}

/** `POST /admin/ai/verify` (system.integration.manage). The status and the integrations list are re-read either way. */
export function useVerifyAi() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => verifyAi(),
    onSuccess: () => toast.success("Check recorded. The status below is the latest."),
    onSettled: () => {
      for (const key of invalidationMap["agents.ai_verified"]) void client.invalidateQueries({ queryKey: key });
    },
  });
}

/** `GET /traces/{correlation_id}`. A 404 is an answer ("not visible to you"), so it is not retried. */
export function useTrace(correlationId: string | null) {
  return useQuery({
    queryKey: queryKeys.agents.trace(correlationId ?? ""),
    queryFn: ({ signal }) => fetchTrace(correlationId!, signal),
    enabled: correlationId !== null,
    retry: (count, error) => !(error instanceof ProblemError && error.status === 404) && count < 2,
  });
}

// ---- one org setting (AI routing) ----

export function useSetting(key: string, enabled = true) {
  return useQuery({ queryKey: queryKeys.org.setting(key), queryFn: ({ signal }) => fetchSetting(key, signal), enabled });
}

export function useSettingRevisions(key: string, enabled: boolean) {
  return useQuery({ queryKey: queryKeys.org.settingRevisions(key), queryFn: ({ signal }) => fetchSettingRevisions(key, signal), enabled });
}

export type SaveSettingOutcome = "saved" | "conflict" | "invalid" | "failed";

/**
 * Saves one setting with `expected_version`. A 409 sets `conflict` (nothing is overwritten);
 * a 422 lands on its fields through `fieldErrors`; every failed attempt gets a fresh
 * Idempotency-Key, because a retry carries a corrected value.
 */
export function useSaveSetting(setting: SettingRead) {
  const queryClient = useQueryClient();
  const online = useOnline();
  const [pending, setPending] = useState(false);
  const [conflict, setConflict] = useState<ConflictInfo | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [idempotencyKey, setIdempotencyKey] = useState(() => createIdempotencyKey());

  const save = async (value: Json, reason: string): Promise<SaveSettingOutcome> => {
    if (pending || !online) return "failed";
    setPending(true);
    setConflict(null);
    setFieldErrors({});
    try {
      await updateSetting(setting.key, { value, expected_version: setting.version, change_reason: reason }, idempotencyKey);
      await Promise.all(invalidationMap["org.setting_changed"].map((queryKey) => queryClient.invalidateQueries({ queryKey })));
      toast.success("Routing saved. New assistant requests use it from now on.");
      return "saved";
    } catch (error) {
      setIdempotencyKey(createIdempotencyKey());
      const conflictInfo = conflictFromError(error);
      if (conflictInfo) {
        setConflict(conflictInfo);
        return "conflict";
      }
      if (error instanceof ProblemError && error.status === 422) {
        const errors: Record<string, string> = {};
        for (const issue of error.validationIssues) errors[fieldPathFromLoc(issue.loc)] = issue.msg;
        setFieldErrors(errors);
        toast.error("The routing was not saved", { description: error.detail ?? error.title });
        return "invalid";
      }
      toast.error("The routing was not saved", { description: problemText(error) });
      return "failed";
    } finally {
      setPending(false);
    }
  };

  /** After a conflict: read the latest version again (the caller then closes its editor). */
  const reload = async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.org.settings() });
    await queryClient.invalidateQueries({ queryKey: queryKeys.org.setting(setting.key) });
  };

  return { save, reload, pending, conflict, fieldErrors, offline: !online };
}

// ---- integrations ----

/** `GET /system/integrations` (system.integration.read). */
export function useIntegrations(enabled: boolean) {
  return useQuery({ queryKey: queryKeys.system.integrations(), queryFn: ({ signal }) => fetchIntegrations(signal), enabled });
}

// ---- WhatsApp ----

function useChannelsRefresh() {
  const client = useQueryClient();
  return () => Promise.all(invalidationMap["channels.changed"].map((queryKey) => client.invalidateQueries({ queryKey })));
}

export function useWhatsAppAccount() {
  return useQuery({ queryKey: queryKeys.channels.account(), queryFn: ({ signal }) => fetchAccount(signal) });
}

/** `POST /channels/whatsapp/account/verify` (channels.account.manage, recent sign-in). */
export function useVerifyWhatsApp() {
  const refresh = useChannelsRefresh();
  return useMutation({
    mutationFn: () => verifyAccount(),
    onSuccess: (result) => {
      toast.success("Checks finished", { description: result.account.label_text });
      void refresh();
    },
  });
}

/** `POST /channels/whatsapp/enrolments` (agents.assistant.use, recent sign-in). The code is shown once. */
export function useCreateEnrolment() {
  const refresh = useChannelsRefresh();
  return useMutation({
    mutationFn: () => createEnrolment(),
    onSuccess: () => void refresh(),
  });
}

export function useMyIdentities(enabled = true) {
  return useQuery({ queryKey: queryKeys.channels.identities("mine"), queryFn: ({ signal }) => fetchIdentities("mine", signal), enabled });
}

export function useUnlinkIdentity() {
  const refresh = useChannelsRefresh();
  return useMutation({
    mutationFn: (identityId: string) => unlinkIdentity(identityId),
    onSuccess: () => {
      toast.success("Number unlinked. The assistant no longer answers it.");
      void refresh();
    },
    onError: (error) => toast.error("The number could not be unlinked", { description: problemText(error) }),
  });
}

export function useUpdateConsent(identityId: string) {
  const refresh = useChannelsRefresh();
  return useMutation({
    mutationFn: ({ purpose, on }: { purpose: ConsentPurpose; on: boolean }) => updateConsent(identityId, purpose, on ? "opted_in" : "opted_out"),
    onSuccess: () => {
      toast.success("Preference saved");
      void refresh();
    },
    onError: (error) => toast.error("The preference was not saved", { description: problemText(error) }),
  });
}

/** `GET /channels/whatsapp/messages` (channels.outbox.manage): unknown, failed, blocked and escalated. */
export function useAttentionMessages(enabled: boolean) {
  return useQuery({ queryKey: queryKeys.channels.messages(), queryFn: ({ signal }) => fetchAttentionMessages(signal), enabled });
}

export function useResolveOutbox() {
  const refresh = useChannelsRefresh();
  return useMutation({
    mutationFn: ({ outboxId, action }: { outboxId: string; action: "resend" | "cancel" }) => resolveOutbox(outboxId, action),
    onSuccess: (_result, { action }) => {
      toast.success(action === "resend" ? "Queued as a new message" : "Closed without sending");
      void refresh();
    },
    onError: (error, { action }) =>
      toast.error(action === "resend" ? "The message could not be queued again" : "The message could not be closed", { description: problemText(error) }),
  });
}

/** `GET /channels/whatsapp/templates` (channels.account.manage). */
export function useTemplates(enabled: boolean) {
  return useQuery({ queryKey: queryKeys.channels.templates(), queryFn: ({ signal }) => fetchTemplates(signal), enabled });
}

export function useSyncTemplates() {
  const refresh = useChannelsRefresh();
  return useMutation({
    mutationFn: () => syncTemplates(),
    onSuccess: () => {
      toast.success("Templates synced");
      void refresh();
    },
    onError: (error) => toast.error("The templates could not be synced", { description: problemText(error) }),
  });
}

/** The worker answers within a few seconds; poll while the simulator is on screen. */
const SIMULATOR_POLL_MS = 2000;

/** `GET /channels/whatsapp/demo/thread` (demo mode only). */
export function useDemoThread(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.channels.demoThread(),
    queryFn: ({ signal }) => fetchDemoThread(signal),
    refetchInterval: SIMULATOR_POLL_MS,
    enabled,
  });
}

/** `POST /channels/whatsapp/demo/inbound` (demo mode only): text, a button press or a demo voice note. */
export function useSendDemoMessage() {
  const refresh = useChannelsRefresh();
  return useMutation({
    mutationFn: (input: DemoInput) => sendDemoInbound(input),
    onSuccess: () => refresh(),
  });
}
