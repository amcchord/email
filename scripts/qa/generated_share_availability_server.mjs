#!/usr/bin/env node

// Deterministic, generated-only Share Availability fixture. It binds only to
// loopback, serves the built frontend, keeps state in memory, and has no
// provider, production, environment, or outbound-network integration.

import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import { createServer } from 'node:http';
import { dirname, extname, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const GENERATED_SHARE_AVAILABILITY_HOST = '127.0.0.1';
const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const frontendDist = resolve(scriptDirectory, '../../frontend/dist');
const GENERATED_AT = '2026-08-31T16:00:00.000Z';
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

const GENERATED_USERS = Object.freeze({
  'generated-a': Object.freeze({
    id: 7301,
    username: 'availability-user-a@example.test',
    is_admin: false,
    account_ids: Object.freeze([1, 2]),
  }),
  'generated-b': Object.freeze({
    id: 7302,
    username: 'availability-user-b@example.test',
    is_admin: false,
    account_ids: Object.freeze([3]),
  }),
});

const GENERATED_ACCOUNTS = Object.freeze({
  1: Object.freeze({
    id: 1,
    email: 'owner@example.test',
    display_name: 'Generated Availability Owner',
    description: 'Generated Availability Primary',
    short_label: 'Primary',
    is_active: true,
    has_calendar_scope: true,
    created_at: '2026-08-01T12:00:00.000Z',
    sync_status: Object.freeze({
      status: 'idle',
      messages_synced: 1,
      total_messages: 1,
      last_full_sync: '2026-08-31T15:45:00.000Z',
      last_incremental_sync: '2026-08-31T15:55:00.000Z',
    }),
    calendar_sync_status: Object.freeze({
      status: 'idle',
      events_synced: 3,
      last_full_sync: '2026-08-31T15:40:00.000Z',
      last_incremental_sync: '2026-08-31T15:55:00.000Z',
      needs_reauth: false,
    }),
  }),
  2: Object.freeze({
    id: 2,
    email: 'projects@example.test',
    display_name: 'Generated Availability Projects',
    description: 'Generated Availability Secondary',
    short_label: 'Projects',
    is_active: true,
    has_calendar_scope: true,
    created_at: '2026-08-01T12:00:00.000Z',
    sync_status: Object.freeze({
      status: 'idle',
      messages_synced: 1,
      total_messages: 1,
      last_full_sync: '2026-08-31T15:45:00.000Z',
      last_incremental_sync: '2026-08-31T15:55:00.000Z',
    }),
    calendar_sync_status: Object.freeze({
      status: 'idle',
      events_synced: 3,
      last_full_sync: '2026-08-31T15:40:00.000Z',
      last_incremental_sync: '2026-08-31T15:55:00.000Z',
      needs_reauth: false,
    }),
  }),
  3: Object.freeze({
    id: 3,
    email: 'availability-user-b@example.test',
    display_name: 'Generated Availability User B',
    description: 'Generated Availability User B',
    short_label: 'User B',
    is_active: true,
    has_calendar_scope: true,
    created_at: '2026-08-01T12:00:00.000Z',
    sync_status: Object.freeze({ status: 'idle', messages_synced: 0, total_messages: 0 }),
    calendar_sync_status: Object.freeze({
      status: 'idle',
      events_synced: 1,
      last_full_sync: '2026-08-31T15:40:00.000Z',
      last_incremental_sync: '2026-08-31T15:55:00.000Z',
      needs_reauth: false,
    }),
  }),
});

function generatedEmail(overrides = {}) {
  return Object.freeze({
    id: 101,
    account_id: 1,
    account_email: 'owner@example.test',
    gmail_message_id: 'generated-availability-message-101',
    gmail_thread_id: 'generated-availability-thread-101',
    message_id_header: '<generated-availability-101@example.test>',
    from_name: 'Generated Scheduling Requester',
    from_address: 'requester@example.test',
    reply_to: 'requester@example.test',
    to_addresses: Object.freeze([{ name: 'Availability Owner', address: 'owner@example.test' }]),
    cc_addresses: Object.freeze([]),
    bcc_addresses: Object.freeze([]),
    subject: 'Generated request for meeting times',
    snippet: 'Please share a few generated times for next week.',
    body_text: 'Please share a few generated times for next week. No real mailbox data is used.',
    body_html: '<p>Please share a few generated times for next week.</p><p>No real mailbox data is used.</p>',
    date: '2026-08-31T14:00:00.000Z',
    labels: Object.freeze(['INBOX', 'UNREAD']),
    is_read: false,
    is_starred: false,
    is_trash: false,
    is_spam: false,
    is_sent: false,
    is_draft: false,
    has_attachments: false,
    attachments: Object.freeze([]),
    needs_reply: true,
    summary: 'A generated sender asked for meeting availability.',
    category: 'scheduling',
    action_items: Object.freeze(['Reply with generated availability.']),
    ai_action_items: Object.freeze(['Reply with generated availability.']),
    suggested_reply: null,
    reply_options: null,
    is_subscription: false,
    ...overrides,
  });
}

const GENERATED_EMAILS_BY_USER = Object.freeze({
  'generated-a': Object.freeze([generatedEmail()]),
  'generated-b': Object.freeze([]),
});

// These generated events deliberately contain content that must never appear
// in an availability response. The server self-test treats the values as leak
// sentinels while the calendar page can still exercise ordinary event reads.
const GENERATED_EVENTS = Object.freeze([
  Object.freeze({
    id: 7401,
    account_id: 1,
    account_email: 'owner@example.test',
    google_event_id: 'generated-private-event-7401',
    calendar_id: 'primary',
    summary: 'GENERATED_PRIVATE_EVENT_TITLE_MUST_NOT_ESCAPE',
    description: 'GENERATED_PRIVATE_EVENT_DESCRIPTION_MUST_NOT_ESCAPE',
    location: null,
    start_time: '2026-09-01T13:30:00.000Z',
    end_time: '2026-09-01T14:30:00.000Z',
    start_date: null,
    end_date: null,
    timezone: 'America/New_York',
    is_all_day: false,
    recurring_event_id: null,
    recurrence_rule: null,
    status: 'confirmed',
    html_link: null,
    hangout_link: null,
    organizer_email: 'generated-organizer@example.test',
    organizer_name: 'Generated Organizer',
    organizer_self: false,
    attendees: Object.freeze([{ email: 'generated-attendee@example.test', response_status: 'accepted' }]),
    visibility: 'private',
    transparency: 'opaque',
    reminders: null,
    created_at: GENERATED_AT,
    updated_at: GENERATED_AT,
  }),
  Object.freeze({
    id: 7402,
    account_id: 2,
    account_email: 'projects@example.test',
    google_event_id: 'generated-private-event-7402',
    calendar_id: 'primary',
    summary: 'GENERATED_SECOND_PRIVATE_TITLE_MUST_NOT_ESCAPE',
    description: null,
    location: null,
    start_time: '2026-09-02T16:00:00.000Z',
    end_time: '2026-09-02T17:00:00.000Z',
    start_date: null,
    end_date: null,
    timezone: 'America/New_York',
    is_all_day: false,
    recurring_event_id: null,
    recurrence_rule: null,
    status: 'confirmed',
    html_link: null,
    hangout_link: null,
    organizer_email: 'generated-organizer@example.test',
    organizer_name: 'Generated Organizer',
    organizer_self: false,
    attendees: Object.freeze([]),
    visibility: 'private',
    transparency: 'opaque',
    reminders: null,
    created_at: GENERATED_AT,
    updated_at: GENERATED_AT,
  }),
]);

const AVAILABILITY_REQUEST_KEYS = Object.freeze([
  'account_ids',
  'day_end',
  'day_start',
  'duration_minutes',
  'end_date',
  'include_weekends',
  'minimum_notice_minutes',
  'start_date',
  'step_minutes',
  'timezone',
]);
const RESPONSE_KEYS = Object.freeze([
  'coverage',
  'duration_minutes',
  'generated_at',
  'ready',
  'slots',
  'timezone',
]);
const ALLOWED_SCENARIOS = new Set([
  'ready',
  'stale',
  'reauthorization-required',
  'calendar-not-enabled',
  'no-full',
  'sync-error',
  'syncing',
  'fail-once',
  'held',
  'slow-session',
]);
const EMAIL_PATTERN = /[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+/giu;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/u;
const TIME_PATTERN = /^(?:[01]\d|2[0-3]):[0-5]\d$/u;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;

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
assertGeneratedAddresses(GENERATED_EMAILS_BY_USER);
assertGeneratedAddresses(GENERATED_EVENTS);

function freshCounters() {
  return {
    account_reads: 0,
    event_reads: 0,
    sync_status_reads: 0,
    availability_requests: 0,
    availability_successes: 0,
    incomplete_coverage_responses: 0,
    transient_failures: 0,
    held_availability_requests: 0,
    released_held_requests: 0,
    slow_availability_requests: 0,
    stale_session_responses: 0,
    draft_reads: 0,
    allowed_draft_writes: 0,
    auth_rejections: 0,
    ownership_rejections: 0,
    validation_errors: 0,
    non_generated_rejections: 0,
    rejected_email_send_attempts: 0,
    rejected_mail_mutation_attempts: 0,
    rejected_calendar_write_attempts: 0,
    rejected_event_creation_attempts: 0,
    rejected_event_hold_attempts: 0,
    rejected_provider_action_attempts: 0,
    provider_reads: 0,
    provider_calls: 0,
    provider_writes: 0,
    email_sends: 0,
    mail_mutations: 0,
    calendar_writes: 0,
    event_creations: 0,
    event_holds: 0,
    unexpected_writes: 0,
    unknown_routes: 0,
    external_network_calls: 0,
  };
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

async function readJson(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > 262_144) {
      throw Object.assign(new Error('Request body is too large'), { status: 422 });
    }
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
  } catch {
    throw Object.assign(new Error('Only .example.test addresses are accepted'), {
      status: 422,
      nonGenerated: true,
    });
  }
  return payload;
}

function writeError(response, status, code, detail) {
  return writeJson(response, { code, detail }, status);
}

async function existingFile(pathname) {
  try {
    const fileStat = await stat(pathname);
    return fileStat.isFile() ? fileStat : null;
  } catch {
    return null;
  }
}

async function serveFrontend(response, url, headOnly = false) {
  let decodedPath;
  try {
    decodedPath = decodeURIComponent(url.pathname);
  } catch {
    return writeError(response, 400, 'qa_url_malformed', 'Malformed generated QA URL');
  }
  const relativePath = decodedPath === '/' ? 'index.html' : decodedPath.replace(/^\/+/, '');
  let candidate = resolve(frontendDist, relativePath);
  if (candidate !== frontendDist && !candidate.startsWith(`${frontendDist}${sep}`)) {
    return writeError(response, 404, 'qa_static_not_found', 'Generated QA static path not found');
  }
  let fileStat = await existingFile(candidate);
  if (!fileStat && !extname(relativePath)) {
    candidate = resolve(frontendDist, 'index.html');
    fileStat = await existingFile(candidate);
  }
  if (!fileStat) {
    return writeError(response, 404, 'qa_static_not_found', 'Generated QA static file not found');
  }
  response.writeHead(200, {
    'Content-Type': STATIC_MIME_TYPES[extname(candidate).toLowerCase()] || 'application/octet-stream',
    'Content-Length': fileStat.size,
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
  });
  if (headOnly) return response.end();
  const stream = createReadStream(candidate);
  stream.on('error', () => {
    if (!response.headersSent) {
      writeError(response, 500, 'qa_static_error', 'Could not read generated QA static file');
    } else response.destroy();
  });
  stream.pipe(response);
}

function validateTimeZone(value) {
  if (typeof value !== 'string' || value.length < 1 || value.length > 80) return false;
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: value }).format(new Date(GENERATED_AT));
    return true;
  } catch {
    return false;
  }
}

function validateAvailabilityRequest(payload, ownsAccount) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new Error('Request body must be an object');
  }
  if (JSON.stringify(Object.keys(payload).sort()) !== JSON.stringify(AVAILABILITY_REQUEST_KEYS)) {
    throw new Error(`Request fields must be exactly: ${AVAILABILITY_REQUEST_KEYS.join(', ')}`);
  }
  if (
    !Array.isArray(payload.account_ids)
    || payload.account_ids.length < 1
    || payload.account_ids.length > 20
    || !payload.account_ids.every(value => Number.isSafeInteger(value) && value > 0)
    || new Set(payload.account_ids).size !== payload.account_ids.length
  ) throw new Error('account_ids must contain unique positive integers');
  if (!payload.account_ids.every(ownsAccount)) {
    throw Object.assign(new Error('Account not found'), { status: 404, ownership: true });
  }
  if (!DATE_PATTERN.test(payload.start_date) || !Number.isFinite(Date.parse(`${payload.start_date}T00:00:00Z`))) {
    throw new Error('start_date must be a valid YYYY-MM-DD date');
  }
  if (!DATE_PATTERN.test(payload.end_date) || !Number.isFinite(Date.parse(`${payload.end_date}T00:00:00Z`))) {
    throw new Error('end_date must be a valid YYYY-MM-DD date');
  }
  if (payload.start_date > payload.end_date) throw new Error('start_date must not be after end_date');
  if (payload.start_date < '2026-08-31' || payload.end_date > '2026-09-20') {
    throw new Error('start_date and end_date must be within the next 21 local calendar days');
  }
  if (![15, 30, 45, 60, 90, 120].includes(payload.duration_minutes)) {
    throw new Error('duration_minutes is unsupported');
  }
  if (![15, 30].includes(payload.step_minutes)) throw new Error('step_minutes is unsupported');
  if (
    !TIME_PATTERN.test(payload.day_start)
    || !TIME_PATTERN.test(payload.day_end)
    || payload.day_start < '06:00'
    || payload.day_start > '22:00'
    || payload.day_end < '06:00'
    || payload.day_end > '22:00'
  ) {
    throw new Error('Workday times must be HH:MM');
  }
  if (payload.day_start >= payload.day_end) throw new Error('day_start must be before day_end');
  if (typeof payload.include_weekends !== 'boolean') throw new Error('include_weekends must be boolean');
  if (!validateTimeZone(payload.timezone)) throw new Error('timezone must be a supported IANA time zone');
  if (
    !Number.isSafeInteger(payload.minimum_notice_minutes)
    || payload.minimum_notice_minutes < 0
    || payload.minimum_notice_minutes > 10_080
  ) throw new Error('minimum_notice_minutes must be between 0 and 10080');
  return clone(payload);
}

function coverageStateForScenario(scenario, accountId) {
  if (accountId !== 2) return 'ready';
  if (scenario === 'stale') return 'stale';
  if (scenario === 'reauthorization-required') return 'reauthorization_required';
  if (scenario === 'calendar-not-enabled') return 'calendar_not_enabled';
  if (scenario === 'no-full') return 'sync_incomplete';
  if (scenario === 'sync-error') return 'sync_error';
  if (scenario === 'syncing') return 'syncing';
  return 'ready';
}

function availabilitySlots(request) {
  const candidates = [
    ['2026-09-01T10:30:00-04:00', '2026-09-01T11:00:00-04:00'],
    ['2026-09-02T14:00:00-04:00', '2026-09-02T14:30:00-04:00'],
    ['2026-09-03T15:30:00-04:00', '2026-09-03T16:00:00-04:00'],
  ];
  return candidates
    .filter(([start]) => start.slice(0, 10) >= request.start_date && start.slice(0, 10) <= request.end_date)
    .map(([start]) => {
      const startDate = new Date(start);
      const end = new Date(startDate.getTime() + request.duration_minutes * 60_000);
      const sign = start.endsWith('-04:00') ? '-04:00' : 'Z';
      const endLocal = new Date(end.getTime() - 4 * 60 * 60_000).toISOString().slice(0, 19) + sign;
      return { start, end: endLocal };
    });
}

function availabilityResponse(request, scenario) {
  const coverage = request.account_ids.map(accountId => {
    const state = coverageStateForScenario(scenario, accountId);
    return {
      account_id: accountId,
      account_email: GENERATED_ACCOUNTS[accountId].email,
      state,
      last_success_at: state === 'calendar_not_enabled' || state === 'sync_incomplete'
        ? null
        : '2026-08-31T15:55:00.000Z',
    };
  });
  const ready = coverage.every(item => item.state === 'ready');
  const response = {
    ready,
    generated_at: GENERATED_AT,
    timezone: request.timezone,
    duration_minutes: request.duration_minutes,
    coverage,
    slots: ready ? availabilitySlots(request) : [],
  };
  if (JSON.stringify(Object.keys(response).sort()) !== JSON.stringify([...RESPONSE_KEYS].sort())) {
    throw new Error('Generated availability response changed shape');
  }
  return response;
}

function syncStatusesFor(user, scenario) {
  return user.account_ids.map(accountId => {
    const state = coverageStateForScenario(scenario, accountId);
    return {
      account_id: accountId,
      account_email: GENERATED_ACCOUNTS[accountId].email,
      status: state === 'syncing' ? 'syncing' : (state === 'sync_error' ? 'error' : 'idle'),
      sync_token: null,
      last_full_sync: ['calendar_not_enabled', 'sync_incomplete'].includes(state)
        ? null
        : '2026-08-31T15:40:00.000Z',
      last_incremental_sync: state === 'stale'
        ? '2026-08-25T12:00:00.000Z'
        : '2026-08-31T15:55:00.000Z',
      error_message: state === 'sync_error' ? 'Generated calendar sync error' : null,
      events_synced: state === 'sync_incomplete' ? 0 : 3,
      started_at: state === 'syncing' ? '2026-08-31T15:59:00.000Z' : null,
      completed_at: state === 'syncing' ? null : '2026-08-31T15:55:00.000Z',
      needs_reauth: state === 'reauthorization_required',
    };
  });
}

function publicDraft(record, includeContent = false) {
  const response = {
    client_draft_id: record.client_draft_id,
    account_id: record.account_id,
    source_email_id: record.source_email_id,
    revision: record.revision,
    synced_revision: record.revision,
    state: record.state,
    next_attempt_at: null,
    attempt_count: 1,
    can_undo_discard: record.state === 'discarded',
    discard_at: null,
    discard_undo_until: null,
    linked_send_id: null,
    error_code: null,
    error_message: null,
    attachment_count: Array.isArray(record.attachments) ? record.attachments.length : 0,
    attachment_bytes: 0,
    created_at: record.created_at,
    updated_at: record.updated_at,
    synced_at: record.updated_at,
    discarded_at: record.state === 'discarded' ? record.updated_at : null,
  };
  if (includeContent && record.state !== 'discarded') Object.assign(response, clone(record.payload));
  return response;
}

function routeKey(request, pathname) {
  return `${request.method || 'GET'} ${pathname}`;
}

function wait(milliseconds) {
  return new Promise(resolveWait => setTimeout(resolveWait, milliseconds));
}

export function createGeneratedShareAvailabilityFixture() {
  let currentUserKey = 'generated-a';
  let sessionGeneration = 1;
  let scenario = 'ready';
  let counters = freshCounters();
  let requests = [];
  let held = [];
  let failRemaining = 0;
  let drafts = new Map();
  const eventStreams = new Set();

  function currentUser() {
    return GENERATED_USERS[currentUserKey] || null;
  }

  function ownsAccount(accountId, userKey = currentUserKey) {
    return GENERATED_USERS[userKey]?.account_ids.includes(accountId) || false;
  }

  function record(action, status, extra = {}) {
    requests.push({
      sequence: requests.length + 1,
      action,
      status,
      user: currentUserKey,
      session_generation: sessionGeneration,
      ...extra,
    });
  }

  function requireAuth(response, action) {
    if (currentUser()) return true;
    counters.auth_rejections += 1;
    record(action, 401);
    writeError(response, 401, 'not_authenticated', 'Not authenticated');
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
    writeError(response, status, error.ownership ? 'not_found' : 'invalid_request', error.message);
  }

  function reset(nextScenario = 'ready', nextUser = 'generated-a') {
    if (!ALLOWED_SCENARIOS.has(nextScenario)) throw new Error('scenario is invalid');
    if (nextUser !== 'anonymous' && !GENERATED_USERS[nextUser]) {
      throw new Error('current_user must be a generated fixture identity');
    }
    for (const pending of held.splice(0)) {
      writeError(pending.response, 409, 'fixture_reset', 'Generated fixture reset');
    }
    currentUserKey = nextUser;
    sessionGeneration += 1;
    scenario = nextScenario;
    counters = freshCounters();
    requests = [];
    failRemaining = nextScenario === 'fail-once' ? 1 : 0;
    drafts = new Map();
  }

  function auditPayload() {
    return {
      fixture: 'generated-share-availability',
      localhost_only: true,
      fixture_domains: ['example.test'],
      current_user: currentUserKey,
      session_generation: sessionGeneration,
      scenario,
      pending_held_requests: held.length,
      event_content_sentinels: [
        'GENERATED_PRIVATE_EVENT_TITLE_MUST_NOT_ESCAPE',
        'GENERATED_PRIVATE_EVENT_DESCRIPTION_MUST_NOT_ESCAPE',
        'GENERATED_SECOND_PRIVATE_TITLE_MUST_NOT_ESCAPE',
      ],
      allowed_state_writes: ['generated compose draft state', 'generated QA controls'],
      counters: clone(counters),
      requests: clone(requests),
    };
  }

  async function handleControl(request, response, pathname) {
    if (request.method === 'GET' && pathname === '/__qa/audit') {
      return writeJson(response, auditPayload());
    }
    if (request.method === 'POST' && pathname === '/__qa/reset') {
      try {
        const payload = await readJson(request);
        reset(payload.scenario ?? 'ready', payload.current_user ?? 'generated-a');
        return writeJson(response, { reset: true, scenario, current_user: currentUserKey });
      } catch (error) {
        if (error.nonGenerated) counters.non_generated_rejections += 1;
        counters.validation_errors += 1;
        return writeError(response, error.status || 422, 'invalid_control', error.message);
      }
    }
    if (request.method === 'POST' && pathname === '/__qa/session') {
      try {
        const payload = await readJson(request);
        if (payload.current_user !== 'anonymous' && !GENERATED_USERS[payload.current_user]) {
          throw new Error('current_user must be a generated fixture identity');
        }
        currentUserKey = payload.current_user;
        sessionGeneration += 1;
        return writeJson(response, { current_user: currentUserKey, session_generation: sessionGeneration });
      } catch (error) {
        if (error.nonGenerated) counters.non_generated_rejections += 1;
        counters.validation_errors += 1;
        return writeError(response, error.status || 422, 'invalid_control', error.message);
      }
    }
    if (request.method === 'POST' && pathname === '/__qa/release') {
      const pending = held.splice(0);
      for (const item of pending) {
        if (item.sessionGeneration !== sessionGeneration || item.userKey !== currentUserKey) {
          counters.stale_session_responses += 1;
        }
        counters.released_held_requests += 1;
        const payload = availabilityResponse(item.availabilityRequest, item.scenario);
        record('calendar.availability.held-release', 200, {
          captured_user: item.userKey,
          captured_generation: item.sessionGeneration,
          account_ids: item.availabilityRequest.account_ids,
        });
        writeJson(item.response, payload);
      }
      return writeJson(response, { released: pending.length });
    }
    return false;
  }

  function listAccounts() {
    return currentUser().account_ids.map(accountId => {
      const account = clone(GENERATED_ACCOUNTS[accountId]);
      const state = coverageStateForScenario(scenario, accountId);
      if (state === 'calendar_not_enabled') {
        account.has_calendar_scope = false;
        account.calendar_sync_status = null;
      } else if (state === 'reauthorization_required') {
        account.calendar_sync_status.needs_reauth = true;
      } else if (state === 'sync_incomplete') {
        account.calendar_sync_status.last_full_sync = null;
        account.calendar_sync_status.events_synced = 0;
      } else if (state === 'stale') {
        account.calendar_sync_status.last_incremental_sync = '2026-08-25T12:00:00.000Z';
      } else if (state === 'sync_error') {
        account.calendar_sync_status.status = 'error';
        account.calendar_sync_status.error_message = 'Generated calendar sync error';
      } else if (state === 'syncing') account.calendar_sync_status.status = 'syncing';
      return account;
    });
  }

  function emailsForCurrentUser() {
    return clone(GENERATED_EMAILS_BY_USER[currentUserKey] || []);
  }

  function draftKey(clientDraftId, userKey = currentUserKey) {
    return `${userKey}:${clientDraftId}`;
  }

  function lookupDraft(clientDraftId) {
    const record = drafts.get(draftKey(clientDraftId));
    return record && record.owner_user_id === currentUser()?.id ? record : null;
  }

  async function saveDraft(request, response, pathname) {
    let payload;
    try {
      payload = await readJson(request);
      if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('Draft body must be an object');
      if (typeof payload.client_draft_id !== 'string' || !UUID_PATTERN.test(payload.client_draft_id)) {
        throw new Error('client_draft_id must be a generated UUID');
      }
      if (!Number.isSafeInteger(Number(payload.revision)) || Number(payload.revision) < 1) {
        throw new Error('revision must be a positive integer');
      }
      if (typeof payload.mutation_id !== 'string' || !payload.mutation_id.trim()) {
        throw new Error('mutation_id is required');
      }
      if (!Number.isSafeInteger(Number(payload.account_id)) || !ownsAccount(Number(payload.account_id))) {
        throw Object.assign(new Error('Account not found'), { status: 404, ownership: true });
      }
      if (payload.source_email_id !== null && payload.source_email_id !== undefined) {
        const source = emailsForCurrentUser().find(email => email.id === Number(payload.source_email_id));
        if (!source || source.account_id !== Number(payload.account_id)) {
          throw Object.assign(new Error('Source email not found'), { status: 404, ownership: true });
        }
      }
    } catch (error) {
      return reject(response, 'compose.draft.save', error);
    }
    const key = draftKey(payload.client_draft_id);
    const existing = drafts.get(key);
    const revision = Number(payload.revision);
    if (existing && revision < existing.revision) {
      counters.validation_errors += 1;
      return writeError(response, 409, 'draft_revision_conflict', 'Draft revision is older than generated state');
    }
    const now = GENERATED_AT;
    const recordValue = {
      owner_user_id: currentUser().id,
      client_draft_id: payload.client_draft_id,
      account_id: Number(payload.account_id),
      source_email_id: payload.source_email_id ?? null,
      revision,
      state: 'synced',
      created_at: existing?.created_at || now,
      updated_at: now,
      attachments: clone(payload.attachments || []),
      payload: clone(payload),
    };
    drafts.set(key, recordValue);
    counters.allowed_draft_writes += 1;
    record('compose.draft.save', 202, {
      account_id: recordValue.account_id,
      client_draft_id: recordValue.client_draft_id,
      revision,
    });
    return writeJson(response, publicDraft(recordValue, true), 202);
  }

  function rejectMutation(request, response, pathname) {
    const key = routeKey(request, pathname);
    if (pathname === '/api/compose/send' || pathname.startsWith('/api/compose/sends/')) {
      counters.rejected_email_send_attempts += 1;
      record(key, 405, { rejected: 'email-send' });
      return writeError(response, 405, 'generated_send_rejected', 'Generated fixture rejects email sends');
    }
    if (/^\/api\/calendar\/events(?:\/|$)/u.test(pathname)) {
      counters.rejected_calendar_write_attempts += 1;
      counters.rejected_event_creation_attempts += 1;
      record(key, 405, { rejected: 'event-creation' });
      return writeError(response, 405, 'generated_event_write_rejected', 'Generated fixture rejects event writes');
    }
    if (/\/holds?(?:\/|$)/u.test(pathname)) {
      counters.rejected_calendar_write_attempts += 1;
      counters.rejected_event_hold_attempts += 1;
      record(key, 405, { rejected: 'event-hold' });
      return writeError(response, 405, 'generated_event_hold_rejected', 'Generated fixture rejects event holds');
    }
    if (pathname.startsWith('/api/calendar/') || /\/sync(?:$|\?)/u.test(pathname)) {
      counters.rejected_calendar_write_attempts += 1;
      counters.rejected_provider_action_attempts += 1;
      record(key, 405, { rejected: 'calendar-provider-action' });
      return writeError(response, 405, 'generated_calendar_write_rejected', 'Generated fixture rejects calendar writes');
    }
    if (pathname.startsWith('/api/emails/') || pathname.startsWith('/api/ai/')) {
      counters.rejected_mail_mutation_attempts += 1;
      counters.rejected_provider_action_attempts += 1;
      record(key, 405, { rejected: 'mail-provider-action' });
      return writeError(response, 405, 'generated_mail_write_rejected', 'Generated fixture rejects mail mutations');
    }
    counters.unexpected_writes += 1;
    record(key, 405, { rejected: 'unexpected-write' });
    return writeError(response, 405, 'generated_write_rejected', 'Generated fixture rejects mutations');
  }

  async function handle(request, response) {
    const url = new URL(request.url || '/', 'http://127.0.0.1');
    const { pathname } = url;

    if (!pathname.startsWith('/api/') && !pathname.startsWith('/__qa/')) {
      if (!['GET', 'HEAD'].includes(request.method || 'GET')) {
        counters.unexpected_writes += 1;
        return writeError(response, 405, 'generated_write_rejected', 'Generated fixture rejects mutations');
      }
      return serveFrontend(response, url, request.method === 'HEAD');
    }
    if (pathname.startsWith('/__qa/')) {
      const handled = await handleControl(request, response, pathname);
      if (handled !== false) return;
      counters.unknown_routes += 1;
      return writeError(response, 404, 'qa_route_not_found', 'Generated QA route not found');
    }

    if (request.method === 'GET' && pathname === '/api/build-version') {
      return writeJson(response, { version: 'generated-share-availability-qa' });
    }
    if (request.method === 'GET' && pathname === '/api/auth/me') {
      if (!requireAuth(response, 'auth.me')) return;
      const user = currentUser();
      return writeJson(response, { id: user.id, username: user.username, is_admin: user.is_admin });
    }
    if (request.method === 'GET' && pathname === '/api/auth/ui-preferences') {
      return writeJson(response, { thread_order: 'newest_first', theme: 'amber', color_scheme: 'light' });
    }
    if (request.method === 'GET' && pathname === '/api/auth/keyboard-shortcuts') {
      return writeJson(response, { shortcuts: {} });
    }
    if (request.method === 'GET' && pathname === '/api/auth/ai-preferences') {
      return writeJson(response, {
        chat_plan_model: 'generated-model',
        chat_execute_model: 'generated-model',
        chat_verify_model: 'generated-model',
        agentic_model: 'generated-model',
        custom_prompt_model: 'generated-model',
        unsubscribe_model: 'generated-model',
        allowed_models: ['generated-model'],
        labels: { 'generated-model': 'Generated QA model' },
      });
    }
    if (request.method === 'GET' && pathname === '/api/auth/about-me') return writeJson(response, { about_me: '' });
    if (request.method === 'GET' && pathname === '/api/auth/api-tokens') return writeJson(response, []);
    if (request.method === 'GET' && pathname === '/api/admin/feature-flags') {
      return writeJson(response, { desktop_app_enabled: false });
    }
    if (request.method === 'GET' && pathname === '/api/accounts/allowed') return writeJson(response, []);
    if (request.method === 'GET' && pathname === '/api/accounts/') {
      if (!requireAuth(response, 'accounts.list')) return;
      counters.account_reads += 1;
      return writeJson(response, listAccounts());
    }
    const mailSyncMatch = pathname.match(/^\/api\/accounts\/(\d+)\/sync-status$/u);
    if (request.method === 'GET' && mailSyncMatch) {
      if (!requireAuth(response, 'accounts.sync-status')) return;
      const accountId = Number(mailSyncMatch[1]);
      if (!ownsAccount(accountId)) {
        counters.ownership_rejections += 1;
        return writeError(response, 404, 'not_found', 'Account not found');
      }
      return writeJson(response, clone(GENERATED_ACCOUNTS[accountId].sync_status));
    }

    if (request.method === 'GET' && pathname === '/api/events/stream') {
      response.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
      });
      response.write(': generated Share Availability QA stream\n\n');
      eventStreams.add(response);
      request.on('close', () => {
        eventStreams.delete(response);
        response.end();
      });
      return;
    }

    if (request.method === 'GET' && pathname === '/api/calendar/sync-status') {
      if (!requireAuth(response, 'calendar.sync-status')) return;
      counters.sync_status_reads += 1;
      return writeJson(response, syncStatusesFor(currentUser(), scenario));
    }
    if (request.method === 'GET' && pathname === '/api/calendar/events') {
      if (!requireAuth(response, 'calendar.events')) return;
      counters.event_reads += 1;
      const accountId = Number(url.searchParams.get('account_id')) || null;
      if (accountId && !ownsAccount(accountId)) {
        counters.ownership_rejections += 1;
        return writeError(response, 404, 'not_found', 'Account not found');
      }
      const events = GENERATED_EVENTS.filter(event => ownsAccount(event.account_id) && (!accountId || event.account_id === accountId));
      return writeJson(response, { events: clone(events), total: events.length });
    }
    if (request.method === 'GET' && pathname === '/api/calendar/upcoming') {
      if (!requireAuth(response, 'calendar.upcoming')) return;
      counters.event_reads += 1;
      const events = GENERATED_EVENTS.filter(event => ownsAccount(event.account_id));
      return writeJson(response, { events: clone(events) });
    }
    if (request.method === 'POST' && pathname === '/api/calendar/availability') {
      if (!requireAuth(response, 'calendar.availability')) return;
      const capturedUserKey = currentUserKey;
      const capturedGeneration = sessionGeneration;
      const capturedScenario = scenario;
      let availabilityRequest;
      try {
        availabilityRequest = validateAvailabilityRequest(
          await readJson(request),
          accountId => ownsAccount(accountId, capturedUserKey),
        );
      } catch (error) {
        return reject(response, 'calendar.availability', error);
      }
      counters.availability_requests += 1;
      if (failRemaining > 0) {
        failRemaining -= 1;
        counters.transient_failures += 1;
        record('calendar.availability', 503, { captured_user: capturedUserKey });
        return writeError(response, 503, 'availability_temporarily_unavailable', 'Generated availability is temporarily unavailable');
      }
      if (capturedScenario === 'held') {
        counters.held_availability_requests += 1;
        held.push({
          response,
          availabilityRequest,
          userKey: capturedUserKey,
          sessionGeneration: capturedGeneration,
          scenario: 'ready',
        });
        request.on('close', () => {
          const index = held.findIndex(item => item.response === response);
          if (index >= 0 && response.destroyed) held.splice(index, 1);
        });
        return;
      }
      if (capturedScenario === 'slow-session') {
        counters.slow_availability_requests += 1;
        await wait(650);
        if (capturedGeneration !== sessionGeneration || capturedUserKey !== currentUserKey) {
          counters.stale_session_responses += 1;
        }
      }
      const payload = availabilityResponse(availabilityRequest, capturedScenario);
      if (payload.ready) counters.availability_successes += 1;
      else counters.incomplete_coverage_responses += 1;
      record('calendar.availability', 200, {
        captured_user: capturedUserKey,
        captured_generation: capturedGeneration,
        account_ids: availabilityRequest.account_ids,
        ready: payload.ready,
        coverage_states: payload.coverage.map(item => item.state),
        slot_count: payload.slots.length,
      });
      return writeJson(response, payload);
    }

    if (request.method === 'GET' && (pathname === '/api/emails/' || pathname === '/api/emails')) {
      if (!requireAuth(response, 'emails.list')) return;
      const emails = emailsForCurrentUser();
      return writeJson(response, { emails, total: emails.length, page: 1, page_size: 50 });
    }
    if (request.method === 'GET' && pathname === '/api/emails/conversations') {
      if (!requireAuth(response, 'emails.conversations')) return;
      const conversations = emailsForCurrentUser().map(email => ({
        thread_id: email.gmail_thread_id,
        account_id: email.account_id,
        subject: email.subject,
        snippet: email.snippet,
        latest_date: email.date,
        date: email.date,
        message_count: 1,
        unread_count: email.is_read ? 0 : 1,
        participants: [{ name: email.from_name, address: email.from_address }],
        emails: [email],
      }));
      return writeJson(response, {
        conversations,
        total: conversations.length,
        page: 1,
        page_size: 50,
        total_pages: conversations.length ? 1 : 0,
      });
    }
    if (request.method === 'GET' && pathname === '/api/emails/conversations/split') {
      const emails = emailsForCurrentUser();
      return writeJson(response, {
        sections: [{ key: 'generated', label: 'Generated', emails }],
        emails,
        total: emails.length,
        page: 1,
        page_size: 50,
      });
    }
    const threadMatch = pathname.match(/^\/api\/emails\/thread\/([^/]+)$/u);
    if (request.method === 'GET' && threadMatch) {
      const threadId = decodeURIComponent(threadMatch[1]);
      const emails = emailsForCurrentUser().filter(email => email.gmail_thread_id === threadId);
      if (!emails.length) return writeError(response, 404, 'not_found', 'Generated thread not found');
      return writeJson(response, { thread_id: threadId, subject: emails[0].subject, emails });
    }
    const emailMatch = pathname.match(/^\/api\/emails\/(\d+)$/u);
    if (request.method === 'GET' && emailMatch) {
      const email = emailsForCurrentUser().find(item => item.id === Number(emailMatch[1]));
      if (!email) return writeError(response, 404, 'not_found', 'Generated email not found');
      return writeJson(response, email);
    }
    if (request.method === 'GET' && pathname === '/api/emails/labels/all') return writeJson(response, []);
    if (request.method === 'GET' && pathname === '/api/emails/actions/recent') return writeJson(response, []);
    if (request.method === 'GET' && pathname === '/api/saved-views') {
      return writeJson(response, { items: [], max_views: 12 });
    }
    if (request.method === 'GET' && pathname === '/api/snoozes') {
      return writeJson(response, { items: [], total: 0, limit: 200, offset: 0 });
    }

    if (request.method === 'POST' && pathname === '/api/compose/draft') {
      if (!requireAuth(response, 'compose.draft.save')) return;
      return saveDraft(request, response, pathname);
    }
    if (request.method === 'GET' && pathname === '/api/compose/drafts/recent') {
      if (!requireAuth(response, 'compose.drafts.recent')) return;
      counters.draft_reads += 1;
      const rows = [...drafts.values()]
        .filter(recordValue => recordValue.owner_user_id === currentUser().id)
        .map(recordValue => publicDraft(recordValue));
      return writeJson(response, rows);
    }
    const draftClientMatch = pathname.match(/^\/api\/compose\/drafts\/by-client-id\/([^/]+)$/u);
    if (request.method === 'GET' && draftClientMatch) {
      if (!requireAuth(response, 'compose.draft.lookup')) return;
      counters.draft_reads += 1;
      const found = lookupDraft(decodeURIComponent(draftClientMatch[1]));
      return found
        ? writeJson(response, publicDraft(found, true))
        : writeError(response, 404, 'draft_not_found', 'Generated draft not found');
    }
    const draftSourceMatch = pathname.match(/^\/api\/compose\/drafts\/by-source-email\/([^/]+)$/u);
    const draftEmailMatch = pathname.match(/^\/api\/compose\/drafts\/by-email\/([^/]+)$/u);
    if (request.method === 'GET' && (draftSourceMatch || draftEmailMatch)) {
      if (!requireAuth(response, 'compose.draft.lookup-source')) return;
      counters.draft_reads += 1;
      const sourceEmailId = Number(decodeURIComponent((draftSourceMatch || draftEmailMatch)[1]));
      const accountId = Number(url.searchParams.get('account_id')) || null;
      const found = [...drafts.values()].find(recordValue => (
        recordValue.owner_user_id === currentUser().id
        && Number(recordValue.source_email_id) === sourceEmailId
        && (!accountId || recordValue.account_id === accountId)
        && recordValue.state !== 'discarded'
      ));
      return found
        ? writeJson(response, publicDraft(found, true))
        : writeError(response, 404, 'draft_not_found', 'Generated draft not found');
    }
    const discardMatch = pathname.match(/^\/api\/compose\/drafts\/([^/]+)\/(discard|undo-discard)$/u);
    if (request.method === 'POST' && discardMatch) {
      if (!requireAuth(response, 'compose.draft.state')) return;
      const found = lookupDraft(decodeURIComponent(discardMatch[1]));
      if (!found) return writeError(response, 404, 'draft_not_found', 'Generated draft not found');
      try {
        const payload = await readJson(request);
        if (typeof payload.mutation_id !== 'string' || !payload.mutation_id.trim()) throw new Error('mutation_id is required');
      } catch (error) {
        return reject(response, 'compose.draft.state', error);
      }
      found.state = discardMatch[2] === 'discard' ? 'discarded' : 'synced';
      found.updated_at = GENERATED_AT;
      counters.allowed_draft_writes += 1;
      record(`compose.draft.${discardMatch[2]}`, 202, { client_draft_id: found.client_draft_id });
      return writeJson(response, publicDraft(found), 202);
    }
    if (request.method === 'GET' && pathname === '/api/compose/recipients') {
      const accountId = Number(url.searchParams.get('account_id'));
      if (!ownsAccount(accountId)) return writeError(response, 404, 'not_found', 'Account not found');
      return writeJson(response, { recipients: [] });
    }
    if (request.method === 'GET' && pathname === '/api/compose/snippets') return writeJson(response, { snippets: [] });
    if (request.method === 'GET' && pathname === '/api/compose/signatures') {
      return writeJson(response, { accounts: [], total: 0 });
    }
    if (request.method === 'GET' && pathname === '/api/follow-up/policies') {
      return writeJson(response, { accounts: [], total: 0 });
    }
    if (request.method === 'GET' && pathname === '/api/compose/sends/recent') return writeJson(response, []);
    if (request.method === 'GET' && pathname === '/api/compose/sends/scheduled') return writeJson(response, []);

    if (request.method === 'GET' && pathname === '/api/todos/') return writeJson(response, { todos: [] });
    if (request.method === 'GET' && pathname === '/api/ai/trends') return writeJson(response, { summary: '', needs_attention: [] });
    if (request.method === 'GET' && pathname === '/api/ai/stats') {
      return writeJson(response, { total_emails: 0, total_analyzed: 0, models: {}, unanalyzed: {} });
    }
    if (request.method === 'GET' && pathname === '/api/ai/processing/status') {
      return writeJson(response, { active: false, just_finished: false });
    }
    if (request.method === 'GET' && pathname === '/api/ai/needs-reply') {
      const emails = emailsForCurrentUser();
      return writeJson(response, { emails, total: emails.length });
    }
    if (request.method === 'GET' && pathname === '/api/ai/awaiting-response') return writeJson(response, { emails: [], total: 0 });
    if (request.method === 'GET' && pathname === '/api/ai/digests') return writeJson(response, { digests: [], total: 0 });
    if (request.method === 'GET' && pathname === '/api/chat/conversations') return writeJson(response, []);

    if (!['GET', 'HEAD'].includes(request.method || 'GET')) {
      return rejectMutation(request, response, pathname);
    }
    counters.unknown_routes += 1;
    record(routeKey(request, pathname), 404);
    return writeError(response, 404, 'route_not_found', 'Generated fixture route not found');
  }

  const server = createServer((request, response) => {
    handle(request, response).catch(() => {
      if (!response.headersSent) {
        writeError(response, 500, 'fixture_error', 'Generated fixture failure');
      } else response.destroy();
    });
  });

  return {
    listen(port = 0) {
      return new Promise((resolveListen, rejectListen) => {
        server.once('error', rejectListen);
        server.listen(port, GENERATED_SHARE_AVAILABILITY_HOST, () => {
          server.off('error', rejectListen);
          resolveListen(server.address());
        });
      });
    },
    close() {
      for (const stream of eventStreams) stream.end();
      eventStreams.clear();
      for (const pending of held.splice(0)) {
        writeError(pending.response, 409, 'fixture_closing', 'Generated fixture closing');
      }
      return new Promise((resolveClose, rejectClose) => {
        server.close(error => (error ? rejectClose(error) : resolveClose()));
      });
    },
    audit: auditPayload,
  };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const fixture = createGeneratedShareAvailabilityFixture();
  const requestedPort = Number.parseInt(process.env.QA_PORT || process.argv[2] || '4184', 10);
  const address = await fixture.listen(requestedPort);
  process.stdout.write(
    `Generated Share Availability fixture listening on http://${GENERATED_SHARE_AVAILABILITY_HOST}:${address.port}\n`,
  );
}
