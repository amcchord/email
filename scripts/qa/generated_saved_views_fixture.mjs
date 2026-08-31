#!/usr/bin/env node

// Deterministic, in-memory Saved Views API for generated browser QA. The
// fixture has no network or provider client and stores only bounded names,
// validated search text, opaque UUIDs, and exact generated account scope.

const MAX_VIEWS = 12;
const GENERATED_USERS = Object.freeze({
  'generated-a': Object.freeze({
    id: 1,
    username: 'saved-view-user-a@example.test',
    account_ids: Object.freeze([1, 2]),
  }),
  'generated-b': Object.freeze({
    id: 2,
    username: 'saved-view-user-b@example.test',
    account_ids: Object.freeze([3]),
  }),
});

const GENERATED_ACCOUNTS = Object.freeze({
  1: Object.freeze({
    id: 1,
    email: 'search.primary@example.test',
    display_name: 'Generated Search Primary',
    description: 'Generated Search Primary',
    short_label: 'Primary',
    is_active: true,
    has_calendar_scope: true,
  }),
  2: Object.freeze({
    id: 2,
    email: 'search.secondary@example.test',
    display_name: 'Generated Search Secondary',
    description: 'Generated Search Secondary',
    short_label: 'Secondary',
    is_active: true,
    has_calendar_scope: true,
  }),
  3: Object.freeze({
    id: 3,
    email: 'search.user-b@example.test',
    display_name: 'Generated Search User B',
    description: 'Generated Search User B',
    short_label: 'User B',
    is_active: true,
    has_calendar_scope: false,
  }),
});

const IDS = Object.freeze({
  primary: '42b9e2c4-971d-4a11-bf8c-68f457496f21',
  primaryCreate: '90ddf129-7dab-4422-a2b0-a2ae1425e90a',
  secondary: 'ca2f8ef6-5c48-4050-8832-a12ddc17ff6a',
  secondaryCreate: 'cf7e3901-2f0b-469e-a1a2-9b9d50855f66',
  foreign: '72727272-cf14-4a8b-9589-d984385616c8',
  foreignCreate: 'c66da2e3-ef3f-40f9-9539-391809e1e9f1',
});

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const CONTROL_PATTERN = /[\u0000-\u001f\u007f]/;

function copy(value) {
  return JSON.parse(JSON.stringify(value));
}

function seededViews() {
  return new Map([
    ['generated-a', [
      {
        id: IDS.primary,
        create_id: IDS.primaryCreate,
        name: 'Generated Launch',
        account_id: 1,
        query: 'from:renee+launch@example.test subject:"Quarterly & Planning" has:attachment -is:read in:inbox',
        revision: 3,
        position: 0,
        created_at: '2026-08-30T13:00:00Z',
        updated_at: '2026-08-30T13:30:00Z',
      },
      {
        id: IDS.secondary,
        create_id: IDS.secondaryCreate,
        name: 'Generated Secondary',
        account_id: 2,
        query: 'from:renee+launch@example.test subject:"Quarterly & Planning" -is:read in:inbox',
        revision: 1,
        position: 1,
        created_at: '2026-08-30T13:10:00Z',
        updated_at: '2026-08-30T13:10:00Z',
      },
    ]],
    ['generated-b', [
      {
        id: IDS.foreign,
        create_id: IDS.foreignCreate,
        name: 'Generated User B Only',
        account_id: 3,
        query: 'from:renee+launch@example.test subject:"Quarterly & Planning" has:attachment -is:read in:inbox',
        revision: 7,
        position: 0,
        created_at: '2026-08-30T12:00:00Z',
        updated_at: '2026-08-30T12:30:00Z',
      },
    ]],
  ]);
}

function freshCounters() {
  return {
    list_requests: 0,
    creates: 0,
    updates: 0,
    deletes: 0,
    reorders: 0,
    conflicts: 0,
    validation_errors: 0,
    auth_rejections: 0,
    ownership_rejections: 0,
    held_requests: 0,
    transient_failures: 0,
    expected_local_mutations: 0,
    mail_mutations: 0,
    calendar_mutations: 0,
    provider_mutations: 0,
    provider_sends: 0,
    external_network_calls: 0,
  };
}

function writeJson(response, payload, status = 200) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
    'Cache-Control': 'private, no-store',
  });
  response.end(body);
}

function writeEmpty(response, status = 204) {
  response.writeHead(status, { 'Cache-Control': 'private, no-store' });
  response.end();
}

function detail(code, message) {
  return { detail: { code, message } };
}

async function readJson(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > 16_384) throw Object.assign(new Error('Request body is too large'), { status: 422 });
    chunks.push(chunk);
  }
  if (chunks.length === 0) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    throw Object.assign(new Error('Request body must be valid JSON'), { status: 422 });
  }
}

function validateName(value) {
  if (typeof value !== 'string') throw new Error('name must be a string');
  const name = value.trim().replace(/\s+/g, ' ');
  if (!name || name.length > 80 || CONTROL_PATTERN.test(name)) {
    throw new Error('name must contain 1 to 80 printable characters');
  }
  return name;
}

function validateQuery(value) {
  if (typeof value !== 'string') throw new Error('query must be a string');
  const query = value.trim();
  if (!query || query.length > 512 || CONTROL_PATTERN.test(query)) {
    throw new Error('query must contain 1 to 512 printable characters');
  }
  if (query.includes('(') || query.includes(')')) throw new Error('Parentheses are not supported');
  const quoteCount = [...query].filter(character => character === '"').length;
  if (quoteCount % 2 !== 0) throw new Error('Search contains an unterminated quote');
  return query;
}

function validateUuid(value, fieldName) {
  if (typeof value !== 'string' || !UUID_PATTERN.test(value)) {
    throw new Error(`${fieldName} must be a UUID`);
  }
  return value.toLowerCase();
}

function validateRevision(value) {
  if (!Number.isSafeInteger(value) || value < 1) throw new Error('revision must be a positive integer');
  return value;
}

export function createGeneratedSavedViewsFixture() {
  let viewsByUser = seededViews();
  let counters = freshCounters();
  let requests = [];
  let currentUserKey = 'generated-a';
  let sessionGeneration = 1;
  let sequence = 0;
  let failureRemaining = 0;
  let holdNextList = false;
  let heldRelease = null;
  let heldPromise = null;

  function currentUser() {
    return GENERATED_USERS[currentUserKey] || null;
  }

  function ownedAccounts(userKey = currentUserKey) {
    const user = GENERATED_USERS[userKey];
    if (!user) return [];
    return user.account_ids.map(accountId => ({
      ...GENERATED_ACCOUNTS[accountId],
      sync_status: { status: 'idle', last_incremental_sync: '2026-08-30T14:00:00.000Z' },
      calendar_sync_status: accountId === 3 ? null : { status: 'idle' },
    }));
  }

  function ownsAccount(accountId, userKey = currentUserKey) {
    if (accountId === null) return true;
    return GENERATED_USERS[userKey]?.account_ids.includes(accountId) || false;
  }

  function ordered(userKey) {
    return [...(viewsByUser.get(userKey) || [])].sort((left, right) => (
      left.position - right.position || left.id.localeCompare(right.id)
    ));
  }

  function responseList(userKey) {
    return { items: copy(ordered(userKey)), max_views: MAX_VIEWS };
  }

  function timestamp() {
    sequence += 1;
    return new Date(Date.parse('2026-08-30T14:00:00Z') + sequence * 1000).toISOString();
  }

  function audit(action, status, extra = {}) {
    requests.push({
      sequence: requests.length + 1,
      action,
      user: currentUserKey,
      session_generation: sessionGeneration,
      status,
      ...extra,
    });
  }

  function rejectAuth(response, action) {
    counters.auth_rejections += 1;
    audit(action, 401);
    writeJson(response, { detail: 'Not authenticated' }, 401);
  }

  function rejectValidation(response, action, message) {
    counters.validation_errors += 1;
    audit(action, 422);
    writeJson(response, detail('saved_view_validation', message), 422);
  }

  function validatePayload(payload, userKey, { create = false } = {}) {
    const accountId = payload.account_id === null ? null : Number(payload.account_id);
    if (payload.account_id !== null && (!Number.isSafeInteger(accountId) || accountId < 1)) {
      throw new Error('account_id must be null or a positive integer');
    }
    if (!ownsAccount(accountId, userKey)) {
      throw Object.assign(new Error('Account not found'), { status: 404, ownership: true });
    }
    return {
      ...(create ? { create_id: validateUuid(payload.create_id, 'create_id') } : {}),
      name: validateName(payload.name),
      account_id: accountId,
      query: validateQuery(payload.query),
    };
  }

  async function maybeFail(response, action) {
    if (failureRemaining < 1) return false;
    failureRemaining -= 1;
    counters.transient_failures += 1;
    audit(action, 503);
    writeJson(response, { detail: 'Generated Saved Views service is temporarily unavailable' }, 503);
    return true;
  }

  async function handleControl(request, response, url) {
    if (url.pathname === '/api/test/saved-views-audit' && request.method === 'GET') {
      return writeJson(response, {
        fixture: 'generated-saved-views',
        localhost_only: true,
        fixture_domains: ['example.test'],
        allowed_routes: [
          'GET /api/saved-views',
          'POST /api/saved-views',
          'PUT /api/saved-views/{id}',
          'DELETE /api/saved-views/{id}?revision=N',
          'POST /api/saved-views/reorder',
        ],
        current_user: currentUserKey,
        session_generation: sessionGeneration,
        fixture_account_ids: currentUser()?.account_ids || [],
        counters: copy(counters),
        requests: copy(requests),
        pending_held_requests: heldRelease ? 1 : 0,
      });
    }

    if (request.method !== 'POST') return false;
    if (url.pathname === '/api/test/saved-views/reset') {
      const payload = await readJson(request);
      const requestedUser = payload.current_user || 'generated-a';
      if (requestedUser !== 'anonymous' && !GENERATED_USERS[requestedUser]) {
        return writeJson(response, { detail: 'Unknown generated user' }, 422);
      }
      viewsByUser = seededViews();
      counters = freshCounters();
      requests = [];
      currentUserKey = requestedUser;
      sessionGeneration += 1;
      sequence = 0;
      failureRemaining = 0;
      holdNextList = false;
      if (heldRelease) heldRelease();
      heldRelease = null;
      heldPromise = null;
      return writeJson(response, { current_user: currentUserKey, session_generation: sessionGeneration });
    }
    if (url.pathname === '/api/test/saved-views/session') {
      const payload = await readJson(request);
      if (payload.current_user !== 'anonymous' && !GENERATED_USERS[payload.current_user]) {
        return writeJson(response, { detail: 'Unknown generated user' }, 422);
      }
      currentUserKey = payload.current_user;
      sessionGeneration += 1;
      return writeJson(response, { current_user: currentUserKey, session_generation: sessionGeneration });
    }
    if (url.pathname === '/api/test/saved-views/scenario') {
      const payload = await readJson(request);
      if (!['clean', 'fail-next', 'hold-next-list'].includes(payload.scenario)) {
        return writeJson(response, { detail: 'Unknown generated scenario' }, 422);
      }
      failureRemaining = payload.scenario === 'fail-next' ? 1 : 0;
      holdNextList = payload.scenario === 'hold-next-list';
      return writeJson(response, { scenario: payload.scenario });
    }
    if (url.pathname === '/api/test/saved-views/release') {
      if (heldRelease) heldRelease();
      heldRelease = null;
      heldPromise = null;
      return writeJson(response, { released: true });
    }
    return false;
  }

  async function handle(request, response, url) {
    const controlPath = url.pathname.startsWith('/api/test/saved-views');
    if (controlPath) {
      const handled = await handleControl(request, response, url);
      return handled === false ? false : true;
    }

    if (url.pathname !== '/api/saved-views'
      && url.pathname !== '/api/saved-views/reorder'
      && !/^\/api\/saved-views\/[^/]+$/.test(url.pathname)) return false;

    const requestUserKey = currentUserKey;
    if (!GENERATED_USERS[requestUserKey]) {
      rejectAuth(response, 'auth');
      return true;
    }

    const action = request.method === 'GET'
      ? 'list'
      : url.pathname === '/api/saved-views/reorder'
        ? 'reorder'
        : request.method === 'POST'
          ? 'create'
          : request.method === 'PUT'
            ? 'update'
            : request.method === 'DELETE'
              ? 'delete'
              : 'unsupported';

    if (await maybeFail(response, action)) return true;

    if (request.method === 'GET' && url.pathname === '/api/saved-views') {
      counters.list_requests += 1;
      if (holdNextList) {
        holdNextList = false;
        counters.held_requests += 1;
        heldPromise = new Promise(resolve => { heldRelease = resolve; });
        await heldPromise;
        heldPromise = null;
        heldRelease = null;
      }
      const payload = responseList(requestUserKey);
      audit('list', 200, { item_count: payload.items.length, request_user: requestUserKey });
      writeJson(response, payload);
      return true;
    }

    if (request.method === 'POST' && url.pathname === '/api/saved-views') {
      let payload;
      try {
        payload = validatePayload(await readJson(request), requestUserKey, { create: true });
      } catch (error) {
        if (error.status === 404) {
          counters.ownership_rejections += 1;
          audit('create', 404);
          writeJson(response, detail('saved_view_not_found', 'Saved view not found'), 404);
        } else rejectValidation(response, 'create', error.message);
        return true;
      }
      const views = viewsByUser.get(requestUserKey);
      const replay = views.find(view => view.create_id === payload.create_id);
      if (replay) {
        const matches = ['name', 'account_id', 'query'].every(field => replay[field] === payload[field]);
        if (!matches) {
          counters.conflicts += 1;
          audit('create', 409, { resource_id: replay.id });
          writeJson(response, detail('saved_view_conflict', 'create_id already belongs to another saved view'), 409);
        } else {
          audit('create-replay', 200, { resource_id: replay.id });
          writeJson(response, copy(replay));
        }
        return true;
      }
      if (views.length >= MAX_VIEWS) {
        counters.conflicts += 1;
        audit('create', 409);
        writeJson(response, detail('saved_view_limit', 'Saved view limit reached'), 409);
        return true;
      }
      const now = timestamp();
      const item = {
        id: `00000000-0000-4000-8000-${String(sequence).padStart(12, '0')}`,
        ...payload,
        revision: 1,
        position: views.length,
        created_at: now,
        updated_at: now,
      };
      views.push(item);
      counters.creates += 1;
      counters.expected_local_mutations += 1;
      audit('create', 201, { resource_id: item.id, account_id: item.account_id });
      writeJson(response, copy(item), 201);
      return true;
    }

    if (request.method === 'POST' && url.pathname === '/api/saved-views/reorder') {
      let payload;
      try {
        payload = await readJson(request);
        if (!Array.isArray(payload.expected_order) || !Array.isArray(payload.view_ids)) {
          throw new Error('expected_order and view_ids must be arrays');
        }
        payload.expected_order = payload.expected_order.map(value => validateUuid(value, 'expected_order item'));
        payload.view_ids = payload.view_ids.map(value => validateUuid(value, 'view_ids item'));
      } catch (error) {
        rejectValidation(response, 'reorder', error.message);
        return true;
      }
      const current = ordered(requestUserKey);
      const currentIds = current.map(view => view.id);
      const uniqueIds = new Set(payload.view_ids);
      if (uniqueIds.size !== currentIds.length
        || payload.view_ids.length !== currentIds.length
        || currentIds.some(id => !uniqueIds.has(id))) {
        counters.conflicts += 1;
        audit('reorder', 409);
        writeJson(response, detail('saved_view_conflict', 'Saved view reorder must contain the exact collection'), 409);
        return true;
      }
      if (payload.expected_order.length !== currentIds.length
        || currentIds.some((id, index) => payload.expected_order[index] !== id)) {
        counters.conflicts += 1;
        audit('reorder', 409);
        writeJson(response, detail('saved_view_conflict', 'Saved view order changed elsewhere'), 409);
        return true;
      }
      const byId = new Map(current.map(view => [view.id, view]));
      const now = timestamp();
      const reordered = payload.view_ids.map((id, position) => {
        const item = byId.get(id);
        if (item.position !== position) {
          item.position = position;
          item.revision += 1;
          item.updated_at = now;
        }
        return item;
      });
      viewsByUser.set(requestUserKey, reordered);
      counters.reorders += 1;
      counters.expected_local_mutations += 1;
      audit('reorder', 200, { item_count: reordered.length });
      writeJson(response, responseList(requestUserKey));
      return true;
    }

    const match = url.pathname.match(/^\/api\/saved-views\/([^/]+)$/);
    if (!match) return false;
    let resourceId;
    try {
      resourceId = validateUuid(decodeURIComponent(match[1]), 'id');
    } catch (error) {
      rejectValidation(response, action, error.message);
      return true;
    }
    const views = viewsByUser.get(requestUserKey);
    const index = views.findIndex(view => view.id === resourceId);
    if (index < 0) {
      counters.ownership_rejections += 1;
      audit(action, 404, { resource_id: resourceId });
      writeJson(response, detail('saved_view_not_found', 'Saved view not found'), 404);
      return true;
    }
    const existing = views[index];

    if (request.method === 'PUT') {
      let payload;
      try {
        const body = await readJson(request);
        payload = {
          revision: validateRevision(body.revision),
          ...validatePayload(body, requestUserKey),
        };
      } catch (error) {
        if (error.status === 404) {
          counters.ownership_rejections += 1;
          audit('update', 404, { resource_id: resourceId });
          writeJson(response, detail('saved_view_not_found', 'Saved view not found'), 404);
        } else rejectValidation(response, 'update', error.message);
        return true;
      }
      if (payload.revision !== existing.revision) {
        const replay = payload.revision + 1 === existing.revision
          && ['name', 'account_id', 'query'].every(field => payload[field] === existing[field]);
        if (replay) {
          audit('update-replay', 200, { resource_id: resourceId });
          writeJson(response, copy(existing));
          return true;
        }
        counters.conflicts += 1;
        audit('update', 409, { resource_id: resourceId });
        writeJson(response, detail('saved_view_conflict', 'Saved view changed elsewhere'), 409);
        return true;
      }
      const updated = {
        ...existing,
        name: payload.name,
        account_id: payload.account_id,
        query: payload.query,
        revision: existing.revision + 1,
        updated_at: timestamp(),
      };
      views[index] = updated;
      counters.updates += 1;
      counters.expected_local_mutations += 1;
      audit('update', 200, { resource_id: resourceId, account_id: updated.account_id });
      writeJson(response, copy(updated));
      return true;
    }

    if (request.method === 'DELETE') {
      let revision;
      try {
        revision = validateRevision(Number(url.searchParams.get('revision')));
      } catch (error) {
        rejectValidation(response, 'delete', error.message);
        return true;
      }
      if (revision !== existing.revision) {
        counters.conflicts += 1;
        audit('delete', 409, { resource_id: resourceId });
        writeJson(response, detail('saved_view_conflict', 'Saved view changed elsewhere'), 409);
        return true;
      }
      views.splice(index, 1);
      const now = timestamp();
      views.forEach((view, position) => {
        if (view.position !== position) {
          view.position = position;
          view.revision += 1;
          view.updated_at = now;
        }
      });
      counters.deletes += 1;
      counters.expected_local_mutations += 1;
      audit('delete', 204, { resource_id: resourceId });
      writeEmpty(response);
      return true;
    }

    writeJson(response, { detail: `Method ${request.method} not allowed` }, 405);
    return true;
  }

  return {
    handle,
    currentAuthUser: currentUser,
    currentAccounts: ownedAccounts,
    currentUserOwnsAccount: ownsAccount,
    snapshot: () => ({ counters: copy(counters), requests: copy(requests) }),
  };
}
