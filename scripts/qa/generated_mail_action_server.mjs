#!/usr/bin/env node

// Deterministic, local-only API for manual browser QA. It never reads Gmail,
// production configuration, credentials, or mailbox data. Run this server on
// port 8000, then run the frontend Vite server and open `/?page=inbox`.

import { createServer } from 'node:http';
import { randomUUID } from 'node:crypto';

const port = Number.parseInt(process.env.QA_API_PORT || '8000', 10);
const now = new Date('2026-08-30T14:00:00Z');
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

function applyAction(email, action) {
  const labels = new Set(email.labels);
  if (action === 'mark_read') labels.delete('UNREAD');
  if (action === 'mark_unread') labels.add('UNREAD');
  if (action === 'star') labels.add('STARRED');
  if (action === 'unstar') labels.delete('STARRED');
  if (action === 'archive') labels.delete('INBOX');
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

  if (request.method === 'GET' && pathname === '/api/auth/me') {
    return writeJson(response, { id: 1, username: 'qa-user', is_admin: false });
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
    if (operation.state !== 'staged' || Date.now() >= Date.parse(operation.undo_until)) {
      return writeJson(response, { detail: 'The generated undo window has closed' }, 409);
    }
    const before = snapshots.get(undoMatch[1]) || [];
    before.forEach(email => emails.set(email.id, email));
    operation.state = 'cancelled';
    operation.items.forEach(item => {
      item.state = 'cancelled';
      item.cancelled_at = new Date().toISOString();
    });
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
