#!/usr/bin/env node

// Deterministic, local-only API for manual browser QA. It never reads Gmail,
// production configuration, credentials, or mailbox data. Run this server on
// port 8000, then run the frontend Vite server and open `/?page=inbox`.

import { createServer } from 'node:http';
import { randomUUID } from 'node:crypto';

const port = Number.parseInt(process.env.QA_API_PORT || '8000', 10);
const now = new Date('2026-08-30T14:00:00Z');
let clockMs = now.getTime();
let lostActionResponses = Number.parseInt(process.env.QA_LOST_ACTION_RESPONSES || '0', 10);
let lostLookupResponses = Number.parseInt(process.env.QA_LOST_LOOKUP_RESPONSES || '0', 10);

const generatedEmails = [
  ['Quinn Rivera', 'Design review notes', 'The updated navigation hierarchy is ready for review.'],
  ['Sam Chen', 'Monday launch checklist', 'Three items remain before the generated QA launch.'],
  ['Jordan Lee', 'Dinner next week?', 'Would Tuesday evening work for everyone?'],
  ['Morgan Patel', 'Quarterly planning packet', 'I attached the generated planning outline.'],
  ['Casey Kim', 'Your test receipt', 'This generated receipt confirms a $0.00 QA order.'],
  ['Taylor Brooks', 'Accessibility follow-up', 'Keyboard and narrow-screen checks look promising.'],
].map(([fromName, subject, snippet], index) => ({
  id: index + 101,
  account_id: 1,
  account_email: 'qa.generated@example.test',
  gmail_message_id: `generated-message-${index + 1}`,
  gmail_thread_id: `generated-thread-${index + 1}`,
  message_id_header: `<generated-${index + 1}@example.test>`,
  from_name: fromName,
  from_address: `${fromName.toLowerCase().replaceAll(' ', '.')}@example.test`,
  reply_to: `${fromName.toLowerCase().replaceAll(' ', '.')}@example.test`,
  to_addresses: [{ name: 'QA User', address: 'qa.generated@example.test' }],
  cc_addresses: [],
  subject,
  snippet,
  body_text: `${snippet}\n\nThis message was generated locally for browser testing.`,
  body_html: `<p>${snippet}</p><p>This message was generated locally for browser testing.</p>`,
  date: new Date(now.getTime() - index * 38 * 60_000).toISOString(),
  labels: ['INBOX', ...(index < 3 ? ['UNREAD'] : []), ...(index === 3 ? ['STARRED'] : [])],
  is_read: index >= 3,
  is_starred: index === 3,
  is_trash: false,
  is_spam: false,
  attachments: [],
  ai_action_items: [],
  is_subscription: false,
}));

const emails = new Map(generatedEmails.map(email => [email.id, email]));
const snapshots = new Map();
const operations = new Map();
const snoozes = new Map();
const snoozesByIdempotency = new Map();
const audit = {
  fixture_domains: ['example.test'],
  provider_calls: 0,
  snooze_creates: [],
  snooze_replays: [],
  snooze_reschedules: [],
  snooze_cancels: [],
  snooze_returns: [],
  clock_changes: [],
  rejected_mutations: [],
  unknown_routes: [],
};
const seededFailure = {
  request_id: '00000000-0000-4000-8000-000000000099',
  idempotency_key: '00000000-0000-4000-8000-000000000098',
  action: 'star',
  state: 'failed',
  accepted_count: 1,
  undo_until: null,
  created_at: new Date(now.getTime() - 60_000).toISOString(),
  items: [{
    id: 99,
    email_id: 106,
    account_id: 1,
    gmail_message_id: 'generated-message-6',
    sequence: 1,
    action: 'star',
    state: 'failed',
    attempt_count: 3,
    next_attempt_at: null,
    error_code: 'generated_transient_failure',
    error_message: 'Generated Gmail timeout',
    applied_at: null,
    failed_at: new Date(now.getTime() - 30_000).toISOString(),
    cancelled_at: null,
  }],
};
operations.set(seededFailure.request_id, seededFailure);

function writeJson(response, payload, status = 200) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(body),
    'Cache-Control': 'no-store',
  });
  response.end(body);
}

async function readJson(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  return chunks.length ? JSON.parse(Buffer.concat(chunks).toString('utf8')) : {};
}

function generatedClock() {
  return new Date(clockMs);
}

function isUuid(value) {
  return typeof value === 'string'
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

function isActiveSnooze(snooze) {
  return ['pending_archive', 'scheduled', 'pending_return'].includes(snooze.state);
}

function snoozeResponse(snooze) {
  const email = emails.get(snooze.email_id);
  return {
    id: snooze.id,
    email_id: snooze.email_id,
    account_id: snooze.account_id,
    account_email: 'qa.generated@example.test',
    gmail_thread_id: snooze.gmail_thread_id,
    wake_at: snooze.wake_at,
    time_zone: snooze.time_zone,
    condition: snooze.condition,
    state: snooze.state,
    status_detail: snooze.status_detail,
    archive_required: snooze.archive_required,
    archive_action_request_id: snooze.archive_action_request_id,
    archive_undo_until: snooze.archive_undo_until,
    error_code: snooze.error_code,
    error_message: snooze.error_message,
    created_at: snooze.created_at,
    updated_at: snooze.updated_at,
    scheduled_at: snooze.scheduled_at,
    returned_at: snooze.returned_at,
    cancelled_at: snooze.cancelled_at,
    dismissed_at: snooze.dismissed_at,
    failed_at: snooze.failed_at,
    email: email ? structuredClone(email) : null,
  };
}

function processDueSnoozes() {
  for (const snooze of snoozes.values()) {
    if (snooze.state === 'pending_archive' && snooze.archive_action_request_id) {
      const operation = operations.get(snooze.archive_action_request_id);
      if (operation?.state === 'cancelled') {
        snooze.state = 'cancelled';
        snooze.status_detail = 'archive_undone';
        snooze.cancelled_at = generatedClock().toISOString();
        snooze.updated_at = snooze.cancelled_at;
      } else if (Date.parse(snooze.archive_undo_until) <= clockMs) {
        if (operation) {
          operation.state = 'applied';
          operation.items.forEach(item => {
            item.state = 'applied';
            item.next_attempt_at = null;
            item.applied_at = generatedClock().toISOString();
          });
        }
        snooze.state = 'scheduled';
        snooze.status_detail = 'scheduled';
        snooze.scheduled_at = generatedClock().toISOString();
        snooze.updated_at = snooze.scheduled_at;
      }
    }
    if (!isActiveSnooze(snooze) || Date.parse(snooze.wake_at) > clockMs) continue;
    const email = emails.get(snooze.email_id);
    snooze.updated_at = generatedClock().toISOString();
    if (!email) {
      snooze.state = 'failed';
      snooze.status_detail = 'failed';
      snooze.error_code = 'email_missing';
      snooze.error_message = 'The generated email no longer exists';
      snooze.failed_at = snooze.updated_at;
      continue;
    }
    if (email.is_trash || email.is_spam) {
      snooze.state = 'dismissed';
      snooze.status_detail = 'protected_mailbox';
      snooze.dismissed_at = snooze.updated_at;
      continue;
    }
    if (snooze.condition === 'if_no_reply' && snooze.generated_reply_received) {
      snooze.state = 'dismissed';
      snooze.status_detail = 'reply_received';
      snooze.dismissed_at = snooze.updated_at;
      continue;
    }
    applyAction(email, 'unarchive');
    snooze.state = 'returned';
    snooze.status_detail = 'returned_to_inbox';
    snooze.returned_at = snooze.updated_at;
    audit.snooze_returns.push({ id: snooze.id, at: snooze.updated_at, reason: 'due' });
  }
}

function validateSnoozePayload(payload) {
  const email = emails.get(Number(payload?.email_id));
  if (!email) return 'Choose a generated email';
  if (email.is_trash || email.is_spam) return 'Trash and spam cannot be snoozed';
  if (!isUuid(payload?.idempotency_key)) return 'A UUID idempotency_key is required';
  if (!['always', 'if_no_reply'].includes(payload?.condition || 'always')) {
    return 'Choose a valid reminder condition';
  }
  if (typeof payload?.time_zone !== 'string' || !payload.time_zone.trim()) {
    return 'A timezone is required';
  }
  const wakeAt = Date.parse(payload?.wake_at);
  if (!Number.isFinite(wakeAt) || wakeAt <= clockMs) return 'wake_at must be in the future';
  return null;
}

async function handleSnoozeCreate(request, response) {
  const payload = await readJson(request);
  const validationError = validateSnoozePayload(payload);
  if (validationError) {
    audit.rejected_mutations.push({ route: '/api/snoozes', reason: validationError });
    return writeJson(response, { detail: { code: 'snooze_invalid', message: validationError } }, 422);
  }
  const existing = snoozesByIdempotency.get(payload.idempotency_key);
  if (existing) {
    audit.snooze_replays.push(existing.id);
    return writeJson(response, snoozeResponse(existing), 202);
  }
  const email = emails.get(Number(payload.email_id));
  const alreadyActive = [...snoozes.values()].find(
    item => item.email_id === email.id && isActiveSnooze(item),
  );
  if (alreadyActive) {
    return writeJson(response, { detail: { code: 'snooze_conflict', message: 'This email is already snoozed' } }, 409);
  }
  const createdAt = generatedClock().toISOString();
  const archiveRequired = email.labels.includes('INBOX');
  const archiveRequestId = archiveRequired ? randomUUID() : null;
  let archiveUndoUntil = null;
  if (archiveRequired) {
    const operationPayload = {
      action: 'archive',
      email_ids: [email.id],
      idempotency_key: randomUUID(),
    };
    const selected = [email];
    snapshots.set(archiveRequestId, selected.map(item => structuredClone(item)));
    selected.forEach(item => applyAction(item, 'archive'));
    archiveUndoUntil = new Date(clockMs + 10_000).toISOString();
    operations.set(archiveRequestId, {
      request_id: archiveRequestId,
      idempotency_key: operationPayload.idempotency_key,
      action: 'archive',
      state: 'staged',
      accepted_count: 1,
      undo_until: archiveUndoUntil,
      created_at: createdAt,
      items: [{
        id: 2_000 + operations.size,
        email_id: email.id,
        account_id: email.account_id,
        gmail_message_id: email.gmail_message_id,
        sequence: 1,
        action: 'archive',
        state: 'staged',
        attempt_count: 0,
        next_attempt_at: archiveUndoUntil,
        error_code: null,
        error_message: null,
        applied_at: null,
        failed_at: null,
        cancelled_at: null,
      }],
    });
  }
  const snooze = {
    id: randomUUID(),
    idempotency_key: payload.idempotency_key,
    email_id: email.id,
    account_id: email.account_id,
    gmail_thread_id: email.gmail_thread_id,
    wake_at: new Date(payload.wake_at).toISOString(),
    time_zone: payload.time_zone,
    condition: payload.condition || 'always',
    state: archiveRequired ? 'pending_archive' : 'scheduled',
    status_detail: archiveRequired ? 'archiving' : 'scheduled',
    archive_required: archiveRequired,
    archive_action_request_id: archiveRequestId,
    archive_undo_until: archiveUndoUntil,
    error_code: null,
    error_message: null,
    created_at: createdAt,
    updated_at: createdAt,
    scheduled_at: archiveRequired ? null : createdAt,
    returned_at: null,
    cancelled_at: null,
    dismissed_at: null,
    failed_at: null,
    generated_reply_received: false,
  };
  snoozes.set(snooze.id, snooze);
  snoozesByIdempotency.set(snooze.idempotency_key, snooze);
  audit.snooze_creates.push({ id: snooze.id, email_id: email.id, wake_at: snooze.wake_at });
  return writeJson(response, snoozeResponse(snooze), 202);
}

function applyAction(email, action) {
  const labels = new Set(email.labels);
  if (action === 'mark_read') labels.delete('UNREAD');
  if (action === 'mark_unread') labels.add('UNREAD');
  if (action === 'star') labels.add('STARRED');
  if (action === 'unstar') labels.delete('STARRED');
  if (action === 'archive') labels.delete('INBOX');
  if (action === 'unarchive') labels.add('INBOX');
  if (action === 'trash') labels.add('TRASH');
  if (action === 'untrash') labels.delete('TRASH');
  if (action === 'spam') {
    labels.add('SPAM');
    labels.delete('INBOX');
  }
  if (action === 'unspam') {
    labels.delete('SPAM');
    labels.add('INBOX');
  }
  email.labels = [...labels];
  email.is_read = !labels.has('UNREAD');
  email.is_starred = labels.has('STARRED');
  email.is_trash = labels.has('TRASH');
  email.is_spam = labels.has('SPAM');
}

function visibleEmails(mailbox) {
  const all = [...emails.values()];
  if (mailbox === 'ALL') return all.filter(email => !email.is_trash && !email.is_spam);
  if (mailbox === 'STARRED') return all.filter(email => email.is_starred && !email.is_trash && !email.is_spam);
  if (mailbox === 'TRASH') return all.filter(email => email.is_trash);
  if (mailbox === 'SPAM') return all.filter(email => email.is_spam);
  if (mailbox === 'SENT' || mailbox === 'DRAFTS') return [];
  return all.filter(email => email.labels.includes('INBOX') && !email.is_trash && !email.is_spam);
}

async function handleActionCreate(request, response) {
  const payload = await readJson(request);
  const existing = [...operations.values()].find(
    operation => operation.idempotency_key === payload.idempotency_key,
  );
  if (existing) {
    if (lostActionResponses > 0) {
      lostActionResponses -= 1;
      return writeJson(response, { detail: 'Failed to fetch' }, 503);
    }
    return writeJson(response, existing, 202);
  }

  const requestId = randomUUID();
  const selected = payload.email_ids.map(id => emails.get(id)).filter(Boolean);
  snapshots.set(requestId, selected.map(email => structuredClone(email)));
  selected.forEach(email => applyAction(email, payload.action));
  const createdAt = new Date();
  const operation = {
    request_id: requestId,
    idempotency_key: payload.idempotency_key || randomUUID(),
    action: payload.action,
    state: 'staged',
    accepted_count: selected.length,
    undo_until: new Date(createdAt.getTime() + 10_000).toISOString(),
    created_at: createdAt.toISOString(),
    items: selected.map((email, index) => ({
      id: 1_000 + operations.size + index,
      email_id: email.id,
      account_id: email.account_id,
      gmail_message_id: email.gmail_message_id,
      sequence: 1,
      action: payload.action,
      state: 'staged',
      attempt_count: 0,
      next_attempt_at: null,
      error_code: null,
      error_message: null,
      applied_at: null,
      failed_at: null,
      cancelled_at: null,
    })),
  };
  operation.items.forEach(item => { item.next_attempt_at = operation.undo_until; });
  operations.set(requestId, operation);
  if (lostActionResponses > 0) {
    lostActionResponses -= 1;
    return writeJson(response, { detail: 'Failed to fetch' }, 503);
  }
  return writeJson(response, operation, 202);
}

async function handleRequest(request, response) {
  const url = new URL(request.url, `http://${request.headers.host}`);
  const { pathname } = url;
  processDueSnoozes();

  if (request.method === 'GET' && pathname === '/api/auth/me') {
    return writeJson(response, { id: 1, username: 'qa-user', is_admin: false });
  }
  if (request.method === 'GET' && pathname === '/api/health') {
    return writeJson(response, { status: 'ok', version: 'generated-snooze-qa' });
  }
  if (request.method === 'GET' && pathname === '/api/auth/ui-preferences') {
    return writeJson(response, { thread_order: 'asc', theme: 'default', color_scheme: 'light' });
  }
  if (request.method === 'GET' && pathname === '/api/auth/keyboard-shortcuts') {
    return writeJson(response, { shortcuts: {} });
  }
  if (request.method === 'GET' && pathname === '/api/accounts/') {
    return writeJson(response, [{
      id: 1,
      email: 'qa.generated@example.test',
      display_name: 'Generated QA',
      has_calendar_scope: true,
      sync_status: { status: 'idle', last_incremental_sync: new Date().toISOString() },
      calendar_sync_status: { status: 'idle' },
    }]);
  }
  if (request.method === 'GET' && pathname === '/api/emails/labels/all') {
    return writeJson(response, []);
  }
  if (request.method === 'GET' && pathname === '/api/build-version') {
    return writeJson(response, { version: 'generated-qa' });
  }
  if (request.method === 'GET' && pathname === '/api/events/stream') {
    response.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
    });
    response.write(': generated QA stream\n\n');
    request.on('close', () => response.end());
    return;
  }
  if (request.method === 'GET' && pathname === '/api/emails/') {
    const visible = visibleEmails(url.searchParams.get('mailbox') || 'INBOX');
    return writeJson(response, { emails: visible, total: visible.length, page: 1, page_size: 50 });
  }
  if (request.method === 'GET' && pathname === '/api/emails/actions/recent') {
    return writeJson(response, [...operations.values()].slice(-20).reverse());
  }
  if (request.method === 'POST' && pathname === '/api/snoozes') {
    return handleSnoozeCreate(request, response);
  }
  if (request.method === 'GET' && pathname === '/api/snoozes') {
    const state = url.searchParams.get('state') || 'active';
    const limit = Math.max(1, Math.min(200, Number(url.searchParams.get('limit') || 50)));
    const offset = Math.max(0, Number(url.searchParams.get('offset') || 0));
    let items = [...snoozes.values()];
    if (state === 'active') items = items.filter(isActiveSnooze);
    else if (state === 'cancelled') items = items.filter(item => ['cancelled', 'dismissed'].includes(item.state));
    else if (state !== 'all') items = items.filter(item => item.state === state);
    items.sort((a, b) => Date.parse(a.wake_at) - Date.parse(b.wake_at));
    return writeJson(response, {
      items: items.slice(offset, offset + limit).map(snoozeResponse),
      total: items.length,
      limit,
      offset,
    });
  }

  const snoozeItemMatch = pathname.match(/^\/api\/snoozes\/([^/]+)$/);
  if (request.method === 'GET' && snoozeItemMatch) {
    const snooze = snoozes.get(snoozeItemMatch[1]);
    return writeJson(response, snooze ? snoozeResponse(snooze) : { detail: 'Not found' }, snooze ? 200 : 404);
  }

  const snoozeIdempotencyMatch = pathname.match(/^\/api\/snoozes\/by-idempotency\/([^/]+)$/);
  if (request.method === 'GET' && snoozeIdempotencyMatch) {
    const snooze = snoozesByIdempotency.get(snoozeIdempotencyMatch[1]);
    return writeJson(response, snooze ? snoozeResponse(snooze) : { detail: 'Not found' }, snooze ? 200 : 404);
  }

  const rescheduleMatch = pathname.match(/^\/api\/snoozes\/([^/]+)\/reschedule$/);
  if (request.method === 'PATCH' && rescheduleMatch) {
    const snooze = snoozes.get(rescheduleMatch[1]);
    if (!snooze) return writeJson(response, { detail: 'Not found' }, 404);
    const payload = await readJson(request);
    const wakeAt = Date.parse(payload.wake_at);
    if (!isActiveSnooze(snooze) || !Number.isFinite(wakeAt) || wakeAt <= clockMs) {
      return writeJson(response, { detail: { code: 'snooze_conflict', message: 'Choose a future time for an active snooze' } }, 409);
    }
    snooze.wake_at = new Date(wakeAt).toISOString();
    snooze.time_zone = String(payload.time_zone || snooze.time_zone);
    snooze.updated_at = generatedClock().toISOString();
    audit.snooze_reschedules.push({ id: snooze.id, wake_at: snooze.wake_at });
    return writeJson(response, snoozeResponse(snooze));
  }

  const cancelSnoozeMatch = pathname.match(/^\/api\/snoozes\/([^/]+)\/cancel$/);
  if (request.method === 'POST' && cancelSnoozeMatch) {
    const snooze = snoozes.get(cancelSnoozeMatch[1]);
    if (!snooze) return writeJson(response, { detail: 'Not found' }, 404);
    if (isActiveSnooze(snooze)) {
      const email = emails.get(snooze.email_id);
      if (email?.is_trash || email?.is_spam) {
        snooze.state = 'dismissed';
        snooze.status_detail = 'protected_mailbox';
        snooze.dismissed_at = generatedClock().toISOString();
        snooze.updated_at = snooze.dismissed_at;
      } else if (email) {
        applyAction(email, 'unarchive');
        snooze.state = 'cancelled';
        snooze.status_detail = 'cancelled';
        snooze.cancelled_at = generatedClock().toISOString();
        snooze.updated_at = snooze.cancelled_at;
      }
    }
    audit.snooze_cancels.push({ id: snooze.id, at: generatedClock().toISOString() });
    return writeJson(response, snoozeResponse(snooze));
  }

  const returnSnoozeMatch = pathname.match(/^\/api\/snoozes\/([^/]+)\/return-now$/);
  if (request.method === 'POST' && returnSnoozeMatch) {
    const snooze = snoozes.get(returnSnoozeMatch[1]);
    if (!snooze) return writeJson(response, { detail: 'Not found' }, 404);
    const email = emails.get(snooze.email_id);
    if (email?.is_trash || email?.is_spam) {
      snooze.state = 'dismissed';
      snooze.status_detail = 'protected_mailbox';
      snooze.dismissed_at = generatedClock().toISOString();
    } else if (email) {
      applyAction(email, 'unarchive');
      snooze.state = 'returned';
      snooze.status_detail = 'returned_now';
      snooze.returned_at = generatedClock().toISOString();
    } else {
      snooze.state = 'failed';
      snooze.status_detail = 'failed';
      snooze.error_code = 'email_missing';
      snooze.failed_at = generatedClock().toISOString();
    }
    snooze.updated_at = generatedClock().toISOString();
    audit.snooze_returns.push({ id: snooze.id, at: snooze.updated_at, reason: 'return_now' });
    return writeJson(response, snoozeResponse(snooze));
  }

  if (request.method === 'GET' && pathname === '/api/__qa/snooze-audit') {
    return writeJson(response, {
      ...audit,
      clock: generatedClock().toISOString(),
      active_snoozes: [...snoozes.values()].filter(isActiveSnooze).map(snoozeResponse),
      all_snoozes: [...snoozes.values()].map(snoozeResponse),
    });
  }
  if (request.method === 'POST' && pathname === '/api/__qa/clock') {
    const payload = await readJson(request);
    const next = Date.parse(payload.now);
    if (!Number.isFinite(next) || next < clockMs) {
      return writeJson(response, { detail: 'Generated clock only moves forward' }, 422);
    }
    clockMs = next;
    audit.clock_changes.push(generatedClock().toISOString());
    processDueSnoozes();
    return writeJson(response, { now: generatedClock().toISOString() });
  }
  if (request.method === 'POST' && pathname === '/api/__qa/generated-reply') {
    const payload = await readJson(request);
    const snooze = snoozes.get(payload.snooze_id);
    if (!snooze) return writeJson(response, { detail: 'Not found' }, 404);
    snooze.generated_reply_received = true;
    return writeJson(response, { ok: true, snooze_id: snooze.id });
  }
  if (request.method === 'POST' && pathname === '/api/__qa/protected-mailbox') {
    const payload = await readJson(request);
    const email = emails.get(Number(payload.email_id));
    if (!email || !['trash', 'spam'].includes(payload.mailbox)) {
      return writeJson(response, { detail: 'Choose a generated email and protected mailbox' }, 422);
    }
    applyAction(email, payload.mailbox);
    return writeJson(response, { ok: true, email });
  }
  if (request.method === 'POST' && pathname === '/api/emails/actions') {
    return handleActionCreate(request, response);
  }

  const idempotencyMatch = pathname.match(/^\/api\/emails\/actions\/by-idempotency\/([^/]+)$/);
  if (request.method === 'GET' && idempotencyMatch) {
    if (lostLookupResponses > 0) {
      lostLookupResponses -= 1;
      return writeJson(response, { detail: 'Failed to fetch' }, 503);
    }
    const operation = [...operations.values()].find(
      item => item.idempotency_key === idempotencyMatch[1],
    );
    return writeJson(response, operation || { detail: 'Not found' }, operation ? 200 : 404);
  }

  const undoMatch = pathname.match(/^\/api\/emails\/actions\/([^/]+)\/undo$/);
  if (request.method === 'POST' && undoMatch) {
    const operation = operations.get(undoMatch[1]);
    if (!operation) return writeJson(response, { detail: 'Not found' }, 404);
    if (operation.state !== 'staged' || clockMs >= Date.parse(operation.undo_until)) {
      return writeJson(response, { detail: 'The generated undo window has closed' }, 409);
    }
    const before = snapshots.get(undoMatch[1]) || [];
    before.forEach(email => emails.set(email.id, email));
    operation.state = 'cancelled';
    operation.items.forEach(item => {
      item.state = 'cancelled';
      item.cancelled_at = generatedClock().toISOString();
    });
    for (const snooze of snoozes.values()) {
      if (snooze.archive_action_request_id !== operation.request_id || !isActiveSnooze(snooze)) continue;
      snooze.state = 'cancelled';
      snooze.status_detail = 'archive_undone';
      snooze.cancelled_at = generatedClock().toISOString();
      snooze.updated_at = snooze.cancelled_at;
    }
    return writeJson(response, operation);
  }

  const retryMatch = pathname.match(/^\/api\/emails\/actions\/([^/]+)\/retry$/);
  if (request.method === 'POST' && retryMatch) {
    const operation = operations.get(retryMatch[1]);
    if (!operation) return writeJson(response, { detail: 'Not found' }, 404);
    operation.state = 'retry_wait';
    operation.items.filter(item => item.state === 'failed').forEach(item => {
      item.state = 'retry_wait';
      item.next_attempt_at = new Date().toISOString();
    });
    return writeJson(response, operation);
  }

  const actionMatch = pathname.match(/^\/api\/emails\/actions\/([^/]+)$/);
  if (request.method === 'GET' && actionMatch) {
    return writeJson(response, operations.get(actionMatch[1]) || { detail: 'Not found' }, operations.has(actionMatch[1]) ? 200 : 404);
  }

  const emailMatch = pathname.match(/^\/api\/emails\/(\d+)$/);
  if (request.method === 'GET' && emailMatch) {
    const email = emails.get(Number(emailMatch[1]));
    return writeJson(response, email || { detail: 'Not found' }, email ? 200 : 404);
  }

  audit.unknown_routes.push({ method: request.method, pathname });
  return writeJson(response, { detail: `No generated QA route for ${request.method} ${pathname}` }, 404);
}

const server = createServer((request, response) => {
  handleRequest(request, response).catch(error => {
    writeJson(response, { detail: error.message }, 500);
  });
});

server.listen(port, '127.0.0.1', () => {
  process.stdout.write(`Generated mail-action QA API listening on http://127.0.0.1:${port}\n`);
});

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
