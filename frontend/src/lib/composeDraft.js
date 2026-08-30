export const LEGACY_COMPOSE_DRAFT_KEY = 'composeLocalDraftV1';
export const UNSCOPED_COMPOSE_DRAFT_PREFIX = 'composeLocalDraftV2:';
export const LEGACY_COMPOSE_LAST_ACCOUNT_KEY = 'composeLastAccountId';
const SCOPED_COMPOSE_DRAFT_PREFIX = 'composeLocalDraftV3';
const SCOPED_COMPOSE_LAST_ACCOUNT_PREFIX = 'composeLastAccountV2';

function storageUserId(userId) {
  if (typeof userId === 'number') {
    return Number.isSafeInteger(userId) && userId > 0 ? String(userId) : null;
  }
  if (typeof userId !== 'string') return null;
  const value = userId;
  if (!/^[a-zA-Z0-9._-]{1,128}$/.test(value)) return null;
  return value;
}

export function composeDraftStorageKey(userId, data) {
  const safeUserId = storageUserId(userId);
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
  const safeUserId = storageUserId(userId);
  return safeUserId
    ? `${SCOPED_COMPOSE_LAST_ACCOUNT_PREFIX}:user:${safeUserId}`
    : null;
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
  return Boolean(
    draft.to || draft.cc || draft.bcc || draft.subject || draft.body_html
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
