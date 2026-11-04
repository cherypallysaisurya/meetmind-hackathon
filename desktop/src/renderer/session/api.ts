import { SERVICE_URL } from "../config";
import type { Profile } from "../profile";
import type { CardBody, CardSource } from "./ServiceConnection";

// The service's HTTP side: health (which also says the auth mode) and the profile.
// Local mode sends no token. Phase 4 adds the Cognito token as a bearer header here.

export type Health = { status: string; mode: "local" | "cognito"; llm: "local" | "meta"; answerModel: string };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(SERVICE_URL + path, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  if (!response.ok) throw new Error(`${init?.method ?? "GET"} ${path}: ${response.status}`);
  return response.json() as Promise<T>;
}

export function getHealth(): Promise<Health> {
  return request<Health>("/api/health");
}

export async function getProfile(): Promise<Profile | null> {
  const response = await fetch(SERVICE_URL + "/api/profile");
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`GET /api/profile: ${response.status}`);
  return response.json() as Promise<Profile>;
}

export function saveProfile(profile: Profile): Promise<Profile> {
  return request<Profile>("/api/profile", { method: "PUT", body: JSON.stringify(profile) });
}

export async function getReplays(): Promise<string[]> {
  const response = await request<{ files: string[] }>("/api/replays");
  return response.files;
}

export type DocumentRecord = { docId: string; name: string; type: string; addedAt: number; chunkCount: number; status: string };

export async function getDocuments(): Promise<DocumentRecord[]> {
  const response = await request<{ documents: DocumentRecord[] }>("/api/documents");
  return response.documents;
}

export async function uploadDocument(file: File): Promise<DocumentRecord> {
  const body = new FormData();
  body.append("file", file, file.name);
  const response = await fetch(SERVICE_URL + "/api/documents", { method: "POST", body });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail ?? `upload failed (${response.status})`);
  }
  return response.json() as Promise<DocumentRecord>;
}

export async function deleteDocument(docId: string): Promise<void> {
  await request(`/api/documents/${docId}`, { method: "DELETE" });
}

export type PreparedMeeting = { sessionId: string; title: string; agenda: string; participants: string[]; held: boolean };
type PreparedBody = { title: string; agenda: string; participants: string[] };

export async function getPrepared(): Promise<PreparedMeeting[]> {
  const response = await request<{ meetings: PreparedMeeting[] }>("/api/prep");
  return response.meetings;
}

export function createPrepared(body: PreparedBody): Promise<PreparedMeeting> {
  return request<PreparedMeeting>("/api/prep", { method: "POST", body: JSON.stringify(body) });
}

export function updatePrepared(sessionId: string, body: PreparedBody): Promise<PreparedMeeting> {
  return request<PreparedMeeting>(`/api/prep/${sessionId}`, { method: "PUT", body: JSON.stringify(body) });
}

export async function deletePrepared(sessionId: string): Promise<void> {
  await request(`/api/prep/${sessionId}`, { method: "DELETE" });
}

export type PrepStatus = { state: "idle" | "predicting" | "writing" | "done" | "failed"; done: number; total: number; seconds: number; error: string | null };
export type PreparedCardRecord = { cardId: string; question: string; variants: string[]; card: Omit<CardBody, "partial">; sources: CardSource[]; userEdited: boolean };

// A spoken answer to a prepared question, checked (decision 0009). Nothing is saved until the user keeps it.
export type Rehearsal = {
  heard: string;
  line: string;
  points: string[];
  check: { verdict: "supports" | "contradicts" | "not_found"; line: string; quote: string; document: string; location: string };
};

export async function rehearseCard(sessionId: string, cardId: string, audio: Uint8Array<ArrayBuffer>): Promise<Rehearsal> {
  const response = await fetch(`${SERVICE_URL}/api/prep/${sessionId}/cards/${cardId}/rehearse`, {
    method: "POST", body: audio, headers: { "Content-Type": "application/octet-stream" },
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail ?? `rehearsal failed (${response.status})`);
  }
  return response.json() as Promise<Rehearsal>;
}

export function buildPrepared(sessionId: string): Promise<PrepStatus> {
  return request<PrepStatus>(`/api/prep/${sessionId}/build`, { method: "POST" });
}

export function getPrepStatus(sessionId: string): Promise<PrepStatus> {
  return request<PrepStatus>(`/api/prep/${sessionId}/status`);
}

export async function getPreparedCards(sessionId: string): Promise<PreparedCardRecord[]> {
  const response = await request<{ cards: PreparedCardRecord[] }>(`/api/prep/${sessionId}/cards`);
  return response.cards;
}

export function addPreparedCard(sessionId: string, question: string): Promise<PreparedCardRecord> {
  return request<PreparedCardRecord>(`/api/prep/${sessionId}/cards`, { method: "POST", body: JSON.stringify({ question }) });
}

export function editPreparedCard(sessionId: string, cardId: string, line: string, points: string[]): Promise<PreparedCardRecord> {
  return request<PreparedCardRecord>(`/api/prep/${sessionId}/cards/${cardId}`, { method: "PUT", body: JSON.stringify({ line, points }) });
}

export async function deletePreparedCard(sessionId: string, cardId: string): Promise<void> {
  await request(`/api/prep/${sessionId}/cards/${cardId}`, { method: "DELETE" });
}
