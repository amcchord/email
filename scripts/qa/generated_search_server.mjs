#!/usr/bin/env node

// Deterministic, read-only browser-QA server for structured email search.
// It binds only to localhost, serves immutable .example.test fixtures and the
// built frontend, makes no outbound requests, and rejects every mutation.

import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import { createServer } from 'node:http';
import { dirname, extname, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const host = '127.0.0.1';
const port = Number.parseInt(process.env.QA_PORT || '4178', 10);
const fixtureNow = new Date('2026-08-30T14:00:00Z');
const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const frontendDist = resolve(scriptDirectory, '../../frontend/dist');

const compoundQuery = 'from:renee+launch@example.test subject:"Quarterly & Planning" has:attachment -is:read in:inbox';
const removalQuery = 'from:renee+launch@example.test subject:"Quarterly & Planning" -is:read in:inbox';

const scenarioQueries = Object.freeze({
  compound: compoundQuery,
  removal: removalQuery,
  zero_results: 'no-match',
  slow_overlap: 'slow:request',
  fast_overlap: 'fast:request',
  validation_error: 'backend-error',
  service_error: 'service-down',
});

function deepFreeze(value) {
  if (!value || typeof value !== 'object' || Object.isFrozen(value)) return value;
  for (const nestedValue of Object.values(value)) deepFreeze(nestedValue);
  return Object.freeze(value);
}

function generatedEmail(overrides) {
  const accountId = overrides.account_id || 1;
  const accountEmail = accountId === 1
    ? 'search.primary@example.test'
    : 'search.secondary@example.test';
  const id = overrides.id;
  const snippet = Object.hasOwn(overrides, 'snippet')
    ? overrides.snippet
    : 'Generated locally for structured-search browser QA.';
  const bodyText = Object.hasOwn(overrides, 'body_text')
    ? overrides.body_text
    : `${snippet || 'This fixture intentionally has no snippet.'}\n\nNo real mailbox data is used.`;
  const bodyHtml = Object.hasOwn(overrides, 'body_html')
    ? overrides.body_html
    : `<p>${snippet || 'This fixture intentionally has no snippet.'}</p><p>No real mailbox data is used.</p>`;

  return {
    id,
    account_id: accountId,
    account_email: accountEmail,
    gmail_message_id: `generated-search-message-${id}`,
    gmail_thread_id: `generated-search-thread-${id}`,
    message_id_header: `<generated-search-${id}@example.test>`,
    from_name: Object.hasOwn(overrides, 'from_name')
      ? overrides.from_name
      : 'Generated Sender',
    from_address: overrides.from_address || `sender-${id}@example.test`,
    reply_to: Object.hasOwn(overrides, 'reply_to')
      ? overrides.reply_to
      : (overrides.from_address || `sender-${id}@example.test`),
    to_addresses: Object.hasOwn(overrides, 'to_addresses')
      ? overrides.to_addresses
      : [{ name: 'Search QA', address: accountEmail }],
    cc_addresses: Object.hasOwn(overrides, 'cc_addresses') ? overrides.cc_addresses : [],
    bcc_addresses: Object.hasOwn(overrides, 'bcc_addresses') ? overrides.bcc_addresses : [],
    subject: Object.hasOwn(overrides, 'subject') ? overrides.subject : `Generated message ${id}`,
    snippet,
    body_text: bodyText,
    body_html: bodyHtml,
    date: overrides.date || '2026-08-30T12:00:00Z',
    labels: overrides.labels || ['INBOX'],
    is_read: overrides.is_read ?? true,
    is_starred: overrides.is_starred ?? false,
    is_trash: overrides.is_trash ?? false,
    is_spam: overrides.is_spam ?? false,
    is_sent: overrides.is_sent ?? false,
    is_draft: overrides.is_draft ?? false,
    has_attachments: overrides.has_attachments ?? false,
    attachments: overrides.attachments || [],
    ai_action_items: [],
    is_subscription: false,
  };
}

const generatedEmails = deepFreeze([
  generatedEmail({
    id: 301,
    from_name: 'Renée Launch',
    from_address: 'renee+launch@example.test',
    subject: 'Quarterly & Planning',
    snippet: 'Exact phrase fixture with the generated launch packet attached.',
    date: '2026-03-08T01:30:00-05:00',
    labels: ['INBOX', 'UNREAD', 'STARRED', 'Label_QA_SHARED'],
    is_read: false,
    is_starred: true,
    has_attachments: true,
    attachments: [{
      id: 'attachment-301',
      filename: 'quarterly-planning-generated.txt',
      content_type: 'text/plain',
      size_bytes: 43,
    }],
    to_addresses: [{ name: 'Primary Search QA', address: 'search.primary@example.test' }],
    cc_addresses: [{ name: 'Generated Observer', address: 'observer@example.test' }],
  }),
  generatedEmail({
    id: 302,
    from_name: 'Renée Launch',
    from_address: 'renee+launch@example.test',
    subject: 'Quarterly notes and Planning',
    snippet: 'Quarterly and Planning both occur, but the exact subject phrase does not.',
    date: '2026-03-08T03:30:00-04:00',
    labels: ['INBOX', 'UNREAD', 'STARRED'],
    is_read: false,
    is_starred: true,
    has_attachments: true,
    attachments: [{
      id: 'attachment-302',
      filename: 'near-miss-generated.txt',
      content_type: 'text/plain',
      size_bytes: 37,
    }],
  }),
  generatedEmail({
    id: 303,
    from_name: 'Renée Launch',
    from_address: 'renee+launch@example.test',
    subject: 'Quarterly & Planning',
    snippet: 'Read peer for the exact generated search fixture.',
    date: '2026-08-29T16:20:00Z',
    labels: ['INBOX', 'STARRED'],
    is_read: true,
    is_starred: true,
    has_attachments: true,
    attachments: [{
      id: 'attachment-303',
      filename: 'read-peer-generated.txt',
      content_type: 'text/plain',
      size_bytes: 31,
    }],
  }),
  generatedEmail({
    id: 304,
    from_name: 'Renée Launch',
    from_address: 'renee+launch@example.test',
    subject: 'Quarterly & Planning',
    snippet: 'Unread peer ticket:1234 deliberately missing an attachment.',
    date: '2026-08-29T16:10:00Z',
    labels: ['INBOX', 'UNREAD', 'STARRED'],
    is_read: false,
    is_starred: true,
    has_attachments: false,
  }),
  generatedEmail({
    id: 305,
    from_name: 'Primary Search QA',
    from_address: 'search.primary@example.test',
    subject: 'Sent fixture with legacy recipients',
    snippet: 'Recipient arrays use the legacy string shape.',
    date: '2026-08-28T18:00:00Z',
    labels: ['SENT'],
    is_sent: true,
    to_addresses: ['legacy.recipient@example.test'],
    cc_addresses: ['legacy.copy@example.test'],
  }),
  generatedEmail({
    id: 306,
    from_name: 'Primary Search QA',
    from_address: 'search.primary@example.test',
    subject: 'Draft fixture with JSON recipients',
    snippet: 'Recipient arrays use the object JSON shape.',
    date: '2026-08-28T17:30:00Z',
    labels: ['DRAFT'],
    is_draft: true,
    to_addresses: [{ name: 'Draft Recipient', address: 'draft.recipient@example.test' }],
  }),
  generatedEmail({
    id: 307,
    from_name: 'Generated Support',
    from_address: 'support@example.test',
    subject: 'Archived case ticket:1234',
    snippet: 'Generated archived custom-label fixture for ticket:1234.',
    body_text: 'The literal token ticket:1234 is preserved in this generated fixture.',
    date: '2026-08-27T14:00:00Z',
    labels: ['Label_QA_SHARED'],
  }),
  generatedEmail({
    id: 308,
    from_name: 'Generated Trash',
    from_address: 'trash@example.test',
    subject: 'Trash-only generated fixture',
    date: '2026-08-26T14:00:00Z',
    labels: ['TRASH'],
    is_trash: true,
  }),
  generatedEmail({
    id: 309,
    from_name: 'Generated Spam',
    from_address: 'spam@example.test',
    subject: 'Spam-only generated fixture',
    date: '2026-08-25T14:00:00Z',
    labels: ['SPAM'],
    is_spam: true,
  }),
  generatedEmail({
    id: 310,
    from_name: null,
    from_address: 'null-fields@example.test',
    reply_to: null,
    subject: null,
    snippet: null,
    body_text: null,
    body_html: null,
    date: '2026-08-24T12:00:00Z',
    labels: ['INBOX', 'Label_QA_SHARED'],
    to_addresses: null,
    cc_addresses: null,
    bcc_addresses: null,
  }),
  generatedEmail({
    id: 311,
    account_id: 2,
    from_name: 'Secondary Equal Time',
    from_address: 'equal-time@example.test',
    subject: 'Equal timestamp, second account',
    snippet: 'Shares an exact timestamp and custom label with another-account mail.',
    date: '2026-08-24T12:00:00Z',
    labels: ['INBOX', 'Label_QA_SHARED'],
    to_addresses: ['search.secondary@example.test'],
  }),
  generatedEmail({
    id: 312,
    account_id: 2,
    from_name: 'Renée Launch',
    from_address: 'renee+launch@example.test',
    subject: 'Quarterly & Planning',
    snippet: 'Read generated peer proves account isolation for matching visible fields.',
    date: '2026-08-23T15:00:00Z',
    labels: ['INBOX', 'STARRED', 'Label_QA_SHARED'],
    is_read: true,
    is_starred: true,
    has_attachments: true,
    attachments: [{
      id: 'attachment-312',
      filename: 'secondary-account-generated.txt',
      content_type: 'text/plain',
      size_bytes: 45,
    }],
  }),
]);

const emailsById = new Map(generatedEmails.map(email => [email.id, email]));

const scenarios = deepFreeze({
  // Baseline order is newest first; the equal-timestamp pair remains stable.
  '': { result_ids: [303, 304, 305, 306, 307, 308, 309, 310, 311, 312, 302, 301] },
  [compoundQuery]: { result_ids: [301] },
  [removalQuery]: { result_ids: [301, 304] },
  'no-match': { result_ids: [] },
  'slow:request': { result_ids: [310], delay_ms: 650 },
  'fast:request': { result_ids: [311], delay_ms: 15 },
  'in:sent': { result_ids: [305], overrides_mailbox: true },
  'in:trash': { result_ids: [308], overrides_mailbox: true },
  'in:spam': { result_ids: [309], overrides_mailbox: true },
  'in:trash OR in:spam': { result_ids: [309, 308], overrides_mailbox: true },
  'in:anywhere': { result_ids: [309, 308, 305, 301], overrides_mailbox: true },
  'backend-error': {
    result_ids: [],
    status: 422,
    detail: 'Generated search validation error for backend-error',
  },
  'service-down': {
    result_ids: [],
    status: 503,
    detail: 'Generated search service unavailable for service-down',
  },
  'ticket:1234': { result_ids: [304, 307] },
  'subject:"Quarterly & Planning"': { result_ids: [301, 303, 304, 312] },
});

const generatedAccounts = deepFreeze([
  {
    id: 1,
    email: 'search.primary@example.test',
    display_name: 'Generated Search Primary',
    description: 'Generated Search Primary',
    short_label: 'Primary',
    has_calendar_scope: true,
    sync_status: { status: 'idle', last_incremental_sync: fixtureNow.toISOString() },
    calendar_sync_status: { status: 'idle' },
  },
  {
    id: 2,
    email: 'search.secondary@example.test',
    display_name: 'Generated Search Secondary',
    description: 'Generated Search Secondary',
    short_label: 'Secondary',
    has_calendar_scope: true,
    sync_status: { status: 'idle', last_incremental_sync: fixtureNow.toISOString() },
    calendar_sync_status: { status: 'idle' },
  },
]);

const generatedLabels = deepFreeze([
  {
    id: 1,
    account_id: 1,
    gmail_label_id: 'Label_QA_SHARED',
    name: 'Generated Shared Search',
    label_type: 'user',
  },
  {
    id: 2,
    account_id: 2,
    gmail_label_id: 'Label_QA_SHARED',
    name: 'Generated Shared Search',
    label_type: 'user',
  },
]);

const audit = {
  queries: [],
  action_status_reads: [],
  mutation_attempts: [],
  unknown_routes: [],
};
let receivedSequence = 0;
let respondedSequence = 0;

function beginAudit(request, url, extra = {}) {
  receivedSequence += 1;
  return {
    received_sequence: receivedSequence,
    responded_sequence: null,
    method: request.method,
    original_url: request.url || '',
    pathname: url.pathname,
    status: null,
    ...extra,
  };
}

function completeAudit(entry, status, resultIds = []) {
  respondedSequence += 1;
  entry.responded_sequence = respondedSequence;
  entry.status = status;
  entry.result_ids = [...resultIds];
}

function writeJson(response, payload, status = 200, extraHeaders = {}) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
    'Cache-Control': 'no-store',
    ...extraHeaders,
  });
  response.end(body);
}

function writeHtml(response, body, status = 200) {
  response.writeHead(status, {
    'Content-Type': 'text/html; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
    'Cache-Control': 'no-store',
  });
  response.end(body);
}

function mobileQaFrame(response, url) {
  const scenario = url.searchParams.get('scenario') === 'compound' ? 'compound' : 'suggestions';
  const query = scenario === 'compound' ? compoundQuery : '';
  const body = `<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Generated mobile search QA</title>
  <style>
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; background: #111827; }
    body { display: grid; min-height: 100vh; place-items: start center; padding: 12px; }
    iframe { width: 375px; height: 812px; max-width: 100%; border: 0; border-radius: 14px; background: white; box-shadow: 0 22px 70px rgb(0 0 0 / .4); }
  </style>
</head>
<body data-qa-ready="false">
  <iframe id="mobile-app" src="/" title="Generated mail at 375 by 812 pixels"></iframe>
  <script>
    const scenario = ${JSON.stringify(scenario)};
    const query = ${JSON.stringify(query)};
    const frame = document.getElementById('mobile-app');
    const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
    const publishMetrics = (doc, input) => {
      const frameWindow = frame.contentWindow;
      const popover = doc.querySelector('.suggestion-popover');
      const interactive = [...doc.querySelectorAll('.clear-search, [role="option"], .search-chip, .summary-actions button')];
      const popoverRect = popover?.getBoundingClientRect();
      document.body.dataset.qaMetrics = JSON.stringify({
        innerWidth: frameWindow.innerWidth,
        innerHeight: frameWindow.innerHeight,
        clientWidth: doc.documentElement.clientWidth,
        scrollWidth: doc.documentElement.scrollWidth,
        inputHeight: input.getBoundingClientRect().height,
        inputFontSize: frameWindow.getComputedStyle(input).fontSize,
        ariaExpanded: input.getAttribute('aria-expanded'),
        minInteractiveHeight: interactive.length
          ? Math.min(...interactive.map(element => element.getBoundingClientRect().height))
          : null,
        popover: popoverRect ? {
          left: popoverRect.left,
          right: popoverRect.right,
          top: popoverRect.top,
          height: popoverRect.height,
        } : null,
        chipCount: doc.querySelectorAll('.search-chip').length,
        resultCountText: doc.querySelector('.summary-copy strong')?.textContent?.trim() || null,
      });
    };
    frame.addEventListener('load', async () => {
      const doc = frame.contentDocument;
      for (let attempt = 0; attempt < 80; attempt += 1) {
        const emailTab = doc.querySelector('[aria-label="Email tab"]');
        if (emailTab) {
          emailTab.click();
          break;
        }
        await delay(25);
      }
      for (let attempt = 0; attempt < 80; attempt += 1) {
        const input = doc.getElementById('email-search-input');
        if (input) {
          if (scenario === 'compound') {
            const setter = Object.getOwnPropertyDescriptor(
              frame.contentWindow.HTMLInputElement.prototype,
              'value',
            ).set;
            setter.call(input, query);
            input.dispatchEvent(new frame.contentWindow.Event('input', { bubbles: true }));
            input.dispatchEvent(new frame.contentWindow.KeyboardEvent('keydown', {
              key: 'Enter',
              code: 'Enter',
              bubbles: true,
            }));
            await delay(220);
          } else {
            input.focus();
            await delay(80);
          }
          publishMetrics(doc, input);
          document.body.dataset.qaReady = 'true';
          break;
        }
        await delay(25);
      }
    });
  </script>
</body>
</html>`;
  return writeHtml(response, body);
}

function positiveInteger(value, fallback) {
  const parsed = Number.parseInt(value || '', 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function visibleInMailbox(email, mailbox) {
  const normalized = mailbox.toUpperCase();
  if (normalized === 'ALL') return !email.is_trash && !email.is_spam;
  if (normalized === 'STARRED') return email.is_starred && !email.is_trash && !email.is_spam;
  if (normalized === 'TRASH') return email.is_trash;
  if (normalized === 'SPAM') return email.is_spam;
  if (normalized === 'SENT') return email.is_sent && !email.is_trash;
  if (normalized === 'DRAFTS' || normalized === 'DRAFT') return email.is_draft;
  if (normalized === 'INBOX') {
    return email.labels.includes('INBOX') && !email.is_trash && !email.is_spam;
  }
  return email.labels.some(label => label.toUpperCase() === normalized)
    && !email.is_trash
    && !email.is_spam;
}

function wait(delayMs) {
  if (!delayMs) return Promise.resolve();
  return new Promise(resolveWait => setTimeout(resolveWait, delayMs));
}

async function listEmails(request, response, url) {
  const decodedSearch = url.searchParams.get('search') ?? '';
  const mailbox = url.searchParams.get('mailbox') || 'INBOX';
  const accountValue = url.searchParams.get('account_id');
  const accountId = accountValue === null ? null : Number.parseInt(accountValue, 10);
  const page = positiveInteger(url.searchParams.get('page'), 1);
  const pageSize = Math.min(positiveInteger(url.searchParams.get('page_size'), 50), 200);
  const entry = beginAudit(request, url, {
    decoded_search: decodedSearch,
    mailbox,
    account: accountValue,
    account_id: Number.isFinite(accountId) ? accountId : null,
    page,
    page_size: pageSize,
    result_ids: [],
  });
  audit.queries.push(entry);

  const scenario = Object.hasOwn(scenarios, decodedSearch) ? scenarios[decodedSearch] : null;
  if (!scenario) {
    completeAudit(entry, 422);
    return writeJson(
      response,
      { detail: 'No generated search QA scenario for decoded search' },
      422,
    );
  }

  await wait(scenario.delay_ms);

  const status = scenario.status || 200;
  if (status !== 200) {
    completeAudit(entry, status);
    return writeJson(response, { detail: scenario.detail }, status);
  }

  const filtered = scenario.result_ids
    .map(id => emailsById.get(id))
    .filter(Boolean)
    .filter(email => scenario.overrides_mailbox || visibleInMailbox(email, mailbox))
    .filter(email => accountId === null || email.account_id === accountId);
  const offset = (page - 1) * pageSize;
  const pageEmails = filtered.slice(offset, offset + pageSize);
  const resultIds = pageEmails.map(email => email.id);

  completeAudit(entry, 200, resultIds);
  return writeJson(response, {
    emails: pageEmails,
    total: filtered.length,
    page,
    page_size: pageSize,
  });
}

const mimeTypes = Object.freeze({
  '.css': 'text/css; charset=utf-8',
  '.gif': 'image/gif',
  '.html': 'text/html; charset=utf-8',
  '.ico': 'image/x-icon',
  '.jpeg': 'image/jpeg',
  '.jpg': 'image/jpeg',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.txt': 'text/plain; charset=utf-8',
  '.webp': 'image/webp',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
});

async function existingFile(pathname) {
  try {
    const fileStat = await stat(pathname);
    return fileStat.isFile() ? fileStat : null;
  } catch {
    return null;
  }
}

async function serveFrontend(request, response, url) {
  let decodedPath;
  try {
    decodedPath = decodeURIComponent(url.pathname);
  } catch {
    const entry = beginAudit(request, url);
    audit.unknown_routes.push(entry);
    completeAudit(entry, 400);
    writeJson(response, { detail: 'Malformed generated QA URL' }, 400);
    return;
  }

  const relativePath = decodedPath === '/' ? 'index.html' : decodedPath.replace(/^\/+/, '');
  let candidate = resolve(frontendDist, relativePath);
  const insideDist = candidate === frontendDist || candidate.startsWith(`${frontendDist}${sep}`);
  if (!insideDist) {
    const entry = beginAudit(request, url);
    audit.unknown_routes.push(entry);
    completeAudit(entry, 404);
    writeJson(response, { detail: 'Generated QA static path not found' }, 404);
    return;
  }

  let fileStat = await existingFile(candidate);
  if (!fileStat && !extname(relativePath)) {
    candidate = resolve(frontendDist, 'index.html');
    fileStat = await existingFile(candidate);
  }
  if (!fileStat) {
    const entry = beginAudit(request, url);
    audit.unknown_routes.push(entry);
    completeAudit(entry, 404);
    writeJson(response, { detail: 'Generated QA static file not found' }, 404);
    return;
  }

  response.writeHead(200, {
    'Content-Type': mimeTypes[extname(candidate).toLowerCase()] || 'application/octet-stream',
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

const eventStreams = new Set();

async function handleGet(request, response, url) {
  const { pathname } = url;

  if (pathname === '/__qa/mobile') return mobileQaFrame(response, url);
  if (pathname === '/api/test/audit') {
    return writeJson(response, {
      fixture: 'generated-structured-search',
      fixture_domains: ['example.test'],
      fixture_account_ids: generatedAccounts.map(account => account.id),
      fixture_message_ids: generatedEmails.map(email => email.id),
      scenarios: scenarioQueries,
      queries: audit.queries,
      action_status_reads: audit.action_status_reads,
      mutation_attempts: audit.mutation_attempts,
      unknown_routes: audit.unknown_routes,
    });
  }
  if (pathname === '/api/auth/me') {
    return writeJson(response, { id: 1, username: 'generated-search-qa', is_admin: false });
  }
  if (pathname === '/api/auth/ui-preferences') {
    return writeJson(response, { thread_order: 'asc', theme: 'default', color_scheme: 'light' });
  }
  if (pathname === '/api/auth/keyboard-shortcuts') {
    return writeJson(response, { shortcuts: {} });
  }
  if (pathname === '/api/accounts/') return writeJson(response, generatedAccounts);
  if (pathname === '/api/build-version') {
    return writeJson(response, { version: 'generated-structured-search-qa' });
  }
  if (pathname === '/api/events/stream') {
    response.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
    });
    response.write(': generated structured-search QA stream\n\n');
    eventStreams.add(response);
    request.on('close', () => {
      eventStreams.delete(response);
      response.end();
    });
    return;
  }
  if (pathname === '/api/emails/labels/all') {
    const accountId = Number.parseInt(url.searchParams.get('account_id') || '', 10);
    const labels = Number.isFinite(accountId)
      ? generatedLabels.filter(label => label.account_id === accountId)
      : generatedLabels;
    return writeJson(response, labels);
  }
  if (pathname === '/api/emails/' || pathname === '/api/emails') {
    return listEmails(request, response, url);
  }
  if (pathname === '/api/emails/actions/recent') {
    const entry = beginAudit(request, url);
    audit.action_status_reads.push(entry);
    completeAudit(entry, 200);
    return writeJson(response, []);
  }
  if (pathname === '/api/calendar/sync-status') {
    return writeJson(response, { status: 'idle', accounts: [] });
  }
  if (pathname === '/api/calendar/events') {
    return writeJson(response, { events: [], total: 0 });
  }
  if (pathname === '/api/calendar/upcoming') return writeJson(response, { events: [] });
  if (pathname === '/api/todos/') return writeJson(response, { todos: [] });
  if (pathname === '/api/ai/needs-reply') {
    return writeJson(response, { emails: [], total: 0 });
  }
  if (pathname === '/api/ai/trends') {
    return writeJson(response, { summary: '', needs_attention: [] });
  }
  if (pathname === '/api/ai/awaiting-response') {
    return writeJson(response, { emails: [], total: 0 });
  }
  if (pathname === '/api/ai/digests') {
    return writeJson(response, { digests: [], total: 0 });
  }
  if (pathname === '/api/chat/conversations') return writeJson(response, []);

  const emailMatch = pathname.match(/^\/api\/emails\/(\d+)$/);
  if (emailMatch) {
    const email = emailsById.get(Number(emailMatch[1]));
    return writeJson(response, email || { detail: 'Generated email not found' }, email ? 200 : 404);
  }

  const attachmentMatch = pathname.match(/^\/api\/emails\/(\d+)\/attachments\/([^/]+)\/download$/);
  if (attachmentMatch) {
    const email = emailsById.get(Number(attachmentMatch[1]));
    const attachmentId = decodeURIComponent(attachmentMatch[2]);
    const attachment = email?.attachments?.find(item => item.id === attachmentId);
    if (!attachment) return writeJson(response, { detail: 'Generated attachment not found' }, 404);
    const body = Buffer.from(`Generated attachment ${attachment.id} for ${email.message_id_header}\n`);
    response.writeHead(200, {
      'Content-Type': attachment.content_type,
      'Content-Length': body.length,
      'Content-Disposition': `attachment; filename="${attachment.filename}"`,
      'Cache-Control': 'no-store',
    });
    response.end(body);
    return;
  }

  if (!pathname.startsWith('/api/')) return serveFrontend(request, response, url);

  const entry = beginAudit(request, url);
  audit.unknown_routes.push(entry);
  completeAudit(entry, 404);
  return writeJson(
    response,
    { detail: `No generated read-only QA route for GET ${pathname}` },
    404,
  );
}

async function handleRequest(request, response) {
  const url = new URL(request.url, `http://${host}:${port}`);
  const { pathname } = url;

  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method)) {
    const entry = beginAudit(request, url);
    audit.mutation_attempts.push(entry);
    completeAudit(entry, 405);
    return writeJson(
      response,
      { detail: 'Generated structured-search QA is read-only' },
      405,
      { Allow: 'GET' },
    );
  }
  if (request.method === 'GET') return handleGet(request, response, url);

  const entry = beginAudit(request, url);
  audit.unknown_routes.push(entry);
  completeAudit(entry, 405);
  return writeJson(
    response,
    { detail: `Unsupported method ${request.method}` },
    405,
    { Allow: 'GET' },
  );
}

const server = createServer((request, response) => {
  Promise.resolve(handleRequest(request, response)).catch(error => {
    if (!response.headersSent) writeJson(response, { detail: error.message }, 500);
    else response.destroy();
  });
});

server.listen(port, host, () => {
  process.stdout.write(`Generated structured-search QA listening on http://${host}:${port}\n`);
});

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    for (const response of eventStreams) response.end();
    eventStreams.clear();
    server.close(() => process.exit(0));
  });
}
