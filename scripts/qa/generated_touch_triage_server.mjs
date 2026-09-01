#!/usr/bin/env node

// Deterministic generated-only API and SPA host for touch-first Inbox triage.
// It binds only to loopback, accepts only reserved .example.test identities,
// and keeps preferences, staged mail actions, snoozes, and QA controls in
// memory. It has no provider, Gmail, calendar, AI, worker, terminal, secret,
// production, or outbound-network capability.

import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import { createServer } from 'node:http';
import { dirname, extname, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const GENERATED_TOUCH_TRIAGE_HOST = '127.0.0.1';

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const frontendDist = resolve(scriptDirectory, '../../frontend/dist');
const FIXTURE_NOW = '2026-08-31T20:00:00.000Z';
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const EMAIL_RE = /[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+/giu;
const SWIPE_ACTIONS = new Set(['archive', 'snooze', 'toggle_read', 'toggle_star', 'none']);
const SCENARIOS = new Set([
  'ready',
  'lost-action-once',
  'lost-snooze-once',
  'slow-dataset',
  'dataset-error',
]);
const STATIC_MIME_TYPES = Object.freeze({
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.ico': 'image/x-icon',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml; charset=utf-8',
  '.webp': 'image/webp',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
});

const GENERATED_USER = Object.freeze({
  id: 8801,
  username: 'touch-owner@example.test',
  is_admin: false,
  account_ids: Object.freeze([9101, 9102]),
});

const GENERATED_ACCOUNTS = Object.freeze({
  9101: Object.freeze({
    id: 9101,
    email: 'touch-primary@example.test',
    display_name: 'Generated Touch Primary',
    description: 'Generated Touch Primary',
    short_label: 'Primary',
    is_active: true,
    has_calendar_scope: false,
    created_at: '2026-08-01T12:00:00.000Z',
    sync_status: Object.freeze({
      status: 'idle',
      messages_synced: 6,
      total_messages: 6,
      last_full_sync: '2026-08-31T19:30:00.000Z',
      last_incremental_sync: '2026-08-31T19:55:00.000Z',
    }),
    calendar_sync_status: null,
  }),
  9102: Object.freeze({
    id: 9102,
    email: 'touch-secondary@example.test',
    display_name: 'Generated Touch Secondary',
    description: 'Generated Touch Secondary',
    short_label: 'Secondary',
    is_active: true,
    has_calendar_scope: false,
    created_at: '2026-08-01T12:00:00.000Z',
    sync_status: Object.freeze({
      status: 'idle',
      messages_synced: 2,
      total_messages: 2,
      last_full_sync: '2026-08-31T19:30:00.000Z',
      last_incremental_sync: '2026-08-31T19:55:00.000Z',
    }),
    calendar_sync_status: null,
  }),
});

function generatedEmail({
  id,
  accountId,
  subject,
  sender,
  date,
  labels = ['INBOX'],
  isRead = false,
  isStarred = false,
}) {
  const account = GENERATED_ACCOUNTS[accountId];
  const address = `${sender.toLowerCase().replaceAll(' ', '.')}@example.test`;
  return Object.freeze({
    id,
    account_id: accountId,
    account_email: account.email,
    gmail_message_id: `generated-touch-message-${id}`,
    gmail_thread_id: `generated-touch-thread-${id}`,
    message_id_header: `<generated-touch-${id}@example.test>`,
    from_name: sender,
    from_address: address,
    reply_to: address,
    to_addresses: Object.freeze([{ name: account.display_name, address: account.email }]),
    cc_addresses: Object.freeze([]),
    bcc_addresses: Object.freeze([]),
    subject,
    snippet: `Generated touch triage fixture for ${subject}.`,
    body_text: 'Generated locally for touch triage QA. No real mailbox data is used.',
    body_html: '<p>Generated locally for touch triage QA.</p><p>No real mailbox data is used.</p>',
    date,
    labels: Object.freeze([
      ...labels,
      ...(isRead ? [] : ['UNREAD']),
      ...(isStarred ? ['STARRED'] : []),
    ]),
    is_read: isRead,
    is_starred: isStarred,
    is_trash: labels.includes('TRASH'),
    is_spam: labels.includes('SPAM'),
    is_sent: false,
    is_draft: false,
    has_attachments: false,
    attachments: Object.freeze([]),
    needs_reply: false,
    ai_summary: null,
    ai_action_items: Object.freeze([]),
    ai_category: null,
    ai_priority: null,
    ai_email_type: null,
    is_subscription: false,
    suggested_reply: null,
    reply_options: null,
  });
}

const GENERATED_EMAILS = Object.freeze([
  generatedEmail({
    id: 101,
    accountId: 9101,
    sender: 'Ada Touch',
    subject: 'Generated swipe archive target',
    date: '2026-08-31T19:58:00.000Z',
  }),
  generatedEmail({
    id: 102,
    accountId: 9101,
    sender: 'Grace Touch',
    subject: 'Generated swipe snooze target',
    date: '2026-08-31T19:57:00.000Z',
    isRead: true,
  }),
  generatedEmail({
    id: 103,
    accountId: 9101,
    sender: 'Linus Touch',
    subject: 'Generated toggle read target',
    date: '2026-08-31T19:56:00.000Z',
  }),
  generatedEmail({
    id: 104,
    accountId: 9101,
    sender: 'Margaret Touch',
    subject: 'Generated toggle star target',
    date: '2026-08-31T19:55:00.000Z',
    isRead: true,
  }),
  generatedEmail({
    id: 201,
    accountId: 9102,
    sender: 'Katherine Touch',
    subject: 'Generated secondary account one',
    date: '2026-08-31T19:54:00.000Z',
  }),
  generatedEmail({
    id: 202,
    accountId: 9102,
    sender: 'Radia Touch',
    subject: 'Generated secondary account two',
    date: '2026-08-31T19:53:00.000Z',
    isRead: true,
    isStarred: true,
  }),
  generatedEmail({
    id: 301,
    accountId: 9101,
    sender: 'Protected Trash',
    subject: 'Generated protected trash target',
    date: '2026-08-31T19:52:00.000Z',
    labels: ['TRASH'],
    isRead: true,
  }),
  generatedEmail({
    id: 302,
    accountId: 9101,
    sender: 'Protected Spam',
    subject: 'Generated protected spam target',
    date: '2026-08-31T19:51:00.000Z',
    labels: ['SPAM'],
    isRead: true,
  }),
]);

function clone(value) {
  return structuredClone(value);
}

function freshCounters() {
  return {
    account_reads: 0,
    preference_reads: 0,
    preference_updates: 0,
    expected_preference_writes: 0,
    conversation_reads: 0,
    split_reads: 0,
    detail_reads: 0,
    thread_reads: 0,
    dataset_delays: 0,
    dataset_failures: 0,
    stale_dataset_responses: 0,
    mail_action_requests: 0,
    mail_action_creates: 0,
    mail_action_replays: 0,
    mail_action_conflicts: 0,
    mail_action_lookups: 0,
    mail_action_undos: 0,
    mail_action_retries: 0,
    lost_action_responses: 0,
    expected_mail_action_writes: 0,
    snooze_requests: 0,
    snooze_creates: 0,
    snooze_replays: 0,
    snooze_lookups: 0,
    snooze_cancels: 0,
    lost_snooze_responses: 0,
    expected_snooze_writes: 0,
    snooze_archive_action_writes: 0,
    session_changes: 0,
    auth_rejections: 0,
    ownership_rejections: 0,
    validation_errors: 0,
    protected_mailbox_rejections: 0,
    non_generated_rejections: 0,
    rejected_provider_attempts: 0,
    rejected_gmail_attempts: 0,
    rejected_mail_attempts: 0,
    rejected_calendar_attempts: 0,
    rejected_ai_attempts: 0,
    rejected_worker_attempts: 0,
    rejected_terminal_attempts: 0,
    unexpected_writes: 0,
    unknown_routes: 0,
    provider_reads: 0,
    provider_calls: 0,
    provider_writes: 0,
    gmail_reads: 0,
    gmail_writes: 0,
    email_sends: 0,
    mail_mutations: 0,
    calendar_reads: 0,
    calendar_writes: 0,
    ai_calls: 0,
    worker_jobs: 0,
    terminal_reads: 0,
    terminal_operations: 0,
    external_network_calls: 0,
  };
}

function assertGeneratedAddresses(value, label) {
  const serialized = JSON.stringify(value);
  const matches = serialized.match(EMAIL_RE) || [];
  for (const address of matches) {
    if (!address.toLowerCase().endsWith('.example.test') && !address.toLowerCase().endsWith('@example.test')) {
      throw new Error(`${label} contains a non-generated email address`);
    }
  }
}

function writeJson(response, payload, status = 200) {
  assertGeneratedAddresses(payload, 'response');
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
    'Cache-Control': 'private, no-store',
    'X-Content-Type-Options': 'nosniff',
  });
  response.end(body);
}

function writeError(response, status, code, message) {
  return writeJson(response, { detail: { code, message } }, status);
}

async function readJson(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > 65_536) throw Object.assign(new Error('Request body is too large'), { status: 422 });
    chunks.push(chunk);
  }
  if (!chunks.length) return {};
  let payload;
  try {
    payload = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    throw Object.assign(new Error('Request body must be valid JSON'), { status: 422 });
  }
  try {
    assertGeneratedAddresses(payload, 'request');
  } catch (error) {
    throw Object.assign(error, { status: 422, nonGenerated: true });
  }
  return payload;
}

function exactKeys(value, allowed, required = allowed) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw Object.assign(new Error('Request body must be an object'), { status: 422 });
  }
  const keys = Object.keys(value);
  if (keys.some(key => !allowed.includes(key)) || required.some(key => !keys.includes(key))) {
    throw Object.assign(new Error('Request body fields are invalid'), { status: 422 });
  }
}

function generatedUuid(sequence) {
  return `70000000-0000-4000-8000-${String(sequence).padStart(12, '0')}`;
}

function emailInMailbox(email, mailbox) {
  if (mailbox === 'TRASH') return email.is_trash;
  if (mailbox === 'SPAM') return email.is_spam;
  if (mailbox === 'STARRED') return email.is_starred && !email.is_trash && !email.is_spam;
  if (mailbox === 'ALL') return !email.is_trash && !email.is_spam;
  return email.labels.includes('INBOX') && !email.is_trash && !email.is_spam;
}

function applyAction(email, action) {
  const labels = new Set(email.labels || []);
  if (action === 'archive') labels.delete('INBOX');
  if (action === 'unarchive') labels.add('INBOX');
  if (action === 'mark_read') labels.delete('UNREAD');
  if (action === 'mark_unread') labels.add('UNREAD');
  if (action === 'star') labels.add('STARRED');
  if (action === 'unstar') labels.delete('STARRED');
  email.labels = [...labels];
  email.is_read = !labels.has('UNREAD');
  email.is_starred = labels.has('STARRED');
}

function conversationSummary(email) {
  return {
    ...clone(email),
    anchor_email_id: email.id,
    conversation_key: `${email.account_id}:thread:${email.gmail_thread_id}`,
    member_count: 1,
    matched_count: 1,
    unread_count: email.is_read ? 0 : 1,
    starred_count: email.is_starred ? 1 : 0,
    star_state: email.is_starred ? 'all' : 'none',
    label_coverage: Object.fromEntries((email.labels || []).map(label => [label, 'all'])),
    conversation_scope: true,
    inbox_placement: email.id % 2 === 0 ? 'other' : 'focused',
    inbox_placement_reason: email.id % 2 === 0 ? 'subscription' : 'direct_or_fyi',
    inbox_placement_source: 'system',
    inbox_placement_rule_id: null,
    inbox_placement_rule_scope: null,
    inbox_placement_rule_revision: null,
  };
}

function operationResponse(operation) {
  return clone(operation);
}

export function createGeneratedTouchTriageFixture() {
  let currentUser = 'generated-a';
  let sessionGeneration = 1;
  let scenario = 'ready';
  let emails = new Map();
  let preferences = null;
  let operations = new Map();
  let operationByKey = new Map();
  let actionSnapshots = new Map();
  let snoozes = new Map();
  let snoozeByKey = new Map();
  let counters = freshCounters();
  let requests = [];
  let recordSequence = 0;
  let lostActionRemaining = 0;
  let lostSnoozeRemaining = 0;
  let delayedDatasetRemaining = 0;
  const eventStreams = new Set();

  function reset(nextScenario = 'ready', nextUser = 'generated-a') {
    if (!SCENARIOS.has(nextScenario)) throw new Error('scenario is invalid');
    if (!['generated-a', 'anonymous'].includes(nextUser)) throw new Error('current_user is invalid');
    currentUser = nextUser;
    sessionGeneration += 1;
    scenario = nextScenario;
    emails = new Map(GENERATED_EMAILS.map(email => [email.id, clone(email)]));
    preferences = {
      thread_order: 'newest_first',
      theme: 'amber',
      color_scheme: 'light',
      swipe_left_action: 'archive',
      swipe_right_action: 'snooze',
    };
    operations = new Map();
    operationByKey = new Map();
    actionSnapshots = new Map();
    snoozes = new Map();
    snoozeByKey = new Map();
    counters = freshCounters();
    requests = [];
    recordSequence = 0;
    lostActionRemaining = nextScenario === 'lost-action-once' ? 1 : 0;
    lostSnoozeRemaining = nextScenario === 'lost-snooze-once' ? 1 : 0;
    delayedDatasetRemaining = nextScenario === 'slow-dataset' ? 1 : 0;
  }

  reset();

  function record(action, status, extra = {}) {
    requests.push({
      sequence: requests.length + 1,
      action,
      status,
      current_user: currentUser,
      session_generation: sessionGeneration,
      ...extra,
    });
  }

  function requireAuth(response, action) {
    if (currentUser === 'generated-a') return true;
    counters.auth_rejections += 1;
    record(action, 401);
    writeError(response, 401, 'not_authenticated', 'Not authenticated');
    return false;
  }

  function ownsAccount(accountId) {
    return GENERATED_USER.account_ids.includes(Number(accountId));
  }

  function ownedEmail(emailId) {
    const email = emails.get(Number(emailId));
    return email && ownsAccount(email.account_id) ? email : null;
  }

  function auditPayload() {
    return {
      fixture: 'generated-touch-first-triage:v1',
      generated_only: true,
      localhost_only: true,
      fixture_domains: ['example.test'],
      current_user: currentUser,
      session_generation: sessionGeneration,
      scenario,
      allowed_state_writes: [
        'generated UI preferences',
        'generated staged mail actions',
        'generated snoozes',
        'generated QA controls',
      ],
      preferences: clone(preferences),
      inbox_totals: {
        all: [...emails.values()].filter(email => emailInMailbox(email, 'INBOX')).length,
        primary: [...emails.values()].filter(email => email.account_id === 9101 && emailInMailbox(email, 'INBOX')).length,
        secondary: [...emails.values()].filter(email => email.account_id === 9102 && emailInMailbox(email, 'INBOX')).length,
      },
      operations: [...operations.values()].map(operationResponse),
      snoozes: [...snoozes.values()].map(snooze => clone(snooze.response)),
      counters: clone(counters),
      requests: clone(requests),
    };
  }

  function reject(response, action, error) {
    const status = error.status || 422;
    counters.validation_errors += 1;
    if (error.nonGenerated) counters.non_generated_rejections += 1;
    record(action, status);
    return writeError(response, status, status === 404 ? 'not_found' : 'invalid_request', error.message);
  }

  function activeSnooze(snooze) {
    return ['pending_archive', 'scheduled'].includes(snooze.response.state);
  }

  function buildOperation(payload, targetEmails, { source = 'direct' } = {}) {
    recordSequence += 1;
    const requestId = generatedUuid(recordSequence);
    const nowMs = Date.parse(FIXTURE_NOW) + recordSequence * 1000;
    const undoUntil = new Date(nowMs + 10_000).toISOString();
    const snapshot = targetEmails.map(email => clone(email));
    targetEmails.forEach(email => applyAction(email, payload.action));
    const operation = {
      request_id: requestId,
      idempotency_key: payload.idempotency_key,
      action: payload.action,
      state: 'staged',
      accepted_count: targetEmails.length,
      undo_until: undoUntil,
      created_at: new Date(nowMs).toISOString(),
      items: targetEmails.map((email, index) => ({
        id: 10_000 + recordSequence * 10 + index,
        email_id: email.id,
        account_id: email.account_id,
        gmail_message_id: email.gmail_message_id,
        sequence: 1,
        action: payload.action,
        state: 'staged',
        attempt_count: 0,
        next_attempt_at: undoUntil,
        error_code: null,
        error_message: null,
        applied_at: null,
        failed_at: null,
        cancelled_at: null,
      })),
      generated_source: source,
    };
    operations.set(requestId, operation);
    operationByKey.set(payload.idempotency_key, {
      fingerprint: JSON.stringify({
        action: payload.action,
        email_ids: [...payload.email_ids].sort((left, right) => left - right),
        scope: payload.scope || 'messages',
      }),
      operation,
    });
    actionSnapshots.set(requestId, snapshot);
    counters.mail_action_creates += 1;
    counters.expected_mail_action_writes += 1;
    if (source === 'snooze') counters.snooze_archive_action_writes += 1;
    return operation;
  }

  async function handleMailAction(request, response) {
    counters.mail_action_requests += 1;
    let payload;
    try {
      payload = await readJson(request);
      exactKeys(payload, ['email_ids', 'action', 'idempotency_key', 'scope'], ['email_ids', 'action', 'idempotency_key']);
      if (!Array.isArray(payload.email_ids) || payload.email_ids.length < 1 || payload.email_ids.length > 200) {
        throw new Error('email_ids are invalid');
      }
      if (new Set(payload.email_ids).size !== payload.email_ids.length) throw new Error('email_ids must be unique');
      if (!['archive', 'mark_read', 'mark_unread', 'star', 'unstar'].includes(payload.action)) {
        throw new Error('action is invalid');
      }
      if (!UUID_RE.test(payload.idempotency_key)) throw new Error('idempotency_key is invalid');
      if (!['messages', 'conversations', undefined].includes(payload.scope)) throw new Error('scope is invalid');
    } catch (error) {
      return reject(response, 'mail-action.create', error);
    }

    const fingerprint = JSON.stringify({
      action: payload.action,
      email_ids: [...payload.email_ids].sort((left, right) => left - right),
      scope: payload.scope || 'messages',
    });
    const existing = operationByKey.get(payload.idempotency_key);
    if (existing) {
      if (existing.fingerprint !== fingerprint) {
        counters.mail_action_conflicts += 1;
        record('mail-action.conflict', 409);
        return writeError(response, 409, 'idempotency_conflict', 'Idempotency key payload conflict');
      }
      counters.mail_action_replays += 1;
      record('mail-action.replay', 202, { request_id: existing.operation.request_id });
      return writeJson(response, operationResponse(existing.operation), 202);
    }

    const requested = payload.email_ids.map(ownedEmail);
    if (requested.some(email => !email)) {
      counters.ownership_rejections += 1;
      record('mail-action.not-found', 404);
      return writeError(response, 404, 'not_found', 'Email not found');
    }
    if (payload.action === 'archive' && requested.some(email => email.is_trash || email.is_spam)) {
      counters.protected_mailbox_rejections += 1;
      record('mail-action.protected', 422);
      return writeError(response, 422, 'protected_mailbox', 'Restore spam or trash before archiving');
    }

    const expanded = new Map();
    for (const email of requested) {
      const targets = payload.scope === 'conversations'
        ? [...emails.values()].filter(item => item.account_id === email.account_id && item.gmail_thread_id === email.gmail_thread_id)
        : [email];
      targets.forEach(target => expanded.set(target.id, target));
    }
    const operation = buildOperation(payload, [...expanded.values()]);
    record('mail-action.create', 202, { request_id: operation.request_id, action: operation.action });
    if (lostActionRemaining > 0) {
      lostActionRemaining -= 1;
      counters.lost_action_responses += 1;
      request.socket.destroy();
      return;
    }
    return writeJson(response, operationResponse(operation), 202);
  }

  function snoozeResponse(record) {
    return clone(record.response);
  }

  async function handleSnoozeCreate(request, response) {
    counters.snooze_requests += 1;
    let payload;
    try {
      payload = await readJson(request);
      exactKeys(payload, ['email_id', 'wake_at', 'time_zone', 'condition', 'idempotency_key'], ['email_id', 'wake_at', 'time_zone', 'condition', 'idempotency_key']);
      if (!Number.isSafeInteger(payload.email_id) || payload.email_id <= 0) throw new Error('email_id is invalid');
      if (!UUID_RE.test(payload.idempotency_key)) throw new Error('idempotency_key is invalid');
      if (!['always', 'if_no_reply'].includes(payload.condition)) throw new Error('condition is invalid');
      if (payload.time_zone !== 'America/New_York') throw new Error('time_zone must be generated America/New_York');
      if (!Number.isFinite(Date.parse(payload.wake_at)) || Date.parse(payload.wake_at) <= Date.parse(FIXTURE_NOW)) {
        throw new Error('wake_at must be after the generated clock');
      }
    } catch (error) {
      return reject(response, 'snooze.create', error);
    }

    const existing = snoozeByKey.get(payload.idempotency_key);
    if (existing) {
      const fingerprint = JSON.stringify({
        email_id: payload.email_id,
        wake_at: new Date(payload.wake_at).toISOString(),
        time_zone: payload.time_zone,
        condition: payload.condition,
      });
      if (existing.fingerprint !== fingerprint) {
        record('snooze.conflict', 409);
        return writeError(response, 409, 'snooze_conflict', 'Idempotency key payload conflict');
      }
      counters.snooze_replays += 1;
      record('snooze.replay', 202, { snooze_id: existing.response.id });
      return writeJson(response, snoozeResponse(existing), 202);
    }

    const email = ownedEmail(payload.email_id);
    if (!email) {
      counters.ownership_rejections += 1;
      record('snooze.not-found', 404);
      return writeError(response, 404, 'not_found', 'Email not found');
    }
    if (email.is_trash || email.is_spam) {
      counters.protected_mailbox_rejections += 1;
      record('snooze.protected', 422);
      return writeError(response, 422, 'protected_mailbox', 'Restore spam or trash before snoozing');
    }
    if ([...snoozes.values()].some(record => (
      activeSnooze(record)
      && record.response.account_id === email.account_id
      && record.response.gmail_thread_id === email.gmail_thread_id
    ))) {
      record('snooze.active-conflict', 409);
      return writeError(response, 409, 'snooze_conflict', 'This conversation is already snoozed');
    }

    recordSequence += 1;
    const snoozeId = generatedUuid(recordSequence);
    const conversation = [...emails.values()].filter(item => (
      item.account_id === email.account_id && item.gmail_thread_id === email.gmail_thread_id
    ));
    const originalConversation = conversation.map(clone);
    const inboxMembers = conversation.filter(item => emailInMailbox(item, 'INBOX'));
    let archiveOperation = null;
    if (inboxMembers.length) {
      archiveOperation = buildOperation({
        action: 'archive',
        email_ids: inboxMembers.map(item => item.id),
        idempotency_key: generatedUuid(recordSequence + 100_000),
        scope: 'messages',
      }, inboxMembers, { source: 'snooze' });
    }
    const now = new Date(Date.parse(FIXTURE_NOW) + recordSequence * 1000).toISOString();
    const responsePayload = {
      id: snoozeId,
      email_id: email.id,
      account_id: email.account_id,
      account_email: email.account_email,
      gmail_thread_id: email.gmail_thread_id,
      wake_at: new Date(payload.wake_at).toISOString(),
      time_zone: payload.time_zone,
      condition: payload.condition,
      origin: 'manual',
      state: inboxMembers.length ? 'pending_archive' : 'scheduled',
      status_detail: inboxMembers.length ? 'archiving' : 'scheduled',
      archive_required: inboxMembers.length > 0,
      originally_in_inbox: inboxMembers.length > 0,
      conversation_message_count: conversation.length,
      archive_action_request_id: archiveOperation?.request_id || null,
      archive_undo_until: archiveOperation?.undo_until || null,
      error_code: null,
      error_message: null,
      created_at: now,
      updated_at: now,
      scheduled_at: inboxMembers.length ? null : now,
      returned_at: null,
      cancelled_at: null,
      dismissed_at: null,
      failed_at: null,
      email: clone(email),
    };
    const fingerprint = JSON.stringify({
      email_id: payload.email_id,
      wake_at: responsePayload.wake_at,
      time_zone: payload.time_zone,
      condition: payload.condition,
    });
    const recordValue = { fingerprint, response: responsePayload, original: originalConversation };
    snoozes.set(snoozeId, recordValue);
    snoozeByKey.set(payload.idempotency_key, recordValue);
    counters.snooze_creates += 1;
    counters.expected_snooze_writes += 1;
    record('snooze.create', 202, { snooze_id: snoozeId });
    if (lostSnoozeRemaining > 0) {
      lostSnoozeRemaining -= 1;
      counters.lost_snooze_responses += 1;
      request.socket.destroy();
      return;
    }
    return writeJson(response, snoozeResponse(recordValue), 202);
  }

  function listConversations(url) {
    const mailbox = url.searchParams.get('mailbox') || 'INBOX';
    const rawAccountId = url.searchParams.get('account_id');
    const accountId = rawAccountId === null ? null : Number(rawAccountId);
    if (accountId !== null && (!Number.isSafeInteger(accountId) || !ownsAccount(accountId))) {
      throw Object.assign(new Error('Account not found'), { status: 404 });
    }
    const page = Math.max(1, Number(url.searchParams.get('page')) || 1);
    const pageSize = Math.max(1, Math.min(200, Number(url.searchParams.get('page_size')) || 50));
    const rows = [...emails.values()]
      .filter(email => emailInMailbox(email, mailbox))
      .filter(email => accountId === null || email.account_id === accountId)
      .map(conversationSummary)
      .sort((left, right) => Date.parse(right.date) - Date.parse(left.date) || right.id - left.id);
    const start = (page - 1) * pageSize;
    return {
      conversations: rows.slice(start, start + pageSize),
      total: rows.length,
      page,
      page_size: pageSize,
      total_pages: rows.length ? Math.ceil(rows.length / pageSize) : 0,
    };
  }

  async function maybeDelayDataset(response, capturedGeneration) {
    if (scenario === 'dataset-error') {
      counters.dataset_failures += 1;
      writeError(response, 503, 'generated_dataset_error', 'Generated Inbox dataset is unavailable');
      return true;
    }
    if (delayedDatasetRemaining > 0) {
      delayedDatasetRemaining -= 1;
      counters.dataset_delays += 1;
      await new Promise(resolveDelay => setTimeout(resolveDelay, 500));
      if (capturedGeneration !== sessionGeneration) counters.stale_dataset_responses += 1;
    }
    return false;
  }

  function emitEvent(eventType = 'emails_updated') {
    const payload = JSON.stringify({ type: eventType, generated: true });
    for (const stream of eventStreams) stream.write(`data: ${payload}\n\n`);
  }

  async function handleControl(request, response, pathname) {
    if (request.method === 'GET' && pathname === '/__qa/audit') return writeJson(response, auditPayload());
    if (request.method === 'POST' && pathname === '/__qa/reset') {
      try {
        const payload = await readJson(request);
        exactKeys(payload, ['scenario', 'current_user'], []);
        reset(payload.scenario || 'ready', payload.current_user || 'generated-a');
        return writeJson(response, { reset: true, scenario, current_user: currentUser, session_generation: sessionGeneration });
      } catch (error) {
        return reject(response, 'qa.reset', error);
      }
    }
    if (request.method === 'POST' && pathname === '/__qa/scenario') {
      try {
        const payload = await readJson(request);
        exactKeys(payload, ['scenario']);
        if (!SCENARIOS.has(payload.scenario)) throw new Error('scenario is invalid');
        scenario = payload.scenario;
        lostActionRemaining = scenario === 'lost-action-once' ? 1 : 0;
        lostSnoozeRemaining = scenario === 'lost-snooze-once' ? 1 : 0;
        delayedDatasetRemaining = scenario === 'slow-dataset' ? 1 : 0;
        return writeJson(response, { scenario });
      } catch (error) {
        return reject(response, 'qa.scenario', error);
      }
    }
    if (request.method === 'POST' && pathname === '/__qa/session') {
      try {
        const payload = await readJson(request);
        exactKeys(payload, ['current_user']);
        if (!['generated-a', 'anonymous'].includes(payload.current_user)) throw new Error('current_user is invalid');
        currentUser = payload.current_user;
        sessionGeneration += 1;
        counters.session_changes += 1;
        emitEvent('session_changed');
        return writeJson(response, { current_user: currentUser, session_generation: sessionGeneration });
      } catch (error) {
        return reject(response, 'qa.session', error);
      }
    }
    if (request.method === 'POST' && pathname === '/__qa/emit') {
      try {
        const payload = await readJson(request);
        exactKeys(payload, ['type']);
        if (!['emails_updated', 'new_emails', 'snooze_updated'].includes(payload.type)) {
          throw new Error('event type is invalid');
        }
        emitEvent(payload.type);
        return writeJson(response, { emitted: payload.type });
      } catch (error) {
        return reject(response, 'qa.emit', error);
      }
    }
    return false;
  }

  function rejectMutation(request, response, pathname) {
    const path = pathname.toLowerCase();
    if (path.includes('gmail') || path.includes('provider')) {
      counters.rejected_provider_attempts += 1;
      counters.rejected_gmail_attempts += 1;
      return writeError(response, 405, 'provider_operation_rejected', 'Generated fixture rejects provider and Gmail operations');
    }
    if (path.startsWith('/api/calendar')) {
      counters.rejected_calendar_attempts += 1;
      return writeError(response, 405, 'calendar_operation_rejected', 'Generated fixture rejects calendar operations');
    }
    if (path.startsWith('/api/terminal')) {
      counters.rejected_terminal_attempts += 1;
      return writeError(response, 405, 'terminal_operation_rejected', 'Generated fixture rejects terminal operations');
    }
    if (path.startsWith('/api/ai')) {
      counters.rejected_ai_attempts += 1;
      return writeError(response, 405, 'ai_operation_rejected', 'Generated fixture rejects AI operations');
    }
    if (path.includes('worker')) {
      counters.rejected_worker_attempts += 1;
      return writeError(response, 405, 'worker_operation_rejected', 'Generated fixture rejects worker operations');
    }
    if (path.startsWith('/api/emails') || path.startsWith('/api/snoozes') || path.startsWith('/api/compose')) {
      counters.rejected_mail_attempts += 1;
    }
    counters.unexpected_writes += 1;
    record(`${request.method} ${pathname}`, 405);
    return writeError(response, 405, 'unexpected_write_rejected', 'Generated fixture rejects this write');
  }

  async function serveStatic(response, pathname) {
    let requested = pathname === '/' ? '/index.html' : pathname;
    try {
      requested = decodeURIComponent(requested);
    } catch {
      return false;
    }
    const relative = requested.replace(/^\/+/, '');
    let candidate = resolve(frontendDist, relative);
    if (candidate !== frontendDist && !candidate.startsWith(`${frontendDist}${sep}`)) return false;
    try {
      let info = await stat(candidate);
      if (info.isDirectory()) {
        candidate = resolve(candidate, 'index.html');
        info = await stat(candidate);
      }
      if (!info.isFile()) return false;
      response.writeHead(200, {
        'Content-Type': STATIC_MIME_TYPES[extname(candidate)] || 'application/octet-stream',
        'Content-Length': info.size,
        'Cache-Control': candidate.endsWith('index.html') ? 'no-store' : 'public, max-age=60',
        'X-Content-Type-Options': 'nosniff',
      });
      createReadStream(candidate).pipe(response);
      return true;
    } catch {
      return false;
    }
  }

  async function handle(request, response) {
    const url = new URL(request.url, `http://${request.headers.host || GENERATED_TOUCH_TRIAGE_HOST}`);
    const { pathname } = url;

    if (pathname.startsWith('/__qa/')) {
      const handled = await handleControl(request, response, pathname);
      if (handled !== false) return;
    }

    if (request.method === 'GET' && pathname === '/api/health') {
      return writeJson(response, { status: 'ok', version: 'generated-touch-triage' });
    }
    if (request.method === 'GET' && pathname === '/api/build-version') {
      return writeJson(response, { version: 'generated-touch-triage' });
    }
    if (request.method === 'GET' && pathname === '/api/events/stream') {
      response.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
      });
      response.write(': generated touch triage stream\n\n');
      eventStreams.add(response);
      request.on('close', () => eventStreams.delete(response));
      return;
    }

    if (pathname.startsWith('/api/') && !requireAuth(response, `${request.method} ${pathname}`)) return;

    if (request.method === 'GET' && pathname === '/api/auth/me') {
      return writeJson(response, { id: GENERATED_USER.id, username: GENERATED_USER.username, is_admin: false });
    }
    if (request.method === 'POST' && pathname === '/api/auth/refresh') {
      return writeJson(response, { access_token: 'generated-touch-session', token_type: 'bearer' });
    }
    if (request.method === 'POST' && pathname === '/api/auth/logout') {
      currentUser = 'anonymous';
      sessionGeneration += 1;
      counters.session_changes += 1;
      return writeJson(response, { ok: true });
    }
    if (request.method === 'GET' && pathname === '/api/accounts/') {
      counters.account_reads += 1;
      return writeJson(response, Object.values(GENERATED_ACCOUNTS).map(clone));
    }
    if (request.method === 'GET' && pathname === '/api/auth/ui-preferences') {
      counters.preference_reads += 1;
      return writeJson(response, clone(preferences));
    }
    if (request.method === 'PUT' && pathname === '/api/auth/ui-preferences') {
      try {
        const payload = await readJson(request);
        exactKeys(
          payload,
          ['thread_order', 'theme', 'color_scheme', 'swipe_left_action', 'swipe_right_action'],
          [],
        );
        if (payload.thread_order !== undefined && !['newest_first', 'oldest_first'].includes(payload.thread_order)) {
          throw new Error('thread_order is invalid');
        }
        if (payload.theme !== undefined && !['amber', 'blue', 'rose', 'emerald', 'purple', 'mono'].includes(payload.theme)) {
          throw new Error('theme is invalid');
        }
        if (payload.color_scheme !== undefined && !['light', 'dark', 'system'].includes(payload.color_scheme)) {
          throw new Error('color_scheme is invalid');
        }
        for (const key of ['swipe_left_action', 'swipe_right_action']) {
          if (payload[key] !== undefined && !SWIPE_ACTIONS.has(payload[key])) throw new Error(`${key} is invalid`);
        }
        preferences = { ...preferences, ...payload };
        counters.preference_updates += 1;
        counters.expected_preference_writes += 1;
        record('preferences.update', 200, { fields: Object.keys(payload).sort() });
        return writeJson(response, clone(preferences));
      } catch (error) {
        return reject(response, 'preferences.update', error);
      }
    }
    if (request.method === 'GET' && pathname === '/api/auth/keyboard-shortcuts') {
      return writeJson(response, { shortcuts: {} });
    }
    if (request.method === 'GET' && pathname === '/api/auth/ai-preferences') {
      return writeJson(response, {});
    }
    if (request.method === 'GET' && pathname === '/api/emails/labels/all') return writeJson(response, []);
    if (request.method === 'GET' && pathname === '/api/calendar/sync-status') return writeJson(response, []);
    if (request.method === 'GET' && pathname === '/api/calendar/events') return writeJson(response, { events: [], total: 0 });
    if (request.method === 'GET' && pathname === '/api/calendar/upcoming') return writeJson(response, { events: [] });
    if (request.method === 'GET' && pathname === '/api/compose/sends/recent') return writeJson(response, { operations: [] });
    if (request.method === 'GET' && pathname === '/api/compose/sends/scheduled') return writeJson(response, { operations: [] });
    if (request.method === 'GET' && pathname === '/api/compose/drafts/recent') return writeJson(response, []);
    if (request.method === 'GET' && pathname === '/api/saved-views') return writeJson(response, { items: [], max_views: 12 });
    if (request.method === 'GET' && pathname === '/api/follow-up/policies') return writeJson(response, { accounts: [], total: 0 });
    if (request.method === 'GET' && pathname === '/api/emails/actions/recent') {
      return writeJson(response, [...operations.values()].slice(-20).reverse().map(operationResponse));
    }

    if (request.method === 'GET' && pathname === '/api/emails/conversations') {
      const capturedGeneration = sessionGeneration;
      counters.conversation_reads += 1;
      if (await maybeDelayDataset(response, capturedGeneration)) return;
      try {
        return writeJson(response, listConversations(url));
      } catch (error) {
        counters.ownership_rejections += 1;
        return writeError(response, error.status || 422, 'not_found', error.message);
      }
    }
    if (request.method === 'GET' && pathname === '/api/emails/conversations/split') {
      const capturedGeneration = sessionGeneration;
      counters.split_reads += 1;
      if (await maybeDelayDataset(response, capturedGeneration)) return;
      let all;
      try {
        all = listConversations(new URL(`${url.origin}${url.pathname}?${new URLSearchParams({
          ...Object.fromEntries(url.searchParams),
          mailbox: 'INBOX',
          page: '1',
          page_size: '200',
        })}`));
      } catch (error) {
        counters.ownership_rejections += 1;
        return writeError(response, error.status || 422, 'not_found', error.message);
      }
      const page = Math.max(1, Number(url.searchParams.get('page')) || 1);
      const pageSize = Math.max(1, Math.min(100, Number(url.searchParams.get('page_size')) || 25));
      const section = placement => {
        const rows = all.conversations.filter(item => item.inbox_placement === placement);
        const start = (page - 1) * pageSize;
        return {
          conversations: rows.slice(start, start + pageSize),
          total: rows.length,
          page,
          page_size: pageSize,
          total_pages: rows.length ? Math.ceil(rows.length / pageSize) : 0,
        };
      };
      const focused = section('focused');
      const other = section('other');
      return writeJson(response, { focused, other, total: focused.total + other.total });
    }

    if (request.method === 'POST' && pathname === '/api/emails/actions') {
      return handleMailAction(request, response);
    }
    const actionByKey = pathname.match(/^\/api\/emails\/actions\/by-idempotency\/([^/]+)$/);
    if (request.method === 'GET' && actionByKey) {
      counters.mail_action_lookups += 1;
      const existing = operationByKey.get(actionByKey[1]);
      return writeJson(response, existing ? operationResponse(existing.operation) : { detail: 'Not found' }, existing ? 200 : 404);
    }
    const actionUndo = pathname.match(/^\/api\/emails\/actions\/([^/]+)\/undo$/);
    if (request.method === 'POST' && actionUndo) {
      const operation = operations.get(actionUndo[1]);
      if (!operation) return writeError(response, 404, 'not_found', 'Action not found');
      if (operation.state !== 'staged') return writeError(response, 409, 'undo_closed', 'Undo is no longer available');
      const snapshot = actionSnapshots.get(operation.request_id) || [];
      snapshot.forEach(email => emails.set(email.id, clone(email)));
      operation.state = 'cancelled';
      operation.items.forEach(item => {
        item.state = 'cancelled';
        item.cancelled_at = new Date(Date.parse(FIXTURE_NOW) + recordSequence * 1000).toISOString();
      });
      counters.mail_action_undos += 1;
      counters.expected_mail_action_writes += 1;
      record('mail-action.undo', 200, { request_id: operation.request_id });
      return writeJson(response, operationResponse(operation));
    }
    const actionRetry = pathname.match(/^\/api\/emails\/actions\/([^/]+)\/retry$/);
    if (request.method === 'POST' && actionRetry) {
      const operation = operations.get(actionRetry[1]);
      if (!operation) return writeError(response, 404, 'not_found', 'Action not found');
      counters.mail_action_retries += 1;
      operation.state = 'retry_wait';
      return writeJson(response, operationResponse(operation));
    }
    const actionById = pathname.match(/^\/api\/emails\/actions\/([^/]+)$/);
    if (request.method === 'GET' && actionById) {
      counters.mail_action_lookups += 1;
      const operation = operations.get(actionById[1]);
      return writeJson(response, operation ? operationResponse(operation) : { detail: 'Not found' }, operation ? 200 : 404);
    }

    if (request.method === 'POST' && pathname === '/api/snoozes') return handleSnoozeCreate(request, response);
    if (request.method === 'GET' && pathname === '/api/snoozes') {
      const active = [...snoozes.values()].filter(activeSnooze).map(snoozeResponse);
      return writeJson(response, { items: active, total: active.length, limit: 50, offset: 0 });
    }
    const snoozeByIdempotency = pathname.match(/^\/api\/snoozes\/by-idempotency\/([^/]+)$/);
    if (request.method === 'GET' && snoozeByIdempotency) {
      counters.snooze_lookups += 1;
      const recordValue = snoozeByKey.get(snoozeByIdempotency[1]);
      return writeJson(response, recordValue ? snoozeResponse(recordValue) : { detail: 'Not found' }, recordValue ? 200 : 404);
    }
    const snoozeCancel = pathname.match(/^\/api\/snoozes\/([^/]+)\/cancel$/);
    if (request.method === 'POST' && snoozeCancel) {
      const recordValue = snoozes.get(snoozeCancel[1]);
      if (!recordValue) return writeError(response, 404, 'not_found', 'Snooze not found');
      recordValue.original.forEach(email => emails.set(email.id, clone(email)));
      recordValue.response.state = 'cancelled';
      recordValue.response.status_detail = 'cancelled';
      recordValue.response.cancelled_at = FIXTURE_NOW;
      recordValue.response.updated_at = FIXTURE_NOW;
      counters.snooze_cancels += 1;
      counters.expected_snooze_writes += 1;
      return writeJson(response, snoozeResponse(recordValue));
    }
    const snoozeById = pathname.match(/^\/api\/snoozes\/([^/]+)$/);
    if (request.method === 'GET' && snoozeById) {
      counters.snooze_lookups += 1;
      const recordValue = snoozes.get(snoozeById[1]);
      return writeJson(response, recordValue ? snoozeResponse(recordValue) : { detail: 'Not found' }, recordValue ? 200 : 404);
    }

    const threadMatch = pathname.match(/^\/api\/emails\/thread\/([^/]+)$/);
    if (request.method === 'GET' && threadMatch) {
      counters.thread_reads += 1;
      const accountId = Number(url.searchParams.get('account_id'));
      const threadId = decodeURIComponent(threadMatch[1]);
      const members = [...emails.values()].filter(email => (
        email.account_id === accountId && email.gmail_thread_id === threadId
      ));
      if (!members.length) return writeError(response, 404, 'not_found', 'Thread not found');
      return writeJson(response, {
        thread_id: threadId,
        subject: members[0].subject,
        emails: members.map(clone),
        participants: members.map(email => ({ name: email.from_name, address: email.from_address })),
      });
    }
    const emailMatch = pathname.match(/^\/api\/emails\/(\d+)$/);
    if (request.method === 'GET' && emailMatch) {
      counters.detail_reads += 1;
      const email = ownedEmail(emailMatch[1]);
      return writeJson(response, email ? clone(email) : { detail: 'Not found' }, email ? 200 : 404);
    }

    if (pathname.startsWith('/api/') && !['GET', 'HEAD'].includes(request.method || 'GET')) {
      return rejectMutation(request, response, pathname);
    }
    if (pathname.startsWith('/api/')) {
      counters.unknown_routes += 1;
      record(`${request.method} ${pathname}`, 404);
      return writeError(response, 404, 'route_not_found', 'Generated fixture route not found');
    }

    if (['GET', 'HEAD'].includes(request.method || 'GET')) {
      if (await serveStatic(response, pathname)) return;
      if (!extname(pathname) && await serveStatic(response, '/index.html')) return;
    }
    response.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
    response.end('Not found');
  }

  const server = createServer((request, response) => {
    handle(request, response).catch(error => {
      if (!response.headersSent) writeError(response, 500, 'fixture_error', error?.message || 'Generated fixture failure');
      else response.destroy();
    });
  });

  return {
    listen(port = 0) {
      return new Promise((resolveListen, rejectListen) => {
        server.once('error', rejectListen);
        server.listen(port, GENERATED_TOUCH_TRIAGE_HOST, () => {
          server.off('error', rejectListen);
          resolveListen(server.address());
        });
      });
    },
    close() {
      for (const stream of eventStreams) stream.end();
      eventStreams.clear();
      return new Promise((resolveClose, rejectClose) => {
        server.close(error => (error ? rejectClose(error) : resolveClose()));
      });
    },
    audit: auditPayload,
  };
}

async function runCli() {
  const port = Number.parseInt(process.env.QA_TOUCH_TRIAGE_PORT || process.argv[2] || '0', 10);
  const fixture = createGeneratedTouchTriageFixture();
  const address = await fixture.listen(Number.isSafeInteger(port) ? port : 0);
  process.stdout.write(`Generated touch triage QA listening on http://${GENERATED_TOUCH_TRIAGE_HOST}:${address.port}\n`);
  const close = () => fixture.close().finally(() => process.exit(0));
  process.once('SIGINT', close);
  process.once('SIGTERM', close);
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  runCli().catch(error => {
    process.stderr.write(`${error.stack || error.message}\n`);
    process.exitCode = 1;
  });
}
