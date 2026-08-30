import {
  composeDraftHasContent,
  composeDraftStoragePrefix,
  createComposeDraftIntent,
  normalizeComposeDraftUserId,
} from './composeDraft.js';

export const DRAFT_STORAGE_SCHEMA_VERSION = 1;
export const DEFAULT_DRAFT_DATABASE_NAME = 'mailDurableDraftsV1';
const RECORD_STORE = 'drafts';

function defaultRandomUuid() {
  if (typeof globalThis.crypto?.randomUUID === 'function') return globalThis.crypto.randomUUID();
  throw new Error('Secure random UUID generation is unavailable');
}

export function cloneDraftValue(value, seen = new Map()) {
  if (value === null || typeof value !== 'object') return value;
  if (typeof globalThis.structuredClone === 'function') return globalThis.structuredClone(value);
  if (seen.has(value)) return seen.get(value);
  if (value instanceof ArrayBuffer) return value.slice(0);
  if (ArrayBuffer.isView(value)) {
    const buffer = value.buffer.slice(value.byteOffset, value.byteOffset + value.byteLength);
    return new value.constructor(buffer);
  }
  if (typeof Blob !== 'undefined' && value instanceof Blob) return value.slice(0, value.size, value.type);
  if (Array.isArray(value)) {
    const copy = [];
    seen.set(value, copy);
    value.forEach(item => copy.push(cloneDraftValue(item, seen)));
    return copy;
  }
  const copy = {};
  seen.set(value, copy);
  for (const [key, item] of Object.entries(value)) copy[key] = cloneDraftValue(item, seen);
  return copy;
}

export function draftStorageKey(userId, clientDraftId) {
  const safeUserId = normalizeComposeDraftUserId(userId);
  if (!safeUserId || typeof clientDraftId !== 'string' || !clientDraftId) return null;
  return `${safeUserId}:${clientDraftId}`;
}

export function draftStorageNamespace(userId, intentKey) {
  const safeUserId = normalizeComposeDraftUserId(userId);
  if (!safeUserId || typeof intentKey !== 'string' || !intentKey.trim()) return null;
  return `draft:user:${safeUserId}:intent:${encodeURIComponent(intentKey.trim())}`;
}

function normalizeRecord(record) {
  if (!record || typeof record !== 'object') throw new TypeError('Draft record is required');
  const userId = normalizeComposeDraftUserId(record.user_id);
  const clientDraftId = String(record.client_draft_id || '');
  const storageKey = draftStorageKey(userId, clientDraftId);
  if (!storageKey) throw new TypeError('Draft record requires a valid user and client draft ID');
  if (!Number.isSafeInteger(record.revision) || record.revision < 0) {
    throw new TypeError('Draft revision must be a non-negative integer');
  }
  return {
    ...cloneDraftValue(record),
    schema_version: DRAFT_STORAGE_SCHEMA_VERSION,
    storage_key: storageKey,
    user_id: userId,
    client_draft_id: clientDraftId,
  };
}

function sortNewest(records) {
  return records.sort((left, right) => {
    const updated = String(right.updated_at || '').localeCompare(String(left.updated_at || ''));
    return updated || right.revision - left.revision;
  });
}

export function createMemoryDraftStorage(initialRecords = []) {
  const records = new Map();
  for (const initial of initialRecords) {
    const record = normalizeRecord(initial);
    records.set(record.storage_key, record);
  }

  return Object.freeze({
    durability: 'memory',
    async get(userId, clientDraftId) {
      const record = records.get(draftStorageKey(userId, clientDraftId));
      return record ? cloneDraftValue(record) : null;
    },
    async put(value) {
      const record = normalizeRecord(value);
      records.set(record.storage_key, record);
      return cloneDraftValue(record);
    },
    async delete(userId, clientDraftId) {
      return records.delete(draftStorageKey(userId, clientDraftId));
    },
    async list(userId, { includeDiscarded = false } = {}) {
      const safeUserId = normalizeComposeDraftUserId(userId);
      if (!safeUserId) return [];
      const matches = [...records.values()].filter(record => (
        record.user_id === safeUserId
        && (includeDiscarded || record.status !== 'discarded')
      ));
      return cloneDraftValue(sortNewest(matches));
    },
    async findByIntent(userId, intentKey) {
      const matches = await this.list(userId, { includeDiscarded: false });
      return matches.find(record => record.intent_key === intentKey) || null;
    },
    async findByLegacyKey(userId, legacyStorageKey) {
      const matches = await this.list(userId, { includeDiscarded: true });
      return matches.find(record => record.legacy_storage_key === legacyStorageKey) || null;
    },
    close() {},
  });
}

function requestResult(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error('IndexedDB request failed'));
  });
}

function transactionDone(transaction) {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error || new Error('IndexedDB transaction failed'));
    transaction.onabort = () => reject(transaction.error || new Error('IndexedDB transaction aborted'));
  });
}

export function createIndexedDbDraftStorage({
  indexedDB = globalThis.indexedDB,
  databaseName = DEFAULT_DRAFT_DATABASE_NAME,
} = {}) {
  if (!indexedDB?.open) throw new Error('IndexedDB is unavailable');
  const opened = new Promise((resolve, reject) => {
    const request = indexedDB.open(databaseName, DRAFT_STORAGE_SCHEMA_VERSION);
    request.onupgradeneeded = () => {
      const database = request.result;
      const store = database.objectStoreNames.contains(RECORD_STORE)
        ? request.transaction.objectStore(RECORD_STORE)
        : database.createObjectStore(RECORD_STORE, { keyPath: 'storage_key' });
      if (!store.indexNames.contains('user_id')) store.createIndex('user_id', 'user_id', { unique: false });
      if (!store.indexNames.contains('user_intent')) {
        store.createIndex('user_intent', ['user_id', 'intent_key'], { unique: false });
      }
      if (!store.indexNames.contains('user_legacy')) {
        store.createIndex('user_legacy', ['user_id', 'legacy_storage_key'], { unique: false });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error('IndexedDB could not be opened'));
    request.onblocked = () => reject(new Error('IndexedDB upgrade is blocked by another tab'));
  });

  async function withStore(mode, callback) {
    const database = await opened;
    const transaction = database.transaction(RECORD_STORE, mode);
    const completion = transactionDone(transaction);
    const result = await callback(transaction.objectStore(RECORD_STORE));
    await completion;
    return result;
  }

  return Object.freeze({
    durability: 'indexeddb',
    async get(userId, clientDraftId) {
      const key = draftStorageKey(userId, clientDraftId);
      if (!key) return null;
      const result = await withStore('readonly', store => requestResult(store.get(key)));
      return result ? cloneDraftValue(result) : null;
    },
    async put(value) {
      const record = normalizeRecord(value);
      await withStore('readwrite', store => requestResult(store.put(record)));
      return cloneDraftValue(record);
    },
    async delete(userId, clientDraftId) {
      const key = draftStorageKey(userId, clientDraftId);
      if (!key) return false;
      await withStore('readwrite', store => requestResult(store.delete(key)));
      return true;
    },
    async list(userId, { includeDiscarded = false } = {}) {
      const safeUserId = normalizeComposeDraftUserId(userId);
      if (!safeUserId) return [];
      const values = await withStore('readonly', store => requestResult(store.index('user_id').getAll(safeUserId)));
      return cloneDraftValue(sortNewest(values.filter(record => includeDiscarded || record.status !== 'discarded')));
    },
    async findByIntent(userId, intentKey) {
      const safeUserId = normalizeComposeDraftUserId(userId);
      if (!safeUserId || !intentKey) return null;
      const values = await withStore('readonly', store => requestResult(
        store.index('user_intent').getAll([safeUserId, intentKey]),
      ));
      return cloneDraftValue(sortNewest(values.filter(record => record.status !== 'discarded'))[0] || null);
    },
    async findByLegacyKey(userId, legacyStorageKey) {
      const safeUserId = normalizeComposeDraftUserId(userId);
      if (!safeUserId || !legacyStorageKey) return null;
      const value = await withStore('readonly', store => requestResult(
        store.index('user_legacy').get([safeUserId, legacyStorageKey]),
      ));
      return value ? cloneDraftValue(value) : null;
    },
    async close() {
      const database = await opened;
      database.close();
    },
  });
}

function legacySnapshot(draft) {
  const {
    saved_at: _savedAt,
    revision: _revision,
    mutation_id: _mutationId,
    status: _status,
    ...snapshot
  } = draft;
  return cloneDraftValue(snapshot);
}

/**
 * Migrate only scoped V3 values for the authenticated user. A legacy key is
 * removed after its durable write succeeds; malformed values are preserved so
 * a caller can offer manual recovery instead of silently destroying content.
 */
export async function migrateLegacyScopedDrafts({
  storage,
  localStorage = globalThis.localStorage,
  userId,
  randomUUID = defaultRandomUuid,
  now = () => new Date().toISOString(),
} = {}) {
  if (!storage?.put || !localStorage) throw new TypeError('Draft and legacy storage are required');
  const safeUserId = normalizeComposeDraftUserId(userId);
  const prefix = composeDraftStoragePrefix(safeUserId);
  if (!prefix) return { migrated: [], skipped: [], failed: [] };
  const keys = [];
  try {
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      if (key?.startsWith(prefix)) keys.push(key);
    }
  } catch (error) {
    return { migrated: [], skipped: [], failed: [{ key: null, error }] };
  }

  const result = { migrated: [], skipped: [], failed: [] };
  for (const key of keys) {
    try {
      const serialized = localStorage.getItem(key);
      const draft = JSON.parse(serialized || 'null');
      if (!composeDraftHasContent(draft)) {
        result.skipped.push(key);
        continue;
      }
      const prior = await storage.findByLegacyKey?.(safeUserId, key);
      if (prior) {
        localStorage.removeItem(key);
        result.migrated.push(prior.client_draft_id);
        continue;
      }
      const intent = createComposeDraftIntent({
        client_draft_id: draft.client_draft_id,
        draft_key: key.slice(prefix.length),
      }, { randomUUID });
      const timestamp = now();
      const record = await storage.put({
        schema_version: DRAFT_STORAGE_SCHEMA_VERSION,
        user_id: safeUserId,
        client_draft_id: intent.client_draft_id,
        intent_key: intent.intent_key,
        draft_key: intent.draft_key,
        legacy_storage_key: key,
        revision: Math.max(1, Number.isSafeInteger(draft.revision) ? draft.revision : 1),
        mutation_id: randomUUID(),
        synced_revision: 0,
        status: 'local-only',
        snapshot: legacySnapshot(draft),
        server: {},
        tombstone: null,
        created_at: draft.saved_at || timestamp,
        updated_at: draft.saved_at || timestamp,
      });
      localStorage.removeItem(key);
      result.migrated.push(record.client_draft_id);
    } catch (error) {
      result.failed.push({ key, error });
    }
  }
  return result;
}
