import { analyzeEmailSearch } from './emailSearch.js';

export const MAX_SAVED_VIEWS = 12;
export const MAX_SAVED_VIEW_NAME_CHARS = 80;
export const MAX_SAVED_VIEW_QUERY_CHARS = 512;

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function fail(message) {
  throw new Error(`Invalid saved views response: ${message}`);
}

function positiveInteger(value, field) {
  if (!Number.isSafeInteger(value) || value < 1) fail(`${field} must be a positive integer`);
  return value;
}

function nonNegativeInteger(value, field) {
  if (!Number.isSafeInteger(value) || value < 0) fail(`${field} must be a non-negative integer`);
  return value;
}

function uuid(value, field) {
  if (typeof value !== 'string' || !UUID_PATTERN.test(value)) fail(`${field} must be a UUID`);
  return value.toLowerCase();
}

function timestamp(value, field) {
  if (typeof value !== 'string' || !Number.isFinite(Date.parse(value))) fail(`${field} must be an ISO timestamp`);
  return value;
}

export function normalizeSavedViewName(value) {
  if (typeof value !== 'string') throw new Error('Saved view name is required.');
  const name = value.trim().replace(/\s+/g, ' ');
  if (!name) throw new Error('Saved view name is required.');
  if (name.length > MAX_SAVED_VIEW_NAME_CHARS) {
    throw new Error(`Saved view names are limited to ${MAX_SAVED_VIEW_NAME_CHARS} characters.`);
  }
  return name;
}

export function normalizeSavedViewQuery(value) {
  if (typeof value !== 'string') throw new Error('A structured search is required.');
  const query = value.trim();
  if (!query) throw new Error('A structured search is required.');
  if (query.length > MAX_SAVED_VIEW_QUERY_CHARS) {
    throw new Error(`Saved view searches are limited to ${MAX_SAVED_VIEW_QUERY_CHARS} characters.`);
  }
  const analysis = analyzeEmailSearch(query);
  if (!analysis.valid || analysis.clauses.length === 0) {
    throw new Error(analysis.error?.message || 'Fix the structured search before saving this view.');
  }
  return query;
}

export function normalizeSavedViewAccountId(value) {
  if (value === null) return null;
  if (!Number.isSafeInteger(value) || value < 1) throw new Error('Choose a connected account or All accounts.');
  return value;
}

export function normalizeSavedView(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) fail('view must be an object');
  return Object.freeze({
    id: uuid(raw.id, 'id'),
    create_id: uuid(raw.create_id, 'create_id'),
    name: normalizeSavedViewName(raw.name),
    account_id: normalizeSavedViewAccountId(raw.account_id),
    query: normalizeSavedViewQuery(raw.query),
    revision: positiveInteger(raw.revision, 'revision'),
    position: nonNegativeInteger(raw.position, 'position'),
    created_at: timestamp(raw.created_at, 'created_at'),
    updated_at: timestamp(raw.updated_at, 'updated_at'),
  });
}

export function normalizeSavedViewsResponse(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) fail('collection must be an object');
  if (!Array.isArray(raw.items)) fail('items must be an array');
  if (raw.max_views !== MAX_SAVED_VIEWS) fail(`max_views must equal ${MAX_SAVED_VIEWS}`);
  if (raw.items.length > MAX_SAVED_VIEWS) fail('too many items');

  const items = raw.items.map(normalizeSavedView).sort((a, b) => a.position - b.position);
  const ids = new Set();
  const createIds = new Set();
  const positions = new Set();
  for (const item of items) {
    if (ids.has(item.id)) fail('duplicate id');
    if (createIds.has(item.create_id)) fail('duplicate create_id');
    if (positions.has(item.position)) fail('duplicate position');
    ids.add(item.id);
    createIds.add(item.create_id);
    positions.add(item.position);
  }
  return Object.freeze({ items: Object.freeze(items), max_views: MAX_SAVED_VIEWS });
}

function bodyFields({ name, accountId, query }) {
  return {
    name: normalizeSavedViewName(name),
    account_id: normalizeSavedViewAccountId(accountId),
    query: normalizeSavedViewQuery(query),
  };
}

export function createSavedViewPayload({ createId, name, accountId = null, query }) {
  return { create_id: uuid(createId, 'create_id'), ...bodyFields({ name, accountId, query }) };
}

export function replaceSavedViewPayload({ revision, name, accountId = null, query }) {
  return { revision: positiveInteger(revision, 'revision'), ...bodyFields({ name, accountId, query }) };
}

export function reorderSavedViewsPayload(currentItems, desiredIds) {
  const expected_order = currentItems.map(item => uuid(item.id, 'id'));
  const view_ids = desiredIds.map(id => uuid(id, 'id'));
  if (expected_order.length > MAX_SAVED_VIEWS || view_ids.length !== expected_order.length) {
    throw new Error('Saved view order must include every view exactly once.');
  }
  if (new Set(view_ids).size !== view_ids.length || view_ids.some(id => !expected_order.includes(id))) {
    throw new Error('Saved view order must include every view exactly once.');
  }
  return { expected_order, view_ids };
}

export function savedViewMatches(view, accountId, query) {
  if (!view) return false;
  try {
    return view.account_id === normalizeSavedViewAccountId(accountId)
      && view.query === normalizeSavedViewQuery(query);
  } catch {
    return false;
  }
}

export function isSavableStructuredSearch(query) {
  try {
    normalizeSavedViewQuery(query);
    return true;
  } catch {
    return false;
  }
}
