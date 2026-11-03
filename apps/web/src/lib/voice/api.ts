/**
 * Voice and vision endpoints (typed from the generated schema). Recordings and screenshots are
 * multipart with one `file` part; their ids and counts travel as query parameters (never content).
 */

import { api, createIdempotencyKey, idempotencyHeaders, unwrap, type ApiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];
export type VoiceCapabilities = Schemas["VoiceCapabilities"];
export type Utterance = Schemas["UtteranceOut"];
export type UtteranceSubmitted = Schemas["UtteranceSubmitted"];
export type SpeechOut = Schemas["SpeechOut"];
export type ReadbackOut = Schemas["ReadbackOut"];
export type VisionCapabilities = Schemas["VisionCapabilities"];
export type ScreenCapture = Schemas["ScreenCaptureOut"];
export type ScreenAnswer = Schemas["ScreenAnswerOut"];
export type ExtractionCard = Schemas["ExtractionCard"];
export type ExtractionField = Schemas["ExtractionField"];
export type LanguageCode = Schemas["VoiceCapabilities"]["speech_language"];
type ScreenContextBody = Schemas["ScreenContext"];

const asForm = (blob: Blob, name: string): FormData => {
  const form = new FormData();
  form.append("file", blob, name);
  return form;
};
const passThrough = (body: unknown) => body as BodyInit;

export const fetchVoiceCapabilities = (signal?: AbortSignal, client: ApiClient = api) =>
  unwrap(client.GET("/api/v1/voice/capabilities", { signal }));

export interface TranscribeInput {
  utteranceId: string;
  conversationId?: string | null;
  language?: LanguageCode;
  durationMs?: number;
}

export function transcribe(recording: Blob, input: TranscribeInput, client: ApiClient = api): Promise<Utterance> {
  const extension = recording.type.includes("ogg") ? "ogg" : recording.type.includes("mp4") ? "m4a" : recording.type.includes("wav") ? "wav" : "webm";
  return unwrap(
    client.POST("/api/v1/voice/transcriptions", {
      params: {
        query: {
          utterance_id: input.utteranceId,
          conversation_id: input.conversationId ?? undefined,
          language: input.language,
          duration_ms: input.durationMs,
        },
      },
      body: asForm(recording, `recording.${extension}`) as never,
      bodySerializer: passThrough,
    }),
  );
}

export const createBrowserUtterance = (
  body: { id: string; text: string; language?: LanguageCode; confidence?: number | null; duration_ms?: number | null },
  client: ApiClient = api,
) => unwrap(client.POST("/api/v1/voice/utterances", { body: { ...body, language: body.language ?? "en-IN" }, headers: idempotencyHeaders(createIdempotencyKey()) }));

export interface SubmitInput {
  conversationId: string;
  text: string;
  context?: ScreenContextBody | null;
  correctsTurnId?: string | null;
}

/** Sends the final transcript as one turn; the utterance id doubles as the Idempotency-Key. */
export const submitUtterance = (utteranceId: string, input: SubmitInput, client: ApiClient = api) =>
  unwrap(
    client.POST("/api/v1/voice/utterances/{utterance_id}/submit", {
      params: { path: { utterance_id: utteranceId } },
      body: {
        conversation_id: input.conversationId,
        text: input.text,
        context: input.context ?? null,
        corrects_turn_id: input.correctsTurnId ?? null,
      },
      headers: idempotencyHeaders(utteranceId),
    }),
  );

export const createSpeech = (text: string, language?: LanguageCode, client: ApiClient = api) =>
  unwrap(client.POST("/api/v1/voice/speech", { body: { text, language }, headers: idempotencyHeaders(createIdempotencyKey()) }));

export const createReadback = (subjectType: string, subjectId: string, client: ApiClient = api) =>
  unwrap(
    client.POST("/api/v1/voice/readbacks", {
      body: { subject_type: subjectType, subject_id: subjectId },
      headers: idempotencyHeaders(createIdempotencyKey()),
    }),
  );

// ---- vision ---------------------------------------------------------------------------------
export const fetchVisionCapabilities = (signal?: AbortSignal, client: ApiClient = api) =>
  unwrap(client.GET("/api/v1/vision/capabilities", { signal }));

export function uploadScreenCapture(
  image: Blob,
  input: { conversationId?: string | null; maskedCount: number; routePath: string | null },
  client: ApiClient = api,
): Promise<ScreenCapture> {
  return unwrap(
    client.POST("/api/v1/vision/screen-captures", {
      params: {
        query: { conversation_id: input.conversationId ?? undefined, masked_count: input.maskedCount, route_path: input.routePath ?? undefined },
      },
      body: asForm(image, image.type === "image/png" ? "screen.png" : "screen.webp") as never,
      bodySerializer: passThrough,
      headers: idempotencyHeaders(createIdempotencyKey()),
    }),
  );
}

export const removeScreenCapture = (captureId: string, client: ApiClient = api) =>
  unwrap(client.DELETE("/api/v1/vision/screen-captures/{capture_id}", { params: { path: { capture_id: captureId } } }));

export const askAboutScreen = (
  body: { capture_id: string; question: string; conversation_id?: string | null; context?: ScreenContextBody | null },
  client: ApiClient = api,
) => unwrap(client.POST("/api/v1/vision/screen-answers", { body, headers: idempotencyHeaders(createIdempotencyKey()) }));

export const createExtraction = (body: { file_id: string; kind?: ExtractionCard["extraction_kind"] | null }, client: ApiClient = api) =>
  unwrap(client.POST("/api/v1/vision/extractions", { body, headers: idempotencyHeaders(createIdempotencyKey()) }));

export const confirmExtraction = (
  requestId: string,
  body: { expected_version: number; header: Record<string, string | null>; lines: Record<string, string | null>[] },
  client: ApiClient = api,
) =>
  unwrap(
    client.POST("/api/v1/vision/extractions/{request_id}/confirm", {
      params: { path: { request_id: requestId } },
      body,
      headers: idempotencyHeaders(createIdempotencyKey()),
    }),
  );
