#!/usr/bin/env node

// Deterministic, generated-only fixture for trainable Focused/Other rules.
// The server binds only to loopback, serves frontend/dist, keeps rule state in
// memory, derives every selector from .example.test Inbox anchors, and rejects
// every provider, Gmail, mail, calendar, AI, worker, and terminal operation.

import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import { createServer } from 'node:http';
import { dirname, extname, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const GENERATED_INBOX_RULES_HOST = '127.0.0.1';
const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const frontendDist = resolve(scriptDirectory, '../../frontend/dist');
const FIXTURE_NOW = '2026-08-31T18:00:00.000Z';
const EMAIL_PATTERN = /[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+/giu;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
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

const RULE_SCOPES = Object.freeze(['conversation', 'sender', 'domain']);
const PLACEMENTS = Object.freeze(['focused', 'other']);
const SCENARIOS = new Set(['ready', 'precedence', 'conflict-once', 'fail-once', 'slow-session', 'error']);

const GENERATED_USERS = Object.freeze({
  'generated-a': Object.freeze({
    id: 7601,
    username: 'focused-rules-owner@example.test',
    is_admin: false,
    account_ids: Object.freeze([1, 2]),
  }),
});

const GENERATED_ACCOUNTS = Object.freeze({
  1: Object.freeze({
    id: 1,
    email: 'focused-primary@example.test',
    display_name: 'Generated Focused Primary',
    description: 'Generated Focused Primary',
    short_label: 'Primary',
    is_active: true,
    has_calendar_scope: false,
    created_at: '2026-08-01T12:00:00.000Z',
    sync_status: Object.freeze({
      status: 'idle',
      messages_synced: 4,
      total_messages: 4,
      last_full_sync: '2026-08-31T17:30:00.000Z',
      last_incremental_sync: '2026-08-31T17:55:00.000Z',
    }),
    calendar_sync_status: null,
  }),
  2: Object.freeze({
    id: 2,
    email: 'focused-secondary@example.test',
    display_name: 'Generated Focused Secondary',
    description: 'Generated Focused Secondary',
    short_label: 'Secondary',
    is_active: true,
    has_calendar_scope: false,
    created_at: '2026-08-01T12:00:00.000Z',
    sync_status: Object.freeze({
      status: 'idle',
      messages_synced: 2,
      total_messages: 2,
      last_full_sync: '2026-08-31T17:30:00.000Z',
      last_incremental_sync: '2026-08-31T17:55:00.000Z',
    }),
    calendar_sync_status: null,
  }),
});

function generatedEmail(overrides) {
  const account = GENERATED_ACCOUNTS[overrides.account_id];
  const id = overrides.id;
  return Object.freeze({
    id,
    account_id: account.id,
    account_email: account.email,
    gmail_message_id: `generated-focused-message-${id}`,
    gmail_thread_id: `generated-focused-thread-${overrides.thread_suffix}`,
    message_id_header: `<generated-focused-${id}@example.test>`,
    from_name: overrides.from_name,
    from_address: overrides.from_address,
    reply_to: overrides.from_address,
    to_addresses: Object.freeze([{ name: account.display_name, address: account.email }]),
    cc_addresses: Object.freeze([]),
    bcc_addresses: Object.freeze([]),
    subject: overrides.subject,
    snippet: overrides.snippet || 'Generated locally for Focused and Other rule QA.',
    body_text: 'Generated locally for Focused and Other rule QA. No real mailbox data is used.',
    body_html: '<p>Generated locally for Focused and Other rule QA.</p><p>No real mailbox data is used.</p>',
    date: overrides.date,
    labels: Object.freeze(['INBOX', ...(overrides.is_read ? [] : ['UNREAD'])]),
    is_read: overrides.is_read ?? true,
    is_starred: false,
    is_trash: false,
    is_spam: false,
    is_sent: false,
    is_draft: false,
    has_attachments: false,
    attachments: Object.freeze([]),
    needs_reply: overrides.needs_reply ?? false,
    summary: null,
    category: null,
    action_items: Object.freeze([]),
    ai_action_items: Object.freeze([]),
    suggested_reply: null,
    reply_options: null,
    is_subscription: overrides.system_reason === 'subscription',
    system_placement: overrides.system_placement,
    system_reason: overrides.system_reason,
  });
}

const GENERATED_EMAILS = Object.freeze([
  generatedEmail({
    id: 101,
    account_id: 1,
    thread_suffix: 'primary-alex-one',
    from_name: 'Generated Alex',
    from_address: 'alex@sender.example.test',
    subject: 'Generated priority proposal',
    date: '2026-08-31T17:50:00.000Z',
    is_read: false,
    needs_reply: true,
    system_placement: 'focused',
    system_reason: 'needs_reply',
  }),
  generatedEmail({
    id: 102,
    account_id: 1,
    thread_suffix: 'primary-alex-two',
    from_name: 'Generated Alex',
    from_address: 'alex@sender.example.test',
    subject: 'Generated sender follow-up',
    date: '2026-08-31T17:40:00.000Z',
    system_placement: 'focused',
    system_reason: 'trusted_contact',
  }),
  generatedEmail({
    id: 103,
    account_id: 1,
    thread_suffix: 'primary-blair',
    from_name: 'Generated Blair',
    from_address: 'blair@sender.example.test',
    subject: 'Generated exact-domain peer',
    date: '2026-08-31T17:30:00.000Z',
    system_placement: 'focused',
    system_reason: 'direct_or_fyi',
  }),
  generatedEmail({
    id: 104,
    account_id: 1,
    thread_suffix: 'primary-subdomain',
    from_name: 'Generated Subdomain Alerts',
    from_address: 'alerts@sub.sender.example.test',
    subject: 'Generated subdomain must not match',
    date: '2026-08-31T17:20:00.000Z',
    system_placement: 'other',
    system_reason: 'subscription',
  }),
  generatedEmail({
    id: 201,
    account_id: 2,
    thread_suffix: 'secondary-alex',
    from_name: 'Generated Alex',
    from_address: 'alex@sender.example.test',
    subject: 'Generated same sender, second account',
    date: '2026-08-31T17:10:00.000Z',
    system_placement: 'focused',
    system_reason: 'trusted_contact',
  }),
  generatedEmail({
    id: 202,
    account_id: 2,
    thread_suffix: 'secondary-blair',
    from_name: 'Generated Blair',
    from_address: 'blair@sender.example.test',
    subject: 'Generated same domain, second account',
    date: '2026-08-31T17:00:00.000Z',
    system_placement: 'other',
    system_reason: 'low_priority',
  }),
]);

const RULE_IDS = Object.freeze({
  domain: '0b442648-5d15-4b18-89de-5c4f6b11c401',
  sender: '7539d0a7-4180-4a34-9cde-ea9ca4a42202',
  conversation: 'a75a9672-9a11-4852-bf1f-1c88292f4303',
});

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function assertGeneratedAddresses(value, path = 'fixture') {
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertGeneratedAddresses(item, `${path}[${index}]`));
    return;
  }
  if (value && typeof value === 'object') {
    Object.entries(value).forEach(([key, item]) => assertGeneratedAddresses(item, `${path}.${key}`));
    return;
  }
  if (typeof value !== 'string') return;
  for (const match of value.matchAll(EMAIL_PATTERN)) {
    const domain = match[0].toLowerCase().split('@').at(-1);
    if (domain !== 'example.test' && !domain?.endsWith('.example.test')) {
      throw new Error(`Non-generated address rejected at ${path}`);
    }
  }
}

assertGeneratedAddresses(GENERATED_USERS);
assertGeneratedAddresses(GENERATED_ACCOUNTS);
assertGeneratedAddresses(GENERATED_EMAILS);

function addressDomain(address) {
  return String(address || '').trim().toLowerCase().split('@')[1] || '';
}

function ruleMatchValue(email, scope) {
  if (scope === 'conversation') return `thread:${email.gmail_thread_id}`;
  if (scope === 'sender') return email.from_address.toLowerCase();
  if (scope === 'domain') return addressDomain(email.from_address);
  return null;
}

function publicSelector(rule) {
  if (rule.scope === 'conversation') return rule.conversation_subject;
  return rule.match_value;
}

function publicRule(rule) {
  return {
    id: rule.id,
    account_id: rule.account_id,
    account_email: GENERATED_ACCOUNTS[rule.account_id].email,
    scope: rule.scope,
    display_value: publicSelector(rule),
    placement: rule.placement,
    enabled: rule.enabled,
    revision: rule.revision,
    created_at: rule.created_at,
    updated_at: rule.updated_at,
  };
}

function seededRules() {
  const primaryAccount = GENERATED_ACCOUNTS[1];
  const conversation = GENERATED_EMAILS.find(email => email.id === 101);
  return [
    {
      id: RULE_IDS.domain,
      owner_user_id: GENERATED_USERS['generated-a'].id,
      account_id: primaryAccount.id,
      scope: 'domain',
      match_value: 'sender.example.test',
      conversation_subject: null,
      placement: 'other',
      enabled: true,
      revision: 1,
      created_at: '2026-08-31T17:00:01.000Z',
      updated_at: '2026-08-31T17:00:01.000Z',
    },
    {
      id: RULE_IDS.sender,
      owner_user_id: GENERATED_USERS['generated-a'].id,
      account_id: primaryAccount.id,
      scope: 'sender',
      match_value: 'alex@sender.example.test',
      conversation_subject: null,
      placement: 'focused',
      enabled: true,
      revision: 1,
      created_at: '2026-08-31T17:00:02.000Z',
      updated_at: '2026-08-31T17:00:02.000Z',
    },
    {
      id: RULE_IDS.conversation,
      owner_user_id: GENERATED_USERS['generated-a'].id,
      account_id: primaryAccount.id,
      scope: 'conversation',
      match_value: `thread:${conversation.gmail_thread_id}`,
      conversation_subject: conversation.subject,
      placement: 'other',
      enabled: true,
      revision: 1,
      created_at: '2026-08-31T17:00:03.000Z',
      updated_at: '2026-08-31T17:00:03.000Z',
    },
  ];
}

function freshCounters() {
  return {
    account_reads: 0,
    split_reads: 0,
    candidate_reads: 0,
    ledger_reads: 0,
    rule_creates: 0,
    rule_upserts: 0,
    rule_updates: 0,
    rule_deletes: 0,
    expected_rule_writes: 0,
    conflicts: 0,
    transient_failures: 0,
    delayed_requests: 0,
    stale_session_responses: 0,
    validation_errors: 0,
    ownership_rejections: 0,
    auth_rejections: 0,
    non_generated_rejections: 0,
    rejected_provider_attempts: 0,
    rejected_gmail_attempts: 0,
    rejected_mail_attempts: 0,
    rejected_calendar_attempts: 0,
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

function writeError(response, status, code, detail, extra = {}) {
  return writeJson(response, { code, detail, ...extra }, status);
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
  } catch {
    throw Object.assign(new Error('Only .example.test addresses are accepted'), {
      status: 422,
      nonGenerated: true,
    });
  }
  return payload;
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
  if (!fileStat) return writeError(response, 404, 'qa_static_not_found', 'Generated QA static file not found');
  response.writeHead(200, {
    'Content-Type': STATIC_MIME_TYPES[extname(candidate).toLowerCase()] || 'application/octet-stream',
    'Content-Length': fileStat.size,
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
  });
  if (headOnly) return response.end();
  const stream = createReadStream(candidate);
  stream.on('error', () => response.destroy());
  stream.pipe(response);
}

function wait(milliseconds) {
  return new Promise(resolveWait => setTimeout(resolveWait, milliseconds));
}

function exactObjectKeys(value, allowed, required = allowed) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Request body must be an object');
  const actual = Object.keys(value);
  if (actual.some(key => !allowed.includes(key))) throw new Error('Request contains an unexpected field');
  if (required.some(key => !Object.hasOwn(value, key))) throw new Error('Request is missing a required field');
}

function positiveInteger(value, name) {
  if (!Number.isSafeInteger(value) || value < 1) throw new Error(`${name} must be a positive integer`);
  return value;
}

function revisionOrNull(value, name = 'expected_revision') {
  if (value === 0) return 0;
  return positiveInteger(value, name);
}

function generatedUuid(value, name = 'create_id') {
  if (value === null || value === undefined) return null;
  if (typeof value !== 'string' || !UUID_PATTERN.test(value)) throw new Error(`${name} must be a UUID`);
  return value.toLowerCase();
}

function placement(value) {
  if (!PLACEMENTS.includes(value)) throw new Error('placement must be focused or other');
  return value;
}

function scope(value) {
  if (!RULE_SCOPES.includes(value)) throw new Error('scope must be conversation, sender, or domain');
  return value;
}

function buildConversation(email, resolved) {
  return {
    conversation_key: `${email.account_id}:${email.gmail_thread_id}`,
    account_id: email.account_id,
    account_email: email.account_email,
    anchor_email_id: email.id,
    gmail_message_id: email.gmail_message_id,
    gmail_thread_id: email.gmail_thread_id,
    subject: email.subject,
    from_address: email.from_address,
    from_name: email.from_name,
    to_addresses: clone(email.to_addresses),
    date: email.date,
    snippet: email.snippet,
    is_draft: false,
    is_sent: false,
    is_trash: false,
    is_spam: false,
    is_read: email.is_read,
    unread_count: email.is_read ? 0 : 1,
    is_starred: false,
    star_state: 'none',
    has_attachments: false,
    labels: clone(email.labels),
    label_coverage: {},
    member_count: 1,
    matched_count: 1,
    ai_category: null,
    ai_priority: null,
    ai_email_type: null,
    is_subscription: email.is_subscription,
    needs_reply: email.needs_reply,
    needs_reply_ignored: false,
    unsubscribe_info: null,
    thread_digest_type: null,
    thread_digest_summary: null,
    thread_digest_outcome: null,
    thread_digest_resolved: null,
    thread_digest_count: null,
    inbox_placement: resolved.placement,
    inbox_placement_reason: resolved.reason,
    inbox_placement_source: resolved.rule ? 'rule' : 'system',
    inbox_placement_rule_id: resolved.rule?.id || null,
    inbox_placement_rule_scope: resolved.rule?.scope || null,
    inbox_placement_rule_revision: resolved.rule?.revision || null,
  };
}

export function createGeneratedInboxRulesFixture() {
  let currentUserKey = 'generated-a';
  let sessionGeneration = 1;
  let scenario = 'ready';
  let rules = [];
  let counters = freshCounters();
  let requests = [];
  let sequence = 0;
  let failureRemaining = 0;
  let conflictRemaining = 0;
  let slowRemaining = 0;
  const eventStreams = new Set();

  function currentUser() {
    return GENERATED_USERS[currentUserKey] || null;
  }

  function ownsAccount(accountId, userKey = currentUserKey) {
    return GENERATED_USERS[userKey]?.account_ids.includes(accountId) || false;
  }

  function emailsFor(userKey = currentUserKey) {
    const user = GENERATED_USERS[userKey];
    if (!user) return [];
    return GENERATED_EMAILS.filter(email => user.account_ids.includes(email.account_id));
  }

  function ruleTimestamp() {
    sequence += 1;
    return new Date(Date.parse(FIXTURE_NOW) + sequence * 1000).toISOString();
  }

  function nextRuleId() {
    const suffix = String(sequence + rules.length + 1).padStart(12, '0');
    return `11111111-2222-4333-8444-${suffix}`;
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

  function ownedEmail(emailId, userKey = currentUserKey) {
    return emailsFor(userKey).find(email => email.id === Number(emailId)) || null;
  }

  function ownedRules(userKey = currentUserKey) {
    const user = GENERATED_USERS[userKey];
    if (!user) return [];
    return rules.filter(rule => rule.owner_user_id === user.id && user.account_ids.includes(rule.account_id));
  }

  function matchingRule(email, candidateScope, userKey = currentUserKey) {
    const value = ruleMatchValue(email, candidateScope);
    return ownedRules(userKey).find(rule => (
      rule.account_id === email.account_id
      && rule.scope === candidateScope
      && rule.match_value === value
    )) || null;
  }

  function resolvePlacement(email, userKey = currentUserKey) {
    for (const candidateScope of RULE_SCOPES) {
      const rule = matchingRule(email, candidateScope, userKey);
      if (rule?.enabled) {
        return {
          placement: rule.placement,
          reason: `user_rule_${rule.placement}`,
          rule,
        };
      }
    }
    return { placement: email.system_placement, reason: email.system_reason, rule: null };
  }

  function candidatePayload(email) {
    return {
      account_id: email.account_id,
      account_email: email.account_email,
      anchor_email_id: email.id,
      conversation_label: email.subject || '(No subject)',
      sender_address: email.from_address,
      sender_domain: addressDomain(email.from_address),
      rules: RULE_SCOPES
        .map(candidateScope => matchingRule(email, candidateScope))
        .filter(Boolean)
        .map(publicRule),
    };
  }

  function listPayload(accountId = null) {
    const items = ownedRules()
      .filter(rule => accountId === null || rule.account_id === accountId)
      .map(publicRule)
      .sort((left, right) => (
        left.account_id - right.account_id
        || RULE_SCOPES.indexOf(left.scope) - RULE_SCOPES.indexOf(right.scope)
        || left.display_value.localeCompare(right.display_value)
      ));
    return { items, max_rules_per_account: 500 };
  }

  function reset(nextScenario = 'ready', nextUser = 'generated-a') {
    if (!SCENARIOS.has(nextScenario)) throw new Error('scenario is invalid');
    if (nextUser !== 'anonymous' && !GENERATED_USERS[nextUser]) throw new Error('current_user is invalid');
    currentUserKey = nextUser;
    sessionGeneration += 1;
    scenario = nextScenario;
    rules = nextScenario === 'precedence' ? seededRules() : [];
    counters = freshCounters();
    requests = [];
    sequence = 0;
    failureRemaining = nextScenario === 'fail-once' ? 1 : 0;
    conflictRemaining = nextScenario === 'conflict-once' ? 1 : 0;
    slowRemaining = nextScenario === 'slow-session' ? 1 : 0;
  }

  function auditPayload() {
    const allResolved = emailsFor('generated-a').map(email => ({
      email_id: email.id,
      account_id: email.account_id,
      sender_address: email.from_address,
      domain: addressDomain(email.from_address),
      placement: resolvePlacement(email, 'generated-a').placement,
      reason: resolvePlacement(email, 'generated-a').reason,
      source: resolvePlacement(email, 'generated-a').rule ? 'rule' : 'system',
      rule_scope: resolvePlacement(email, 'generated-a').rule?.scope || null,
    }));
    return {
      fixture: 'generated-inbox-placement-rules',
      generated_only: true,
      localhost_only: true,
      fixture_domains: ['example.test'],
      current_user: currentUserKey,
      session_generation: sessionGeneration,
      scenario,
      allowed_state_writes: ['generated local Inbox placement rules', 'generated QA controls'],
      precedence: ['conversation', 'sender', 'exact-domain', 'system'],
      rules: clone(rules.map(publicRule)),
      resolved: allResolved,
      counters: clone(counters),
      requests: clone(requests),
    };
  }

  function reject(response, action, error) {
    const status = error.status || 422;
    if (error.ownership) counters.ownership_rejections += 1;
    else {
      counters.validation_errors += 1;
      if (error.nonGenerated) counters.non_generated_rejections += 1;
    }
    record(action, status);
    return writeError(response, status, error.ownership ? 'not_found' : 'invalid_request', error.message);
  }

  async function maybeScenarioFailure(response, action, capturedUserKey, capturedGeneration) {
    if (scenario === 'error') {
      counters.transient_failures += 1;
      record(action, 503, { captured_user: capturedUserKey, fixture_scenario: 'error' });
      writeError(response, 503, 'inbox_rules_unavailable', 'Generated Focused and Other rules are unavailable');
      return true;
    }
    if (failureRemaining > 0) {
      failureRemaining -= 1;
      counters.transient_failures += 1;
      record(action, 503, { captured_user: capturedUserKey, fixture_scenario: 'fail-once' });
      writeError(response, 503, 'inbox_rules_temporarily_unavailable', 'Generated Focused and Other rules are temporarily unavailable');
      return true;
    }
    if (slowRemaining > 0) {
      slowRemaining -= 1;
      counters.delayed_requests += 1;
      await wait(650);
      if (capturedUserKey !== currentUserKey || capturedGeneration !== sessionGeneration) {
        counters.stale_session_responses += 1;
      }
    }
    return false;
  }

  async function handleControl(request, response, pathname) {
    if (request.method === 'GET' && pathname === '/__qa/audit') return writeJson(response, auditPayload());
    if (request.method === 'POST' && pathname === '/__qa/reset') {
      try {
        const payload = await readJson(request);
        exactObjectKeys(payload, ['scenario', 'current_user'], []);
        reset(payload.scenario ?? 'ready', payload.current_user ?? 'generated-a');
        return writeJson(response, { reset: true, scenario, current_user: currentUserKey });
      } catch (error) {
        return reject(response, 'qa.reset', error);
      }
    }
    if (request.method === 'POST' && pathname === '/__qa/session') {
      try {
        const payload = await readJson(request);
        exactObjectKeys(payload, ['current_user']);
        if (payload.current_user !== 'anonymous' && !GENERATED_USERS[payload.current_user]) {
          throw new Error('current_user is invalid');
        }
        currentUserKey = payload.current_user;
        sessionGeneration += 1;
        return writeJson(response, { current_user: currentUserKey, session_generation: sessionGeneration });
      } catch (error) {
        return reject(response, 'qa.session', error);
      }
    }
    if (request.method === 'POST' && pathname === '/__qa/scenario') {
      try {
        const payload = await readJson(request);
        exactObjectKeys(payload, ['scenario']);
        if (!SCENARIOS.has(payload.scenario)) throw new Error('scenario is invalid');
        scenario = payload.scenario;
        failureRemaining = scenario === 'fail-once' ? 1 : 0;
        conflictRemaining = scenario === 'conflict-once' ? 1 : 0;
        slowRemaining = scenario === 'slow-session' ? 1 : 0;
        return writeJson(response, { scenario });
      } catch (error) {
        return reject(response, 'qa.scenario', error);
      }
    }
    return false;
  }

  async function handleCandidate(request, response, accountId, emailId) {
    if (!requireAuth(response, 'inbox-rules.candidate')) return;
    const capturedUserKey = currentUserKey;
    const capturedGeneration = sessionGeneration;
    const email = ownedEmail(emailId, capturedUserKey);
    if (!ownsAccount(accountId, capturedUserKey) || !email || email.account_id !== accountId) {
      counters.ownership_rejections += 1;
      record('inbox-rules.candidate', 404, {
        account_id: Number(accountId),
        anchor_email_id: Number(emailId),
      });
      return writeError(response, 404, 'not_found', 'Inbox conversation not found');
    }
    counters.candidate_reads += 1;
    if (await maybeScenarioFailure(response, 'inbox-rules.candidate', capturedUserKey, capturedGeneration)) return;
    const payload = candidatePayload(email);
    record('inbox-rules.candidate', 200, {
      captured_user: capturedUserKey,
      captured_generation: capturedGeneration,
      anchor_email_id: email.id,
      account_id: email.account_id,
    });
    return writeJson(response, payload);
  }

  async function handleLedger(request, response, url) {
    if (!requireAuth(response, 'inbox-rules.list')) return;
    const capturedUserKey = currentUserKey;
    const capturedGeneration = sessionGeneration;
    let accountId = null;
    if (url.searchParams.has('account_id')) {
      accountId = Number(url.searchParams.get('account_id'));
      if (!Number.isSafeInteger(accountId) || accountId < 1 || !ownsAccount(accountId, capturedUserKey)) {
        counters.ownership_rejections += 1;
        record('inbox-rules.list', 404, { account_id: accountId });
        return writeError(response, 404, 'not_found', 'Inbox placement rule not found');
      }
    }
    counters.ledger_reads += 1;
    if (await maybeScenarioFailure(response, 'inbox-rules.list', capturedUserKey, capturedGeneration)) return;
    const payload = listPayload(accountId);
    record('inbox-rules.list', 200, {
      captured_user: capturedUserKey,
      captured_generation: capturedGeneration,
      account_id: accountId,
      total: payload.items.length,
    });
    return writeJson(response, payload);
  }

  async function handleUpsert(request, response) {
    if (!requireAuth(response, 'inbox-rules.upsert')) return;
    const capturedUserKey = currentUserKey;
    const capturedGeneration = sessionGeneration;
    let payload;
    let email;
    let requestedScope;
    let requestedPlacement;
    let expectedRevision;
    try {
      payload = await readJson(request);
      exactObjectKeys(
        payload,
        ['create_id', 'account_id', 'anchor_email_id', 'scope', 'placement', 'enabled', 'expected_revision'],
      );
      const accountId = positiveInteger(payload.account_id, 'account_id');
      if (!ownsAccount(accountId, capturedUserKey)) {
        throw Object.assign(new Error('Inbox conversation not found'), { status: 404, ownership: true });
      }
      email = ownedEmail(positiveInteger(payload.anchor_email_id, 'anchor_email_id'), capturedUserKey);
      if (!email || email.account_id !== accountId) {
        throw Object.assign(new Error('Inbox conversation not found'), { status: 404, ownership: true });
      }
      requestedScope = scope(payload.scope);
      requestedPlacement = placement(payload.placement);
      expectedRevision = revisionOrNull(payload.expected_revision);
      if (typeof payload.enabled !== 'boolean') throw new Error('enabled must be boolean');
      generatedUuid(payload.create_id);
    } catch (error) {
      return reject(response, 'inbox-rules.upsert', error);
    }
    if (await maybeScenarioFailure(response, 'inbox-rules.upsert', capturedUserKey, capturedGeneration)) return;

    const value = ruleMatchValue(email, requestedScope);
    let existing = rules.find(rule => (
      rule.owner_user_id === GENERATED_USERS[capturedUserKey].id
      && rule.account_id === email.account_id
      && rule.scope === requestedScope
      && rule.match_value === value
    )) || null;
    if (conflictRemaining > 0) {
      conflictRemaining -= 1;
      counters.conflicts += 1;
      record('inbox-rules.upsert', 409, { account_id: email.account_id, scope: requestedScope });
      return writeError(response, 409, 'rule_revision_conflict', 'Focused and Other rule changed elsewhere', {
        current_rule: existing ? publicRule(existing) : null,
      });
    }
    const requestReplay = existing
      && (
        (expectedRevision === 0
          && existing.create_id === payload.create_id
          && existing.revision === 1)
        || (expectedRevision > 0 && existing.revision === expectedRevision + 1)
      )
      && existing.placement === requestedPlacement
      && existing.enabled === payload.enabled;
    if (requestReplay) {
      record('inbox-rules.upsert-replay', 200, {
        account_id: email.account_id,
        anchor_email_id: email.id,
        scope: requestedScope,
        revision: existing.revision,
      });
      return writeJson(response, publicRule(existing));
    }
    if ((existing?.revision ?? 0) !== expectedRevision) {
      counters.conflicts += 1;
      record('inbox-rules.upsert', 409, { account_id: email.account_id, scope: requestedScope });
      return writeError(response, 409, 'rule_revision_conflict', 'Focused and Other rule changed elsewhere', {
        current_rule: existing ? publicRule(existing) : null,
      });
    }

    let responseStatus = 200;
    if (existing) {
      if (existing.placement !== requestedPlacement || existing.enabled !== payload.enabled) {
        existing.placement = requestedPlacement;
        existing.enabled = payload.enabled;
        existing.revision += 1;
        existing.updated_at = ruleTimestamp();
        counters.rule_upserts += 1;
        counters.expected_rule_writes += 1;
      }
    } else {
      const now = ruleTimestamp();
      existing = {
        id: nextRuleId(),
        create_id: payload.create_id,
        owner_user_id: GENERATED_USERS[capturedUserKey].id,
        account_id: email.account_id,
        scope: requestedScope,
        match_value: value,
        conversation_subject: requestedScope === 'conversation' ? email.subject : null,
        placement: requestedPlacement,
        enabled: payload.enabled,
        revision: 1,
        created_at: now,
        updated_at: now,
      };
      rules.push(existing);
      counters.rule_creates += 1;
      counters.expected_rule_writes += 1;
      responseStatus = 201;
    }
    record('inbox-rules.upsert', responseStatus, {
      account_id: email.account_id,
      anchor_email_id: email.id,
      scope: requestedScope,
      placement: requestedPlacement,
      revision: existing.revision,
    });
    return writeJson(response, publicRule(existing), responseStatus);
  }

  async function handleUpdate(request, response, ruleId) {
    if (!requireAuth(response, 'inbox-rules.update')) return;
    let payload;
    let requestedPlacement;
    let expectedRevision;
    try {
      generatedUuid(ruleId, 'rule_id');
      payload = await readJson(request);
      exactObjectKeys(payload, ['placement', 'enabled', 'revision']);
      requestedPlacement = placement(payload.placement);
      if (typeof payload.enabled !== 'boolean') throw new Error('enabled must be boolean');
      expectedRevision = positiveInteger(payload.revision, 'revision');
    } catch (error) {
      return reject(response, 'inbox-rules.update', error);
    }
    const existing = ownedRules().find(rule => rule.id === ruleId) || null;
    if (!existing) {
      counters.ownership_rejections += 1;
      record('inbox-rules.update', 404, { rule_id: ruleId });
      return writeError(response, 404, 'not_found', 'Focused and Other rule not found');
    }
    if (
      conflictRemaining === 0
      && existing.revision === expectedRevision + 1
      && existing.placement === requestedPlacement
      && existing.enabled === payload.enabled
    ) {
      record('inbox-rules.update-replay', 200, { rule_id: ruleId, revision: existing.revision });
      return writeJson(response, publicRule(existing));
    }
    if (existing.revision !== expectedRevision || conflictRemaining > 0) {
      conflictRemaining = Math.max(0, conflictRemaining - 1);
      counters.conflicts += 1;
      record('inbox-rules.update', 409, { rule_id: ruleId });
      return writeError(response, 409, 'rule_revision_conflict', 'Focused and Other rule changed elsewhere', {
        current_rule: publicRule(existing),
      });
    }
    if (existing.placement !== requestedPlacement || existing.enabled !== payload.enabled) {
      existing.placement = requestedPlacement;
      existing.enabled = payload.enabled;
      existing.revision += 1;
      existing.updated_at = ruleTimestamp();
      counters.rule_updates += 1;
      counters.expected_rule_writes += 1;
    }
    record('inbox-rules.update', 200, { rule_id: ruleId, revision: existing.revision });
    return writeJson(response, publicRule(existing));
  }

  async function handleDelete(response, ruleId, url) {
    if (!requireAuth(response, 'inbox-rules.delete')) return;
    let expectedRevision;
    try {
      generatedUuid(ruleId, 'rule_id');
      expectedRevision = positiveInteger(Number(url.searchParams.get('revision')), 'revision');
    } catch (error) {
      return reject(response, 'inbox-rules.delete', error);
    }
    const index = rules.findIndex(rule => (
      rule.id === ruleId && rule.owner_user_id === currentUser().id && ownsAccount(rule.account_id)
    ));
    if (index < 0) {
      counters.ownership_rejections += 1;
      record('inbox-rules.delete', 404, { rule_id: ruleId });
      return writeError(response, 404, 'not_found', 'Focused and Other rule not found');
    }
    const existing = rules[index];
    if (existing.revision !== expectedRevision || conflictRemaining > 0) {
      conflictRemaining = Math.max(0, conflictRemaining - 1);
      counters.conflicts += 1;
      record('inbox-rules.delete', 409, { rule_id: ruleId });
      return writeError(response, 409, 'rule_revision_conflict', 'Focused and Other rule changed elsewhere', {
        current_rule: publicRule(existing),
      });
    }
    rules.splice(index, 1);
    counters.rule_deletes += 1;
    counters.expected_rule_writes += 1;
    record('inbox-rules.delete', 204, { rule_id: ruleId });
    response.writeHead(204, {
      'Cache-Control': 'private, no-store',
      'X-Content-Type-Options': 'nosniff',
    });
    response.end();
  }

  function splitPayload(url) {
    const accountId = url.searchParams.has('account_id') ? Number(url.searchParams.get('account_id')) : null;
    if (accountId !== null && (!Number.isSafeInteger(accountId) || !ownsAccount(accountId))) {
      throw Object.assign(new Error('Account not found'), { status: 404, ownership: true });
    }
    const page = Math.max(1, Number(url.searchParams.get('page')) || 1);
    const pageSize = Math.max(1, Math.min(100, Number(url.searchParams.get('page_size')) || 25));
    const rows = emailsFor()
      .filter(email => accountId === null || email.account_id === accountId)
      .map(email => buildConversation(email, resolvePlacement(email)))
      .sort((left, right) => Date.parse(right.date) - Date.parse(left.date));
    const byPlacement = requestedPlacement => {
      const matching = rows.filter(row => row.inbox_placement === requestedPlacement);
      const start = (page - 1) * pageSize;
      return {
        conversations: matching.slice(start, start + pageSize),
        total: matching.length,
        page,
        page_size: pageSize,
        total_pages: matching.length ? Math.ceil(matching.length / pageSize) : 0,
      };
    };
    const focused = byPlacement('focused');
    const other = byPlacement('other');
    return { focused, other, total: focused.total + other.total };
  }

  function rejectMutation(request, response, pathname) {
    const key = `${request.method || 'GET'} ${pathname}`;
    if (pathname.startsWith('/api/compose/send') || pathname.includes('/send')) {
      counters.rejected_mail_attempts += 1;
      record(key, 405, { rejected: 'email-send' });
      return writeError(response, 405, 'generated_send_rejected', 'Generated fixture rejects email sends');
    }
    if (pathname.startsWith('/api/calendar/')) {
      counters.rejected_calendar_attempts += 1;
      record(key, 405, { rejected: 'calendar-operation' });
      return writeError(response, 405, 'generated_calendar_rejected', 'Generated fixture rejects calendar operations');
    }
    if (pathname.startsWith('/api/terminal/')) {
      counters.rejected_terminal_attempts += 1;
      record(key, 405, { rejected: 'terminal-operation' });
      return writeError(response, 405, 'generated_terminal_rejected', 'Generated fixture rejects terminal operations');
    }
    if (pathname.includes('/gmail') || pathname.includes('/provider')) {
      counters.rejected_gmail_attempts += 1;
      counters.rejected_provider_attempts += 1;
      record(key, 405, { rejected: 'provider-operation' });
      return writeError(response, 405, 'generated_provider_rejected', 'Generated fixture rejects provider operations');
    }
    if (pathname.startsWith('/api/emails/') || pathname.startsWith('/api/ai/')) {
      counters.rejected_mail_attempts += 1;
      record(key, 405, { rejected: 'mail-operation' });
      return writeError(response, 405, 'generated_mail_rejected', 'Generated fixture rejects mail operations');
    }
    counters.unexpected_writes += 1;
    record(key, 405, { rejected: 'unexpected-write' });
    return writeError(response, 405, 'generated_write_rejected', 'Generated fixture rejects mutations');
  }

  async function handle(request, response) {
    const url = new URL(request.url || '/', 'http://127.0.0.1');
    const { pathname } = url;

    if (!pathname.startsWith('/api/') && !pathname.startsWith('/__qa/')) {
      if (!['GET', 'HEAD'].includes(request.method || 'GET')) return rejectMutation(request, response, pathname);
      return serveFrontend(response, url, request.method === 'HEAD');
    }
    if (pathname.startsWith('/__qa/')) {
      const handled = await handleControl(request, response, pathname);
      if (handled !== false) return;
      counters.unknown_routes += 1;
      return writeError(response, 404, 'qa_route_not_found', 'Generated QA route not found');
    }

    if (request.method === 'GET' && pathname === '/api/build-version') {
      return writeJson(response, { version: 'generated-inbox-placement-rules-qa' });
    }
    if (request.method === 'GET' && pathname === '/api/auth/me') {
      if (!requireAuth(response, 'auth.me')) return;
      const user = currentUser();
      return writeJson(response, { id: user.id, username: user.username, is_admin: user.is_admin });
    }
    if (request.method === 'POST' && pathname === '/api/auth/refresh') {
      counters.auth_rejections += 1;
      record('auth.refresh', 401);
      return writeError(response, 401, 'not_authenticated', 'Not authenticated');
    }
    if (request.method === 'GET' && pathname === '/api/auth/ui-preferences') {
      return writeJson(response, { thread_order: 'newest_first', theme: 'amber', color_scheme: 'light' });
    }
    if (request.method === 'GET' && pathname === '/api/auth/keyboard-shortcuts') return writeJson(response, { shortcuts: {} });
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
    if (request.method === 'GET' && pathname === '/api/admin/feature-flags') return writeJson(response, { desktop_app_enabled: false });
    if (request.method === 'GET' && pathname === '/api/accounts/allowed') return writeJson(response, []);
    if (request.method === 'GET' && pathname === '/api/accounts/') {
      if (!requireAuth(response, 'accounts.list')) return;
      counters.account_reads += 1;
      return writeJson(response, currentUser().account_ids.map(accountId => clone(GENERATED_ACCOUNTS[accountId])));
    }
    const accountSyncMatch = pathname.match(/^\/api\/accounts\/(\d+)\/sync-status$/u);
    if (request.method === 'GET' && accountSyncMatch) {
      const accountId = Number(accountSyncMatch[1]);
      if (!ownsAccount(accountId)) return writeError(response, 404, 'not_found', 'Account not found');
      return writeJson(response, clone(GENERATED_ACCOUNTS[accountId].sync_status));
    }
    if (request.method === 'GET' && pathname === '/api/events/stream') {
      response.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
      });
      response.write(': generated Inbox rules QA stream\n\n');
      eventStreams.add(response);
      request.on('close', () => {
        eventStreams.delete(response);
        response.end();
      });
      return;
    }

    if (request.method === 'GET' && pathname === '/api/inbox-placement-rules/candidate') {
      const accountId = Number(url.searchParams.get('account_id'));
      const emailId = Number(url.searchParams.get('anchor_email_id'));
      if (!Number.isSafeInteger(accountId) || accountId < 1 || !Number.isSafeInteger(emailId) || emailId < 1) {
        counters.validation_errors += 1;
        record('inbox-rules.candidate', 422);
        return writeError(response, 422, 'invalid_request', 'Candidate account and conversation are required');
      }
      return handleCandidate(request, response, accountId, emailId);
    }
    if (request.method === 'GET' && pathname === '/api/inbox-placement-rules') return handleLedger(request, response, url);
    if (request.method === 'POST' && pathname === '/api/inbox-placement-rules') return handleUpsert(request, response);
    const ruleMatch = pathname.match(/^\/api\/inbox-placement-rules\/([0-9a-f-]+)$/iu);
    if (request.method === 'PUT' && ruleMatch) return handleUpdate(request, response, ruleMatch[1].toLowerCase());
    if (request.method === 'DELETE' && ruleMatch) return handleDelete(response, ruleMatch[1].toLowerCase(), url);

    if (request.method === 'GET' && pathname === '/api/emails/conversations/split') {
      if (!requireAuth(response, 'emails.split')) return;
      try {
        const payload = splitPayload(url);
        counters.split_reads += 1;
        record('emails.split', 200, {
          account_id: url.searchParams.has('account_id') ? Number(url.searchParams.get('account_id')) : null,
          focused_total: payload.focused.total,
          other_total: payload.other.total,
          total: payload.total,
        });
        return writeJson(response, payload);
      } catch (error) {
        return reject(response, 'emails.split', error);
      }
    }
    if (request.method === 'GET' && pathname === '/api/emails/conversations') {
      const payload = splitPayload(url);
      const conversations = [...payload.focused.conversations, ...payload.other.conversations];
      return writeJson(response, {
        conversations,
        total: payload.total,
        page: payload.focused.page,
        page_size: payload.focused.page_size,
        total_pages: Math.max(payload.focused.total_pages, payload.other.total_pages),
      });
    }
    if (request.method === 'GET' && (pathname === '/api/emails/' || pathname === '/api/emails')) {
      const emailRows = emailsFor().map(email => clone(email));
      return writeJson(response, { emails: emailRows, total: emailRows.length, page: 1, page_size: 50, total_pages: 1 });
    }
    const threadMatch = pathname.match(/^\/api\/emails\/thread\/([^/]+)$/u);
    if (request.method === 'GET' && threadMatch) {
      const threadId = decodeURIComponent(threadMatch[1]);
      const threadEmails = emailsFor().filter(email => email.gmail_thread_id === threadId).map(clone);
      if (!threadEmails.length) return writeError(response, 404, 'not_found', 'Generated thread not found');
      return writeJson(response, { thread_id: threadId, subject: threadEmails[0].subject, emails: threadEmails });
    }
    const emailMatch = pathname.match(/^\/api\/emails\/(\d+)$/u);
    if (request.method === 'GET' && emailMatch) {
      const email = ownedEmail(Number(emailMatch[1]));
      return email ? writeJson(response, clone(email)) : writeError(response, 404, 'not_found', 'Generated email not found');
    }
    if (request.method === 'GET' && pathname === '/api/emails/labels/all') return writeJson(response, []);
    if (request.method === 'GET' && pathname === '/api/emails/actions/recent') return writeJson(response, []);
    if (request.method === 'GET' && pathname === '/api/saved-views') return writeJson(response, { items: [], max_views: 12 });
    if (request.method === 'GET' && pathname === '/api/snoozes') return writeJson(response, { items: [], total: 0, limit: 200, offset: 0 });
    if (request.method === 'GET' && pathname === '/api/calendar/sync-status') return writeJson(response, []);
    if (request.method === 'GET' && pathname === '/api/calendar/events') return writeJson(response, { events: [], total: 0 });
    if (request.method === 'GET' && pathname === '/api/calendar/upcoming') return writeJson(response, { events: [] });
    if (request.method === 'GET' && pathname === '/api/compose/drafts/recent') return writeJson(response, []);
    if (request.method === 'GET' && pathname === '/api/compose/sends/recent') return writeJson(response, []);
    if (request.method === 'GET' && pathname === '/api/compose/sends/scheduled') return writeJson(response, []);
    if (request.method === 'GET' && pathname === '/api/compose/snippets') return writeJson(response, { snippets: [] });
    if (request.method === 'GET' && pathname === '/api/compose/signatures') return writeJson(response, { accounts: [], total: 0 });
    if (request.method === 'GET' && pathname === '/api/follow-up/policies') return writeJson(response, { accounts: [], total: 0 });
    if (request.method === 'GET' && pathname === '/api/todos/') return writeJson(response, { todos: [] });
    if (request.method === 'GET' && pathname === '/api/ai/trends') return writeJson(response, { summary: '', needs_attention: [] });
    if (request.method === 'GET' && pathname === '/api/ai/stats') return writeJson(response, { total_emails: 0, total_analyzed: 0, models: {}, unanalyzed: {} });
    if (request.method === 'GET' && pathname === '/api/ai/processing/status') return writeJson(response, { active: false, just_finished: false });
    if (request.method === 'GET' && pathname === '/api/ai/needs-reply') return writeJson(response, { emails: [], total: 0 });
    if (request.method === 'GET' && pathname === '/api/ai/awaiting-response') return writeJson(response, { emails: [], total: 0 });
    if (request.method === 'GET' && pathname === '/api/ai/digests') return writeJson(response, { digests: [], total: 0 });
    if (request.method === 'GET' && pathname === '/api/chat/conversations') return writeJson(response, []);
    if (request.method === 'GET' && pathname === '/api/terminal/settings') {
      return writeJson(response, {
        enabled: false,
        has_api_key: false,
        has_active_api_key: false,
        terminal_count: 0,
        base_url: '',
        settings: null,
        current_version: null,
        image_version: null,
      });
    }
    if (request.method === 'GET' && pathname === '/api/terminal/devices') return writeJson(response, []);

    if (!['GET', 'HEAD'].includes(request.method || 'GET')) return rejectMutation(request, response, pathname);
    counters.unknown_routes += 1;
    record(`${request.method} ${pathname}`, 404);
    return writeError(response, 404, 'route_not_found', 'Generated fixture route not found');
  }

  const server = createServer((request, response) => {
    handle(request, response).catch(error => {
      if (!response.headersSent) {
        writeError(response, 500, 'fixture_error', error?.message || 'Generated fixture failure');
      } else response.destroy();
    });
  });

  return {
    listen(port = 0) {
      return new Promise((resolveListen, rejectListen) => {
        server.once('error', rejectListen);
        server.listen(port, GENERATED_INBOX_RULES_HOST, () => {
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

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const fixture = createGeneratedInboxRulesFixture();
  const requestedPort = Number.parseInt(process.env.QA_PORT || process.argv[2] || '4186', 10);
  const address = await fixture.listen(requestedPort);
  process.stdout.write(
    `Generated Inbox rules fixture listening on http://${GENERATED_INBOX_RULES_HOST}:${address.port}\n`,
  );
}
