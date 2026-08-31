import { parseMailbox } from './recipientField.js';

export const ATTACHMENT_KINDS = Object.freeze(['all', 'document', 'image', 'archive', 'other']);
export const ATTACHMENT_DIRECTIONS = Object.freeze(['all', 'received', 'sent']);

const ATTACHMENT_KIND_SET = new Set(ATTACHMENT_KINDS);
const ATTACHMENT_DIRECTION_SET = new Set(ATTACHMENT_DIRECTIONS);
const ITEM_KEYS = Object.freeze([
  'account_id',
  'attachment_id',
  'email_id',
  'filename',
  'content_type',
  'size_bytes',
  'message_date',
  'sender_name',
  'sender_address',
  'subject',
  'is_sent',
]);
const RESPONSE_KEYS = Object.freeze(['account_id', 'items', 'next_cursor', 'has_more']);

function objectValue(value, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`${label} is malformed`);
  }
  return value;
}

function exactKeys(value, expected, label) {
  const keys = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (keys.length !== wanted.length || keys.some((key, index) => key !== wanted[index])) {
    throw new TypeError(`${label} contains unexpected fields`);
  }
}

function integerValue(value, label, { minimum = 0, maximum = Number.MAX_SAFE_INTEGER } = {}) {
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    throw new TypeError(`${label} is malformed`);
  }
  return value;
}

function textValue(value, label, { nullable = false, allowEmpty = false, maximum = 998 } = {}) {
  if (nullable && value === null) return null;
  if (typeof value !== 'string' || value.length > maximum) {
    throw new TypeError(`${label} is malformed`);
  }
  const normalized = value.trim().replace(/\s+/gu, ' ');
  if (!allowEmpty && !normalized) throw new TypeError(`${label} is malformed`);
  return normalized;
}

function accountValue(value, expectedAccountId, label = 'account_id') {
  const accountId = integerValue(value, label, { minimum: 1 });
  if (accountId !== Number(expectedAccountId)) {
    throw new TypeError(`${label} did not match the requested account`);
  }
  return accountId;
}

function cursorValue(value, label, { nullable = true } = {}) {
  if (nullable && value === null) return null;
  return textValue(value, label, { maximum: 2048 });
}

export function normalizeAttachmentLibraryItem(value, { accountId } = {}) {
  const source = objectValue(value, 'attachment item');
  exactKeys(source, ITEM_KEYS, 'attachment item');
  const normalizedAccountId = accountValue(source.account_id, accountId, 'attachment account_id');
  const senderAddress = textValue(source.sender_address, 'sender_address', {
    nullable: true,
    maximum: 254,
  });
  const parsedSender = senderAddress === null ? null : parseMailbox(senderAddress);
  if (senderAddress !== null && (!parsedSender || parsedSender.name || parsedSender.address !== senderAddress)) {
    throw new TypeError('sender_address is malformed');
  }
  if (typeof source.is_sent !== 'boolean') throw new TypeError('is_sent is malformed');
  if (source.message_date !== null
    && (typeof source.message_date !== 'string' || !Number.isFinite(Date.parse(source.message_date)))) {
    throw new TypeError('message_date is malformed');
  }

  return Object.freeze({
    account_id: normalizedAccountId,
    attachment_id: integerValue(source.attachment_id, 'attachment_id', { minimum: 1 }),
    email_id: integerValue(source.email_id, 'email_id', { minimum: 1 }),
    filename: textValue(source.filename, 'filename', { maximum: 180 }),
    content_type: textValue(source.content_type, 'content_type', { maximum: 255 }),
    size_bytes: source.size_bytes === null ? null : integerValue(source.size_bytes, 'size_bytes'),
    message_date: source.message_date,
    sender_name: textValue(source.sender_name, 'sender_name', {
      nullable: true,
      allowEmpty: false,
      maximum: 255,
    }),
    sender_address: parsedSender?.address ?? null,
    subject: textValue(source.subject, 'subject', { nullable: true, allowEmpty: true, maximum: 500 }),
    is_sent: source.is_sent,
  });
}

export function normalizeAttachmentQueryResponse(value, { accountId } = {}) {
  const source = objectValue(value, 'attachment query response');
  exactKeys(source, RESPONSE_KEYS, 'attachment query response');
  const normalizedAccountId = accountValue(source.account_id, accountId);
  if (!Array.isArray(source.items) || source.items.length > 50) {
    throw new TypeError('attachment items are malformed');
  }
  if (typeof source.has_more !== 'boolean') throw new TypeError('has_more is malformed');
  const items = source.items.map(item => normalizeAttachmentLibraryItem(item, {
    accountId: normalizedAccountId,
  }));
  const identities = items.map(item => `${item.email_id}:${item.attachment_id}`);
  if (new Set(identities).size !== identities.length) {
    throw new TypeError('attachment items contain duplicate identities');
  }
  const nextCursor = source.next_cursor === null
    ? null
    : textValue(source.next_cursor, 'next_cursor', { maximum: 2048 });
  if (source.has_more !== Boolean(nextCursor)) {
    throw new TypeError('attachment pagination is malformed');
  }
  return Object.freeze({
    account_id: normalizedAccountId,
    items: Object.freeze(items),
    next_cursor: nextCursor,
    has_more: source.has_more,
  });
}

export function createAttachmentQueryPayload({
  accountId,
  query = '',
  kind = 'all',
  direction = 'all',
  cursor = null,
  pageSize = 50,
} = {}) {
  const normalizedKind = String(kind || 'all');
  const normalizedDirection = String(direction || 'all');
  if (!ATTACHMENT_KIND_SET.has(normalizedKind)) throw new TypeError('kind is malformed');
  if (!ATTACHMENT_DIRECTION_SET.has(normalizedDirection)) {
    throw new TypeError('direction is malformed');
  }
  const querySource = String(query || '');
  if ([...querySource].some(character => /\p{C}/u.test(character))) {
    throw new TypeError('query is malformed');
  }
  const normalizedQuery = querySource.trim().replace(/\s+/gu, ' ');
  if (normalizedQuery.length > 256) throw new TypeError('query is malformed');
  return Object.freeze({
    account_id: integerValue(Number(accountId), 'account_id', { minimum: 1 }),
    query: normalizedQuery,
    kind: normalizedKind,
    direction: normalizedDirection,
    cursor: cursorValue(cursor, 'cursor'),
    page_size: integerValue(Number(pageSize), 'page_size', { minimum: 1, maximum: 50 }),
  });
}

export function attachmentTransferItem(item, { accountId } = {}) {
  const normalized = normalizeAttachmentLibraryItem(item, { accountId });
  return Object.freeze({
    id: normalized.attachment_id,
    email_id: normalized.email_id,
    account_id: normalized.account_id,
    filename: normalized.filename,
    content_type: normalized.content_type,
    size_bytes: normalized.size_bytes,
  });
}

export function createAttachmentParentIntent(item, { accountId } = {}) {
  const normalized = normalizeAttachmentLibraryItem(item, { accountId });
  return Object.freeze({
    account_id: normalized.account_id,
    email_id: normalized.email_id,
  });
}

export function normalizeAttachmentParentIntent(value) {
  const source = objectValue(value, 'attachment parent intent');
  exactKeys(source, ['account_id', 'email_id'], 'attachment parent intent');
  return Object.freeze({
    account_id: integerValue(source.account_id, 'attachment parent account_id', { minimum: 1 }),
    email_id: integerValue(source.email_id, 'attachment parent email_id', { minimum: 1 }),
  });
}

export function attachmentParentAnchorForAccount(value, accountId) {
  if (value === null) return null;
  const intent = normalizeAttachmentParentIntent(value);
  if (intent.account_id !== Number(accountId)) {
    throw new TypeError('The attachment account no longer matches the active account.');
  }
  return intent.email_id;
}

export function formatAttachmentLibrarySize(sizeBytes) {
  if (!Number.isSafeInteger(sizeBytes) || sizeBytes < 0) return 'Size unavailable';
  if (sizeBytes >= 1048576) return `${(sizeBytes / 1048576).toFixed(1)} MB`;
  if (sizeBytes >= 1024) return `${Math.max(1, Math.ceil(sizeBytes / 1024))} KB`;
  return `${sizeBytes} B`;
}

export function formatAttachmentLibraryDate(value) {
  if (typeof value !== 'string' || !Number.isFinite(Date.parse(value))) return 'Date unavailable';
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })
    .format(new Date(value));
}
