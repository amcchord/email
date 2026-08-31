#!/usr/bin/env node

// Deterministic, generated-only Attachments workspace API. This fixture binds
// only to loopback, keeps all state in memory, accepts only reserved
// .example.test identities, and has no provider, production, environment, or
// outbound-network integration.

import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import { createServer } from 'node:http';
import { dirname, extname, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const GENERATED_ATTACHMENTS_HOST = '127.0.0.1';
const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const frontendDist = resolve(scriptDirectory, '../../frontend/dist');
const STATIC_MIME_TYPES = Object.freeze({
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.ico': 'image/x-icon',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.webp': 'image/webp',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
});

const GENERATED_USERS = Object.freeze({
  'generated-a': Object.freeze({
    id: 7101,
    username: 'attachments-user-a@example.test',
    is_admin: false,
    account_ids: Object.freeze([8101, 8102]),
  }),
  'generated-b': Object.freeze({
    id: 7201,
    username: 'attachments-user-b@example.test',
    is_admin: false,
    account_ids: Object.freeze([8201]),
  }),
});

const GENERATED_ACCOUNTS = Object.freeze({
  8101: Object.freeze({
    id: 8101,
    email: 'attachments-primary@example.test',
    display_name: 'Generated Attachments Primary',
    short_label: 'Primary',
    is_active: true,
  }),
  8102: Object.freeze({
    id: 8102,
    email: 'attachments-secondary@example.test',
    display_name: 'Generated Attachments Secondary',
    short_label: 'Secondary',
    is_active: true,
  }),
  8201: Object.freeze({
    id: 8201,
    email: 'attachments-user-b@example.test',
    display_name: 'Generated Attachments User B',
    short_label: 'User B',
    is_active: true,
  }),
});

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

const INTERNAL_ITEMS = Object.freeze([
  Object.freeze({
    account_id: 8101,
    attachment_id: 9101,
    email_id: 10101,
    filename: 'generated-quarterly-report.pdf',
    content_type: 'application/pdf',
    size_bytes: 85,
    message_date: '2026-08-30T16:00:00.000Z',
    sender_name: 'Generated Reports',
    sender_address: 'reports@example.test',
    subject: 'Generated quarterly attachment',
    is_sent: false,
    kind: 'document',
    direction: 'received',
  }),
  Object.freeze({
    account_id: 8101,
    attachment_id: 9102,
    email_id: 10102,
    filename: '<img src=x onerror=generated-attachment-qa>.png',
    content_type: 'image/png',
    size_bytes: 68,
    message_date: '2026-08-30T15:30:00.000Z',
    sender_name: '<svg onload=generated-attachment-sender>',
    sender_address: 'malicious-metadata@example.test',
    subject: '<script>generated attachment subject</script>',
    is_sent: false,
    kind: 'image',
    direction: 'received',
  }),
  Object.freeze({
    account_id: 8101,
    attachment_id: 9103,
    email_id: 10103,
    filename: 'generated-sent-plan.txt',
    content_type: 'text/plain',
    size_bytes: 62,
    message_date: '2026-08-30T14:45:00.000Z',
    sender_name: 'Attachments User A',
    sender_address: 'attachments-user-a@example.test',
    subject: 'Generated sent attachment',
    is_sent: true,
    kind: 'document',
    direction: 'sent',
  }),
  Object.freeze({
    account_id: 8101,
    attachment_id: 9104,
    email_id: 10104,
    filename: 'generated-bundle.zip',
    content_type: 'application/zip',
    size_bytes: 4096,
    message_date: '2026-08-30T13:00:00.000Z',
    sender_name: 'Generated Archive',
    sender_address: 'archive@example.test',
    subject: 'Generated archive attachment',
    is_sent: false,
    kind: 'archive',
    direction: 'received',
  }),
  Object.freeze({
    account_id: 8102,
    attachment_id: 9201,
    email_id: 10201,
    filename: 'generated-quarterly-report.pdf',
    content_type: 'application/pdf',
    size_bytes: 714,
    message_date: '2026-08-30T15:55:00.000Z',
    sender_name: 'Generated Secondary Reports',
    sender_address: 'secondary-reports@example.test',
    subject: 'Generated secondary attachment',
    is_sent: false,
    kind: 'document',
    direction: 'received',
  }),
  Object.freeze({
    account_id: 8102,
    attachment_id: 9202,
    email_id: 10202,
    filename: 'generated-unknown-metadata.bin',
    content_type: 'application/octet-stream',
    size_bytes: null,
    message_date: null,
    sender_name: null,
    sender_address: null,
    subject: null,
    is_sent: false,
    kind: 'other',
    direction: 'received',
  }),
  Object.freeze({
    account_id: 8201,
    attachment_id: 9301,
    email_id: 10301,
    filename: 'generated-quarterly-report.pdf',
    content_type: 'application/pdf',
    size_bytes: 816,
    message_date: '2026-08-30T15:58:00.000Z',
    sender_name: 'Generated User B Reports',
    sender_address: 'user-b-reports@example.test',
    subject: 'Generated user B private attachment',
    is_sent: false,
    kind: 'document',
    direction: 'received',
  }),
]);

const GENERATED_PDF = Buffer.from(
  '%PDF-1.4\n% generated attachment bytes only\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n',
  'utf8',
);
const GENERATED_TEXT = Buffer.from(
  'Generated attachment bytes only. No mailbox or provider data.\n',
  'utf8',
);
const GENERATED_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
  'base64',
);

const GENERATED_BYTES = new Map([
  ['10101:9101', Object.freeze({ bytes: GENERATED_PDF, content_type: 'application/pdf' })],
  ['10102:9102', Object.freeze({ bytes: GENERATED_PNG, content_type: 'image/png' })],
  ['10103:9103', Object.freeze({ bytes: GENERATED_TEXT, content_type: 'text/plain; charset=utf-8' })],
]);

const REQUEST_KEYS = Object.freeze([
  'account_id',
  'cursor',
  'direction',
  'kind',
  'page_size',
  'query',
]);
const KINDS = new Set(['all', 'document', 'image', 'archive', 'other']);
const DIRECTIONS = new Set(['all', 'received', 'sent']);
const EMAIL_PATTERN = /[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+/giu;
const CONTROL_PATTERN = /[\u0000-\u001f\u007f]/u;
const CURSOR_PREFIX = 'generated-attachment-offset:';
const ALLOWED_SCENARIOS = new Set([
  'normal',
  'empty',
  'held',
  'fail-once',
  'mixed-account-response',
]);

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function assertGeneratedAddresses(value, path = 'fixture') {
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertGeneratedAddresses(item, `${path}[${index}]`));
    return;
  }
  if (value && typeof value === 'object') {
    for (const [key, item] of Object.entries(value)) {
      assertGeneratedAddresses(item, `${path}.${key}`);
    }
    return;
  }
  if (typeof value !== 'string') return;
  for (const match of value.matchAll(EMAIL_PATTERN)) {
    if (!match[0].toLowerCase().endsWith('@example.test')) {
      throw new Error(`Non-generated address rejected at ${path}`);
    }
  }
}

assertGeneratedAddresses(GENERATED_USERS);
assertGeneratedAddresses(GENERATED_ACCOUNTS);
assertGeneratedAddresses(INTERNAL_ITEMS);

function freshCounters() {
  return {
    auth_rejections: 0,
    ownership_rejections: 0,
    validation_errors: 0,
    non_generated_rejections: 0,
    query_requests: 0,
    navigation_reads: 0,
    held_queries: 0,
    transient_failures: 0,
    mixed_account_responses: 0,
    preview_reads: 0,
    download_reads: 0,
    generated_local_byte_reads: 0,
    generated_local_bytes_served: 0,
    provider_reads: 0,
    provider_writes: 0,
    mail_mutations: 0,
    calendar_mutations: 0,
    unexpected_writes: 0,
    external_network_calls: 0,
  };
}

function writeJson(response, payload, status = 200) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
    'Cache-Control': 'private, no-store',
    'X-Content-Type-Options': 'nosniff',
  });
  response.end(body);
}

function writeBytes(response, payload, { download = false, preview = false } = {}) {
  const mime = payload.content_type.split(';', 1)[0].trim().toLowerCase();
  const previewKind = mime === 'application/pdf'
    ? 'pdf'
    : (mime.startsWith('image/') ? 'image' : (mime === 'text/plain' ? 'text' : null));
  const headers = {
    'Content-Type': payload.content_type,
    'Content-Length': payload.bytes.length,
    'Content-Disposition': download
      ? 'attachment; filename="generated-attachment.bin"'
      : 'inline; filename="generated-attachment.bin"',
    'Cache-Control': 'private, no-store',
    'X-Content-Type-Options': 'nosniff',
    'Cross-Origin-Resource-Policy': 'same-origin',
    'Content-Security-Policy': "sandbox; default-src 'none'; script-src 'none'; object-src 'none'",
  };
  if (preview && previewKind) {
    headers['X-Attachment-Preview-Kind'] = previewKind;
    headers['X-Attachment-Preview-Truncated'] = 'false';
  }
  response.writeHead(200, headers);
  response.end(payload.bytes);
}

async function readJson(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > 16_384) {
      throw Object.assign(new Error('Request body is too large'), { status: 422 });
    }
    chunks.push(chunk);
  }
  if (chunks.length === 0) return {};
  let payload;
  try {
    payload = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    throw Object.assign(new Error('Request body must be valid JSON'), { status: 422 });
  }
  try {
    assertGeneratedAddresses(payload, 'request');
  } catch {
    throw Object.assign(new Error('Only .example.test addresses are accepted'), {
      status: 422,
      nonGenerated: true,
    });
  }
  return payload;
}

function projectItem(item) {
  return Object.fromEntries(ITEM_KEYS.map(key => [key, item[key]]));
}

function encodeCursor(offset) {
  return Buffer.from(`${CURSOR_PREFIX}${offset}`, 'utf8').toString('base64url');
}

function decodeCursor(cursor) {
  if (cursor === null) return 0;
  if (typeof cursor !== 'string' || cursor.length > 2048) throw new Error('cursor is invalid');
  let decoded;
  try {
    decoded = Buffer.from(cursor, 'base64url').toString('utf8');
  } catch {
    throw new Error('cursor is invalid');
  }
  if (!decoded.startsWith(CURSOR_PREFIX)) throw new Error('cursor is invalid');
  const offset = Number(decoded.slice(CURSOR_PREFIX.length));
  if (!Number.isSafeInteger(offset) || offset < 1) throw new Error('cursor is invalid');
  return offset;
}

function validateQueryPayload(payload, ownsAccount) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new Error('Request body must be an object');
  }
  if (JSON.stringify(Object.keys(payload).sort()) !== JSON.stringify(REQUEST_KEYS)) {
    throw new Error(`Request fields must be exactly: ${REQUEST_KEYS.join(', ')}`);
  }
  if (!Number.isSafeInteger(payload.account_id) || payload.account_id < 1) {
    throw new Error('account_id must be a positive integer');
  }
  if (!ownsAccount(payload.account_id)) {
    throw Object.assign(new Error('Account not found'), { status: 404, ownership: true });
  }
  if (
    typeof payload.query !== 'string'
    || payload.query.length > 256
    || CONTROL_PATTERN.test(payload.query)
  ) {
    throw new Error('query must be at most 256 printable characters');
  }
  if (!KINDS.has(payload.kind)) throw new Error('kind is invalid');
  if (!DIRECTIONS.has(payload.direction)) throw new Error('direction is invalid');
  if (!Number.isSafeInteger(payload.page_size) || payload.page_size < 1 || payload.page_size > 50) {
    throw new Error('page_size must be between 1 and 50');
  }
  return {
    accountId: payload.account_id,
    query: payload.query.trim().replace(/\s+/gu, ' ').toLocaleLowerCase('en-US'),
    kind: payload.kind,
    direction: payload.direction,
    offset: decodeCursor(payload.cursor),
    pageSize: payload.page_size,
  };
}

function matchesQuery(item, query) {
  if (!query) return true;
  return [item.filename, item.sender_name, item.sender_address, item.subject]
    .filter(value => typeof value === 'string')
    .some(value => value.toLocaleLowerCase('en-US').includes(query));
}

function messageTimestamp(item) {
  if (item.message_date === null) return Number.NEGATIVE_INFINITY;
  const value = Date.parse(item.message_date);
  return Number.isFinite(value) ? value : Number.NEGATIVE_INFINITY;
}

function selectItems(request) {
  return INTERNAL_ITEMS
    .filter(item => item.account_id === request.accountId)
    .filter(item => request.kind === 'all' || item.kind === request.kind)
    .filter(item => request.direction === 'all' || item.direction === request.direction)
    .filter(item => matchesQuery(item, request.query))
    .sort((left, right) => (
      messageTimestamp(right) - messageTimestamp(left)
      || right.attachment_id - left.attachment_id
    ));
}

function routeKey(method, pathname) {
  return `${method} ${pathname}`;
}

async function existingFile(pathname) {
  try {
    const fileStat = await stat(pathname);
    return fileStat.isFile() ? fileStat : null;
  } catch {
    return null;
  }
}

async function serveFrontend(response, url) {
  let decodedPath;
  try {
    decodedPath = decodeURIComponent(url.pathname);
  } catch {
    return writeJson(response, { detail: 'Malformed generated QA URL' }, 400);
  }
  const relativePath = decodedPath === '/' ? 'index.html' : decodedPath.replace(/^\/+/, '');
  let candidate = resolve(frontendDist, relativePath);
  if (candidate !== frontendDist && !candidate.startsWith(`${frontendDist}${sep}`)) {
    return writeJson(response, { detail: 'Generated QA static path not found' }, 404);
  }
  let fileStat = await existingFile(candidate);
  if (!fileStat && !extname(relativePath)) {
    candidate = resolve(frontendDist, 'index.html');
    fileStat = await existingFile(candidate);
  }
  if (!fileStat) return writeJson(response, { detail: 'Generated QA static file not found' }, 404);
  response.writeHead(200, {
    'Content-Type': STATIC_MIME_TYPES[extname(candidate).toLowerCase()] || 'application/octet-stream',
    'Content-Length': fileStat.size,
    'Cache-Control': 'no-store',
  });
  const stream = createReadStream(candidate);
  stream.on('error', () => {
    if (!response.headersSent) writeJson(response, { detail: 'Could not read generated QA static file' }, 500);
    else response.destroy();
  });
  stream.pipe(response);
}

export function createGeneratedAttachmentsFixture() {
  let currentUserKey = 'generated-a';
  let sessionGeneration = 1;
  let scenario = 'normal';
  let counters = freshCounters();
  let auditRequests = [];
  let held = [];
  let failRemaining = 0;
  let holdRemaining = 0;

  function currentUser() {
    return GENERATED_USERS[currentUserKey] || null;
  }

  function ownsAccount(accountId, userKey = currentUserKey) {
    return GENERATED_USERS[userKey]?.account_ids.includes(accountId) || false;
  }

  function record(action, status, extra = {}) {
    auditRequests.push({
      sequence: auditRequests.length + 1,
      action,
      status,
      user: currentUserKey,
      session_generation: sessionGeneration,
      ...extra,
    });
  }

  function authRequired(response, action) {
    if (currentUser()) return true;
    counters.auth_rejections += 1;
    record(action, 401);
    writeJson(response, { detail: 'Not authenticated' }, 401);
    return false;
  }

  function reject(response, action, error) {
    const status = error.status || 422;
    if (error.ownership) counters.ownership_rejections += 1;
    else {
      counters.validation_errors += 1;
      if (error.nonGenerated) counters.non_generated_rejections += 1;
    }
    record(action, status);
    writeJson(response, { detail: error.message }, status);
  }

  function queryResponse(queryRequest, userKey, selectedScenario) {
    const allItems = selectedScenario === 'empty' ? [] : selectItems(queryRequest);
    const pageItems = allItems.slice(
      queryRequest.offset,
      queryRequest.offset + queryRequest.pageSize,
    );
    if (selectedScenario === 'mixed-account-response' && pageItems.length > 0) {
      const foreignItem = INTERNAL_ITEMS.find(item => item.account_id === 8201);
      pageItems.push(foreignItem);
      counters.mixed_account_responses += 1;
    }
    const nextOffset = queryRequest.offset + queryRequest.pageSize;
    const hasMore = nextOffset < allItems.length;
    const payload = {
      account_id: queryRequest.accountId,
      items: pageItems.map(projectItem),
      next_cursor: hasMore ? encodeCursor(nextOffset) : null,
      has_more: hasMore,
    };
    // This guard makes normal fixture corruption fail closed while retaining
    // the one explicit malicious-response scenario for client rejection QA.
    if (selectedScenario !== 'mixed-account-response') {
      if (!payload.items.every(item => ownsAccount(item.account_id, userKey))) {
        throw new Error('Generated fixture attempted to return a foreign account');
      }
    }
    assertGeneratedAddresses(payload);
    return payload;
  }

  function reset(nextScenario = 'normal', nextUser = 'generated-a') {
    if (!ALLOWED_SCENARIOS.has(nextScenario)) throw new Error('scenario is invalid');
    if (nextUser !== 'anonymous' && !GENERATED_USERS[nextUser]) {
      throw new Error('current_user must be a generated fixture identity');
    }
    for (const pending of held.splice(0)) {
      writeJson(pending.response, { detail: 'Generated fixture reset' }, 409);
    }
    currentUserKey = nextUser;
    sessionGeneration += 1;
    scenario = nextScenario;
    counters = freshCounters();
    auditRequests = [];
    failRemaining = nextScenario === 'fail-once' ? 1 : 0;
    holdRemaining = nextScenario === 'held' ? 1 : 0;
  }

  async function handleControl(request, response, pathname) {
    if (request.method === 'GET' && pathname === '/__qa/audit') {
      return writeJson(response, {
        fixture: 'generated-attachments',
        localhost_only: true,
        fixture_domains: ['example.test'],
        current_user: currentUserKey,
        session_generation: sessionGeneration,
        scenario,
        pending_held_queries: held.length,
        allowed_routes: [
          'GET /api/auth/me',
          'GET /api/accounts/',
          'POST /api/attachments/query',
          'GET /api/emails/{email_id}',
          'GET /api/emails/{email_id}/attachments/{attachment_id}/preview',
          'GET /api/emails/{email_id}/attachments/{attachment_id}/download',
        ],
        counters: clone(counters),
        requests: clone(auditRequests),
      });
    }
    if (request.method === 'POST' && pathname === '/__qa/reset') {
      try {
        const payload = await readJson(request);
        reset(payload.scenario ?? 'normal', payload.current_user ?? 'generated-a');
        return writeJson(response, { reset: true, scenario, current_user: currentUserKey });
      } catch (error) {
        if (error.nonGenerated) counters.non_generated_rejections += 1;
        counters.validation_errors += 1;
        return writeJson(response, { detail: error.message }, error.status || 422);
      }
    }
    if (request.method === 'POST' && pathname === '/__qa/session') {
      try {
        const payload = await readJson(request);
        const nextUser = payload.current_user;
        if (nextUser !== 'anonymous' && !GENERATED_USERS[nextUser]) {
          throw new Error('current_user must be a generated fixture identity');
        }
        currentUserKey = nextUser;
        sessionGeneration += 1;
        return writeJson(response, { current_user: currentUserKey, session_generation: sessionGeneration });
      } catch (error) {
        if (error.nonGenerated) counters.non_generated_rejections += 1;
        counters.validation_errors += 1;
        return writeJson(response, { detail: error.message }, error.status || 422);
      }
    }
    if (request.method === 'POST' && pathname === '/__qa/release') {
      const pending = held.splice(0);
      for (const item of pending) {
        try {
          const payload = queryResponse(item.queryRequest, item.userKey, item.scenario);
          record('attachments.query.held-release', 200, {
            captured_user: item.userKey,
            captured_generation: item.sessionGeneration,
          });
          writeJson(item.response, payload);
        } catch (error) {
          writeJson(item.response, { detail: 'Generated fixture failure' }, 500);
        }
      }
      return writeJson(response, { released: pending.length });
    }
    return false;
  }

  async function handle(request, response) {
    const url = new URL(request.url || '/', 'http://127.0.0.1');
    const { pathname } = url;

    if (!pathname.startsWith('/api/') && !pathname.startsWith('/__qa/')) {
      if (!['GET', 'HEAD'].includes(request.method || 'GET')) {
        counters.unexpected_writes += 1;
        return writeJson(response, { detail: 'Generated fixture rejects mutations' }, 405);
      }
      return serveFrontend(response, url);
    }

    if (pathname.startsWith('/__qa/')) {
      const handled = await handleControl(request, response, pathname);
      if (handled !== false) return;
      return writeJson(response, { detail: 'Generated QA route not found' }, 404);
    }

    if (request.method === 'GET' && pathname === '/api/auth/me') {
      if (!authRequired(response, 'auth.me')) return;
      const user = currentUser();
      return writeJson(response, { id: user.id, username: user.username, is_admin: user.is_admin });
    }

    if (request.method === 'GET' && pathname === '/api/build-version') {
      return writeJson(response, { version: 'generated-attachments-qa' });
    }

    if (request.method === 'GET' && pathname === '/api/accounts/') {
      if (!authRequired(response, 'accounts.list')) return;
      return writeJson(
        response,
        currentUser().account_ids.map(accountId => clone(GENERATED_ACCOUNTS[accountId])),
      );
    }

    if (request.method === 'POST' && pathname === '/api/attachments/query') {
      if (!authRequired(response, 'attachments.query')) return;
      const capturedUserKey = currentUserKey;
      const capturedGeneration = sessionGeneration;
      const capturedScenario = scenario;
      let queryRequest;
      try {
        const payload = await readJson(request);
        queryRequest = validateQueryPayload(
          payload,
          accountId => ownsAccount(accountId, capturedUserKey),
        );
      } catch (error) {
        return reject(response, 'attachments.query', error);
      }
      counters.query_requests += 1;
      if (failRemaining > 0) {
        failRemaining -= 1;
        counters.transient_failures += 1;
        record('attachments.query', 503, { captured_user: capturedUserKey });
        return writeJson(response, { detail: 'Generated Attachments service is temporarily unavailable' }, 503);
      }
      if (holdRemaining > 0) {
        holdRemaining -= 1;
        counters.held_queries += 1;
        held.push({
          response,
          queryRequest,
          userKey: capturedUserKey,
          sessionGeneration: capturedGeneration,
          scenario: capturedScenario === 'held' ? 'normal' : capturedScenario,
        });
        request.on('close', () => {
          const index = held.findIndex(item => item.response === response);
          if (index >= 0 && response.destroyed) held.splice(index, 1);
        });
        return;
      }
      try {
        const payload = queryResponse(queryRequest, capturedUserKey, capturedScenario);
        record('attachments.query', 200, {
          captured_user: capturedUserKey,
          captured_generation: capturedGeneration,
          item_count: payload.items.length,
        });
        return writeJson(response, payload);
      } catch {
        record('attachments.query', 500, { captured_user: capturedUserKey });
        return writeJson(response, { detail: 'Generated fixture failure' }, 500);
      }
    }

    const byteMatch = pathname.match(
      /^\/api\/emails\/(\d+)\/attachments\/(\d+)\/(preview|download)$/u,
    );
    if (request.method === 'GET' && byteMatch) {
      const action = byteMatch[3];
      if (!authRequired(response, `attachments.${action}`)) return;
      const emailId = Number(byteMatch[1]);
      const attachmentId = Number(byteMatch[2]);
      const item = INTERNAL_ITEMS.find(candidate => (
        candidate.email_id === emailId
        && candidate.attachment_id === attachmentId
        && ownsAccount(candidate.account_id)
      ));
      const bytes = GENERATED_BYTES.get(`${emailId}:${attachmentId}`);
      if (!item || !bytes) {
        counters.ownership_rejections += 1;
        record(`attachments.${action}`, 404);
        return writeJson(response, { detail: 'Attachment not found' }, 404);
      }
      if (action === 'preview') counters.preview_reads += 1;
      else counters.download_reads += 1;
      counters.generated_local_byte_reads += 1;
      counters.generated_local_bytes_served += bytes.bytes.length;
      record(`attachments.${action}`, 200, { account_id: item.account_id });
      return writeBytes(response, bytes, {
        download: action === 'download',
        preview: action === 'preview',
      });
    }

    const emailMatch = pathname.match(/^\/api\/emails\/(\d+)$/u);
    if (request.method === 'GET' && emailMatch) {
      if (!authRequired(response, 'emails.navigate')) return;
      const emailId = Number(emailMatch[1]);
      const item = INTERNAL_ITEMS.find(candidate => (
        candidate.email_id === emailId && ownsAccount(candidate.account_id)
      ));
      if (!item) {
        counters.ownership_rejections += 1;
        record('emails.navigate', 404);
        return writeJson(response, { detail: 'Email not found' }, 404);
      }
      counters.navigation_reads += 1;
      record('emails.navigate', 200, { account_id: item.account_id });
      return writeJson(response, {
        id: item.email_id,
        account_id: item.account_id,
        gmail_thread_id: `generated-attachment-thread-${item.email_id}`,
        is_read: true,
      });
    }

    if (pathname.startsWith('/api/') && !['GET', 'HEAD'].includes(request.method || 'GET')) {
      counters.unexpected_writes += 1;
      record(routeKey(request.method, pathname), 405);
      return writeJson(response, { detail: 'Generated fixture rejects mutations' }, 405);
    }
    record(routeKey(request.method || 'GET', pathname), 404);
    return writeJson(response, { detail: 'Route not found' }, 404);
  }

  const server = createServer((request, response) => {
    handle(request, response).catch(() => {
      if (!response.headersSent) writeJson(response, { detail: 'Generated fixture failure' }, 500);
      else response.destroy();
    });
  });

  return {
    listen(port = 0) {
      return new Promise((resolve, reject) => {
        server.once('error', reject);
        server.listen(port, GENERATED_ATTACHMENTS_HOST, () => {
          server.off('error', reject);
          resolve(server.address());
        });
      });
    },
    close() {
      for (const pending of held.splice(0)) {
        writeJson(pending.response, { detail: 'Generated fixture closing' }, 409);
      }
      return new Promise((resolve, reject) => {
        server.close(error => (error ? reject(error) : resolve()));
      });
    },
  };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const fixture = createGeneratedAttachmentsFixture();
  const requestedPort = Number.parseInt(process.argv[2] || '4182', 10);
  const address = await fixture.listen(requestedPort);
  process.stdout.write(
    `Generated Attachments fixture listening on http://${GENERATED_ATTACHMENTS_HOST}:${address.port}\n`,
  );
}
