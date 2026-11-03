/**
 * Channels API (backend/app/modules/channels/router.py), typed from the generated schema:
 * - channels_get_account            GET    /api/v1/channels/whatsapp/account
 * - channels_run_account_verify     POST   /api/v1/channels/whatsapp/account/verify       (channels.account.manage, recent sign-in)
 * - channels_create_enrolment       POST   /api/v1/channels/whatsapp/enrolments           (agents.assistant.use, recent sign-in)
 * - channels_list_identities        GET    /api/v1/channels/whatsapp/identities           (?scope=mine|all)
 * - channels_delete_identity        DELETE /api/v1/channels/whatsapp/identities/{id}
 * - channels_update_consent         PUT    /api/v1/channels/whatsapp/consents
 * - channels_list_messages          GET    /api/v1/channels/whatsapp/messages             (channels.outbox.manage)
 * - channels_resolve_outbox         POST   /api/v1/channels/whatsapp/outbox/{id}/resolve
 * - channels_list_templates         GET    /api/v1/channels/whatsapp/templates            (channels.account.manage)
 * - channels_run_templates_sync     POST   /api/v1/channels/whatsapp/templates/sync       (channels.account.manage)
 * - channels_create_demo_inbound    POST   /api/v1/channels/whatsapp/demo/inbound         (demo mode only)
 * - channels_get_demo_thread        GET    /api/v1/channels/whatsapp/demo/thread          (demo mode only)
 * - channels_resolve_review_link    POST   /api/v1/review-links/{token}/resolve
 */

import { api, unwrap, type ApiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];
export type Account = Schemas["AccountRead"];
export type VerifyResult = Schemas["VerifyResult"];
export type Enrolment = Schemas["EnrolmentRead"];
export type Identity = Schemas["IdentityRead"];
export type ConsentPurpose = Schemas["ConsentPurpose"];
export type ConsentStatus = Schemas["ConsentStatus"];
export type Message = Schemas["MessageRead"];
export type Outbox = Schemas["OutboxRead"];
export type Template = Schemas["TemplateRead"];
export type DemoThread = Schemas["DemoThread"];
export type ReviewLinkResolved = Schemas["ReviewLinkResolved"];

export const CONSENT_PURPOSES: readonly ConsentPurpose[] = ["assistant_replies", "daily_briefing", "transactional", "marketing"];
export const DEMO_VOICE_NOTES = ["oak_tray_quote", "hinglish_oak_tray", "unclear"] as const;
export type DemoVoiceNote = (typeof DEMO_VOICE_NOTES)[number];

export function fetchAccount(signal?: AbortSignal, client: ApiClient = api): Promise<Account> {
  return unwrap(client.GET("/api/v1/channels/whatsapp/account", { signal }));
}

export function verifyAccount(client: ApiClient = api): Promise<VerifyResult> {
  return unwrap(client.POST("/api/v1/channels/whatsapp/account/verify"));
}

export function createEnrolment(client: ApiClient = api): Promise<Enrolment> {
  return unwrap(client.POST("/api/v1/channels/whatsapp/enrolments", { body: {} }));
}

export function fetchIdentities(scope: "mine" | "all", signal?: AbortSignal, client: ApiClient = api): Promise<Identity[]> {
  return unwrap(client.GET("/api/v1/channels/whatsapp/identities", { params: { query: { scope } }, signal }));
}

export async function unlinkIdentity(identityId: string, client: ApiClient = api): Promise<void> {
  await unwrap(client.DELETE("/api/v1/channels/whatsapp/identities/{identity_id}", { params: { path: { identity_id: identityId } } }));
}

export function updateConsent(identityId: string, purpose: ConsentPurpose, status: ConsentStatus, client: ApiClient = api): Promise<Schemas["ConsentRead"]> {
  return unwrap(client.PUT("/api/v1/channels/whatsapp/consents", { body: { identity_id: identityId, purpose, status } }));
}

export function fetchAttentionMessages(signal?: AbortSignal, client: ApiClient = api): Promise<Message[]> {
  return unwrap(client.GET("/api/v1/channels/whatsapp/messages", { signal }));
}

export function resolveOutbox(outboxId: string, action: "resend" | "cancel", client: ApiClient = api): Promise<Outbox> {
  return unwrap(
    client.POST("/api/v1/channels/whatsapp/outbox/{outbox_id}/resolve", {
      params: { path: { outbox_id: outboxId } },
      body: { action, confirm: action === "resend" },
    }),
  );
}

export function fetchTemplates(signal?: AbortSignal, client: ApiClient = api): Promise<Template[]> {
  return unwrap(client.GET("/api/v1/channels/whatsapp/templates", { signal }));
}

export function syncTemplates(client: ApiClient = api): Promise<Template[]> {
  return unwrap(client.POST("/api/v1/channels/whatsapp/templates/sync"));
}

export type DemoInput = { text: string } | { button_id: string } | { audio_fixture: DemoVoiceNote };

export function sendDemoInbound(input: DemoInput, client: ApiClient = api): Promise<Schemas["DemoInboundResult"]> {
  return unwrap(client.POST("/api/v1/channels/whatsapp/demo/inbound", { body: input }));
}

export function fetchDemoThread(signal?: AbortSignal, client: ApiClient = api): Promise<DemoThread> {
  return unwrap(client.GET("/api/v1/channels/whatsapp/demo/thread", { signal }));
}

export function resolveReviewLink(token: string, client: ApiClient = api): Promise<ReviewLinkResolved> {
  return unwrap(client.POST("/api/v1/review-links/{token}/resolve", { params: { path: { token } }, body: {} }));
}

/** "1234 5678": easier to read and type than eight digits in a row. */
export function groupCode(code: string): string {
  return code.length === 8 ? `${code.slice(0, 4)} ${code.slice(4)}` : code;
}
