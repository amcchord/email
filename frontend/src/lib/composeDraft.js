export const LEGACY_COMPOSE_DRAFT_KEY = 'composeLocalDraftV1';

export function composeDraftStorageKey(data) {
  const identity = data?.draft_key
    || (data?.thread_id ? `thread:${data.thread_id}` : null)
    || (data?.in_reply_to ? `reply:${data.in_reply_to}` : null)
    || 'new';
  const safeIdentity = String(identity)
    .replace(/[^a-zA-Z0-9._:@<>-]/g, '_')
    .slice(0, 240);
  return `composeLocalDraftV2:${safeIdentity}`;
}

export function composeDraftHasContent(draft) {
  if (!draft || typeof draft !== 'object') return false;
  return Boolean(
    draft.to || draft.cc || draft.bcc || draft.subject || draft.body_html
    || draft.in_reply_to || draft.thread_id,
  );
}

export function composeReplyContext(source = {}) {
  return Object.freeze({
    in_reply_to: source.in_reply_to || null,
    references: source.references || source.in_reply_to || null,
    thread_id: source.thread_id || null,
  });
}
