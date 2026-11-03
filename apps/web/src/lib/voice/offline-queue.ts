/**
 * Offline voice drafts (design §14): a transcript that could not be sent is kept in IndexedDB as
 * "Queued draft — not sent", with the utterance id it was recorded under. It is never sent on its
 * own: on reconnect the person reviews it and sends it, with the same id, so the server's unique
 * constraint yields one turn even if an earlier attempt did reach it. Nothing here represents a
 * commit; there is no success state without a server receipt.
 */

export const QUEUED_LABEL = "Queued draft — not sent";
const DB_NAME = "lk-voice";
const STORE = "drafts";

export interface QueuedDraft {
  /** The utterance id (UUIDv7) the recording was created under. */
  utteranceId: string;
  conversationId: string | null;
  text: string;
  correctsTurnId: string | null;
  queuedAt: string;
  label: typeof QUEUED_LABEL;
}

export interface DraftStore {
  put(draft: QueuedDraft): Promise<void>;
  list(): Promise<QueuedDraft[]>;
  remove(utteranceId: string): Promise<void>;
}

/** An in-memory store (tests, and browsers without IndexedDB: drafts then last for the tab only). */
export class MemoryDraftStore implements DraftStore {
  private readonly drafts = new Map<string, QueuedDraft>();
  async put(draft: QueuedDraft): Promise<void> {
    this.drafts.set(draft.utteranceId, { ...draft });
  }
  async list(): Promise<QueuedDraft[]> {
    return [...this.drafts.values()].sort((a, b) => a.queuedAt.localeCompare(b.queuedAt));
  }
  async remove(utteranceId: string): Promise<void> {
    this.drafts.delete(utteranceId);
  }
}

function request<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export class IndexedDbDraftStore implements DraftStore {
  private db: Promise<IDBDatabase> | null = null;

  constructor(private readonly factory: IDBFactory = indexedDB) {}

  private open(): Promise<IDBDatabase> {
    this.db ??= new Promise((resolve, reject) => {
      const req = this.factory.open(DB_NAME, 1);
      req.onupgradeneeded = () => {
        if (!req.result.objectStoreNames.contains(STORE)) req.result.createObjectStore(STORE, { keyPath: "utteranceId" });
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    return this.db;
  }

  private async store(mode: IDBTransactionMode): Promise<IDBObjectStore> {
    return (await this.open()).transaction(STORE, mode).objectStore(STORE);
  }

  async put(draft: QueuedDraft): Promise<void> {
    await request((await this.store("readwrite")).put(draft));
  }

  async list(): Promise<QueuedDraft[]> {
    const rows = (await request((await this.store("readonly")).getAll())) as QueuedDraft[];
    return rows.sort((a, b) => a.queuedAt.localeCompare(b.queuedAt));
  }

  async remove(utteranceId: string): Promise<void> {
    await request((await this.store("readwrite")).delete(utteranceId));
  }
}

let shared: DraftStore | null = null;

export function draftStore(): DraftStore {
  if (shared) return shared;
  shared = typeof indexedDB === "undefined" ? new MemoryDraftStore() : new IndexedDbDraftStore();
  return shared;
}

export function setDraftStore(store: DraftStore | null): void {
  shared = store;
}

export function queuedDraft(input: Omit<QueuedDraft, "label" | "queuedAt">, now: Date = new Date()): QueuedDraft {
  return { ...input, queuedAt: now.toISOString(), label: QUEUED_LABEL };
}

/** True when a failure means "not sent because offline" (the draft is queued, nothing is claimed). */
export function isOffline(error: unknown, online: boolean = typeof navigator === "undefined" ? true : navigator.onLine): boolean {
  if (!online) return true;
  return Boolean(error && typeof error === "object" && "name" in error && (error as { name: string }).name === "NetworkError");
}
