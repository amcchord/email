const MAX_SIGNATURE_HTML_CHARS = 50_000;
const MAX_SIGNATURE_TEXT_CHARS = 20_000;

function normalizeBodyText(value) {
  return String(value ?? '').replace(/\r\n?/g, '\n').trim();
}

function normalizeBodyHtml(value, sanitizeHtml) {
  const source = String(value ?? '').trim();
  const normalized = typeof sanitizeHtml === 'function'
    ? String(sanitizeHtml(source) ?? '').trim()
    : source;
  // Rich editors commonly serialize a cleared document as `<p></p>` or
  // `<p><br></p>`. Treat that as genuinely empty so disabled policies round
  // trip with the backend's rich/plain parity and can later be enabled safely.
  return signatureHtmlToPlainText(normalized) ? normalized : '';
}

export function signatureHtmlToPlainText(html) {
  const source = String(html ?? '');
  if (typeof document !== 'undefined' && document.createElement) {
    const root = document.createElement('div');
    root.innerHTML = source;
    root.querySelectorAll('br').forEach(node => node.replaceWith('\n'));
    root.querySelectorAll('p, div, li, blockquote, pre, h1, h2, h3').forEach(node => {
      if (!node.textContent?.endsWith('\n')) node.append('\n');
    });
    return String(root.textContent || '')
      .replace(/\u00a0/g, ' ')
      .replace(/\n{3,}/g, '\n\n')
      .trim();
  }
  return source
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/(p|div|li|blockquote|pre|h[1-3])>/gi, '\n')
    .replace(/<[^>]*>/g, '')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'")
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

export function normalizeAccountSignature(record, { sanitizeHtml } = {}) {
  if (!record || typeof record !== 'object' || Array.isArray(record)) return null;
  const accountId = Number(record.account_id);
  const accountEmail = String(record.account_email ?? '').trim();
  const revision = Number(record.revision ?? 0);
  const sanitizerVersion = Number(record.sanitizer_version ?? (revision === 0 ? 1 : NaN));
  if (
    !Number.isSafeInteger(accountId)
    || accountId <= 0
    || !accountEmail
    || !Number.isSafeInteger(revision)
    || revision < 0
    || !Number.isSafeInteger(sanitizerVersion)
    || sanitizerVersion < 1
  ) return null;

  const isDefault = revision === 0;
  const enabled = typeof record.enabled === 'boolean'
    ? record.enabled
    : (isDefault ? false : null);
  const includeOnNew = typeof record.include_on_new === 'boolean'
    ? record.include_on_new
    : (isDefault ? true : null);
  const includeOnReplies = typeof record.include_on_replies === 'boolean'
    ? record.include_on_replies
    : (isDefault ? true : null);
  const includeOnForwards = typeof record.include_on_forwards === 'boolean'
    ? record.include_on_forwards
    : (isDefault ? true : null);
  const sourceHtml = String(record.body_html ?? '').trim();
  const bodyHtml = normalizeBodyHtml(sourceHtml, sanitizeHtml);
  const bodyText = bodyHtml !== sourceHtml
    ? signatureHtmlToPlainText(bodyHtml)
    : normalizeBodyText(record.body_text);

  if (
    enabled === null
    || includeOnNew === null
    || includeOnReplies === null
    || includeOnForwards === null
    || bodyHtml.length > MAX_SIGNATURE_HTML_CHARS
    || bodyText.length > MAX_SIGNATURE_TEXT_CHARS
    || Boolean(bodyHtml) !== Boolean(bodyText)
    || (enabled && (!bodyHtml || !bodyText))
  ) return null;

  return {
    ...record,
    account_id: accountId,
    account_email: accountEmail,
    enabled,
    include_on_new: includeOnNew,
    include_on_replies: includeOnReplies,
    include_on_forwards: includeOnForwards,
    body_html: bodyHtml,
    body_text: bodyText,
    revision,
    sanitizer_version: sanitizerVersion,
  };
}

export function normalizeAccountSignatureList(response, options = {}) {
  if (!response || typeof response !== 'object' || !Array.isArray(response.accounts)) {
    throw new Error('Account signatures response is invalid');
  }
  const accounts = response.accounts.map(record => normalizeAccountSignature(record, options));
  if (accounts.some(account => account === null)) {
    throw new Error('Account signatures response is invalid');
  }
  const accountIds = new Set(accounts.map(account => account.account_id));
  if (accountIds.size !== accounts.length) {
    throw new Error('Account signatures response contains duplicate accounts');
  }
  const total = Number(response.total);
  if (!Number.isSafeInteger(total) || total < 0 || total !== accounts.length) {
    throw new Error('Account signatures response total is invalid');
  }
  return { accounts, total };
}

export function validateAccountSignature(policy, { sanitizeHtml } = {}) {
  if (typeof policy?.enabled !== 'boolean') return 'Choose whether this signature is enabled.';
  if (typeof policy?.include_on_new !== 'boolean') return 'Choose whether to use this signature for new messages.';
  if (typeof policy?.include_on_replies !== 'boolean') return 'Choose whether to use this signature for replies.';
  if (typeof policy?.include_on_forwards !== 'boolean') return 'Choose whether to use this signature for forwards.';
  const bodyHtml = normalizeBodyHtml(policy?.body_html, sanitizeHtml);
  const bodyText = signatureHtmlToPlainText(bodyHtml);
  if (bodyHtml.length > MAX_SIGNATURE_HTML_CHARS || bodyText.length > MAX_SIGNATURE_TEXT_CHARS) {
    return 'The signature is too long.';
  }
  if (policy.enabled && !bodyText) return 'Write signature content before enabling it.';
  if (policy.enabled && ![
    policy.include_on_new,
    policy.include_on_replies,
    policy.include_on_forwards,
  ].some(Boolean)) return 'Choose at least one message type for this signature.';
  const revision = Number(policy?.revision);
  if (!Number.isSafeInteger(revision) || revision < 0) {
    return 'The signature revision is invalid. Reload and try again.';
  }
  return '';
}

export function accountSignaturePayload(policy, options = {}) {
  const validationError = validateAccountSignature(policy, options);
  if (validationError) throw new Error(validationError);
  const bodyHtml = normalizeBodyHtml(policy.body_html, options.sanitizeHtml);
  return {
    enabled: policy.enabled,
    include_on_new: policy.include_on_new,
    include_on_replies: policy.include_on_replies,
    include_on_forwards: policy.include_on_forwards,
    body_html: bodyHtml,
    body_text: signatureHtmlToPlainText(bodyHtml),
    expected_revision: Number(policy.revision),
  };
}

function editableFields(policy, options) {
  const payload = accountSignaturePayload(policy, options);
  delete payload.expected_revision;
  return payload;
}

export function accountSignatureIsDirty(savedPolicy, draftPolicy, options = {}) {
  try {
    return JSON.stringify(editableFields(savedPolicy, options))
      !== JSON.stringify(editableFields(draftPolicy, options));
  } catch {
    return true;
  }
}

export function accountSignatureSummary(policy) {
  if (!policy?.enabled) return 'Off — no signature is added automatically';
  const contexts = [
    policy.include_on_new ? 'new messages' : null,
    policy.include_on_replies ? 'replies' : null,
    policy.include_on_forwards ? 'forwards' : null,
  ].filter(Boolean);
  return contexts.length ? `On for ${contexts.join(', ')}` : 'On — choose a message type';
}

export const COMPOSITION_KINDS = Object.freeze(['new', 'reply', 'forward']);
export const SIGNATURE_MODES = Object.freeze(['default', 'enabled', 'disabled']);

export function normalizeCompositionKind(value, fallback = 'new') {
  const kind = String(value ?? '').trim().toLowerCase();
  return COMPOSITION_KINDS.includes(kind) ? kind : fallback;
}

export function normalizeSignatureMode(value, fallback = 'default') {
  const mode = String(value ?? '').trim().toLowerCase();
  return SIGNATURE_MODES.includes(mode) ? mode : fallback;
}

export function accountSignatureFor(signatures, accountId) {
  const id = Number(accountId);
  if (!Number.isSafeInteger(id) || id <= 0 || !Array.isArray(signatures)) return null;
  return signatures.find(signature => Number(signature?.account_id) === id) || null;
}

export function signatureDefaultIncluded(policy, compositionKind) {
  if (!policy?.enabled) return false;
  const kind = normalizeCompositionKind(compositionKind);
  if (kind === 'reply') return Boolean(policy.include_on_replies);
  if (kind === 'forward') return Boolean(policy.include_on_forwards);
  return Boolean(policy.include_on_new);
}

export function signatureSnapshotFromPolicy(policy) {
  if (!policy?.body_html || !policy?.body_text) return null;
  return Object.freeze({
    applied: true,
    account_id: policy.account_id,
    policy_revision: policy.revision,
    body_html: policy.body_html,
    body_text: policy.body_text,
    content_hash: '',
    sanitizer_version: Number(policy.sanitizer_version || 1),
  });
}

export function normalizeSignatureSnapshot(record, { sanitizeHtml } = {}) {
  if (!record || typeof record !== 'object' || Array.isArray(record)) return null;
  const accountId = Number(record.account_id);
  const policyRevision = Number(record.policy_revision);
  const sanitizerVersion = Number(record.sanitizer_version || 1);
  const applied = record.applied !== false;
  if (
    !Number.isSafeInteger(accountId)
    || accountId <= 0
    || !Number.isSafeInteger(policyRevision)
    || policyRevision < 0
    || !Number.isSafeInteger(sanitizerVersion)
    || sanitizerVersion < 1
  ) return null;
  const bodyHtml = normalizeBodyHtml(record.body_html, sanitizeHtml);
  const bodyText = normalizeBodyText(record.body_text);
  if (!bodyHtml || !bodyText) return null;
  return Object.freeze({
    applied,
    account_id: accountId,
    policy_revision: policyRevision,
    body_html: bodyHtml,
    body_text: bodyText,
    content_hash: String(record.content_hash || ''),
    sanitizer_version: sanitizerVersion,
  });
}

export function effectiveSignatureSnapshot({
  initialized = false,
  mode = 'default',
  compositionKind = 'new',
  policy = null,
  snapshot = null,
} = {}) {
  if (!initialized) return null;
  const normalizedMode = normalizeSignatureMode(mode, 'disabled');
  if (normalizedMode === 'disabled') return null;
  if (normalizedMode === 'default' && !signatureDefaultIncluded(policy, compositionKind)) return null;
  const normalizedSnapshot = normalizeSignatureSnapshot(snapshot);
  if (normalizedSnapshot?.account_id === Number(policy?.account_id)) {
    return normalizedSnapshot.applied
      ? normalizedSnapshot
      : Object.freeze({ ...normalizedSnapshot, applied: true });
  }
  return signatureSnapshotFromPolicy(policy);
}

export function signatureDraftFields({
  compositionKind = 'new',
  mode = 'default',
  quotedHtml = '',
  quotedText = '',
} = {}) {
  return {
    composition_kind: normalizeCompositionKind(compositionKind),
    signature_mode: normalizeSignatureMode(mode),
    quoted_html: String(quotedHtml || ''),
    quoted_text: String(quotedText || ''),
  };
}
