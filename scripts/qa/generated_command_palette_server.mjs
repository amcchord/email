#!/usr/bin/env node

// Deterministic, read-only API for command-palette and search browser QA.
// It binds only to localhost, serves generated .example.test data, makes no
// outbound requests, and rejects every mutating HTTP method.

import { createServer } from 'node:http';

const host = '127.0.0.1';
const port = Number.parseInt(process.env.QA_API_PORT || '8000', 10);
const fixtureNow = new Date('2026-08-30T14:00:00Z');

const generatedEmails = [
  {
    id: 201,
    from_name: 'Quinn Rivera',
    subject: 'Monday launch checklist',
    snippet: 'Three generated launch items remain for QA review.',
    date: '2026-08-30T13:20:00Z',
    labels: ['INBOX', 'UNREAD'],
  },
  {
    id: 202,
    from_name: 'Morgan Patel',
    subject: 'Quarterly planning packet',
    snippet: 'The generated quarterly planning packet is ready.',
    date: '2026-08-29T16:10:00Z',
    labels: ['INBOX', 'STARRED'],
  },
  {
    id: 203,
    from_name: 'Casey Kim',
    subject: 'Your test receipt',
    snippet: 'This generated receipt confirms a $0.00 QA order.',
    date: '2026-08-28T11:45:00Z',
    labels: ['INBOX'],
  },
  {
    id: 204,
    from_name: 'Jordan Lee',
    subject: 'Dinner next week?',
    snippet: 'Would Tuesday evening work for this generated plan?',
    date: '2026-08-27T20:05:00Z',
    labels: ['INBOX', 'UNREAD'],
  },
  {
    id: 205,
    from_name: 'Taylor Brooks',
    subject: 'Accessibility follow-up',
    snippet: 'Keyboard and narrow-screen generated checks look promising.',
    date: '2026-08-20T09:30:00Z',
    labels: [],
  },
  {
    id: 206,
    from_name: 'Alex Rivera',
    subject: 'Launch retrospective',
    snippet: 'Notes from the generated launch retrospective.',
    date: '2026-08-26T15:15:00Z',
    labels: ['INBOX'],
  },
  {
    id: 207,
    from_name: 'Renée Dubois',
    subject: 'Résumé review — Q3',
    snippet: 'A generated résumé review for the third quarter.',
    date: '2026-08-25T12:00:00Z',
    labels: ['INBOX'],
  },
].map((fixture, index) => {
  const addressName = fixture.from_name
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replaceAll(' ', '.');
  const fromAddress = `${addressName}@example.test`;
  const bodyText = `${fixture.snippet}\n\nThis message was generated locally for command-palette browser testing.`;

  return Object.freeze({
    ...fixture,
    account_id: 1,
    account_email: 'qa.generated@example.test',
    gmail_message_id: `generated-command-message-${index + 1}`,
    gmail_thread_id: `generated-command-thread-${index + 1}`,
    message_id_header: `<generated-command-${index + 1}@example.test>`,
    from_address: fromAddress,
    reply_to: fromAddress,
    to_addresses: [{ name: 'QA User', address: 'qa.generated@example.test' }],
    cc_addresses: [],
    body_text: bodyText,
    body_html: `<p>${fixture.snippet}</p><p>This message was generated locally for command-palette browser testing.</p>`,
    is_read: !fixture.labels.includes('UNREAD'),
    is_starred: fixture.labels.includes('STARRED'),
    is_trash: false,
    is_spam: false,
    is_sent: false,
    is_draft: false,
    has_attachments: false,
    attachments: [],
    ai_action_items: [],
    is_subscription: false,
  });
});

const emailsById = new Map(generatedEmails.map(email => [email.id, email]));
const audit = {
  queries: [],
  action_status_reads: [],
  mutation_attempts: [],
  unknown_routes: [],
};
let auditSequence = 0;

function auditEntry(request, pathname) {
  auditSequence += 1;
  return { sequence: auditSequence, method: request.method, pathname };
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

function visibleInMailbox(email, mailbox) {
  if (mailbox === 'ALL') return !email.is_trash && !email.is_spam;
  if (mailbox === 'STARRED') return email.is_starred && !email.is_trash && !email.is_spam;
  if (mailbox === 'TRASH') return email.is_trash;
  if (mailbox === 'SPAM') return email.is_spam;
  if (mailbox === 'SENT') return email.is_sent && !email.is_trash;
  if (mailbox === 'DRAFTS') return email.is_draft;
  return email.labels.includes('INBOX') && !email.is_trash && !email.is_spam;
}

function searchTokens(search) {
  const matches = search.trim().match(/"[^"]+"|\S+/g) || [];
  return matches
    .map(token => token.replace(/^"|"$/g, '').trim().toLocaleLowerCase())
    .filter(Boolean);
}

function matchesPlainSearch(email, search) {
  const tokens = searchTokens(search);
  if (tokens.length === 0) return true;
  const searchable = [
    email.subject,
    email.from_name,
    email.from_address,
    email.snippet,
    email.body_text,
  ].join('\n').toLocaleLowerCase();
  return tokens.every(token => searchable.includes(token));
}

function listEmails(request, response, url) {
  const mailbox = (url.searchParams.get('mailbox') || 'INBOX').toUpperCase();
  const search = url.searchParams.get('search') || '';
  const requestedPage = Number.parseInt(url.searchParams.get('page') || '1', 10);
  const requestedPageSize = Number.parseInt(url.searchParams.get('page_size') || '50', 10);
  const page = Number.isFinite(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  const pageSize = Number.isFinite(requestedPageSize)
    ? Math.max(1, Math.min(requestedPageSize, 200))
    : 50;

  const filtered = generatedEmails
    .filter(email => visibleInMailbox(email, mailbox))
    .filter(email => matchesPlainSearch(email, search))
    .sort((left, right) => Date.parse(right.date) - Date.parse(left.date));
  const offset = (page - 1) * pageSize;
  const pageEmails = filtered.slice(offset, offset + pageSize);

  audit.queries.push({
    ...auditEntry(request, url.pathname),
    mailbox,
    search,
    page,
    page_size: pageSize,
    result_ids: pageEmails.map(email => email.id),
    total: filtered.length,
  });

  return writeJson(response, {
    emails: pageEmails,
    total: filtered.length,
    page,
    page_size: pageSize,
  });
}

function handleGet(request, response, url) {
  const { pathname } = url;

  if (pathname === '/api/test/audit') {
    return writeJson(response, {
      fixture: 'generated-command-palette',
      fixture_domains: ['example.test'],
      queries: audit.queries,
      action_status_reads: audit.action_status_reads,
      mutation_attempts: audit.mutation_attempts,
      unknown_routes: audit.unknown_routes,
    });
  }
  if (pathname === '/api/auth/me') {
    return writeJson(response, { id: 1, username: 'generated-command-qa', is_admin: false });
  }
  if (pathname === '/api/auth/ui-preferences') {
    return writeJson(response, { thread_order: 'asc', theme: 'default', color_scheme: 'light' });
  }
  if (pathname === '/api/auth/keyboard-shortcuts') {
    return writeJson(response, { shortcuts: {} });
  }
  if (pathname === '/api/accounts/') {
    return writeJson(response, [{
      id: 1,
      email: 'qa.generated@example.test',
      display_name: 'Generated Command QA',
      description: 'Generated Command QA',
      has_calendar_scope: true,
      sync_status: { status: 'idle', last_incremental_sync: fixtureNow.toISOString() },
      calendar_sync_status: { status: 'idle' },
    }]);
  }
  if (pathname === '/api/build-version') {
    return writeJson(response, { version: 'generated-command-palette-qa' });
  }
  if (pathname === '/api/events/stream') {
    response.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
    });
    response.write(': generated command-palette QA stream\n\n');
    request.on('close', () => response.end());
    return;
  }
  if (pathname === '/api/emails/labels/all') {
    return writeJson(response, []);
  }
  if (pathname === '/api/emails/') {
    return listEmails(request, response, url);
  }
  if (pathname === '/api/emails/actions/recent') {
    audit.action_status_reads.push(auditEntry(request, pathname));
    return writeJson(response, []);
  }
  if (pathname === '/api/calendar/sync-status') {
    return writeJson(response, { status: 'idle', accounts: [] });
  }
  if (pathname === '/api/calendar/events') {
    return writeJson(response, { events: [], total: 0 });
  }
  if (pathname === '/api/calendar/upcoming') {
    return writeJson(response, { events: [] });
  }
  if (pathname === '/api/todos/') {
    return writeJson(response, { todos: [] });
  }
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
  if (pathname === '/api/chat/conversations') {
    return writeJson(response, []);
  }

  const emailMatch = pathname.match(/^\/api\/emails\/(\d+)$/);
  if (emailMatch) {
    const email = emailsById.get(Number(emailMatch[1]));
    return writeJson(response, email || { detail: 'Generated email not found' }, email ? 200 : 404);
  }

  audit.unknown_routes.push(auditEntry(request, pathname));
  return writeJson(response, { detail: `No generated read-only QA route for GET ${pathname}` }, 404);
}

function handleRequest(request, response) {
  const url = new URL(request.url, `http://${host}:${port}`);
  const { pathname } = url;

  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method)) {
    audit.mutation_attempts.push(auditEntry(request, pathname));
    return writeJson(
      response,
      { detail: 'Generated command-palette QA is read-only' },
      405,
      { Allow: 'GET' },
    );
  }
  if (request.method === 'GET') return handleGet(request, response, url);

  audit.unknown_routes.push(auditEntry(request, pathname));
  return writeJson(response, { detail: `Unsupported method ${request.method}` }, 405, { Allow: 'GET' });
}

const server = createServer((request, response) => {
  try {
    handleRequest(request, response);
  } catch (error) {
    writeJson(response, { detail: error.message }, 500);
  }
});

server.listen(port, host, () => {
  process.stdout.write(`Generated command-palette QA API listening on http://${host}:${port}\n`);
});

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
