export const LEGACY_COMPOSE_DRAFT_KEY = 'composeLocalDraftV1';
export const UNSCOPED_COMPOSE_DRAFT_PREFIX = 'composeLocalDraftV2:';
export const LEGACY_COMPOSE_LAST_ACCOUNT_KEY = 'composeLastAccountId';
export const SCOPED_COMPOSE_DRAFT_PREFIX = 'composeLocalDraftV3';
const SCOPED_COMPOSE_LAST_ACCOUNT_PREFIX = 'composeLastAccountV2';
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function normalizeComposeDraftUserId(userId) {
  if (typeof userId === 'number') {
    return Number.isSafeInteger(userId) && userId > 0 ? String(userId) : null;
  }
  if (typeof userId !== 'string') return null;
  const value = userId;
  if (!/^[a-zA-Z0-9._-]{1,128}$/.test(value)) return null;
  return value;
}

export function composeDraftStorageKey(userId, data) {
  const safeUserId = normalizeComposeDraftUserId(userId);
  if (!safeUserId) return null;
  const identity = data?.draft_key
    || (data?.thread_id ? `thread:${data.thread_id}` : null)
    || (data?.in_reply_to ? `reply:${data.in_reply_to}` : null)
    || 'new';
  const safeIdentity = String(identity)
    .replace(/[^a-zA-Z0-9._:@<>-]/g, '_')
    .slice(0, 240);
  return `${SCOPED_COMPOSE_DRAFT_PREFIX}:user:${safeUserId}:${safeIdentity}`;
}

export function composeLastAccountStorageKey(userId) {
  const safeUserId = normalizeComposeDraftUserId(userId);
  return safeUserId
    ? `${SCOPED_COMPOSE_LAST_ACCOUNT_PREFIX}:user:${safeUserId}`
    : null;
}

export function composeDraftStoragePrefix(userId) {
  const safeUserId = normalizeComposeDraftUserId(userId);
  return safeUserId ? `${SCOPED_COMPOSE_DRAFT_PREFIX}:user:${safeUserId}:` : null;
}

export function isComposeDraftUuid(value) {
  return typeof value === 'string' && UUID_PATTERN.test(value);
}

export function composeDraftIntentFromRoute(value) {
  if (!isComposeDraftUuid(value)) return null;
  const clientDraftId = value.toLowerCase();
  return createComposeDraftIntent({
    client_draft_id: clientDraftId,
    intent_key: `route:${clientDraftId}`,
    draft_key: `client:${clientDraftId}`,
  });
}

export function applyComposeDraftRoute(url, page, data = null) {
  const clientDraftId = isComposeDraftUuid(data?.client_draft_id)
    ? data.client_draft_id.toLowerCase()
    : null;
  if (page === 'compose' && clientDraftId) url.searchParams.set('draft', clientDraftId);
  else url.searchParams.delete('draft');
  return url;
}

export function knownServerRevisionRequiresRefresh(data = {}, state = {}) {
  const knownServerRevision = Number(data?.known_server_revision || 0);
  const loadedRevision = Number(state?.revision || 0);
  return Number.isSafeInteger(knownServerRevision)
    && knownServerRevision > 0
    && Number.isSafeInteger(loadedRevision)
    && knownServerRevision > loadedRevision;
}

function defaultRandomUuid() {
  if (typeof globalThis.crypto?.randomUUID === 'function') return globalThis.crypto.randomUUID();
  throw new Error('Secure random UUID generation is unavailable');
}

export function composeDraftIntentKey(data = {}) {
  return data?.draft_key
    || (data?.thread_id ? `thread:${data.thread_id}` : null)
    || (data?.in_reply_to ? `reply:${data.in_reply_to}` : null)
    || 'new';
}

/**
 * Give one writing intent a stable client identity. Callers retain the returned
 * object for the lifetime of that composer; invoking this for a genuinely new
 * intent deliberately produces a different UUID even when both are `new`.
 */
export function createComposeDraftIntent(data = {}, { randomUUID = defaultRandomUuid } = {}) {
  const existingId = isComposeDraftUuid(data?.client_draft_id)
    ? data.client_draft_id.toLowerCase()
    : null;
  const clientDraftId = existingId || randomUUID();
  if (!isComposeDraftUuid(clientDraftId)) {
    throw new Error('Draft identity must be a UUID');
  }
  return Object.freeze({
    ...data,
    client_draft_id: clientDraftId.toLowerCase(),
    intent_key: data?.intent_key || composeDraftIntentKey(data),
    draft_key: data?.draft_key || `client:${clientDraftId.toLowerCase()}`,
  });
}

/** Create a genuinely new compose intent, even if another composer is open. */
export function newComposeIntent(data = {}, { randomUUID = defaultRandomUuid } = {}) {
  const clientDraftId = randomUUID();
  if (!isComposeDraftUuid(clientDraftId)) throw new Error('Draft identity must be a UUID');
  const normalizedId = clientDraftId.toLowerCase();
  return createComposeDraftIntent({
    composition_kind: 'new',
    signature_mode: 'default',
    signature_initialized: true,
    ...data,
    client_draft_id: normalizedId,
    intent_key: `new:${normalizedId}`,
    draft_key: `client:${normalizedId}`,
  }, { randomUUID });
}

/** Normalize any caller payload before Compose navigation reaches history. */
export function ensureComposeDraftIntent(data = {}, { randomUUID = defaultRandomUuid } = {}) {
  const resumable = isComposeDraftUuid(data?.client_draft_id)
    || Boolean(data?.intent_key || data?.draft_key || data?.thread_id || data?.in_reply_to || data?.source_email_id);
  return resumable
    ? createComposeDraftIntent(data, { randomUUID })
    : newComposeIntent(data, { randomUUID });
}

/**
 * Old drafts were shared by every authenticated identity in one browser.
 * Never migrate or read them: their owner cannot be proven.
 */
export function clearUnscopedComposeStorage(storage = globalThis.localStorage) {
  if (!storage) return;
  try {
    storage.removeItem(LEGACY_COMPOSE_DRAFT_KEY);
    storage.removeItem(LEGACY_COMPOSE_LAST_ACCOUNT_KEY);
    const unsafeKeys = [];
    for (let index = 0; index < storage.length; index += 1) {
      const key = storage.key(index);
      if (key?.startsWith(UNSCOPED_COMPOSE_DRAFT_PREFIX)) unsafeKeys.push(key);
    }
    unsafeKeys.forEach(key => storage.removeItem(key));
  } catch {
    // Storage can be unavailable or access-restricted. Failing closed means
    // callers still never read an unscoped key.
  }
}

export function composeDraftHasContent(draft) {
  if (!draft || typeof draft !== 'object') return false;
  const hasRecipients = ['to', 'cc', 'bcc'].some(field => (
    Array.isArray(draft[field])
      ? draft[field].some(value => String(value || '').trim())
      : Boolean(String(draft[field] || '').trim())
  ));
  return Boolean(
    hasRecipients || draft.subject || draft.body_html
    || draft.quoted_html || draft.quoted_text
    || (Array.isArray(draft.attachments) && draft.attachments.length > 0)
    || draft.in_reply_to || draft.thread_id || draft.source_email_id,
  );
}

export function composeReplyContext(source = {}) {
  return Object.freeze({
    in_reply_to: source.in_reply_to || null,
    references: source.references || source.in_reply_to || null,
    thread_id: source.thread_id || null,
    source_email_id: Number.isSafeInteger(Number(source.source_email_id))
      && Number(source.source_email_id) > 0
      ? Number(source.source_email_id)
      : null,
  });
}
