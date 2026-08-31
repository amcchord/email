#!/usr/bin/env node

// Deterministic localhost-only API for provider-draft browser QA.
//
// This fixture never imports application settings, reads mailbox data, or
// opens an outbound connection. Every user, account, message, attachment, and
// provider mutation is generated in memory under the reserved .example.test
// domain. The audit deliberately omits message content and attachment bytes.

import { createHash, randomUUID } from 'node:crypto';
import { createServer } from 'node:http';
import { pathToFileURL } from 'node:url';

export const GENERATED_PROVIDER_DRAFT_HOST = '127.0.0.1';
export const GENERATED_PROVIDER_DRAFT_SCENARIOS = Object.freeze([
  'clean',
  'lost-response',
  'held-session',
  'delete-fails',
  'offline',
  'recipient-delay',
  'recipient-held-session',
  'snippet-held-session',
  'recipient-fails',
]);

const MAX_BODY_BYTES = 20 * 1024 * 1024;
const MAX_ATTACHMENT_BYTES = 18 * 1024 * 1024;
const MAX_ATTACHMENTS = 10;
const MAX_PERSONAL_SNIPPETS = 250;
const DEFAULT_DISCARD_WINDOW_MS = 10_000;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SNIPPET_SHORTCUT_RE = /^[a-z0-9][a-z0-9_-]{0,31}$/;

const USERS = Object.freeze({
  'generated-a': Object.freeze({
    id: 9101,
    username: 'generated-a',
    display_name: 'Generated Draft User A',
    is_admin: false,
  }),
  'generated-b': Object.freeze({
    id: 9102,
    username: 'generated-b',
    display_name: 'Generated Draft User B',
    is_admin: false,
  }),
});

const ACCOUNTS_BY_USER = Object.freeze({
  9101: Object.freeze([
    Object.freeze({
      id: 1101,
      email: 'sender-a@example.test',
      display_name: 'Generated Sender A',
      description: 'Primary generated account',
      is_active: true,
      has_calendar_scope: true,
      sync_status: Object.freeze({ status: 'idle' }),
      calendar_sync_status: Object.freeze({ status: 'idle' }),
    }),
    Object.freeze({
      id: 1102,
      email: 'alternate-a@example.test',
      display_name: 'Generated Alternate A',
      description: 'Alternate generated account',
      is_active: true,
      has_calendar_scope: true,
      sync_status: Object.freeze({ status: 'idle' }),
      calendar_sync_status: Object.freeze({ status: 'idle' }),
    }),
  ]),
  9102: Object.freeze([
    Object.freeze({
      id: 1201,
      email: 'sender-b@example.test',
      display_name: 'Generated Sender B',
      description: 'Primary generated account',
      is_active: true,
      has_calendar_scope: true,
      sync_status: Object.freeze({ status: 'idle' }),
      calendar_sync_status: Object.freeze({ status: 'idle' }),
    }),
  ]),
});

const SOURCE_MESSAGES = Object.freeze({
  1301: Object.freeze({
    id: 1301,
    owner_user_id: 9101,
    account_id: 1101,
    account_email: 'sender-a@example.test',
    gmail_message_id: 'generated-source-message-a',
    gmail_thread_id: 'generated-source-thread-a',
    message_id_header: '<generated-parent-a@example.test>',
    references_header: '<generated-root-a@example.test>',
    from_name: 'Generated Recipient A',
    from_address: 'recipient-a@example.test',
    reply_to: 'recipient-a@example.test',
    to_addresses: Object.freeze([{ name: 'Generated Sender A', address: 'sender-a@example.test' }]),
    cc_addresses: Object.freeze([]),
    subject: 'Generated reply provenance A',
    snippet: 'Generated source message for draft provenance QA.',
    body_text: 'Generated source message for draft provenance QA.',
    body_html: '<p>Generated source message for draft provenance QA.</p>',
    date: '2026-08-30T16:00:00.000Z',
    labels: Object.freeze(['INBOX']),
    is_read: true,
    is_starred: false,
    is_trash: false,
    is_spam: false,
    is_sent: false,
    is_draft: false,
    has_attachments: false,
    attachments: Object.freeze([]),
    ai_action_items: Object.freeze([]),
    is_subscription: false,
  }),
  1302: Object.freeze({
    id: 1302,
    owner_user_id: 9102,
    account_id: 1201,
    account_email: 'sender-b@example.test',
    gmail_message_id: 'generated-source-message-b',
    gmail_thread_id: 'generated-source-thread-b',
    message_id_header: '<generated-parent-b@example.test>',
    references_header: '<generated-root-b@example.test>',
    from_name: 'Generated Recipient B',
    from_address: 'recipient-b@example.test',
    reply_to: 'recipient-b@example.test',
    to_addresses: Object.freeze([{ name: 'Generated Sender B', address: 'sender-b@example.test' }]),
    cc_addresses: Object.freeze([]),
    subject: 'Generated reply provenance B',
    snippet: 'Generated source message for session-isolation QA.',
    body_text: 'Generated source message for session-isolation QA.',
    body_html: '<p>Generated source message for session-isolation QA.</p>',
    date: '2026-08-30T16:01:00.000Z',
    labels: Object.freeze(['INBOX']),
    is_read: true,
    is_starred: false,
    is_trash: false,
    is_spam: false,
    is_sent: false,
    is_draft: false,
    has_attachments: false,
    attachments: Object.freeze([]),
    ai_action_items: Object.freeze([]),
    is_subscription: false,
  }),
});

// Generated correspondence history for recipient-autocomplete QA. The rows
// deliberately mix current address objects with legacy formatted strings,
// repeat correspondents under older names/casing, and contain owned-address
// decoys. The endpoint below derives and de-duplicates suggestions instead of
// exposing these raw rows.
const RECIPIENT_HISTORY_BY_USER = Object.freeze({
  9101: Object.freeze([
    Object.freeze({
      account_id: 1101,
      occurred_at: '2026-08-30T15:58:00.000Z',
      is_sent: false,
      from_name: 'Lovelace, Ada',
      from_address: 'ADA.CORRESPONDENT@example.test',
      to_addresses: Object.freeze([
        Object.freeze({ name: 'Generated Sender A', address: 'sender-a@example.test' }),
      ]),
      cc_addresses: Object.freeze([]),
    }),
    Object.freeze({
      account_id: 1101,
      occurred_at: '2026-08-29T14:00:00.000Z',
      is_sent: true,
      from_name: 'Generated Sender A',
      from_address: 'sender-a@example.test',
      // Legacy synchronized rows stored mailbox values as strings.
      to_addresses: Object.freeze([
        'Ada Lovelace <ada.correspondent@example.test>',
        'Legacy String Recipient <legacy-string@example.test>',
      ]),
      cc_addresses: Object.freeze([
        'Generated Alternate A <alternate-a@example.test>',
      ]),
    }),
    Object.freeze({
      account_id: 1101,
      occurred_at: '2026-08-28T18:00:00.000Z',
      is_sent: true,
      from_name: 'Generated Sender A',
      from_address: 'sender-a@example.test',
      to_addresses: Object.freeze([
        Object.freeze({ name: 'Casey Current', address: 'casey.duplicate@example.test' }),
      ]),
      cc_addresses: Object.freeze([]),
    }),
    Object.freeze({
      account_id: 1101,
      occurred_at: '2026-08-21T09:00:00.000Z',
      is_sent: false,
      from_name: 'Casey Older',
      from_address: 'CASEY.DUPLICATE@example.test',
      to_addresses: Object.freeze(['sender-a@example.test']),
      cc_addresses: Object.freeze([]),
    }),
    Object.freeze({
      account_id: 1101,
      occurred_at: '2026-08-20T09:00:00.000Z',
      is_sent: true,
      from_name: 'Generated Sender A',
      from_address: 'sender-a@example.test',
      to_addresses: Object.freeze([
        Object.freeze({ name: 'Primary Owned Decoy', address: 'sender-a@example.test' }),
      ]),
      cc_addresses: Object.freeze([]),
    }),
    Object.freeze({
      account_id: 1102,
      occurred_at: '2026-08-30T12:00:00.000Z',
      is_sent: false,
      from_name: 'Alternate Account Only',
      from_address: 'alternate-only@example.test',
      to_addresses: Object.freeze(['alternate-a@example.test']),
      cc_addresses: Object.freeze([]),
    }),
    Object.freeze({
      account_id: 1102,
      occurred_at: '2026-08-19T12:00:00.000Z',
      is_sent: true,
      from_name: 'Generated Alternate A',
      from_address: 'alternate-a@example.test',
      to_addresses: Object.freeze(['sender-a@example.test']),
      cc_addresses: Object.freeze([]),
    }),
  ]),
  9102: Object.freeze([
    Object.freeze({
      account_id: 1201,
      occurred_at: '2026-08-30T15:59:00.000Z',
      is_sent: false,
      from_name: 'User B Private Decoy',
      from_address: 'user-b-only@example.test',
      to_addresses: Object.freeze([
        Object.freeze({ name: 'Generated Sender B', address: 'sender-b@example.test' }),
      ]),
      cc_addresses: Object.freeze([]),
    }),
    Object.freeze({
      account_id: 1201,
      occurred_at: '2026-08-25T10:00:00.000Z',
      is_sent: true,
      from_name: 'Generated Sender B',
      from_address: 'sender-b@example.test',
      to_addresses: Object.freeze([
        'User B Private Decoy <USER-B-ONLY@example.test>',
        'sender-b@example.test',
      ]),
      cc_addresses: Object.freeze([]),
    }),
  ]),
});

const SEEDED_SNIPPETS_BY_USER = Object.freeze({
  9101: Object.freeze([
    Object.freeze({
      snippet_id: '00000000-0000-4000-8000-000000009101',
      name: 'Generated introduction',
      shortcut: 'intro',
      body_html: '<p>Hello from the generated snippet fixture.</p>',
      body_text: 'Hello from the generated snippet fixture.',
    }),
    Object.freeze({
      snippet_id: '00000000-0000-4000-8000-000000009102',
      name: 'Generated follow up',
      shortcut: 'follow-up',
      body_html: '<p>Following up with generated-only content.</p><img src="https://tracker.invalid/pixel.png" onerror="alert(1)"><script>alert(2)</script>',
      body_text: 'Following up with generated-only content.',
    }),
  ]),
  9102: Object.freeze([
    Object.freeze({
      snippet_id: '00000000-0000-4000-8000-000000009201',
      name: 'Generated response',
      shortcut: 'response',
      body_html: '<p>This response belongs only to generated user B.</p>',
      body_text: 'This response belongs only to generated user B.',
    }),
  ]),
});

function integerInRange(raw, fallback, minimum, maximum) {
  const value = Number.parseInt(raw ?? '', 10);
  return Number.isSafeInteger(value)
    ? Math.max(minimum, Math.min(value, maximum))
    : fallback;
}

function isUuid(value) {
  return typeof value === 'string' && UUID_RE.test(value);
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value).sort().map(key => [key, canonicalize(value[key])]),
    );
  }
  return value;
}

function sha256(value) {
  return createHash('sha256')
    .update(typeof value === 'string' ? value : JSON.stringify(canonicalize(value)))
    .digest('hex');
}

function uuidFromDigest(digest) {
  const hex = `${digest.slice(0, 12)}4${digest.slice(13, 16)}8${digest.slice(17, 32)}`;
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20, 32)}`;
}

function mailboxAddress(value) {
  if (typeof value !== 'string') return '';
  const match = value.trim().match(/(?:<([^<>]+)>|([^\s<>]+))$/);
  return (match?.[1] || match?.[2] || '').trim().toLowerCase();
}

function isGeneratedAddress(value) {
  const address = mailboxAddress(value);
  const addrSpecs = typeof value === 'string'
    ? value.match(/[^\s<>"(),;:]+@[^\s<>"(),;:]+/g) || []
    : [];
  return addrSpecs.length === 1
    && addrSpecs[0].toLowerCase() === address
    && /^[^@\s]+@(?:[^@\s.]+\.)*example\.test$/i.test(address);
}

function generatedMailbox(value) {
  let address = '';
  let name = '';
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    address = String(value.address || '').trim().toLowerCase();
    name = String(value.name || '').trim().replace(/\s+/g, ' ');
  } else if (typeof value === 'string') {
    address = mailboxAddress(value);
    const open = value.lastIndexOf('<');
    if (open >= 0) {
      name = value.slice(0, open).trim();
      if (name.startsWith('"') && name.endsWith('"')) {
        name = name.slice(1, -1).replace(/\\(["\\])/g, '$1');
      }
      name = name.trim().replace(/\s+/g, ' ');
    }
  }
  if (
    !/^[^@\s]+@(?:[^@\s.]+\.)*example\.test$/i.test(address)
    || /[\r\n\x00-\x1f\x7f]/.test(name)
  ) return null;
  return { name, address };
}

function formattedGeneratedMailbox({ name, address }) {
  if (!name) return address;
  const escaped = name.replace(/(["\\])/g, '\\$1');
  const display = /[",<>@;:]/.test(name) ? `"${escaped}"` : escaped;
  return `${display} <${address}>`;
}

function generatedRecipientSuggestions(userId, accountId, query, limit) {
  const ownedAddresses = new Set(
    (ACCOUNTS_BY_USER[userId] || []).map(account => account.email.toLowerCase()),
  );
  const correspondents = new Map();
  for (const row of RECIPIENT_HISTORY_BY_USER[userId] || []) {
    if (row.account_id !== accountId) continue;
    const candidates = row.is_sent
      ? [
          ...(Array.isArray(row.to_addresses) ? row.to_addresses : []),
          ...(Array.isArray(row.cc_addresses) ? row.cc_addresses : []),
          ...(Array.isArray(row.bcc_addresses) ? row.bcc_addresses : []),
        ]
      : [{ name: row.from_name, address: row.from_address }];
    const occurredAt = Date.parse(row.occurred_at);
    for (const candidate of candidates) {
      const mailbox = generatedMailbox(candidate);
      if (!mailbox || ownedAddresses.has(mailbox.address)) continue;
      const existing = correspondents.get(mailbox.address);
      if (!existing) {
        correspondents.set(mailbox.address, {
          ...mailbox,
          interaction_count: 1,
          last_contacted_at: occurredAt,
        });
        continue;
      }
      existing.interaction_count += 1;
      if (occurredAt > existing.last_contacted_at) {
        existing.last_contacted_at = occurredAt;
        if (mailbox.name) existing.name = mailbox.name;
      }
    }
  }

  const needle = query.trim().toLocaleLowerCase();
  return [...correspondents.values()]
    .map(item => {
      const name = item.name.toLocaleLowerCase();
      const address = item.address.toLocaleLowerCase();
      let rank = 4;
      if (needle) {
        if (name === needle || address === needle) rank = 0;
        else if (name.startsWith(needle) || address.startsWith(needle)) rank = 1;
        else if (name.includes(needle) || address.includes(needle)) rank = 2;
        else rank = Number.POSITIVE_INFINITY;
      }
      return { ...item, rank };
    })
    .filter(item => Number.isFinite(item.rank))
    .sort((left, right) => (
      left.rank - right.rank
      || right.interaction_count - left.interaction_count
      || right.last_contacted_at - left.last_contacted_at
      || left.address.localeCompare(right.address)
    ))
    .slice(0, limit)
    .map(({ name, address }) => ({
      name,
      address,
      formatted: formattedGeneratedMailbox({ name, address }),
    }));
}

function clone(value) {
  return structuredClone(value);
}

function newCounters() {
  return {
    draft_upsert_requests: 0,
    draft_get_requests: 0,
    draft_discard_requests: 0,
    draft_undo_discard_requests: 0,
    provider_draft_creates: 0,
    provider_draft_updates: 0,
    provider_delete_attempts: 0,
    provider_draft_deletes: 0,
    provider_delete_failures: 0,
    outbound_accepts: 0,
    outbound_cancels: 0,
    outbound_send_now: 0,
    provider_send_lookups: 0,
    provider_sends: 0,
    post_send_archives: 0,
    same_mutation_replays: 0,
    same_revision_replays: 0,
    immutable_revision_conflicts: 0,
    stale_revision_rejections: 0,
    mutation_conflicts: 0,
    account_conflicts: 0,
    source_conflicts: 0,
    lost_responses_after_persist: 0,
    retries_after_lost_response: 0,
    held_responses: 0,
    stale_session_responses_released: 0,
    offline_rejections: 0,
    offline_recoveries: 0,
    attachment_upserts: 0,
    attachment_bytes_upserted: 0,
    attachment_rehydrates: 0,
    attachment_bytes_rehydrated: 0,
    provenance_checks: 0,
    provenance_rejections: 0,
    auth_transitions: 0,
    discard_undos: 0,
    discard_replays: 0,
    snippet_list_requests: 0,
    snippet_create_requests: 0,
    snippet_replace_requests: 0,
    snippet_delete_requests: 0,
    snippet_creates: 0,
    snippet_updates: 0,
    snippet_deletes: 0,
    snippet_create_replays: 0,
    snippet_update_replays: 0,
    snippet_conflicts: 0,
    snippet_not_found: 0,
    snippet_list_held_requests: 0,
    snippet_list_stale_session_responses: 0,
    snippet_list_releases: 0,
    recipient_lookup_requests: 0,
    recipient_lookup_successes: 0,
    recipient_lookup_failures: 0,
    recipient_lookup_delays: 0,
    recipient_lookup_held: 0,
    recipient_lookup_stale_session_responses: 0,
    recipient_lookup_account_rejections: 0,
    expected_mutations: 0,
    unexpected_mutations: 0,
    unknown_routes: 0,
    non_example_test_rejections: 0,
    rejected_payloads: 0,
    qa_control_mutations: 0,
    external_network_calls: 0,
  };
}

function publicUser(user) {
  return user ? clone(user) : null;
}

function accountForUser(userId, accountId) {
  return (ACCOUNTS_BY_USER[userId] || []).find(account => account.id === accountId) || null;
}

function sourceForUser(userId, sourceEmailId) {
  const source = SOURCE_MESSAGES[sourceEmailId];
  return source?.owner_user_id === userId ? source : null;
}

function providerDraftId(userId, sequence) {
  return `generated-provider-draft-${userId}-${String(sequence).padStart(4, '0')}`;
}

export function createGeneratedProviderDraftFixture({
  discardWindowMs = DEFAULT_DISCARD_WINDOW_MS,
} = {}) {
  let scenario = 'clean';
  let connectivity = 'online';
  let currentUser = USERS['generated-a'];
  let activeDiscardWindowMs = integerInRange(
    discardWindowMs,
    DEFAULT_DISCARD_WINDOW_MS,
    1,
    60_000,
  );
  let counters = newCounters();
  let auditSequence = 0;
  let providerSequence = 0;
  let firstLostResponseUsed = false;
  let firstHeldResponseUsed = false;
  let firstRecipientHeldResponseUsed = false;
  let firstSnippetHeldResponseUsed = false;
  const drafts = new Map();
  const outbounds = new Map();
  const outboundIdempotency = new Map();
  const mutations = new Map();
  const snippets = new Map();
  const offlineMutationIds = new Set();
  const events = [];
  const heldResponses = [];
  let clockNowMs = Date.parse('2026-08-30T16:00:00.000Z');

  function logicalKey(userId, clientDraftId) {
    return `${userId}:${clientDraftId}`;
  }

  function mutationKey(userId, mutationId) {
    return `${userId}:${mutationId}`;
  }

  function outboundKey(userId, sendId) {
    return `${userId}:${sendId}`;
  }

  function outboundIdempotencyKey(userId, idempotencyKey) {
    return `${userId}:${idempotencyKey}`;
  }

  function snippetKey(userId, snippetId) {
    return `${userId}:${snippetId}`;
  }

  function clockIso() {
    return new Date(clockNowMs).toISOString();
  }

  function recordEvent(kind, request, pathname, extra = {}) {
    auditSequence += 1;
    const event = {
      sequence: auditSequence,
      kind,
      method: request?.method || null,
      pathname,
      user_id: currentUser?.id || null,
      ...extra,
    };
    events.push(event);
    return event;
  }

  function writeJson(response, payload, status = 200, extraHeaders = {}) {
    if (response.destroyed || response.writableEnded) return;
    const body = JSON.stringify(payload);
    response.writeHead(status, {
      'Content-Type': 'application/json; charset=utf-8',
      'Content-Length': Buffer.byteLength(body),
      'Cache-Control': 'no-store',
      ...extraHeaders,
    });
    response.end(body);
  }

  function writeError(response, status, code, message, extra = {}) {
    writeJson(response, {
      detail: { code, message },
      ...extra,
    }, status);
  }

  function writeEmpty(response, status = 204) {
    if (response.destroyed || response.writableEnded) return;
    response.writeHead(status, {
      'Cache-Control': 'no-store',
    });
    response.end();
  }

  async function readJson(request) {
    const chunks = [];
    let total = 0;
    for await (const chunk of request) {
      total += chunk.length;
      if (total > MAX_BODY_BYTES) throw new Error('Generated QA payload is too large');
      chunks.push(chunk);
    }
    if (chunks.length === 0) return {};
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  }

  function requireUser(response) {
    if (currentUser) return true;
    writeError(response, 401, 'unauthorized', 'Generated authentication is required');
    return false;
  }

  function attachmentBytes(attachment) {
    if (!attachment || typeof attachment !== 'object') {
      throw new Error('Attachment must be an object');
    }
    if (
      typeof attachment.filename !== 'string'
      || !attachment.filename.trim()
      || /[\r\n]/.test(attachment.filename)
    ) {
      throw new Error('Attachment filename is invalid');
    }
    if (
      typeof attachment.content_type !== 'string'
      || !attachment.content_type.trim()
      || /[\r\n]/.test(attachment.content_type)
    ) {
      throw new Error('Attachment content type is invalid');
    }
    if (
      typeof attachment.data_base64 !== 'string'
      || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(
        attachment.data_base64,
      )
    ) {
      throw new Error('Attachment data is not valid base64');
    }
    return Buffer.from(attachment.data_base64, 'base64');
  }

  function normalizeComposePayload(raw) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
      throw new Error('Draft payload must be an object');
    }
    if (!isUuid(raw.client_draft_id)) throw new Error('client_draft_id must be a UUID');
    if (!isUuid(raw.mutation_id)) throw new Error('mutation_id must be a UUID');
    if (!Number.isSafeInteger(raw.revision) || raw.revision < 1) {
      throw new Error('revision must be a positive integer');
    }
    if (!Number.isSafeInteger(raw.account_id) || !accountForUser(currentUser.id, raw.account_id)) {
      throw new Error('Generated account is not owned by this user');
    }

    const recipientFields = {};
    for (const field of ['to', 'cc', 'bcc']) {
      const values = raw[field] ?? [];
      if (!Array.isArray(values)) throw new Error(`${field} must be an array`);
      if (!values.every(isGeneratedAddress)) {
        counters.non_example_test_rejections += 1;
        throw new Error(`${field} accepts only .example.test addresses`);
      }
      recipientFields[field] = values.map(mailboxAddress);
    }

    const attachments = raw.attachments ?? [];
    if (!Array.isArray(attachments)) throw new Error('attachments must be an array');
    if (attachments.length > MAX_ATTACHMENTS) {
      throw new Error(`A draft can include at most ${MAX_ATTACHMENTS} attachments`);
    }
    let attachmentTotal = 0;
    const normalizedAttachments = attachments.map((attachment, attachmentIndex) => {
      const bytes = attachmentBytes(attachment);
      attachmentTotal += bytes.length;
      const attachmentSha256 = sha256(bytes.toString('base64'));
      return {
        attachment_id: uuidFromDigest(sha256({
          attachment_index: attachmentIndex,
          content_type: attachment.content_type.trim(),
          filename: attachment.filename.trim(),
          sha256: attachmentSha256,
        })),
        filename: attachment.filename.trim(),
        content_type: attachment.content_type.trim(),
        size_bytes: bytes.length,
        sha256: attachmentSha256,
        data_base64: bytes.toString('base64'),
      };
    });
    if (attachmentTotal > MAX_ATTACHMENT_BYTES) {
      throw new Error('Attachments exceed the generated 18 MB draft limit');
    }

    const sourceEmailId = raw.source_email_id ?? null;
    let threadId = raw.thread_id || null;
    let inReplyTo = raw.in_reply_to || null;
    let references = raw.references || null;
    if (sourceEmailId !== null) {
      counters.provenance_checks += 1;
      const source = sourceForUser(currentUser.id, sourceEmailId);
      const expectedReferences = source
        ? [source.references_header, source.message_id_header].filter(Boolean).join(' ')
        : null;
      if (
        !source
        || source.account_id !== raw.account_id
        || (threadId && threadId !== source.gmail_thread_id)
        || (inReplyTo && inReplyTo !== source.message_id_header)
        || (references && references !== expectedReferences)
      ) {
        counters.provenance_rejections += 1;
        const error = new Error('Generated reply provenance is not owned by this account');
        error.code = 'draft_provenance_invalid';
        throw error;
      }
      threadId = source.gmail_thread_id;
      inReplyTo = source.message_id_header;
      references = expectedReferences;
    } else if (threadId || inReplyTo || references) {
      counters.provenance_checks += 1;
      counters.provenance_rejections += 1;
      const error = new Error('source_email_id is required for reply provenance');
      error.code = 'draft_provenance_invalid';
      throw error;
    }

    return {
      client_draft_id: raw.client_draft_id,
      mutation_id: raw.mutation_id,
      revision: raw.revision,
      account_id: raw.account_id,
      ...recipientFields,
      subject: typeof raw.subject === 'string' ? raw.subject : '',
      body_html: typeof raw.body_html === 'string' ? raw.body_html : '',
      body_text: typeof raw.body_text === 'string' ? raw.body_text : '',
      in_reply_to: inReplyTo,
      references,
      thread_id: threadId,
      source_email_id: sourceEmailId,
      is_draft: true,
      attachments: normalizedAttachments,
      _attachment_bytes: attachmentTotal,
    };
  }

  function immutablePayload(payload) {
    const {
      mutation_id: _mutationId,
      _attachment_bytes: _attachmentBytes,
      ...immutable
    } = payload;
    return immutable;
  }

  function draftSummary(record) {
    return {
      client_draft_id: record.client_draft_id,
      provider_draft_id_hash: sha256(record.draft_id),
      owner_user_id: record.owner_user_id,
      account_id: record.account_id,
      revision: record.revision,
      synced_revision: record.synced_revision,
      state: record.state,
      can_undo_discard: record.can_undo_discard,
      can_retry: record.can_retry,
      discard_at: record.discard_at,
      discard_undo_until: record.discard_undo_until,
      payload_hash: record.payload_hash,
      attachment_count: record.payload.attachments.length,
      attachment_bytes: record.attachment_bytes,
      provider_create_count: record.provider_create_count,
      provider_update_count: record.provider_update_count,
      provider_delete_count: record.provider_delete_count,
    };
  }

  function draftResponse(record, { includeContent = false } = {}) {
    const response = {
      client_draft_id: record.client_draft_id,
      account_id: record.account_id,
      source_email_id: record.payload.source_email_id,
      revision: record.revision,
      synced_revision: record.synced_revision,
      state: record.state,
      next_attempt_at: record.next_attempt_at,
      attempt_count: record.attempt_count,
      can_undo_discard: record.can_undo_discard,
      discard_at: record.discard_at,
      discard_undo_until: record.discard_undo_until,
      linked_send_id: record.linked_send_id || null,
      error_code: record.error_code,
      error_message: record.error_message,
      attachment_count: record.payload.attachments.length,
      attachment_bytes: record.attachment_bytes,
      created_at: record.created_at,
      updated_at: record.updated_at,
      synced_at: record.synced_at,
      discarded_at: record.discarded_at,
    };
    if (includeContent && record.state !== 'discarded') {
      Object.assign(response, clone(record.payload));
      delete response.mutation_id;
      delete response._attachment_bytes;
    }
    return response;
  }

  function rememberMutation(userId, mutationId, value) {
    mutations.set(mutationKey(userId, mutationId), value);
  }

  function mutationReplay(userId, mutationId, expected) {
    const existing = mutations.get(mutationKey(userId, mutationId));
    if (!existing) return null;
    if (
      existing.kind !== expected.kind
      || existing.client_draft_id !== expected.client_draft_id
      || existing.revision !== expected.revision
      || existing.payload_hash !== expected.payload_hash
    ) {
      counters.mutation_conflicts += 1;
      const error = new Error('mutation_id is already bound to another immutable operation');
      error.code = 'draft_mutation_conflict';
      throw error;
    }
    counters.same_mutation_replays += 1;
    return existing;
  }

  function markExpectedMutation(request, pathname, kind) {
    counters.expected_mutations += 1;
    recordEvent(kind, request, pathname, { expected: true });
  }

  function snippetInvalid(message) {
    const error = new Error(message);
    error.code = 'snippet_invalid';
    return error;
  }

  function normalizeSnippetPayload(body, { replace = false } = {}) {
    if (!body || typeof body !== 'object' || Array.isArray(body)) {
      throw snippetInvalid('Snippet payload must be an object');
    }
    const allowed = new Set([
      'name',
      'shortcut',
      'body_html',
      'body_text',
      replace ? 'expected_revision' : 'snippet_id',
    ]);
    if (Object.keys(body).some(key => !allowed.has(key))) {
      throw snippetInvalid('Snippet payload contains unsupported fields');
    }

    const name = typeof body.name === 'string'
      ? body.name.trim().split(/\s+/).filter(Boolean).join(' ')
      : '';
    let shortcut = typeof body.shortcut === 'string' ? body.shortcut.trim().toLowerCase() : '';
    if (shortcut.startsWith(';')) shortcut = shortcut.slice(1).trim();
    const normalizeBody = value => (
      typeof value === 'string'
        ? value.replace(/\r\n?/g, '\n').trim()
        : ''
    );
    const bodyHtml = normalizeBody(body.body_html);
    const bodyText = normalizeBody(body.body_text);

    if (!name || name.length > 120) throw snippetInvalid('Snippet name is invalid');
    if (!SNIPPET_SHORTCUT_RE.test(shortcut)) throw snippetInvalid('Snippet shortcut is invalid');
    if (!bodyHtml || bodyHtml.length > 50_000 || /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(bodyHtml)) {
      throw snippetInvalid('Snippet HTML is invalid');
    }
    if (!bodyText || bodyText.length > 20_000 || /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(bodyText)) {
      throw snippetInvalid('Snippet text is invalid');
    }

    const normalized = {
      name,
      shortcut,
      body_html: bodyHtml,
      body_text: bodyText,
    };
    if (replace) {
      if (!Number.isSafeInteger(body.expected_revision) || body.expected_revision <= 0) {
        throw snippetInvalid('expected_revision must be a positive integer');
      }
      normalized.expected_revision = body.expected_revision;
    } else {
      if (!isUuid(body.snippet_id)) throw snippetInvalid('snippet_id must be a UUID');
      normalized.snippet_id = body.snippet_id.toLowerCase();
    }
    return normalized;
  }

  function publicSnippet(record) {
    return {
      snippet_id: record.snippet_id,
      name: record.name,
      shortcut: record.shortcut,
      body_html: record.body_html,
      body_text: record.body_text,
      revision: record.revision,
      created_at: record.created_at,
      updated_at: record.updated_at,
    };
  }

  function snippetContentMatches(record, payload) {
    return record.name === payload.name
      && record.shortcut === payload.shortcut
      && record.body_html === payload.body_html
      && record.body_text === payload.body_text;
  }

  function seedSnippets() {
    snippets.clear();
    for (const [userIdRaw, seeded] of Object.entries(SEEDED_SNIPPETS_BY_USER)) {
      const userId = Number(userIdRaw);
      for (const item of seeded) {
        const timestamp = clockIso();
        snippets.set(snippetKey(userId, item.snippet_id), {
          ...clone(item),
          owner_user_id: userId,
          revision: 1,
          created_at: timestamp,
          updated_at: timestamp,
          seeded: true,
        });
      }
    }
  }

  function ownedSnippets() {
    return [...snippets.values()]
      .filter(record => record.owner_user_id === currentUser.id)
      .sort((left, right) => (
        left.name.localeCompare(right.name, undefined, { sensitivity: 'base' })
        || left.snippet_id.localeCompare(right.snippet_id)
      ));
  }

  function handleSnippetList(request, response, pathname) {
    const requestUserId = currentUser.id;
    counters.snippet_list_requests += 1;
    const records = ownedSnippets();
    const payload = {
      snippets: records.map(publicSnippet),
      total: records.length,
      limit: MAX_PERSONAL_SNIPPETS,
    };
    const eventMetadata = {
      count: records.length,
      request_user_id: requestUserId,
    };
    if (
      scenario === 'snippet-held-session'
      && requestUserId === USERS['generated-a'].id
      && !firstSnippetHeldResponseUsed
    ) {
      firstSnippetHeldResponseUsed = true;
      counters.snippet_list_held_requests += 1;
      const held = {
        kind: 'snippet',
        response,
        request_user_id: requestUserId,
        payload,
        event_metadata: eventMetadata,
      };
      heldResponses.push(held);
      request.on('close', () => {
        const index = heldResponses.indexOf(held);
        if (index >= 0) heldResponses.splice(index, 1);
      });
      recordEvent('snippet_list_held', request, pathname, eventMetadata);
      return;
    }
    recordEvent('snippet_listed', request, pathname, eventMetadata);
    return writeJson(response, payload);
  }

  async function handleSnippetCreate(request, response, pathname) {
    markExpectedMutation(request, pathname, 'snippet_create_request');
    counters.snippet_create_requests += 1;
    let payload;
    try {
      payload = normalizeSnippetPayload(await readJson(request));
    } catch (error) {
      counters.rejected_payloads += 1;
      return writeError(response, 422, error.code || 'snippet_invalid', error.message);
    }

    const ownKey = snippetKey(currentUser.id, payload.snippet_id);
    const existing = snippets.get(ownKey);
    if (existing) {
      if (snippetContentMatches(existing, payload)) {
        counters.snippet_create_replays += 1;
        recordEvent('snippet_create_replayed', request, pathname, {
          snippet_id: existing.snippet_id,
          revision: existing.revision,
        });
        return writeJson(response, publicSnippet(existing));
      }
      counters.snippet_conflicts += 1;
      return writeError(response, 409, 'snippet_conflict', 'That snippet request ID is already used');
    }
    if (ownedSnippets().some(record => record.shortcut === payload.shortcut)) {
      counters.snippet_conflicts += 1;
      return writeError(response, 409, 'snippet_conflict', 'That snippet shortcut is already in use');
    }
    if (ownedSnippets().length >= MAX_PERSONAL_SNIPPETS) {
      return writeError(
        response,
        429,
        'snippet_quota_exceeded',
        `A user can keep at most ${MAX_PERSONAL_SNIPPETS} personal snippets`,
      );
    }

    const timestamp = clockIso();
    const record = {
      ...payload,
      owner_user_id: currentUser.id,
      revision: 1,
      created_at: timestamp,
      updated_at: timestamp,
      seeded: false,
    };
    snippets.set(ownKey, record);
    counters.snippet_creates += 1;
    recordEvent('snippet_created', request, pathname, {
      snippet_id: record.snippet_id,
      revision: record.revision,
    });
    return writeJson(response, publicSnippet(record), 201);
  }

  async function handleSnippetReplace(request, response, pathname, snippetId) {
    markExpectedMutation(request, pathname, 'snippet_replace_request');
    counters.snippet_replace_requests += 1;
    if (!isUuid(snippetId)) {
      counters.rejected_payloads += 1;
      return writeError(response, 422, 'snippet_invalid', 'snippet_id must be a UUID');
    }
    let payload;
    try {
      payload = normalizeSnippetPayload(await readJson(request), { replace: true });
    } catch (error) {
      counters.rejected_payloads += 1;
      return writeError(response, 422, error.code || 'snippet_invalid', error.message);
    }

    const record = snippets.get(snippetKey(currentUser.id, snippetId.toLowerCase()));
    if (!record) {
      counters.snippet_not_found += 1;
      return writeError(response, 404, 'snippet_not_found', 'Snippet not found');
    }
    if (record.revision === payload.expected_revision + 1 && snippetContentMatches(record, payload)) {
      counters.snippet_update_replays += 1;
      recordEvent('snippet_update_replayed', request, pathname, {
        snippet_id: record.snippet_id,
        revision: record.revision,
      });
      return writeJson(response, publicSnippet(record));
    }
    if (record.revision !== payload.expected_revision) {
      counters.snippet_conflicts += 1;
      return writeError(
        response,
        409,
        'snippet_conflict',
        'This snippet changed on another device; refresh it',
      );
    }
    if (ownedSnippets().some(item => (
      item.snippet_id !== record.snippet_id && item.shortcut === payload.shortcut
    ))) {
      counters.snippet_conflicts += 1;
      return writeError(response, 409, 'snippet_conflict', 'That snippet shortcut is already in use');
    }

    Object.assign(record, {
      name: payload.name,
      shortcut: payload.shortcut,
      body_html: payload.body_html,
      body_text: payload.body_text,
      revision: record.revision + 1,
      updated_at: clockIso(),
    });
    counters.snippet_updates += 1;
    recordEvent('snippet_updated', request, pathname, {
      snippet_id: record.snippet_id,
      revision: record.revision,
    });
    return writeJson(response, publicSnippet(record));
  }

  function handleSnippetDelete(request, response, pathname, snippetId, expectedRevisionRaw) {
    markExpectedMutation(request, pathname, 'snippet_delete_request');
    counters.snippet_delete_requests += 1;
    const expectedRevision = Number(expectedRevisionRaw);
    if (!isUuid(snippetId) || !Number.isSafeInteger(expectedRevision) || expectedRevision <= 0) {
      counters.rejected_payloads += 1;
      return writeError(response, 422, 'snippet_invalid', 'A UUID and positive expected_revision are required');
    }

    const key = snippetKey(currentUser.id, snippetId.toLowerCase());
    const record = snippets.get(key);
    if (!record) {
      counters.snippet_not_found += 1;
      recordEvent('snippet_delete_replayed_or_hidden', request, pathname, {
        snippet_id: snippetId.toLowerCase(),
      });
      return writeEmpty(response);
    }
    if (record.revision !== expectedRevision) {
      counters.snippet_conflicts += 1;
      return writeError(
        response,
        409,
        'snippet_conflict',
        'This snippet changed on another device; refresh it',
      );
    }

    snippets.delete(key);
    counters.snippet_deletes += 1;
    recordEvent('snippet_deleted', request, pathname, {
      snippet_id: record.snippet_id,
      revision: record.revision,
    });
    return writeEmpty(response);
  }

  async function handleRecipientSuggestions(request, response, pathname, url) {
    const requestUserId = currentUser.id;
    counters.recipient_lookup_requests += 1;
    const accountId = Number(url.searchParams.get('account_id'));
    if (!Number.isSafeInteger(accountId) || !accountForUser(requestUserId, accountId)) {
      counters.recipient_lookup_account_rejections += 1;
      recordEvent('recipient_lookup_account_rejected', request, pathname, {
        account_id: Number.isSafeInteger(accountId) ? accountId : null,
        request_user_id: requestUserId,
      });
      return writeError(response, 404, 'account_not_found', 'Generated account not found');
    }

    const query = String(
      url.searchParams.has('q')
        ? url.searchParams.get('q')
        : url.searchParams.get('query') || '',
    ).trim();
    if (query.length > 200 || /[\r\n\x00-\x1f\x7f]/.test(query)) {
      counters.rejected_payloads += 1;
      counters.recipient_lookup_failures += 1;
      recordEvent('recipient_lookup_rejected', request, pathname, {
        account_id: accountId,
        query_length: query.length,
        request_user_id: requestUserId,
      });
      return writeError(response, 422, 'recipient_query_invalid', 'Recipient query is invalid');
    }
    const limit = integerInRange(url.searchParams.get('limit'), 8, 1, 20);

    if (scenario === 'recipient-fails') {
      counters.recipient_lookup_failures += 1;
      recordEvent('recipient_lookup_failed', request, pathname, {
        account_id: accountId,
        query_length: query.length,
        request_user_id: requestUserId,
      });
      return writeError(
        response,
        503,
        'recipient_lookup_unavailable',
        'Generated recipient suggestions are temporarily unavailable',
      );
    }

    const payload = {
      suggestions: generatedRecipientSuggestions(requestUserId, accountId, query, limit),
    };
    const eventMetadata = {
      account_id: accountId,
      query_length: query.length,
      request_user_id: requestUserId,
      result_count: payload.suggestions.length,
    };

    if (scenario === 'recipient-held-session' && !firstRecipientHeldResponseUsed) {
      firstRecipientHeldResponseUsed = true;
      counters.recipient_lookup_delays += 1;
      counters.recipient_lookup_held += 1;
      const held = {
        kind: 'recipient',
        response,
        request_user_id: requestUserId,
        payload,
        event_metadata: eventMetadata,
      };
      heldResponses.push(held);
      request.on('close', () => {
        const index = heldResponses.indexOf(held);
        if (index >= 0) heldResponses.splice(index, 1);
      });
      recordEvent('recipient_lookup_held', request, pathname, eventMetadata);
      return;
    }

    if (scenario === 'recipient-delay') {
      counters.recipient_lookup_delays += 1;
      recordEvent('recipient_lookup_delayed', request, pathname, eventMetadata);
      await new Promise(resolve => setTimeout(resolve, 60));
      if (currentUser?.id !== requestUserId) {
        counters.recipient_lookup_stale_session_responses += 1;
      }
    }

    counters.recipient_lookup_successes += 1;
    recordEvent('recipient_lookup_succeeded', request, pathname, eventMetadata);
    return writeJson(response, payload);
  }

  seedSnippets();

  function dropResponseAfterPersistence(request, response, record) {
    firstLostResponseUsed = true;
    record.state = 'reconciling';
    record.updated_at = new Date().toISOString();
    counters.lost_responses_after_persist += 1;
    recordEvent('lost_response_after_persist', request, '/api/compose/draft', {
      client_draft_id: record.client_draft_id,
      revision: record.revision,
      payload_hash: record.payload_hash,
    });
    response.socket?.destroy();
  }

  function holdResponseAfterPersistence(request, response, record, mutationId) {
    firstHeldResponseUsed = true;
    record.state = 'syncing';
    record.updated_at = new Date().toISOString();
    counters.held_responses += 1;
    const held = {
      kind: 'draft',
      response,
      request_user_id: currentUser.id,
      client_draft_id: record.client_draft_id,
      mutation_id: mutationId,
    };
    heldResponses.push(held);
    request.on('close', () => {
      const index = heldResponses.indexOf(held);
      if (index >= 0) heldResponses.splice(index, 1);
    });
  }

  function advanceDiscard(request, pathname, record) {
    if (record.state === 'discard_pending') {
      record.can_undo_discard = Date.now() < Date.parse(record.discard_undo_until || '');
      if (record.can_undo_discard) return;
      record.can_retry = false;
      if (scenario === 'delete-fails' && !record.delete_failure_used) {
        record.delete_failure_used = true;
        record.state = 'failed';
        record.error_code = 'generated_provider_delete_unavailable';
        record.error_message = 'Generated provider delete failed before mutation.';
        record.can_retry = true;
        record.updated_at = new Date().toISOString();
        record.attempt_count += 1;
        counters.provider_delete_attempts += 1;
        counters.provider_delete_failures += 1;
        recordEvent('provider_delete_failed', request, pathname, {
          client_draft_id: record.client_draft_id,
          draft_id_hash: sha256(record.draft_id),
        });
        return;
      }
      record.state = 'syncing';
      record.can_undo_discard = false;
      record.next_attempt_at = null;
      record.error_code = null;
      record.error_message = null;
      record.updated_at = new Date().toISOString();
      if (!record.provider_delete_committed) {
        record.provider_delete_committed = true;
        record.provider_delete_count += 1;
        record.attempt_count += 1;
        counters.provider_delete_attempts += 1;
        counters.provider_draft_deletes += 1;
        recordEvent('provider_draft_deleted', request, pathname, {
          client_draft_id: record.client_draft_id,
          draft_id_hash: sha256(record.draft_id),
        });
      }
      return;
    }

    if (record.state === 'failed' && record.delete_failure_used) {
      record.state = 'syncing';
      record.can_retry = false;
      record.error_code = null;
      record.error_message = null;
      record.updated_at = new Date().toISOString();
      if (!record.provider_delete_committed) {
        record.provider_delete_committed = true;
        record.provider_delete_count += 1;
        record.attempt_count += 1;
        counters.provider_delete_attempts += 1;
        counters.provider_draft_deletes += 1;
        recordEvent('provider_draft_deleted', request, pathname, {
          client_draft_id: record.client_draft_id,
          draft_id_hash: sha256(record.draft_id),
        });
      }
      return;
    }

    if (record.state === 'syncing' && record.provider_delete_committed) {
      record.state = 'discarded';
      record.discarded_at = new Date().toISOString();
      record.updated_at = record.discarded_at;
      record.can_undo_discard = false;
      record.can_retry = false;
    }
  }

  async function handleDraftUpsert(request, response, pathname) {
    if (!requireUser(response)) return;
    markExpectedMutation(request, pathname, 'draft_upsert');
    counters.draft_upsert_requests += 1;

    let payload;
    try {
      payload = normalizeComposePayload(await readJson(request));
    } catch (error) {
      counters.rejected_payloads += 1;
      recordEvent('draft_payload_rejected', request, pathname, {
        error_code: error.code || 'draft_invalid',
      });
      return writeError(
        response,
        error.code === 'draft_provenance_invalid' ? 422 : 422,
        error.code || 'draft_invalid',
        error.message,
      );
    }

    const immutable = immutablePayload(payload);
    const payloadHash = sha256(immutable);
    const key = logicalKey(currentUser.id, payload.client_draft_id);
    const existing = drafts.get(key);
    const expectedMutation = {
      kind: 'upsert',
      client_draft_id: payload.client_draft_id,
      revision: payload.revision,
      payload_hash: payloadHash,
    };

    let replay;
    try {
      replay = mutationReplay(currentUser.id, payload.mutation_id, expectedMutation);
    } catch (error) {
      return writeError(response, 409, error.code, error.message);
    }
    if (replay) {
      const replayedDraft = drafts.get(key);
      if (!replayedDraft) {
        return writeError(response, 409, 'draft_mutation_orphaned', 'Generated mutation has no draft');
      }
      if (replay.lost_response) {
        replay.lost_response = false;
        replayedDraft.state = 'synced';
        replayedDraft.updated_at = new Date().toISOString();
        counters.retries_after_lost_response += 1;
      }
      return writeJson(response, draftResponse(replayedDraft), 202);
    }

    if (connectivity === 'offline') {
      offlineMutationIds.add(mutationKey(currentUser.id, payload.mutation_id));
      counters.offline_rejections += 1;
      recordEvent('draft_offline', request, pathname, {
        client_draft_id: payload.client_draft_id,
        revision: payload.revision,
        payload_hash: payloadHash,
      });
      return writeError(
        response,
        503,
        'draft_offline',
        'Generated draft API is offline; keep the local recovery copy.',
        {
          client_draft_id: payload.client_draft_id,
          revision: payload.revision,
          state: 'pending',
        },
      );
    }

    if (existing) {
      if (existing.account_id !== payload.account_id) {
        counters.account_conflicts += 1;
        return writeError(
          response,
          409,
          'draft_account_conflict',
          'A provider draft identity cannot move between generated accounts',
        );
      }
      if (existing.state === 'discarded') {
        return writeError(response, 409, 'draft_discarded', 'This provider draft was discarded');
      }
      if (payload.revision < existing.revision) {
        counters.stale_revision_rejections += 1;
        return writeError(response, 409, 'draft_revision_stale', 'Draft revision is stale');
      }
      if (payload.revision === existing.revision) {
        if (payloadHash !== existing.payload_hash) {
          counters.immutable_revision_conflicts += 1;
          return writeError(
            response,
            409,
            'draft_revision_conflict',
            'Draft revision is already bound to another immutable payload',
          );
        }
        counters.same_revision_replays += 1;
        rememberMutation(currentUser.id, payload.mutation_id, expectedMutation);
        return writeJson(response, draftResponse(existing), 202);
      }

      existing.revision = payload.revision;
      existing.payload = clone(immutable);
      existing.payload_hash = payloadHash;
      existing.attachment_bytes = payload._attachment_bytes;
      existing.state = 'synced';
      existing.synced_revision = payload.revision;
      existing.can_undo_discard = false;
      existing.can_retry = false;
      existing.discard_at = null;
      existing.discard_undo_until = null;
      existing.next_attempt_at = null;
      existing.error_code = null;
      existing.error_message = null;
      existing.synced_at = new Date().toISOString();
      existing.updated_at = existing.synced_at;
      existing.attempt_count += 1;
      existing.provider_update_count += 1;
      counters.provider_draft_updates += 1;
      counters.attachment_upserts += existing.payload.attachments.length;
      counters.attachment_bytes_upserted += existing.attachment_bytes;
    } else {
      if (payload.source_email_id !== null) {
        const sourceOwner = [...drafts.values()].find(candidate => (
          candidate.owner_user_id === currentUser.id
          && candidate.account_id === payload.account_id
          && candidate.payload.source_email_id === payload.source_email_id
          && candidate.state !== 'discarded'
        ));
        if (sourceOwner) {
          counters.source_conflicts += 1;
          return writeError(
            response,
            409,
            'draft_source_exists',
            'A generated reply draft already owns this exact source',
          );
        }
      }
      providerSequence += 1;
      const timestamp = new Date().toISOString();
      drafts.set(key, {
        client_draft_id: payload.client_draft_id,
        draft_id: providerDraftId(currentUser.id, providerSequence),
        email_id: 50_000 + providerSequence,
        owner_user_id: currentUser.id,
        account_id: payload.account_id,
        revision: payload.revision,
        payload: clone(immutable),
        payload_hash: payloadHash,
        attachment_bytes: payload._attachment_bytes,
        state: 'synced',
        synced_revision: payload.revision,
        can_undo_discard: false,
        can_retry: false,
        discard_at: null,
        discard_undo_until: null,
        next_attempt_at: null,
        attempt_count: 1,
        error_code: null,
        error_message: null,
        created_at: timestamp,
        synced_at: timestamp,
        updated_at: timestamp,
        discarded_at: null,
        linked_send_id: null,
        provider_create_count: 1,
        provider_update_count: 0,
        provider_delete_count: 0,
        provider_delete_committed: false,
        delete_failure_used: false,
      });
      counters.provider_draft_creates += 1;
      counters.attachment_upserts += payload.attachments.length;
      counters.attachment_bytes_upserted += payload._attachment_bytes;
    }

    const record = drafts.get(key);
    const storedMutation = { ...expectedMutation, lost_response: false };
    rememberMutation(currentUser.id, payload.mutation_id, storedMutation);
    if (offlineMutationIds.delete(mutationKey(currentUser.id, payload.mutation_id))) {
      counters.offline_recoveries += 1;
    }
    recordEvent(existing ? 'provider_draft_updated' : 'provider_draft_created', request, pathname, {
      client_draft_id: record.client_draft_id,
      revision: record.revision,
      payload_hash: record.payload_hash,
      draft_id_hash: sha256(record.draft_id),
      attachment_count: record.payload.attachments.length,
      attachment_bytes: record.attachment_bytes,
    });

    if (scenario === 'lost-response' && !firstLostResponseUsed) {
      storedMutation.lost_response = true;
      return dropResponseAfterPersistence(request, response, record);
    }
    if (
      scenario === 'held-session'
      && currentUser.id === USERS['generated-a'].id
      && !firstHeldResponseUsed
    ) {
      return holdResponseAfterPersistence(request, response, record, payload.mutation_id);
    }
    return writeJson(response, draftResponse(record), 202);
  }

  function getDraftRecord(response, clientDraftId) {
    if (!isUuid(clientDraftId)) {
      writeError(response, 422, 'draft_invalid', 'client_draft_id must be a UUID');
      return null;
    }
    const record = drafts.get(logicalKey(currentUser.id, clientDraftId));
    if (!record) {
      writeError(response, 404, 'draft_not_found', 'Generated provider draft not found');
      return null;
    }
    return record;
  }

  function handleDraftGet(request, response, pathname, clientDraftId) {
    if (!requireUser(response)) return;
    counters.draft_get_requests += 1;
    const record = getDraftRecord(response, clientDraftId);
    if (!record) return;
    advanceDiscard(request, pathname, record);
    if (record.state === 'reconciling') {
      // A durable lookup is authoritative after a lost browser response.
      record.state = 'synced';
      record.updated_at = new Date().toISOString();
    }
    counters.attachment_rehydrates += record.payload.attachments.length;
    counters.attachment_bytes_rehydrated += record.attachment_bytes;
    recordEvent('draft_rehydrated', request, pathname, {
      client_draft_id: record.client_draft_id,
      revision: record.revision,
      payload_hash: record.payload_hash,
      attachment_count: record.payload.attachments.length,
      attachment_bytes: record.attachment_bytes,
      state: record.state,
    });
    return writeJson(response, draftResponse(record, { includeContent: true }));
  }

  function handleDraftGetByEmail(request, response, pathname, emailId) {
    if (!requireUser(response)) return;
    counters.draft_get_requests += 1;
    if (!Number.isSafeInteger(emailId) || emailId < 50_000) {
      return writeError(response, 404, 'draft_not_found', 'Generated provider draft not found');
    }
    const record = [...drafts.values()].find(candidate => (
      candidate.owner_user_id === currentUser.id
      && candidate.email_id === emailId
      && candidate.state !== 'discarded'
    )) || null;
    if (!record) {
      return writeError(response, 404, 'draft_not_found', 'Generated provider draft not found');
    }
    advanceDiscard(request, pathname, record);
    if (record.state === 'discarded') {
      return writeError(response, 404, 'draft_not_found', 'Generated provider draft not found');
    }
    counters.attachment_rehydrates += record.payload.attachments.length;
    counters.attachment_bytes_rehydrated += record.attachment_bytes;
    recordEvent('draft_rehydrated_by_email', request, pathname, {
      client_draft_id: record.client_draft_id,
      revision: record.revision,
      payload_hash: record.payload_hash,
      state: record.state,
    });
    return writeJson(response, draftResponse(record, { includeContent: true }));
  }

  function handleDraftGetBySource(request, response, pathname, sourceEmailId, accountId) {
    if (!requireUser(response)) return;
    counters.draft_get_requests += 1;
    const source = sourceForUser(currentUser.id, sourceEmailId);
    if (!source || source.account_id !== accountId || !accountForUser(currentUser.id, accountId)) {
      return writeError(response, 404, 'draft_not_found', 'Generated provider draft not found');
    }
    const matches = [...drafts.values()].filter(candidate => (
      candidate.owner_user_id === currentUser.id
      && candidate.account_id === accountId
      && candidate.payload.source_email_id === sourceEmailId
      && candidate.state !== 'discarded'
    ));
    if (matches.length === 0) {
      return writeError(response, 404, 'draft_not_found', 'Generated provider draft not found');
    }
    if (matches.length > 1) {
      return writeError(response, 409, 'draft_conflict', 'Multiple generated replies require review');
    }
    const record = matches[0];
    advanceDiscard(request, pathname, record);
    if (record.state === 'discarded') {
      return writeError(response, 404, 'draft_not_found', 'Generated provider draft not found');
    }
    counters.attachment_rehydrates += record.payload.attachments.length;
    counters.attachment_bytes_rehydrated += record.attachment_bytes;
    recordEvent('draft_rehydrated_by_source', request, pathname, {
      client_draft_id: record.client_draft_id,
      revision: record.revision,
      source_email_id: sourceEmailId,
      state: record.state,
    });
    return writeJson(response, draftResponse(record, { includeContent: true }));
  }

  async function handleDiscard(request, response, pathname, clientDraftId) {
    if (!requireUser(response)) return;
    markExpectedMutation(request, pathname, 'draft_discard');
    counters.draft_discard_requests += 1;
    let body;
    try {
      body = await readJson(request);
    } catch (error) {
      return writeError(response, 422, 'draft_invalid', error.message);
    }
    if (!isUuid(body.mutation_id)) {
      return writeError(response, 422, 'draft_invalid', 'mutation_id must be a UUID');
    }
    const record = getDraftRecord(response, clientDraftId);
    if (!record) return;
    const payloadHash = sha256({ kind: 'discard', client_draft_id: clientDraftId });
    const expectedMutation = {
      kind: 'discard',
      client_draft_id: clientDraftId,
      revision: record.revision,
      payload_hash: payloadHash,
    };
    let replay;
    try {
      replay = mutationReplay(currentUser.id, body.mutation_id, expectedMutation);
    } catch (error) {
      return writeError(response, 409, error.code, error.message);
    }
    if (replay) {
      counters.discard_replays += 1;
      return writeJson(response, draftResponse(record));
    }
    if (record.state === 'discarded') return writeJson(response, draftResponse(record));
    if (record.state !== 'synced' && record.state !== 'discard_pending') {
      return writeError(response, 409, 'draft_discard_conflict', 'Draft cannot be discarded now');
    }
    if (record.state === 'synced') {
      const deadline = new Date(Date.now() + activeDiscardWindowMs).toISOString();
      record.state = 'discard_pending';
      record.can_undo_discard = true;
      record.can_retry = false;
      record.discard_at = deadline;
      record.discard_undo_until = deadline;
      record.next_attempt_at = deadline;
      record.updated_at = new Date().toISOString();
    }
    rememberMutation(currentUser.id, body.mutation_id, expectedMutation);
    recordEvent('draft_discard_staged', request, pathname, {
      client_draft_id: clientDraftId,
      revision: record.revision,
      discard_window_ms: activeDiscardWindowMs,
    });
    return writeJson(response, draftResponse(record), 202);
  }

  async function handleUndoDiscard(request, response, pathname, clientDraftId) {
    if (!requireUser(response)) return;
    markExpectedMutation(request, pathname, 'draft_undo_discard');
    counters.draft_undo_discard_requests += 1;
    let body;
    try {
      body = await readJson(request);
    } catch (error) {
      return writeError(response, 422, 'draft_invalid', error.message);
    }
    if (!isUuid(body.mutation_id)) {
      return writeError(response, 422, 'draft_invalid', 'mutation_id must be a UUID');
    }
    const record = getDraftRecord(response, clientDraftId);
    if (!record) return;
    const payloadHash = sha256({ kind: 'undo-discard', client_draft_id: clientDraftId });
    const expectedMutation = {
      kind: 'undo-discard',
      client_draft_id: clientDraftId,
      revision: record.revision,
      payload_hash: payloadHash,
    };
    let replay;
    try {
      replay = mutationReplay(currentUser.id, body.mutation_id, expectedMutation);
    } catch (error) {
      return writeError(response, 409, error.code, error.message);
    }
    if (replay) return writeJson(response, draftResponse(record));
    advanceDiscard(request, pathname, record);
    if (record.state !== 'discard_pending' || !record.can_undo_discard) {
      return writeError(response, 409, 'draft_discard_expired', 'Draft discard can no longer be undone');
    }
    record.state = 'synced';
    record.can_undo_discard = false;
    record.can_retry = false;
    record.discard_at = null;
    record.discard_undo_until = null;
    record.next_attempt_at = null;
    record.error_code = null;
    record.error_message = null;
    record.updated_at = new Date().toISOString();
    counters.discard_undos += 1;
    rememberMutation(currentUser.id, body.mutation_id, expectedMutation);
    recordEvent('draft_discard_undone', request, pathname, {
      client_draft_id: clientDraftId,
      revision: record.revision,
      draft_id_hash: sha256(record.draft_id),
    });
    return writeJson(response, draftResponse(record));
  }

  function outboundResponse(record) {
    return {
      send_id: record.send_id,
      idempotency_key: record.idempotency_key,
      account_id: record.account_id,
      source_email_id: record.source_email_id,
      archive_source_after_send: record.archive_source_after_send,
      client_draft_id: record.client_draft_id,
      state: record.state,
      scheduled_for: record.scheduled_for,
      schedule_timezone: record.schedule_timezone,
      execute_after: record.execute_after,
      undo_until: record.undo_until,
      next_attempt_at: record.next_attempt_at,
      attempt_count: record.attempt_count,
      max_attempts: 8,
      can_undo: record.state === 'staged' && clockNowMs <= Date.parse(record.undo_until),
      can_cancel: record.state === 'staged' && Boolean(record.scheduled_for)
        && clockNowMs < Date.parse(record.execute_after),
      can_send_now: record.state === 'staged' && Boolean(record.scheduled_for)
        && clockNowMs < Date.parse(record.execute_after),
      can_retry: false,
      provider_message_id: record.provider_message_id,
      error_code: null,
      error_message: null,
      created_at: record.created_at,
      updated_at: record.updated_at,
      sent_at: record.sent_at,
      failed_at: null,
      cancelled_at: record.cancelled_at,
    };
  }

  function advanceOutbound(request, pathname, record) {
    if (record.state !== 'staged' || clockNowMs < Date.parse(record.execute_after)) return;
    counters.provider_send_lookups += 1;
    record.attempt_count += 1;
    record.state = 'sent';
    record.next_attempt_at = null;
    record.provider_message_id = `generated-sent-${record.send_id}`;
    record.sent_at = clockIso();
    record.updated_at = record.sent_at;
    record.payload = null;
    counters.provider_sends += 1;
    if (record.archive_source_after_send) {
      counters.post_send_archives += 1;
      recordEvent('post_send_archive_committed', request, pathname, {
        send_id: record.send_id,
        source_email_id: record.source_email_id,
      });
    }
    const draft = drafts.get(logicalKey(record.owner_user_id, record.client_draft_id));
    if (draft?.linked_send_id === record.send_id) {
      draft.state = 'discarded';
      draft.linked_send_id = record.send_id;
      draft.discarded_at = clockIso();
      draft.updated_at = draft.discarded_at;
    }
    recordEvent('provider_send_committed', request, pathname, {
      send_id: record.send_id,
      scheduled_for: record.scheduled_for,
    });
  }

  function ownedOutbound(sendId) {
    return outbounds.get(outboundKey(currentUser.id, sendId)) || null;
  }

  async function handleOutboundSend(request, response, pathname) {
    markExpectedMutation(request, pathname, 'outbound_accept');
    let body;
    try {
      body = await readJson(request);
      if (!isUuid(body.idempotency_key)) throw new Error('idempotency_key must be a UUID');
      if (!isUuid(body.client_draft_id) || !Number.isSafeInteger(body.draft_revision)) {
        throw new Error('A durable generated draft is required');
      }
      if (!accountForUser(currentUser.id, body.account_id)) {
        throw new Error('Generated account is not owned by this user');
      }
      if (
        body.archive_source_after_send !== undefined
        && typeof body.archive_source_after_send !== 'boolean'
      ) {
        throw new Error('archive_source_after_send must be a boolean when supplied');
      }
      for (const field of ['to', 'cc', 'bcc']) {
        if (!Array.isArray(body[field] || []) || !(body[field] || []).every(isGeneratedAddress)) {
          counters.non_example_test_rejections += 1;
          throw new Error(`${field} accepts only .example.test addresses`);
        }
      }
    } catch (error) {
      counters.rejected_payloads += 1;
      return writeError(response, 422, 'outbound_invalid', error.message);
    }

    const draft = drafts.get(logicalKey(currentUser.id, body.client_draft_id));
    if (
      !draft
      || draft.account_id !== body.account_id
      || draft.revision !== body.draft_revision
      || draft.state !== 'synced'
    ) {
      return writeError(response, 409, 'outbound_conflict', 'Generated draft is not ready to send');
    }
    const provenance = {
      source_email_id: body.source_email_id ?? null,
      thread_id: body.thread_id ?? null,
      in_reply_to: body.in_reply_to ?? null,
      references: body.references ?? null,
    };
    const provenanceChanged = Object.entries(provenance).some(
      ([field, value]) => value !== (draft.payload[field] ?? null),
    );
    if (provenanceChanged) {
      return writeError(
        response,
        409,
        'outbound_conflict',
        'Generated send must retain the draft exact-source provenance',
      );
    }
    const sourceEmailId = provenance.source_email_id;
    const archiveSourceAfterSend = body.archive_source_after_send === true;
    if (archiveSourceAfterSend && !sourceForUser(currentUser.id, sourceEmailId)) {
      return writeError(
        response,
        422,
        'outbound_invalid',
        'Send & archive requires an owned generated source message',
      );
    }
    const scheduleMs = body.scheduled_for ? Date.parse(body.scheduled_for) : null;
    if (body.scheduled_for && (!Number.isFinite(scheduleMs) || scheduleMs < clockNowMs + 60_000)) {
      return writeError(response, 422, 'outbound_invalid', 'Schedule must be at least one minute ahead');
    }
    const immutable = {
      account_id: body.account_id,
      to: body.to || [],
      cc: body.cc || [],
      bcc: body.bcc || [],
      subject: body.subject || '',
      body_html: body.body_html || '',
      body_text: body.body_text || '',
      source_email_id: sourceEmailId,
      thread_id: provenance.thread_id,
      in_reply_to: provenance.in_reply_to,
      references: provenance.references,
      archive_source_after_send: archiveSourceAfterSend,
      client_draft_id: body.client_draft_id,
      draft_revision: body.draft_revision,
      scheduled_for: body.scheduled_for || null,
      schedule_timezone: body.schedule_timezone || null,
    };
    const payloadHash = sha256(immutable);
    const existingId = outboundIdempotency.get(
      outboundIdempotencyKey(currentUser.id, body.idempotency_key),
    );
    if (existingId) {
      const existing = ownedOutbound(existingId);
      if (existing?.payload_hash !== payloadHash) {
        return writeError(response, 409, 'outbound_conflict', 'Idempotency key changed payload');
      }
      return writeJson(response, outboundResponse(existing), 202);
    }

    const sendId = randomUUID();
    const undoUntil = new Date(clockNowMs + DEFAULT_DISCARD_WINDOW_MS).toISOString();
    const executeAfter = body.scheduled_for
      ? new Date(scheduleMs).toISOString()
      : undoUntil;
    const record = {
      send_id: sendId,
      idempotency_key: body.idempotency_key,
      owner_user_id: currentUser.id,
      account_id: body.account_id,
      source_email_id: sourceEmailId,
      archive_source_after_send: archiveSourceAfterSend,
      client_draft_id: body.client_draft_id,
      payload_hash: payloadHash,
      payload: immutable,
      state: 'staged',
      scheduled_for: body.scheduled_for ? new Date(scheduleMs).toISOString() : null,
      schedule_timezone: body.schedule_timezone || null,
      execute_after: executeAfter,
      undo_until: undoUntil,
      next_attempt_at: executeAfter,
      attempt_count: 0,
      provider_message_id: null,
      created_at: clockIso(),
      updated_at: clockIso(),
      sent_at: null,
      cancelled_at: null,
    };
    outbounds.set(outboundKey(currentUser.id, sendId), record);
    outboundIdempotency.set(
      outboundIdempotencyKey(currentUser.id, body.idempotency_key),
      sendId,
    );
    draft.state = 'sending';
    draft.linked_send_id = sendId;
    draft.updated_at = clockIso();
    counters.outbound_accepts += 1;
    recordEvent('outbound_accepted', request, pathname, {
      send_id: sendId,
      scheduled_for: record.scheduled_for,
      archive_source_after_send: record.archive_source_after_send,
    });
    return writeJson(response, outboundResponse(record), 202);
  }

  function handleOutboundGet(request, response, pathname, record) {
    if (!record) return writeError(response, 404, 'outbound_not_found', 'Generated send not found');
    advanceOutbound(request, pathname, record);
    return writeJson(response, outboundResponse(record));
  }

  function cancelOutbound(request, response, pathname, record) {
    markExpectedMutation(request, pathname, 'outbound_cancel');
    if (!record) return writeError(response, 404, 'outbound_not_found', 'Generated send not found');
    if (record.state === 'cancelled') return writeJson(response, outboundResponse(record));
    const undoRequest = pathname.endsWith('/undo');
    const canUndo = undoRequest && clockNowMs <= Date.parse(record.undo_until);
    const canCancelSchedule = !undoRequest && record.scheduled_for
      && clockNowMs < Date.parse(record.execute_after);
    if (record.state !== 'staged' || (!canUndo && !canCancelSchedule)) {
      return writeError(response, 409, 'outbound_conflict', 'Generated schedule can no longer be cancelled');
    }
    record.state = 'cancelled';
    record.payload = null;
    record.next_attempt_at = null;
    record.cancelled_at = clockIso();
    record.updated_at = record.cancelled_at;
    const draft = drafts.get(logicalKey(currentUser.id, record.client_draft_id));
    if (draft?.linked_send_id === record.send_id) {
      draft.state = 'synced';
      draft.linked_send_id = null;
      draft.updated_at = clockIso();
    }
    counters.outbound_cancels += 1;
    return writeJson(response, outboundResponse(record));
  }

  function sendOutboundNow(request, response, pathname, record) {
    markExpectedMutation(request, pathname, 'outbound_send_now');
    if (!record) return writeError(response, 404, 'outbound_not_found', 'Generated send not found');
    if (record.state !== 'staged' || !record.scheduled_for || clockNowMs >= Date.parse(record.execute_after)) {
      return writeError(response, 409, 'outbound_conflict', 'Generated schedule can no longer send early');
    }
    counters.outbound_send_now += 1;
    record.execute_after = clockIso();
    record.undo_until = record.execute_after;
    record.next_attempt_at = record.execute_after;
    advanceOutbound(request, pathname, record);
    return writeJson(response, outboundResponse(record));
  }

  function mailboxEmails() {
    const sources = Object.values(SOURCE_MESSAGES)
      .filter(source => source.owner_user_id === currentUser.id)
      .map(source => clone(source));
    const providerDrafts = [...drafts.values()]
      .filter(record => record.owner_user_id === currentUser.id && record.state !== 'discarded')
      .map(record => ({
        id: record.email_id,
        account_id: record.account_id,
        account_email: accountForUser(currentUser.id, record.account_id)?.email,
        gmail_message_id: `generated-draft-message-${record.draft_id}`,
        gmail_thread_id: record.payload.thread_id,
        message_id_header: `<${record.draft_id}@example.test>`,
        from_name: 'Generated Draft',
        from_address: accountForUser(currentUser.id, record.account_id)?.email,
        reply_to: null,
        to_addresses: record.payload.to.map(address => ({ name: '', address: mailboxAddress(address) })),
        cc_addresses: record.payload.cc.map(address => ({ name: '', address: mailboxAddress(address) })),
        subject: record.payload.subject,
        snippet: 'Generated provider draft fixture.',
        body_text: record.payload.body_text,
        body_html: record.payload.body_html,
        date: record.updated_at,
        labels: ['DRAFT'],
        is_read: true,
        is_starred: false,
        is_trash: false,
        is_spam: false,
        is_sent: false,
        is_draft: true,
        has_attachments: record.payload.attachments.length > 0,
        attachments: record.payload.attachments.map((attachment, attachmentIndex) => ({
          id: attachmentIndex + 1,
          filename: attachment.filename,
          mime_type: attachment.content_type,
          size: Buffer.from(attachment.data_base64, 'base64').length,
        })),
        ai_action_items: [],
        is_subscription: false,
      }));
    return { sources, providerDrafts };
  }

  function mailboxConversations() {
    return Object.values(SOURCE_MESSAGES)
      .filter(source => source.owner_user_id === currentUser.id)
      .map(source => ({
        conversation_key: `${source.account_id}:thread:${source.gmail_thread_id}`,
        account_id: source.account_id,
        account_email: source.account_email,
        anchor_email_id: source.id,
        gmail_message_id: source.gmail_message_id,
        gmail_thread_id: source.gmail_thread_id,
        subject: source.subject,
        from_address: source.from_address,
        from_name: source.from_name,
        to_addresses: source.to_addresses,
        date: source.date,
        snippet: source.snippet,
        is_draft: false,
        is_sent: false,
        is_trash: false,
        is_spam: false,
        is_read: source.is_read,
        unread_count: source.is_read ? 0 : 1,
        is_starred: source.is_starred,
        star_state: source.is_starred ? 'all' : 'none',
        has_attachments: source.has_attachments,
        labels: source.labels,
        label_coverage: Object.fromEntries((source.labels || []).map(label => [label, 'all'])),
        member_count: 1,
        matched_count: 1,
        is_subscription: false,
        needs_reply: true,
        inbox_placement: 'focused',
        inbox_placement_reason: 'needs_reply',
      }));
  }

  function auditPayload() {
    const logicalDrafts = [...drafts.values()].map(draftSummary);
    const logicalOutbounds = [...outbounds.values()].map(record => ({
      send_id: record.send_id,
      owner_user_id: record.owner_user_id,
      account_id: record.account_id,
      state: record.state,
      scheduled_for: record.scheduled_for,
      source_email_id: record.source_email_id,
      archive_source_after_send: record.archive_source_after_send,
      execute_after: record.execute_after,
      attempt_count: record.attempt_count,
      payload_retained: Boolean(record.payload),
    }));
    const logicalSnippets = [...snippets.values()].map(record => ({
      snippet_id: record.snippet_id,
      owner_user_id: record.owner_user_id,
      revision: record.revision,
      seeded: record.seeded,
    }));
    return {
      fixture: 'generated-provider-draft-sessions',
      fixture_domains: ['example.test'],
      localhost_only: true,
      scenario,
      connectivity,
      current_user_id: currentUser?.id || null,
      discard_window_ms: activeDiscardWindowMs,
      clock_now: clockIso(),
      counters: {
        ...counters,
        logical_drafts: logicalDrafts.length,
        live_provider_drafts: logicalDrafts.filter(item => item.state !== 'discarded').length,
        logical_snippets: logicalSnippets.length,
      },
      logical_drafts: logicalDrafts,
      logical_outbounds: logicalOutbounds,
      logical_snippets: logicalSnippets,
      events: clone(events),
    };
  }

  function releaseHeldResponses(request, response) {
    counters.qa_control_mutations += 1;
    const pending = heldResponses.splice(0);
    for (const held of pending) {
      if (held.kind === 'snippet') {
        if (currentUser?.id !== held.request_user_id) {
          counters.stale_session_responses_released += 1;
          counters.snippet_list_stale_session_responses += 1;
        }
        counters.snippet_list_releases += 1;
        recordEvent(
          'snippet_list_released',
          request,
          '/api/compose/snippets',
          held.event_metadata,
        );
        writeJson(held.response, held.payload);
        continue;
      }
      if (held.kind === 'recipient') {
        if (currentUser?.id !== held.request_user_id) {
          counters.stale_session_responses_released += 1;
          counters.recipient_lookup_stale_session_responses += 1;
        }
        counters.recipient_lookup_successes += 1;
        recordEvent(
          'recipient_lookup_released',
          request,
          '/api/compose/recipients',
          held.event_metadata,
        );
        writeJson(held.response, held.payload);
        continue;
      }
      const record = drafts.get(logicalKey(held.request_user_id, held.client_draft_id));
      if (record) {
        record.state = 'synced';
        record.updated_at = new Date().toISOString();
      }
      if (currentUser?.id !== held.request_user_id) {
        counters.stale_session_responses_released += 1;
      }
      writeJson(held.response, record ? draftResponse(record) : {
        detail: { code: 'draft_not_found', message: 'Generated held draft disappeared' },
      }, record ? 202 : 404);
    }
    recordEvent('qa_release_held', request, '/api/qa/release-held', {
      released: pending.length,
    });
    return writeJson(response, { released: pending.length });
  }

  function resetFixture(request, response, body) {
    while (heldResponses.length > 0) {
      writeError(
        heldResponses.shift().response,
        409,
        'qa_reset',
        'Generated fixture was reset',
      );
    }
    const requestedScenario = GENERATED_PROVIDER_DRAFT_SCENARIOS.includes(body.scenario)
      ? body.scenario
      : 'clean';
    const requestedUser = USERS[body.current_user] || USERS['generated-a'];
    scenario = requestedScenario;
    connectivity = scenario === 'offline' ? 'offline' : 'online';
    currentUser = requestedUser;
    activeDiscardWindowMs = integerInRange(
      body.discard_window_ms,
      DEFAULT_DISCARD_WINDOW_MS,
      1,
      60_000,
    );
    counters = newCounters();
    counters.qa_control_mutations = 1;
    auditSequence = 0;
    providerSequence = 0;
    firstLostResponseUsed = false;
    firstHeldResponseUsed = false;
    firstRecipientHeldResponseUsed = false;
    firstSnippetHeldResponseUsed = false;
    drafts.clear();
    outbounds.clear();
    outboundIdempotency.clear();
    mutations.clear();
    offlineMutationIds.clear();
    events.length = 0;
    clockNowMs = Number.isFinite(Date.parse(body.clock_now))
      ? Date.parse(body.clock_now)
      : Date.parse('2026-08-30T16:00:00.000Z');
    seedSnippets();
    recordEvent('qa_reset', request, '/api/qa/reset', {
      scenario,
      discard_window_ms: activeDiscardWindowMs,
      clock_now: clockIso(),
    });
    return writeJson(response, {
      reset: true,
      scenario,
      connectivity,
      current_user_id: currentUser.id,
      discard_window_ms: activeDiscardWindowMs,
    });
  }

  async function handleRequest(request, response) {
    const url = new URL(request.url, `http://${GENERATED_PROVIDER_DRAFT_HOST}`);
    const { pathname } = url;

    if (request.method === 'GET' && pathname === '/api/qa/fixture') {
      return writeJson(response, {
        users: Object.values(USERS).map(publicUser),
        accounts_by_user: clone(ACCOUNTS_BY_USER),
        source_messages: Object.values(SOURCE_MESSAGES).map(source => ({
          id: source.id,
          owner_user_id: source.owner_user_id,
          account_id: source.account_id,
          gmail_thread_id: source.gmail_thread_id,
          message_id_header: source.message_id_header,
          references_header: source.references_header,
        })),
        snippet_ids_by_user: Object.fromEntries(
          Object.entries(SEEDED_SNIPPETS_BY_USER).map(([userId, records]) => [
            userId,
            records.map(record => record.snippet_id),
          ]),
        ),
        recipient_history_counts_by_user: Object.fromEntries(
          Object.entries(RECIPIENT_HISTORY_BY_USER).map(([userId, records]) => [
            userId,
            records.length,
          ]),
        ),
        scenarios: GENERATED_PROVIDER_DRAFT_SCENARIOS,
      });
    }
    if (request.method === 'GET' && pathname === '/api/qa/audit') {
      return writeJson(response, auditPayload());
    }
    if (request.method === 'POST' && pathname === '/api/qa/reset') {
      let body = {};
      try { body = await readJson(request); } catch { body = {}; }
      return resetFixture(request, response, body);
    }
    if (request.method === 'POST' && pathname === '/api/qa/clock') {
      const body = await readJson(request);
      const explicit = Date.parse(body.now);
      if (Number.isFinite(explicit)) clockNowMs = explicit;
      else if (Number.isFinite(Number(body.advance_ms))) clockNowMs += Number(body.advance_ms);
      else return writeError(response, 422, 'qa_invalid', 'Provide now or advance_ms');
      counters.qa_control_mutations += 1;
      recordEvent('qa_clock', request, pathname, { clock_now: clockIso() });
      return writeJson(response, { clock_now: clockIso() });
    }
    if (request.method === 'POST' && pathname === '/api/qa/connectivity') {
      const body = await readJson(request);
      if (!['online', 'offline'].includes(body.draft_api)) {
        return writeError(response, 422, 'qa_invalid', 'draft_api must be online or offline');
      }
      counters.qa_control_mutations += 1;
      connectivity = body.draft_api;
      recordEvent('qa_connectivity', request, pathname, { connectivity });
      return writeJson(response, { connectivity });
    }
    if (request.method === 'POST' && pathname === '/api/qa/release-held') {
      return releaseHeldResponses(request, response);
    }

    if (request.method === 'GET' && pathname === '/api/auth/me') {
      return currentUser
        ? writeJson(response, publicUser(currentUser))
        : writeError(response, 401, 'unauthorized', 'Generated authentication is required');
    }
    if (request.method === 'POST' && pathname === '/api/auth/login') {
      const body = await readJson(request);
      const user = USERS[body.username];
      if (!user || body.password !== 'generated-only') {
        return writeError(response, 401, 'invalid_credentials', 'Invalid generated credentials');
      }
      currentUser = user;
      counters.auth_transitions += 1;
      counters.expected_mutations += 1;
      recordEvent('auth_login', request, pathname, { expected: true, user_id: user.id });
      return writeJson(response, {
        access_token: 'generated-access-only',
        refresh_token: 'generated-refresh-only',
        token_type: 'bearer',
        user: publicUser(user),
      });
    }
    if (request.method === 'POST' && pathname === '/api/auth/logout') {
      const priorUserId = currentUser?.id || null;
      currentUser = null;
      counters.auth_transitions += 1;
      counters.expected_mutations += 1;
      recordEvent('auth_logout', request, pathname, { expected: true, prior_user_id: priorUserId });
      return writeJson(response, { message: 'Logged out' });
    }
    if (request.method === 'POST' && pathname === '/api/auth/refresh') {
      return currentUser
        ? writeJson(response, { access_token: 'generated-access-only', token_type: 'bearer' })
        : writeError(response, 401, 'unauthorized', 'Generated authentication is required');
    }

    if (!pathname.startsWith('/api/') || !requireUser(response)) return;

    if (request.method === 'GET' && pathname === '/api/auth/ui-preferences') {
      return writeJson(response, { thread_order: 'asc', theme: 'default', color_scheme: 'light' });
    }
    if (request.method === 'GET' && pathname === '/api/auth/about-me') {
      return writeJson(response, { about_me: '' });
    }
    if (request.method === 'GET' && pathname === '/api/auth/ai-preferences') {
      return writeJson(response, {
        allowed_models: [],
        labels: {},
        effort_levels: {},
        models_by_preference: {},
      });
    }
    if (request.method === 'GET' && pathname === '/api/auth/api-tokens') {
      return writeJson(response, []);
    }
    if (request.method === 'GET' && pathname === '/api/auth/keyboard-shortcuts') {
      return writeJson(response, { shortcuts: {} });
    }
    if (request.method === 'GET' && pathname === '/api/admin/dashboard') {
      return writeJson(response, {});
    }
    if (request.method === 'GET' && pathname === '/api/admin/settings') {
      return writeJson(response, []);
    }
    if (request.method === 'GET' && pathname === '/api/admin/feature-flags') {
      return writeJson(response, { desktop_app_enabled: false });
    }
    if (request.method === 'GET' && pathname === '/api/accounts/allowed') {
      return writeJson(response, { allowed_accounts: '@example.test' });
    }
    if (request.method === 'GET' && pathname === '/api/accounts/') {
      return writeJson(response, clone(ACCOUNTS_BY_USER[currentUser.id] || []));
    }
    if (request.method === 'GET' && pathname === '/api/terminal/settings') {
      return writeJson(response, {
        code: 'generated-only',
        home_assistant_url: null,
        timezone: 'America/New_York',
        displays: [],
      });
    }
    if (request.method === 'GET' && pathname === '/api/terminal/devices') {
      return writeJson(response, []);
    }
    if (request.method === 'GET' && pathname === '/api/build-version') {
      return writeJson(response, { version: 'generated-provider-draft-qa' });
    }
    if (request.method === 'GET' && pathname === '/api/events/stream') {
      response.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
      });
      response.write(': generated provider-draft QA stream\n\n');
      request.on('close', () => response.end());
      return;
    }
    if (request.method === 'GET' && pathname === '/api/emails/labels/all') {
      return writeJson(response, []);
    }
    if (request.method === 'GET' && pathname === '/api/emails/actions/recent') {
      return writeJson(response, []);
    }
    if (request.method === 'GET' && pathname === '/api/snoozes') {
      return writeJson(response, {
        items: [],
        total: 0,
        limit: Number(url.searchParams.get('limit')) || 200,
        offset: Number(url.searchParams.get('offset')) || 0,
      });
    }
    if (request.method === 'GET' && pathname === '/api/calendar/upcoming') {
      return writeJson(response, []);
    }
    if (request.method === 'GET' && pathname === '/api/todos/') {
      return writeJson(response, []);
    }
    if (request.method === 'GET' && pathname === '/api/ai/trends') {
      return writeJson(response, { summary: '', urgent_count: 0 });
    }
    if (request.method === 'GET' && pathname === '/api/ai/stats') {
      return writeJson(response, {});
    }
    if (request.method === 'GET' && pathname === '/api/ai/processing/status') {
      return writeJson(response, { active: false, just_finished: false });
    }
    if (
      request.method === 'GET'
      && ['/api/ai/needs-reply', '/api/ai/awaiting-response', '/api/ai/digests'].includes(pathname)
    ) {
      return writeJson(response, { emails: [], digests: [], total: 0 });
    }
    if (request.method === 'GET' && pathname === '/api/chat/conversations') {
      return writeJson(response, []);
    }
    if (request.method === 'GET' && pathname === '/api/compose/sends/recent') {
      const records = [...outbounds.values()]
        .filter(record => record.owner_user_id === currentUser.id)
        .sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at));
      records.forEach(record => advanceOutbound(request, pathname, record));
      return writeJson(response, records.map(outboundResponse));
    }
    if (request.method === 'GET' && pathname === '/api/compose/sends/scheduled') {
      const records = [...outbounds.values()]
        .filter(record => record.owner_user_id === currentUser.id && record.state === 'staged' && record.scheduled_for)
        .sort((left, right) => Date.parse(left.execute_after) - Date.parse(right.execute_after));
      records.forEach(record => advanceOutbound(request, pathname, record));
      return writeJson(response, records.filter(record => record.state === 'staged').map(outboundResponse));
    }
    if (request.method === 'GET' && pathname === '/api/compose/drafts/recent') {
      const records = [...drafts.values()]
        .filter(record => record.owner_user_id === currentUser.id)
        .sort((left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at));
      records.forEach(record => advanceDiscard(request, pathname, record));
      return writeJson(response, records.map(record => draftResponse(record)));
    }
    if (request.method === 'GET' && pathname === '/api/emails/') {
      const mailbox = (url.searchParams.get('mailbox') || 'INBOX').toUpperCase();
      const { sources, providerDrafts } = mailboxEmails();
      const visible = mailbox === 'DRAFTS' ? providerDrafts : sources;
      return writeJson(response, {
        emails: visible,
        total: visible.length,
        page: 1,
        page_size: 50,
      });
    }
    if (request.method === 'GET' && pathname === '/api/emails/conversations') {
      const conversations = mailboxConversations();
      return writeJson(response, {
        conversations,
        total: conversations.length,
        page: Number(url.searchParams.get('page')) || 1,
        page_size: Number(url.searchParams.get('page_size')) || 50,
        total_pages: conversations.length ? 1 : 0,
      });
    }
    const threadMatch = pathname.match(/^\/api\/emails\/thread\/([^/]+)$/);
    if (request.method === 'GET' && threadMatch) {
      const threadId = decodeURIComponent(threadMatch[1]);
      const accountId = Number(url.searchParams.get('account_id')) || null;
      const emails = Object.values(SOURCE_MESSAGES)
        .filter(source => (
          source.owner_user_id === currentUser.id
          && source.gmail_thread_id === threadId
          && (!accountId || source.account_id === accountId)
        ))
        .map(source => clone(source));
      if (!emails.length) return writeError(response, 404, 'thread_not_found', 'Generated thread not found');
      return writeJson(response, {
        thread_id: threadId,
        subject: emails[0].subject,
        emails,
        participants: [{ name: emails[0].from_name, address: emails[0].from_address }],
      });
    }
    const emailMatch = pathname.match(/^\/api\/emails\/(\d+)$/);
    if (request.method === 'GET' && emailMatch) {
      const source = sourceForUser(currentUser.id, Number(emailMatch[1]));
      return source
        ? writeJson(response, clone(source))
        : writeError(response, 404, 'email_not_found', 'Generated email not found');
    }

    if (request.method === 'POST' && pathname === '/api/compose/draft') {
      return handleDraftUpsert(request, response, pathname);
    }
    if (request.method === 'GET' && pathname === '/api/compose/recipients') {
      return handleRecipientSuggestions(request, response, pathname, url);
    }
    if (request.method === 'GET' && pathname === '/api/compose/snippets') {
      return handleSnippetList(request, response, pathname);
    }
    if (request.method === 'POST' && pathname === '/api/compose/snippets') {
      return handleSnippetCreate(request, response, pathname);
    }
    const snippetMatch = pathname.match(/^\/api\/compose\/snippets\/([^/]+)$/);
    if (request.method === 'PUT' && snippetMatch) {
      return handleSnippetReplace(
        request,
        response,
        pathname,
        decodeURIComponent(snippetMatch[1]),
      );
    }
    if (request.method === 'DELETE' && snippetMatch) {
      return handleSnippetDelete(
        request,
        response,
        pathname,
        decodeURIComponent(snippetMatch[1]),
        url.searchParams.get('expected_revision'),
      );
    }
    if (request.method === 'POST' && pathname === '/api/compose/send') {
      return handleOutboundSend(request, response, pathname);
    }
    const outboundByKeyMatch = pathname.match(
      /^\/api\/compose\/sends\/by-idempotency\/([^/]+)$/,
    );
    if (request.method === 'GET' && outboundByKeyMatch) {
      const sendId = outboundIdempotency.get(outboundIdempotencyKey(
        currentUser.id,
        decodeURIComponent(outboundByKeyMatch[1]),
      ));
      return handleOutboundGet(request, response, pathname, sendId ? ownedOutbound(sendId) : null);
    }
    const outboundCancelMatch = pathname.match(/^\/api\/compose\/sends\/([^/]+)\/cancel$/);
    if (request.method === 'POST' && outboundCancelMatch) {
      return cancelOutbound(
        request,
        response,
        pathname,
        ownedOutbound(decodeURIComponent(outboundCancelMatch[1])),
      );
    }
    const outboundSendNowMatch = pathname.match(/^\/api\/compose\/sends\/([^/]+)\/send-now$/);
    if (request.method === 'POST' && outboundSendNowMatch) {
      return sendOutboundNow(
        request,
        response,
        pathname,
        ownedOutbound(decodeURIComponent(outboundSendNowMatch[1])),
      );
    }
    const outboundUndoMatch = pathname.match(/^\/api\/compose\/sends\/([^/]+)\/undo$/);
    if (request.method === 'POST' && outboundUndoMatch) {
      const record = ownedOutbound(decodeURIComponent(outboundUndoMatch[1]));
      return cancelOutbound(request, response, pathname, record);
    }
    const outboundGetMatch = pathname.match(/^\/api\/compose\/sends\/([^/]+)$/);
    if (request.method === 'GET' && outboundGetMatch) {
      return handleOutboundGet(
        request,
        response,
        pathname,
        ownedOutbound(decodeURIComponent(outboundGetMatch[1])),
      );
    }
    const detailMatch = pathname.match(
      /^\/api\/compose\/drafts\/by-client-id\/([^/]+)$/,
    );
    if (request.method === 'GET' && detailMatch) {
      return handleDraftGet(
        request,
        response,
        pathname,
        decodeURIComponent(detailMatch[1]),
      );
    }
    const sourceDraftMatch = pathname.match(
      /^\/api\/compose\/drafts\/by-source-email\/(\d+)$/,
    );
    if (request.method === 'GET' && sourceDraftMatch) {
      return handleDraftGetBySource(
        request,
        response,
        pathname,
        Number(sourceDraftMatch[1]),
        Number(url.searchParams.get('account_id')),
      );
    }
    const emailDraftMatch = pathname.match(
      /^\/api\/compose\/drafts\/by-email\/(\d+)$/,
    );
    if (request.method === 'GET' && emailDraftMatch) {
      return handleDraftGetByEmail(
        request,
        response,
        pathname,
        Number(emailDraftMatch[1]),
      );
    }
    const discardMatch = pathname.match(/^\/api\/compose\/drafts\/([^/]+)\/discard$/);
    if (request.method === 'POST' && discardMatch) {
      return handleDiscard(
        request,
        response,
        pathname,
        decodeURIComponent(discardMatch[1]),
      );
    }
    const undoMatch = pathname.match(/^\/api\/compose\/drafts\/([^/]+)\/undo-discard$/);
    if (request.method === 'POST' && undoMatch) {
      return handleUndoDiscard(
        request,
        response,
        pathname,
        decodeURIComponent(undoMatch[1]),
      );
    }

    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method)) {
      counters.unexpected_mutations += 1;
      recordEvent('unexpected_mutation', request, pathname, { expected: false });
      return writeError(
        response,
        405,
        'qa_mutation_rejected',
        'Generated provider-draft QA rejects this mutation',
      );
    }
    counters.unknown_routes += 1;
    recordEvent('unknown_route', request, pathname);
    return writeError(response, 404, 'qa_route_not_found', 'Unknown generated QA route');
  }

  const server = createServer((request, response) => {
    handleRequest(request, response).catch(error => {
      if (!response.destroyed && !response.writableEnded) {
        writeError(response, 500, 'qa_server_failure', error.message);
      }
    });
  });

  async function listen(port = 0) {
    await new Promise((resolve, reject) => {
      server.once('error', reject);
      server.listen(port, GENERATED_PROVIDER_DRAFT_HOST, () => {
        server.off('error', reject);
        resolve();
      });
    });
    return server.address();
  }

  async function close() {
    while (heldResponses.length > 0) {
      writeError(
        heldResponses.shift().response,
        503,
        'qa_server_stopped',
        'Generated provider-draft QA stopped',
      );
    }
    if (!server.listening) return;
    await new Promise((resolve, reject) => {
      server.close(error => (error ? reject(error) : resolve()));
    });
  }

  return {
    server,
    listen,
    close,
    audit: auditPayload,
  };
}

async function runMain() {
  const port = integerInRange(process.env.QA_API_PORT, 8000, 1, 65_535);
  const fixture = createGeneratedProviderDraftFixture({
    discardWindowMs: integerInRange(
      process.env.QA_DRAFT_DISCARD_MS,
      DEFAULT_DISCARD_WINDOW_MS,
      1,
      60_000,
    ),
  });
  await fixture.listen(port);
  process.stdout.write(
    `Generated provider-draft QA API listening on http://${GENERATED_PROVIDER_DRAFT_HOST}:${port}\n`,
  );
  const shutdown = () => {
    void fixture.close().then(() => process.exit(0));
  };
  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await runMain();
}
