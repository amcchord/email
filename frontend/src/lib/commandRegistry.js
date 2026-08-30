/**
 * Pure helpers for building a deterministic command-palette registry.
 *
 * Commands may provide `label`, `keywords`, `id`, `category`, `shortcut`, and
 * either `context` or `contexts`. Unscoped commands and commands whose context
 * is `global` are available everywhere.
 */

const NO_MATCH = -1;

export function normalizeCommandQuery(value) {
  return String(value ?? '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .trim()
    .replace(/\s+/g, ' ');
}

function normalizedValues(value) {
  const values = Array.isArray(value) ? value : [value];
  return values
    .map(normalizeCommandQuery)
    .filter(Boolean);
}

function fieldScore(token, values, weights) {
  let best = NO_MATCH;

  for (const value of values) {
    if (value === token) {
      best = Math.max(best, weights.exact);
      continue;
    }

    const words = value.split(/[^a-z0-9]+/).filter(Boolean);
    if (words.some(word => word === token)) {
      best = Math.max(best, weights.wordExact);
    } else if (words.some(word => word.startsWith(token))) {
      best = Math.max(best, weights.wordPrefix);
    } else if (value.includes(token)) {
      best = Math.max(best, weights.contains);
    }
  }

  return best;
}

/**
 * Return a comparable score, or -1 when every query token cannot be matched.
 * Exact and prefix label matches occupy dedicated tiers above field matches.
 */
export function scoreCommand(command, query) {
  const normalizedQuery = normalizeCommandQuery(query);
  if (!normalizedQuery) return 0;

  const label = normalizeCommandQuery(command?.label);
  if (label === normalizedQuery) return 100_000;
  if (label.startsWith(normalizedQuery)) return 90_000;

  const fields = [
    [label ? [label] : [], { exact: 800, wordExact: 780, wordPrefix: 720, contains: 660 }],
    [normalizedValues(command?.keywords), { exact: 600, wordExact: 580, wordPrefix: 540, contains: 500 }],
    [normalizedValues(command?.id), { exact: 480, wordExact: 460, wordPrefix: 420, contains: 380 }],
    [normalizedValues(command?.category), { exact: 360, wordExact: 340, wordPrefix: 300, contains: 260 }],
    [normalizedValues(command?.shortcut), { exact: 240, wordExact: 220, wordPrefix: 180, contains: 140 }],
  ];

  let score = 0;
  for (const token of normalizedQuery.split(' ')) {
    let tokenScore = NO_MATCH;
    for (const [values, weights] of fields) {
      tokenScore = Math.max(tokenScore, fieldScore(token, values, weights));
    }
    if (tokenScore === NO_MATCH) return NO_MATCH;
    score += tokenScore;
  }

  return score;
}

/**
 * Rank matching commands without mutating the supplied list. Equal scores use
 * original input position as the stable tie-breaker. An empty query returns a
 * shallow copy in exactly the supplied order.
 */
export function rankCommands(commands, query) {
  const list = Array.isArray(commands) ? commands : [];
  const normalizedQuery = normalizeCommandQuery(query);
  if (!normalizedQuery) return [...list];

  return list
    .map((command, index) => ({ command, index, score: scoreCommand(command, normalizedQuery) }))
    .filter(result => result.score !== NO_MATCH)
    .sort((left, right) => right.score - left.score || left.index - right.index)
    .map(result => result.command);
}

function commandContexts(command) {
  const raw = command?.contexts ?? command?.context;
  if (raw == null) return [];
  return normalizedValues(raw);
}

export function commandMatchesContext(command, context) {
  if (command?.global === true) return true;

  const contexts = commandContexts(command);
  if (contexts.length === 0 || contexts.includes('global') || contexts.includes('*')) {
    return true;
  }

  const activeContexts = normalizedValues(context);
  return activeContexts.some(activeContext => contexts.includes(activeContext));
}

export function filterCommandsByContext(commands, context) {
  const list = Array.isArray(commands) ? commands : [];
  return list.filter(command => commandMatchesContext(command, context));
}

export function getVisibleCommands(commands, { context = null, query = '' } = {}) {
  return rankCommands(filterCommandsByContext(commands, context), query);
}

function selectionLength(itemCount) {
  const count = Number(itemCount);
  if (!Number.isFinite(count) || count <= 0) return 0;
  return Math.floor(count);
}

export function clampSelectionIndex(index, itemCount) {
  const count = selectionLength(itemCount);
  if (count === 0) return -1;

  const candidate = Number(index);
  if (!Number.isFinite(candidate)) return 0;
  return Math.min(count - 1, Math.max(0, Math.trunc(candidate)));
}

export function wrapSelectionIndex(index, itemCount) {
  const count = selectionLength(itemCount);
  if (count === 0) return -1;

  const candidate = Number(index);
  if (!Number.isFinite(candidate)) return 0;
  return ((Math.trunc(candidate) % count) + count) % count;
}

export function moveSelectionIndex(index, delta, itemCount, { wrap = true } = {}) {
  const count = selectionLength(itemCount);
  if (count === 0) return -1;

  const movement = Number.isFinite(Number(delta)) ? Math.trunc(Number(delta)) : 0;
  const candidate = Number(index);
  let current;
  if (!Number.isFinite(candidate) || candidate < 0) {
    current = movement < 0 ? count : -1;
  } else {
    current = clampSelectionIndex(candidate, count);
  }
  const next = current + movement;
  return wrap ? wrapSelectionIndex(next, count) : clampSelectionIndex(next, count);
}

/**
 * Issue monotonically increasing tokens for command-palette open sessions.
 * Async command completion may update UI state only while its originating
 * token is still current.
 */
export function createCommandSessionGuard() {
  let generation = 0;

  return {
    begin() {
      generation += 1;
      return generation;
    },
    invalidate() {
      generation += 1;
    },
    isCurrent(token) {
      return token === generation;
    },
  };
}
