import { newComposeIntent } from './composeDraft.js';
import { parseMailbox } from './recipientField.js';

export const CONTACT_RELATIONSHIPS = Object.freeze([
  'all',
  'bidirectional',
  'inbound_only',
  'outbound_only',
]);

const CONTACT_RELATIONSHIP_SET = new Set(CONTACT_RELATIONSHIPS);
const RECENT_DIRECTION_SET = new Set(['inbound_only', 'outbound_only', 'bidirectional']);
const CONTACT_KEY_RE = /^[a-f0-9]{64}$/u;

function objectValue(value, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`${label} is malformed`);
  }
  return value;
}

function integerValue(value, label, { minimum = 0, maximum = Number.MAX_SAFE_INTEGER } = {}) {
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    throw new TypeError(`${label} is malformed`);
  }
  return value;
}

function textValue(value, label, { nullable = false, maximum = 998 } = {}) {
  if (nullable && value === null) return null;
  if (typeof value !== 'string') throw new TypeError(`${label} is malformed`);
  const normalized = value.trim().replace(/\s+/gu, ' ');
  if (!normalized || normalized.length > maximum) throw new TypeError(`${label} is malformed`);
  return normalized;
}

function dateValue(value, label, { nullable = true } = {}) {
  if (nullable && value === null) return null;
  if (typeof value !== 'string' || !value.trim() || !Number.isFinite(Date.parse(value))) {
    throw new TypeError(`${label} is malformed`);
  }
  return value;
}

function accountValue(value, expectedAccountId, label = 'account_id') {
  const accountId = integerValue(value, label, { minimum: 1 });
  if (accountId !== Number(expectedAccountId)) {
    throw new TypeError(`${label} did not match the requested account`);
  }
  return accountId;
}

export function normalizeContactSummary(value, { accountId } = {}) {
  const source = objectValue(value, 'contact');
  const normalizedAccountId = accountValue(source.account_id, accountId, 'contact account_id');
  const contactKey = textValue(source.contact_key, 'contact_key', { maximum: 64 });
  if (!CONTACT_KEY_RE.test(contactKey)) throw new TypeError('contact_key is malformed');

  const parsedAddress = parseMailbox(source.address);
  const parsedFormatted = parseMailbox(source.formatted);
  if (
    !parsedAddress
    || parsedAddress.name
    || parsedAddress.address !== source.address
    || !parsedFormatted
    || parsedFormatted.address !== parsedAddress.address
  ) {
    throw new TypeError('contact mailbox is malformed');
  }

  const relationship = textValue(source.relationship, 'relationship', { maximum: 32 });
  if (!CONTACT_RELATIONSHIP_SET.has(relationship)) {
    throw new TypeError('relationship is malformed');
  }

  return Object.freeze({
    account_id: normalizedAccountId,
    contact_key: contactKey,
    name: source.name === null ? null : textValue(source.name, 'name', { maximum: 255 }),
    address: parsedAddress.address,
    formatted: parsedFormatted.mailbox,
    relationship,
    observed_message_count: integerValue(source.observed_message_count, 'observed_message_count'),
    observed_received_count: integerValue(source.observed_received_count, 'observed_received_count'),
    observed_sent_count: integerValue(source.observed_sent_count, 'observed_sent_count'),
    observed_conversation_count: integerValue(source.observed_conversation_count, 'observed_conversation_count'),
    observed_first_at: dateValue(source.observed_first_at, 'observed_first_at'),
    observed_last_at: dateValue(source.observed_last_at, 'observed_last_at'),
    observed_last_received_at: dateValue(source.observed_last_received_at, 'observed_last_received_at'),
    observed_last_sent_at: dateValue(source.observed_last_sent_at, 'observed_last_sent_at'),
  });
}

export function normalizeContactCoverage(value) {
  const source = objectValue(value, 'coverage');
  if (typeof source.history_may_be_truncated !== 'boolean') {
    throw new TypeError('coverage.history_may_be_truncated is malformed');
  }
  return Object.freeze({
    rows_scanned: integerValue(source.rows_scanned, 'coverage.rows_scanned'),
    row_limit: integerValue(source.row_limit, 'coverage.row_limit', { minimum: 1 }),
    history_may_be_truncated: source.history_may_be_truncated,
    observed_oldest_at: dateValue(source.observed_oldest_at, 'coverage.observed_oldest_at'),
    observed_newest_at: dateValue(source.observed_newest_at, 'coverage.observed_newest_at'),
  });
}

export function normalizeContactQueryResponse(value, { accountId } = {}) {
  const source = objectValue(value, 'contact query response');
  const normalizedAccountId = accountValue(source.account_id, accountId);
  const page = integerValue(source.page, 'page', { minimum: 1 });
  const pageSize = integerValue(source.page_size, 'page_size', { minimum: 1, maximum: 100 });
  const total = integerValue(source.total, 'total');
  const totalPages = integerValue(source.total_pages, 'total_pages');
  if (!Array.isArray(source.contacts) || source.contacts.length > pageSize) {
    throw new TypeError('contacts are malformed');
  }
  const contacts = source.contacts.map(contact => normalizeContactSummary(contact, { accountId: normalizedAccountId }));
  if (
    new Set(contacts.map(contact => contact.contact_key)).size !== contacts.length
    || new Set(contacts.map(contact => contact.address)).size !== contacts.length
  ) {
    throw new TypeError('contacts contain duplicate identities');
  }
  return Object.freeze({
    account_id: normalizedAccountId,
    page,
    page_size: pageSize,
    total,
    total_pages: totalPages,
    coverage: normalizeContactCoverage(source.coverage),
    contacts: Object.freeze(contacts),
  });
}

export function normalizeRecentContactConversation(value, { accountId } = {}) {
  const source = objectValue(value, 'recent conversation');
  const direction = textValue(source.direction, 'recent conversation direction', { maximum: 32 });
  if (!RECENT_DIRECTION_SET.has(direction)) {
    throw new TypeError('recent conversation direction is malformed');
  }
  return Object.freeze({
    account_id: accountValue(source.account_id, accountId, 'recent conversation account_id'),
    anchor_email_id: integerValue(source.anchor_email_id, 'anchor_email_id', { minimum: 1 }),
    thread_id: source.thread_id === null
      ? null
      : textValue(source.thread_id, 'thread_id', { maximum: 255 }),
    observed_last_at: dateValue(source.observed_last_at, 'recent conversation observed_last_at', { nullable: false }),
    observed_message_count: integerValue(source.observed_message_count, 'recent conversation observed_message_count', { minimum: 1 }),
    direction,
  });
}

export function normalizeContactProfileResponse(value, { accountId, contactKey } = {}) {
  const source = objectValue(value, 'contact profile response');
  const normalizedAccountId = accountValue(source.account_id, accountId);
  const contact = normalizeContactSummary(source.contact, { accountId: normalizedAccountId });
  if (contact.contact_key !== contactKey) {
    throw new TypeError('contact profile did not match the requested contact');
  }
  if (!Array.isArray(source.recent_conversations)) {
    throw new TypeError('recent_conversations are malformed');
  }
  const recentConversations = source.recent_conversations.map(item => (
    normalizeRecentContactConversation(item, { accountId: normalizedAccountId })
  ));
  if (new Set(recentConversations.map(item => `${item.thread_id ?? ''}:${item.anchor_email_id}`)).size !== recentConversations.length) {
    throw new TypeError('recent_conversations contain duplicate identities');
  }
  return Object.freeze({
    account_id: normalizedAccountId,
    contact,
    recent_conversations: Object.freeze(recentConversations),
  });
}

export function createContactQueryPayload({
  accountId,
  query = '',
  relationship = 'all',
  page = 1,
  pageSize = 50,
} = {}) {
  const normalizedAccountId = integerValue(Number(accountId), 'account_id', { minimum: 1 });
  const normalizedRelationship = String(relationship || 'all');
  if (!CONTACT_RELATIONSHIP_SET.has(normalizedRelationship)) {
    throw new TypeError('relationship is malformed');
  }
  return Object.freeze({
    account_id: normalizedAccountId,
    query: String(query || '').trim().slice(0, 254),
    relationship: normalizedRelationship,
    page: integerValue(Number(page), 'page', { minimum: 1 }),
    page_size: integerValue(Number(pageSize), 'page_size', { minimum: 1, maximum: 100 }),
  });
}

export function createContactProfilePayload({ accountId, contactKey, recentLimit = 8 } = {}) {
  const normalizedKey = textValue(contactKey, 'contact_key', { maximum: 64 });
  if (!CONTACT_KEY_RE.test(normalizedKey)) throw new TypeError('contact_key is malformed');
  return Object.freeze({
    account_id: integerValue(Number(accountId), 'account_id', { minimum: 1 }),
    contact_key: normalizedKey,
    recent_limit: integerValue(Number(recentLimit), 'recent_limit', { minimum: 1, maximum: 20 }),
  });
}

export function contactComposeIntent(accountId, contact) {
  const normalizedAccountId = integerValue(Number(accountId), 'account_id', { minimum: 1 });
  const normalized = normalizeContactSummary(contact, { accountId: normalizedAccountId });
  return newComposeIntent({
    account_id: normalizedAccountId,
    to: [normalized.formatted],
  });
}

export function contactConversationNavigationIntent(recentConversation) {
  const accountId = integerValue(Number(recentConversation?.account_id), 'account_id', { minimum: 1 });
  return normalizeRecentContactConversation(recentConversation, { accountId });
}

export function normalizeContactConversationNavigationIntent(value) {
  if (value === null) return null;
  const accountId = integerValue(Number(value?.account_id), 'account_id', { minimum: 1 });
  return normalizeRecentContactConversation(value, { accountId });
}

export function contactDisplayName(contact) {
  return contact?.name || contact?.address || 'Unknown contact';
}

export function contactInitials(contact) {
  const source = String(contact?.name || contact?.address || '?').trim();
  const words = source.split(/\s+/u).filter(Boolean);
  return (words.length > 1 ? `${words[0][0]}${words.at(-1)[0]}` : source.slice(0, 2)).toUpperCase();
}

export function formatContactObservedDate(value, { includeTime = false } = {}) {
  if (!value || !Number.isFinite(Date.parse(value))) return 'Not observed';
  return new Intl.DateTimeFormat(undefined, includeTime
    ? { dateStyle: 'medium', timeStyle: 'short' }
    : { dateStyle: 'medium' }).format(new Date(value));
}

export function contactDirectionLabel(direction) {
  if (direction === 'inbound_only') return 'Received';
  if (direction === 'outbound_only') return 'Sent';
  if (direction === 'bidirectional') return 'Sent and received';
  return 'Interaction';
}
