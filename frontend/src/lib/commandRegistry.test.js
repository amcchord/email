import assert from 'node:assert/strict';
import test from 'node:test';

import {
  clampSelectionIndex,
  commandMatchesContext,
  createCommandSessionGuard,
  filterCommandsByContext,
  getVisibleCommands,
  moveSelectionIndex,
  normalizeCommandQuery,
  rankCommands,
  scoreCommand,
  wrapSelectionIndex,
} from './commandRegistry.js';

const commands = [
  {
    id: 'nav.inbox',
    label: 'Go to Inbox',
    keywords: ['mail', 'messages'],
    category: 'Navigation',
    shortcut: 'g i',
    context: 'global',
  },
  {
    id: 'inbox.archive',
    label: 'Archive',
    keywords: ['file', 'remove'],
    category: 'Inbox',
    shortcut: 'e',
    context: 'inbox',
  },
  {
    id: 'email.archive',
    label: 'Archive message',
    keywords: ['file'],
    category: 'Email View',
    shortcut: 'e',
    context: 'email-view',
  },
  {
    id: 'nav.compose',
    label: 'Compose new email',
    keywords: ['write', 'draft'],
    category: 'Navigation',
    shortcut: 'c',
    context: 'global',
  },
];

test('query normalization is deterministic across case, spacing, and accents', () => {
  assert.equal(normalizeCommandQuery('  R\u00c9SUM\u00c9\t  Message  '), 'resume message');
  assert.equal(normalizeCommandQuery(null), '');
});

test('empty query preserves input order and does not return the original array', () => {
  const ranked = rankCommands(commands, '   ');

  assert.deepEqual(ranked, commands);
  assert.notEqual(ranked, commands);
});

test('exact and prefix label matches outrank keyword and id matches', () => {
  const candidates = [
    { id: 'archive', label: 'Move away', keywords: ['archive'] },
    { id: 'other.archive', label: 'Archive message' },
    { id: 'inbox.archive', label: 'Archive' },
  ];

  assert.deepEqual(
    rankCommands(candidates, 'archive').map(command => command.label),
    ['Archive', 'Archive message', 'Move away'],
  );
  assert.ok(scoreCommand(candidates[2], 'archive') > scoreCommand(candidates[0], 'archive'));
});

test('all query tokens must match across searchable command fields', () => {
  assert.deepEqual(
    rankCommands(commands, 'write navigation').map(command => command.id),
    ['nav.compose'],
  );
  assert.deepEqual(rankCommands(commands, 'write calendar'), []);
  assert.equal(rankCommands(commands, 'g i')[0]?.id, 'nav.inbox');
});

test('ties are resolved by original input order', () => {
  const tied = [
    { id: 'first', label: 'First', keywords: ['shared'] },
    { id: 'second', label: 'Second', keywords: ['shared'] },
  ];

  assert.deepEqual(rankCommands(tied, 'shared').map(command => command.id), ['first', 'second']);
});

test('context filtering includes global and unscoped commands in input order', () => {
  const unscoped = { id: 'always', label: 'Always available' };
  const scoped = [...commands, unscoped];

  assert.equal(commandMatchesContext(commands[0], 'inbox'), true);
  assert.equal(commandMatchesContext(commands[1], 'inbox'), true);
  assert.equal(commandMatchesContext(commands[2], 'inbox'), false);
  assert.deepEqual(
    filterCommandsByContext(scoped, 'inbox').map(command => command.id),
    ['nav.inbox', 'inbox.archive', 'nav.compose', 'always'],
  );
});

test('context matching supports multiple command and active contexts', () => {
  const command = { id: 'message.action', contexts: ['inbox', 'email-view'] };

  assert.equal(commandMatchesContext(command, ['calendar', 'email-view']), true);
  assert.equal(commandMatchesContext(command, ['calendar', 'todos']), false);
  assert.equal(commandMatchesContext({ id: 'everywhere', context: '*' }, 'calendar'), true);
  assert.equal(commandMatchesContext({ id: 'explicit', global: true }, null), true);
});

test('visible commands compose context filtering and deterministic ranking', () => {
  assert.deepEqual(
    getVisibleCommands(commands, { context: 'inbox', query: 'archive' }).map(command => command.id),
    ['inbox.archive'],
  );
});

test('selection helpers return -1 for empty lists and normalize invalid input', () => {
  assert.equal(clampSelectionIndex(2, 0), -1);
  assert.equal(wrapSelectionIndex(2, 0), -1);
  assert.equal(moveSelectionIndex(2, 1, 0), -1);
  assert.equal(clampSelectionIndex(Number.NaN, 4), 0);
  assert.equal(wrapSelectionIndex(Number.POSITIVE_INFINITY, 4), 0);
});

test('selection helpers clamp or wrap predictably in both directions', () => {
  assert.equal(clampSelectionIndex(-3, 4), 0);
  assert.equal(clampSelectionIndex(8, 4), 3);
  assert.equal(wrapSelectionIndex(-1, 4), 3);
  assert.equal(wrapSelectionIndex(4, 4), 0);
  assert.equal(moveSelectionIndex(3, 1, 4), 0);
  assert.equal(moveSelectionIndex(0, -1, 4), 3);
  assert.equal(moveSelectionIndex(-1, 1, 4), 0);
  assert.equal(moveSelectionIndex(-1, -1, 4), 3);
  assert.equal(moveSelectionIndex(3, 1, 4, { wrap: false }), 3);
  assert.equal(moveSelectionIndex(0, -1, 4, { wrap: false }), 0);
});

test('command session guard rejects completion from closed or superseded palettes', () => {
  const guard = createCommandSessionGuard();
  const first = guard.begin();
  assert.equal(guard.isCurrent(first), true);

  guard.invalidate();
  assert.equal(guard.isCurrent(first), false);

  const second = guard.begin();
  assert.equal(guard.isCurrent(first), false);
  assert.equal(guard.isCurrent(second), true);
});
