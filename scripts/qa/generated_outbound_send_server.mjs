#!/usr/bin/env node

// Deterministic, localhost-only API for durable outbound-send browser QA.
// It uses generated .example.test identities, never reads app configuration or
// mailbox data, never calls Gmail, and keeps every operation in process memory.
//
// Run alongside Vite:
//   QA_API_PORT=8000 node scripts/qa/generated_outbound_send_server.mjs
//   cd frontend && npm run dev -- --host 127.0.0.1
//   open http://127.0.0.1:5173/?page=compose

import { createHash, randomUUID } from 'node:crypto';
import { createServer } from 'node:http';

const host = '127.0.0.1';
const port = boundedInteger(process.env.QA_API_PORT, 8000, 1, 65_535);
const stageWindowMs = boundedInteger(
  process.env.QA_OUTBOUND_STAGE_MS,
  10_000,
  1,
  60_000,
);
const loseFirstCreateResponse = parseBoolean(
  process.env.QA_OUTBOUND_LOSE_FIRST_CREATE_RESPONSE,
  true,
);
const providerOutcome = process.env.QA_OUTBOUND_PROVIDER_OUTCOME === 'fail-first'
  ? 'fail-first'
  : 'confirm';

const generatedNow = new Date('2026-08-30T16:00:00.000Z').toISOString();
const generatedAccount = Object.freeze({
  id: 1,
  email: 'sender@example.test',
  display_name: 'Generated Send QA',
  description: 'Primary generated account',
  is_active: true,
  has_calendar_scope: true,
  sync_status: Object.freeze({
    status: 'idle',
    last_incremental_sync: generatedNow,
  }),
  calendar_sync_status: Object.freeze({ status: 'idle' }),
});

const operationsById = new Map();
const operationsByIdempotency = new Map();
const audit = {
  create_attempts: [],
  persisted_operations: [],
  idempotent_replays: [],
  conflicts: [],
  status_reads: [],
  undo_attempts: [],
  retry_attempts: [],
  provider_sends: [],
  provider_confirmations: [],
  lost_responses: [],
  rejected_payloads: [],
  mutation_attempts: [],
  unknown_routes: [],
};
let auditSequence = 0;
let firstCreateResponseWasLost = false;

function boundedInteger(raw, fallback, minimum, maximum) {
  const parsed = Number.parseInt(raw || '', 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(minimum, Math.min(parsed, maximum));
}

function parseBoolean(raw, fallback) {
  if (raw === undefined || raw === '') return fallback;
  return !['0', 'false', 'no', 'off'].includes(String(raw).trim().toLowerCase());
}

function auditEntry(request, pathname, extra = {}) {
  auditSequence += 1;
  return {
    sequence: auditSequence,
    method: request.method,
    pathname,
    ...extra,
  };
}

function writeJson(response, payload, status = 200, extraHeaders = {}) {
  if (response.destroyed) return;
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
    'Cache-Control': 'no-store',
    ...extraHeaders,
  });
  response.end(body);
}

function outboundError(response, status, code, message) {
  return writeJson(response, { detail: { code, message } }, status);
}

async function readJson(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > 20 * 1024 * 1024) throw new Error('Generated QA payload is too large');
    chunks.push(chunk);
  }
  if (chunks.length === 0) return {};
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
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

function payloadFingerprint(payload) {
  return createHash('sha256')
    .update(JSON.stringify(canonicalize(payload)))
    .digest('hex');
}

function operationSummary(operation) {
  return {
    send_id: operation.send_id,
    idempotency_key: operation.idempotency_key,
    state: operation.state,
    attempt_count: operation.attempt_count,
    provider_send_count: operation._provider_send_count,
    can_undo: operation.can_undo,
    can_retry: operation.can_retry,
  };
}

function responseShape(operation) {
  return {
    send_id: operation.send_id,
    idempotency_key: operation.idempotency_key,
    account_id: operation.account_id,
    source_email_id: operation.source_email_id,
    state: operation.state,
    execute_after: operation.execute_after,
    undo_until: operation.undo_until,
    next_attempt_at: operation.next_attempt_at,
    attempt_count: operation.attempt_count,
    max_attempts: operation.max_attempts,
    can_undo: operation.can_undo,
    can_retry: operation.can_retry,
    provider_message_id: operation.provider_message_id,
    error_code: operation.error_code,
    error_message: operation.error_message,
    created_at: operation.created_at,
    updated_at: operation.updated_at,
    sent_at: operation.sent_at,
    failed_at: operation.failed_at,
    cancelled_at: operation.cancelled_at,
  };
}

function isUuid(value) {
  return typeof value === 'string'
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

function mailboxAddress(value) {
  if (typeof value !== 'string') return '';
  const match = value.trim().match(/(?:<([^<>]+)>|([^\s<>]+))$/);
  return (match?.[1] || match?.[2] || '').trim().toLowerCase();
}

function isGeneratedAddress(value) {
  const address = mailboxAddress(value);
  return /^[^@\s]+@(?:[^@\s.]+\.)*example\.test$/i.test(address);
}

function validateGeneratedPayload(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return 'The send payload must be an object';
  }
  if (!isUuid(payload.idempotency_key)) return 'A UUID idempotency_key is required';
  if (payload.account_id !== generatedAccount.id) return 'Only the generated account is available';
  if (!Array.isArray(payload.to) || payload.to.length === 0) {
    return 'At least one generated To recipient is required';
  }
  for (const field of ['to', 'cc', 'bcc']) {
    if (!Array.isArray(payload[field] || [])) return `${field} must be an array`;
    if (!(payload[field] || []).every(isGeneratedAddress)) {
      return `${field} accepts only .example.test addresses`;
    }
  }
  if (payload.is_draft === true) return 'The send endpoint does not accept drafts';
  if (payload.source_email_id !== undefined && payload.source_email_id !== null) {
    return 'The generated Compose fixture does not expose source messages';
  }
  if (payload.attachments !== undefined && !Array.isArray(payload.attachments)) {
    return 'attachments must be an array';
  }
  return null;
}

function refreshAuthority(operation) {
  const undoOpen = operation.state === 'staged'
    && Date.now() < Date.parse(operation.undo_until);
  operation.can_undo = undoOpen;
  operation.can_retry = operation.state === 'failed'
    && operation.attempt_count < operation.max_attempts;
  return operation;
}

function stageOperation(payload) {
  const createdAt = new Date();
  const executeAfter = new Date(createdAt.getTime() + stageWindowMs);
  const operation = {
    send_id: randomUUID(),
    idempotency_key: payload.idempotency_key,
    account_id: payload.account_id,
    source_email_id: payload.source_email_id ?? null,
    state: 'staged',
    execute_after: executeAfter.toISOString(),
    undo_until: executeAfter.toISOString(),
    next_attempt_at: executeAfter.toISOString(),
    attempt_count: 0,
    max_attempts: 3,
    can_undo: true,
    can_retry: false,
    provider_message_id: null,
    error_code: null,
    error_message: null,
    created_at: createdAt.toISOString(),
    updated_at: createdAt.toISOString(),
    sent_at: null,
    failed_at: null,
    cancelled_at: null,
    _fingerprint: payloadFingerprint(payload),
    _provider_send_count: 0,
    _failed_once: false,
  };
  operationsById.set(operation.send_id, operation);
  operationsByIdempotency.set(operation.idempotency_key, operation);
  return operation;
}

function advanceOnStatusPoll(request, pathname, operation) {
  refreshAuthority(operation);
  const now = new Date();
  const dueAt = Date.parse(operation.next_attempt_at || operation.execute_after);

  if (
    ['staged', 'retry_wait'].includes(operation.state)
    && Number.isFinite(dueAt)
    && now.getTime() >= dueAt
  ) {
    operation.state = 'processing';
    operation.can_undo = false;
    operation.can_retry = false;
    operation.attempt_count += 1;
    operation._provider_send_count += 1;
    operation.next_attempt_at = null;
    operation.updated_at = now.toISOString();
    const willFail = providerOutcome === 'fail-first' && !operation._failed_once;
    audit.provider_sends.push(auditEntry(request, pathname, {
      send_id: operation.send_id,
      attempt_count: operation.attempt_count,
      provider_send_count: operation._provider_send_count,
      simulated_outcome: willFail ? 'failed' : 'accepted',
    }));

    if (willFail) {
      operation._failed_once = true;
      operation.state = 'failed';
      operation.error_code = 'generated_provider_timeout';
      operation.error_message = 'Generated provider timeout; no external request was made.';
      operation.failed_at = now.toISOString();
      operation.can_retry = true;
    }
  } else if (operation.state === 'processing') {
    operation.state = 'sent';
    operation.provider_message_id = `generated-provider-${operation.send_id}`;
    operation.sent_at = now.toISOString();
    operation.updated_at = now.toISOString();
    operation.can_undo = false;
    operation.can_retry = false;
    audit.provider_confirmations.push(auditEntry(request, pathname, {
      send_id: operation.send_id,
      provider_send_count: operation._provider_send_count,
      provider_message_id: operation.provider_message_id,
    }));
  }

  return refreshAuthority(operation);
}

function recordStatusRead(request, pathname, kind, operation = null) {
  audit.status_reads.push(auditEntry(request, pathname, {
    kind,
    send_id: operation?.send_id ?? null,
    state: operation?.state ?? null,
  }));
}

function loseCreateResponse(request, response, operation) {
  firstCreateResponseWasLost = true;
  audit.lost_responses.push(auditEntry(request, '/api/compose/send', {
    send_id: operation.send_id,
    idempotency_key: operation.idempotency_key,
    persisted_before_disconnect: true,
  }));
  response.socket?.destroy();
}

async function handleCreate(request, response, pathname) {
  audit.mutation_attempts.push(auditEntry(request, pathname, {
    expected: true,
    kind: 'create_outbound_send',
  }));

  let payload;
  try {
    payload = await readJson(request);
  } catch (error) {
    audit.rejected_payloads.push(auditEntry(request, pathname, {
      reason: error.message,
    }));
    return outboundError(response, 422, 'outbound_invalid', error.message);
  }

  const validationError = validateGeneratedPayload(payload);
  const fingerprint = payloadFingerprint(payload);
  audit.create_attempts.push(auditEntry(request, pathname, {
    idempotency_key: typeof payload?.idempotency_key === 'string'
      ? payload.idempotency_key
      : null,
    payload_fingerprint: fingerprint,
    accepted: !validationError,
  }));
  if (validationError) {
    audit.rejected_payloads.push(auditEntry(request, pathname, {
      reason: validationError,
      payload_fingerprint: fingerprint,
    }));
    return outboundError(response, 422, 'outbound_invalid', validationError);
  }

  const existing = operationsByIdempotency.get(payload.idempotency_key);
  if (existing) {
    if (existing._fingerprint !== fingerprint) {
      audit.conflicts.push(auditEntry(request, pathname, {
        send_id: existing.send_id,
        idempotency_key: existing.idempotency_key,
        original_fingerprint: existing._fingerprint,
        conflicting_fingerprint: fingerprint,
      }));
      return outboundError(
        response,
        409,
        'outbound_conflict',
        'This idempotency key is already bound to a different generated payload',
      );
    }
    refreshAuthority(existing);
    audit.idempotent_replays.push(auditEntry(request, pathname, operationSummary(existing)));
    return writeJson(response, responseShape(existing), 202);
  }

  const operation = stageOperation(payload);
  audit.persisted_operations.push(auditEntry(request, pathname, {
    ...operationSummary(operation),
    payload_fingerprint: operation._fingerprint,
    undo_window_ms: stageWindowMs,
  }));
  if (loseFirstCreateResponse && !firstCreateResponseWasLost) {
    return loseCreateResponse(request, response, operation);
  }
  return writeJson(response, responseShape(operation), 202);
}

function handleAudit(response) {
  const providerSendCount = audit.provider_sends.length;
  return writeJson(response, {
    fixture: 'generated-outbound-send',
    fixture_domains: ['example.test'],
    localhost_only: true,
    external_provider_calls: 0,
    configuration: {
      stage_window_ms: stageWindowMs,
      lose_first_create_response: loseFirstCreateResponse,
      provider_outcome: providerOutcome,
    },
    counts: {
      operations: operationsById.size,
      create_attempts: audit.create_attempts.length,
      persisted_operations: audit.persisted_operations.length,
      idempotent_replays: audit.idempotent_replays.length,
      conflicts: audit.conflicts.length,
      status_reads: audit.status_reads.length,
      undo_attempts: audit.undo_attempts.length,
      retry_attempts: audit.retry_attempts.length,
      provider_sends: providerSendCount,
      provider_confirmations: audit.provider_confirmations.length,
      lost_responses: audit.lost_responses.length,
      rejected_payloads: audit.rejected_payloads.length,
      mutation_attempts: audit.mutation_attempts.length,
      unexpected_mutations: audit.mutation_attempts.filter(item => !item.expected).length,
      unknown_routes: audit.unknown_routes.length,
    },
    provider_send_count: providerSendCount,
    operations: [...operationsById.values()].map(operation =>
      operationSummary(refreshAuthority(operation))
    ),
    ...audit,
  });
}

function handleGeneratedGet(request, response, url) {
  const { pathname } = url;
  if (pathname === '/api/qa/audit') return handleAudit(response);
  if (pathname === '/api/auth/me') {
    return writeJson(response, { id: 1, username: 'generated-send-qa', is_admin: false });
  }
  if (pathname === '/api/auth/ui-preferences') {
    return writeJson(response, { thread_order: 'asc', theme: 'default', color_scheme: 'light' });
  }
  if (pathname === '/api/auth/keyboard-shortcuts') {
    return writeJson(response, { shortcuts: {} });
  }
  if (pathname === '/api/accounts/') return writeJson(response, [generatedAccount]);
  if (pathname === '/api/build-version') {
    return writeJson(response, { version: 'generated-outbound-send-qa' });
  }
  if (pathname === '/api/events/stream') {
    response.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
    });
    response.write(': generated outbound-send QA stream\n\n');
    request.on('close', () => response.end());
    return;
  }
  if (pathname === '/api/emails/labels/all') return writeJson(response, []);
  if (pathname === '/api/emails/actions/recent') return writeJson(response, []);
  if (pathname === '/api/emails/') {
    return writeJson(response, { emails: [], total: 0, page: 1, page_size: 50 });
  }

  if (pathname === '/api/compose/sends/recent') {
    const requestedLimit = boundedInteger(url.searchParams.get('limit'), 20, 1, 100);
    const recent = [...operationsById.values()]
      .sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at))
      .slice(0, requestedLimit);
    for (const operation of recent) refreshAuthority(operation);
    recordStatusRead(request, pathname, 'recent');
    return writeJson(response, recent.map(responseShape));
  }

  const byIdempotencyMatch = pathname.match(
    /^\/api\/compose\/sends\/by-idempotency\/([^/]+)$/,
  );
  if (byIdempotencyMatch) {
    const key = decodeURIComponent(byIdempotencyMatch[1]);
    const operation = operationsByIdempotency.get(key);
    if (!operation) {
      recordStatusRead(request, pathname, 'by_idempotency');
      return outboundError(response, 404, 'outbound_not_found', 'Generated send not found');
    }
    advanceOnStatusPoll(request, pathname, operation);
    recordStatusRead(request, pathname, 'by_idempotency', operation);
    return writeJson(response, responseShape(operation));
  }

  const getMatch = pathname.match(/^\/api\/compose\/sends\/([^/]+)$/);
  if (getMatch) {
    const sendId = decodeURIComponent(getMatch[1]);
    const operation = operationsById.get(sendId);
    if (!operation) {
      recordStatusRead(request, pathname, 'by_id');
      return outboundError(response, 404, 'outbound_not_found', 'Generated send not found');
    }
    advanceOnStatusPoll(request, pathname, operation);
    recordStatusRead(request, pathname, 'by_id', operation);
    return writeJson(response, responseShape(operation));
  }

  audit.unknown_routes.push(auditEntry(request, pathname));
  return writeJson(response, { detail: `No generated QA route for GET ${pathname}` }, 404);
}

function undoOperation(request, response, pathname, sendId) {
  audit.mutation_attempts.push(auditEntry(request, pathname, {
    expected: true,
    kind: 'undo_outbound_send',
  }));
  const operation = operationsById.get(sendId);
  audit.undo_attempts.push(auditEntry(request, pathname, {
    send_id: sendId,
    prior_state: operation?.state ?? null,
  }));
  if (!operation) {
    return outboundError(response, 404, 'outbound_not_found', 'Generated send not found');
  }
  refreshAuthority(operation);
  if (!operation.can_undo) {
    return outboundError(response, 409, 'outbound_conflict', 'The generated Undo Send window has closed');
  }
  const cancelledAt = new Date().toISOString();
  operation.state = 'cancelled';
  operation.cancelled_at = cancelledAt;
  operation.updated_at = cancelledAt;
  operation.next_attempt_at = null;
  operation.can_undo = false;
  operation.can_retry = false;
  return writeJson(response, responseShape(operation));
}

function retryOperation(request, response, pathname, sendId) {
  audit.mutation_attempts.push(auditEntry(request, pathname, {
    expected: true,
    kind: 'retry_outbound_send',
  }));
  const operation = operationsById.get(sendId);
  audit.retry_attempts.push(auditEntry(request, pathname, {
    send_id: sendId,
    prior_state: operation?.state ?? null,
  }));
  if (!operation) {
    return outboundError(response, 404, 'outbound_not_found', 'Generated send not found');
  }
  refreshAuthority(operation);
  if (!operation.can_retry) {
    return outboundError(response, 409, 'outbound_conflict', 'This generated send cannot be retried');
  }
  const retryAt = new Date().toISOString();
  operation.state = 'retry_wait';
  operation.next_attempt_at = retryAt;
  operation.updated_at = retryAt;
  operation.error_code = null;
  operation.error_message = null;
  operation.failed_at = null;
  operation.can_undo = false;
  operation.can_retry = false;
  return writeJson(response, responseShape(operation));
}

async function handleRequest(request, response) {
  const url = new URL(request.url, `http://${host}:${port}`);
  const { pathname } = url;

  if (request.method === 'GET') return handleGeneratedGet(request, response, url);
  if (request.method === 'POST' && pathname === '/api/compose/send') {
    return handleCreate(request, response, pathname);
  }

  const undoMatch = pathname.match(/^\/api\/compose\/sends\/([^/]+)\/undo$/);
  if (request.method === 'POST' && undoMatch) {
    return undoOperation(
      request,
      response,
      pathname,
      decodeURIComponent(undoMatch[1]),
    );
  }

  const retryMatch = pathname.match(/^\/api\/compose\/sends\/([^/]+)\/retry$/);
  if (request.method === 'POST' && retryMatch) {
    return retryOperation(
      request,
      response,
      pathname,
      decodeURIComponent(retryMatch[1]),
    );
  }

  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method)) {
    audit.mutation_attempts.push(auditEntry(request, pathname, {
      expected: false,
      kind: 'unexpected_mutation',
    }));
    return writeJson(
      response,
      { detail: 'Generated outbound-send QA permits only its in-memory send lifecycle' },
      405,
      { Allow: 'GET, POST' },
    );
  }

  audit.unknown_routes.push(auditEntry(request, pathname));
  return writeJson(response, { detail: `Unsupported method ${request.method}` }, 405, {
    Allow: 'GET, POST',
  });
}

const server = createServer((request, response) => {
  handleRequest(request, response).catch(error => {
    if (!response.destroyed) writeJson(response, { detail: error.message }, 500);
  });
});

server.listen(port, host, () => {
  process.stdout.write(
    `Generated outbound-send QA API listening on http://${host}:${port} `
      + `(stage=${stageWindowMs}ms, lost-first=${loseFirstCreateResponse}, `
      + `provider=${providerOutcome})\n`,
  );
});

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
