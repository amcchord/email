#!/usr/bin/env node

// Deterministic local-only API for cross-session browser QA. It serves two
// generated users and can hold a User A Todo response until after User B has
// signed in. It never reads Gmail, credentials, production configuration, or
// mailbox data, and it rejects every non-authentication mutation.

import { createServer } from 'node:http';

const port = Number.parseInt(process.env.QA_API_PORT || '8000', 10);

const users = Object.freeze({
  'generated-a': Object.freeze({ id: 9101, username: 'generated-a', is_admin: false }),
  'generated-b': Object.freeze({ id: 9102, username: 'generated-b', is_admin: false }),
});

const accountsByUser = Object.freeze({
  9101: [Object.freeze({
    id: 9201,
    email: 'owner-a@example.test',
    display_name: 'Generated Owner A',
    description: 'Primary generated account',
    has_calendar_scope: true,
    sync_status: { status: 'idle' },
    calendar_sync_status: { status: 'idle' },
  })],
  9102: [Object.freeze({
    id: 9202,
    email: 'owner-b@example.test',
    display_name: 'Generated Owner B',
    description: 'Primary generated account',
    has_calendar_scope: true,
    sync_status: { status: 'idle' },
    calendar_sync_status: { status: 'idle' },
  })],
});

const todosByUser = Object.freeze({
  9101: [Object.freeze({
    id: 9301,
    user_id: 9101,
    email_id: null,
    title: 'GENERATED_A_PRIVATE_TODO_MARKER',
    status: 'pending',
    source: 'manual',
    created_at: '2026-08-30T15:00:00Z',
    completed_at: null,
    ai_draft_status: null,
    ai_draft_body: null,
    ai_draft_to: null,
  })],
  9102: [Object.freeze({
    id: 9302,
    user_id: 9102,
    email_id: null,
    title: 'Generated B current-session todo',
    status: 'pending',
    source: 'manual',
    created_at: '2026-08-30T15:01:00Z',
    completed_at: null,
    ai_draft_status: null,
    ai_draft_body: null,
    ai_draft_to: null,
  })],
});

let currentUser = null;
let holdUserATodos = true;
const heldTodoResponses = [];
const authTransitions = [];
const mutationAttempts = [];
const unknownRoutes = [];

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
  if (chunks.length === 0) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    return {};
  }
}

function requireUser(response) {
  if (currentUser) return true;
  writeJson(response, { detail: 'Unauthorized' }, 401);
  return false;
}

function generatedEmptyMailPage() {
  return { emails: [], total: 0, page: 1, page_size: 50 };
}

function generatedFlowPayload(pathname) {
  if (pathname === '/api/ai/needs-reply') return { emails: [], total: 0 };
  if (pathname === '/api/ai/trends') return { summary: '', needs_attention: [] };
  if (pathname === '/api/ai/awaiting-response') return { emails: [], total: 0 };
  if (pathname === '/api/ai/digests') return { digests: [], total: 0 };
  return null;
}

async function handleRequest(request, response) {
  const url = new URL(request.url, `http://${request.headers.host}`);
  const { pathname } = url;

  if (request.method === 'GET' && pathname === '/api/auth/me') {
    return currentUser
      ? writeJson(response, currentUser)
      : writeJson(response, { detail: 'Unauthorized' }, 401);
  }
  if (request.method === 'POST' && pathname === '/api/auth/refresh') {
    return currentUser
      ? writeJson(response, { refreshed: true })
      : writeJson(response, { detail: 'Unauthorized' }, 401);
  }
  if (request.method === 'POST' && pathname === '/api/auth/login') {
    const body = await readJson(request);
    const nextUser = users[body.username];
    if (!nextUser) return writeJson(response, { detail: 'Invalid generated user' }, 401);
    currentUser = nextUser;
    authTransitions.push({ sequence: authTransitions.length + 1, action: 'login', user_id: currentUser.id });
    return writeJson(response, { access_token: 'generated-only', user: currentUser });
  }
  if (request.method === 'POST' && pathname === '/api/auth/logout') {
    authTransitions.push({
      sequence: authTransitions.length + 1,
      action: 'logout',
      user_id: currentUser?.id || null,
    });
    currentUser = null;
    return writeJson(response, { message: 'Logged out' });
  }

  if (request.method === 'GET' && pathname === '/__qa/audit') {
    return writeJson(response, {
      currentUser,
      holdUserATodos,
      heldTodoResponseCount: heldTodoResponses.length,
      authTransitions,
      mutationAttempts,
      unknownRoutes,
    });
  }
  if (request.method === 'POST' && pathname === '/__qa/release-user-a-todos') {
    holdUserATodos = false;
    const pending = heldTodoResponses.splice(0);
    for (const heldResponse of pending) {
      writeJson(heldResponse, { todos: todosByUser[9101], total: 1 });
    }
    return writeJson(response, { released: pending.length });
  }
  if (request.method === 'POST' && pathname === '/__qa/reset') {
    currentUser = null;
    holdUserATodos = true;
    while (heldTodoResponses.length > 0) {
      writeJson(heldTodoResponses.shift(), { detail: 'Generated QA reset' }, 409);
    }
    authTransitions.length = 0;
    mutationAttempts.length = 0;
    unknownRoutes.length = 0;
    return writeJson(response, { reset: true });
  }

  if (!pathname.startsWith('/api/') || !requireUser(response)) return;

  if (request.method === 'GET' && pathname === '/api/auth/ui-preferences') {
    return writeJson(response, { thread_order: 'asc', theme: 'default', color_scheme: 'light' });
  }
  if (request.method === 'GET' && pathname === '/api/auth/keyboard-shortcuts') {
    return writeJson(response, { shortcuts: {} });
  }
  if (request.method === 'GET' && pathname === '/api/accounts/') {
    return writeJson(response, accountsByUser[currentUser.id]);
  }
  if (request.method === 'GET' && pathname === '/api/build-version') {
    return writeJson(response, { version: 'generated-session-isolation-qa' });
  }
  if (request.method === 'GET' && pathname === '/api/events/stream') {
    response.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
    });
    response.write(': generated session-isolation QA stream\n\n');
    request.on('close', () => response.end());
    return;
  }
  if (request.method === 'GET' && pathname === '/api/emails/labels/all') {
    return writeJson(response, []);
  }
  if (request.method === 'GET' && pathname === '/api/emails/actions/recent') {
    return writeJson(response, []);
  }
  if (request.method === 'GET' && pathname === '/api/emails/') {
    return writeJson(response, generatedEmptyMailPage());
  }
  if (request.method === 'GET' && pathname === '/api/calendar/upcoming') {
    return writeJson(response, { events: [] });
  }
  if (request.method === 'GET' && pathname === '/api/chat/conversations') {
    return writeJson(response, []);
  }
  const flowPayload = generatedFlowPayload(pathname);
  if (request.method === 'GET' && flowPayload) return writeJson(response, flowPayload);

  if (request.method === 'GET' && pathname === '/api/todos/') {
    const requestUserId = currentUser.id;
    if (requestUserId === 9101 && holdUserATodos) {
      heldTodoResponses.push(response);
      request.on('close', () => {
        const index = heldTodoResponses.indexOf(response);
        if (index >= 0) heldTodoResponses.splice(index, 1);
      });
      return;
    }
    const todos = todosByUser[requestUserId] || [];
    return writeJson(response, { todos, total: todos.length });
  }

  if (request.method !== 'GET') {
    mutationAttempts.push({ method: request.method, pathname, user_id: currentUser.id });
    return writeJson(response, { detail: 'Generated QA rejects non-authentication mutations' }, 409);
  }

  unknownRoutes.push({ method: request.method, pathname, user_id: currentUser.id });
  return writeJson(response, { detail: 'Unknown generated QA route' }, 404);
}

const server = createServer((request, response) => {
  void handleRequest(request, response).catch(error => {
    writeJson(response, { detail: `Generated QA server failure: ${error.message}` }, 500);
  });
});

server.listen(port, '127.0.0.1', () => {
  process.stdout.write(`Generated session-isolation QA server listening on http://127.0.0.1:${port}\n`);
});

function shutdown() {
  while (heldTodoResponses.length > 0) {
    writeJson(heldTodoResponses.shift(), { detail: 'Generated QA server stopped' }, 503);
  }
  server.close(() => process.exit(0));
}

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
