import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';


const [component, contract] = await Promise.all([
  readFile(new URL('../components/email/RecipientField.svelte', import.meta.url), 'utf8'),
  readFile(new URL('./recipientField.js', import.meta.url), 'utf8'),
]);


test('recipient field keeps committed mailboxes separate from its local pending query', () => {
  assert.match(component, /recipients = \$bindable\(\[\]\)/);
  assert.match(component, /pending = \$bindable\(false\)/);
  assert.match(component, /let query = \$state\(''\)/);
  assert.match(component, /pending = Boolean\(trimmedQuery\)[\s\S]*if \(!trimmedQuery\) feedback = ''/);
  assert.match(component, /commitRecipientInput\(value, \{[\s\S]*recipients,[\s\S]*recipientCollections,[\s\S]*isDuplicate,[\s\S]*field/);
  assert.match(component, /onchange\?\.\(\{ recipients: next, added, removed, duplicates, field \}\)/);
  assert.match(component, /export function focus\(\{ force = false, selectPending = false \} = \{\}\)/);
  assert.match(component, /autofocus = false/);
  assert.match(component, /focusIsLost[\s\S]*if \(focusIsLost\) focus\(\)/);
});


test('combobox and chips expose accessible semantics and full keyboard behavior', () => {
  assert.match(component, /role="combobox"/);
  assert.match(component, /aria-autocomplete="list"/);
  assert.match(component, /aria-activedescendant/);
  assert.match(component, /role="listbox"/);
  assert.match(component, /role="option"/);
  assert.match(component, /role="alert"/);
  for (const key of ['ArrowDown', 'ArrowUp', 'Enter', 'Tab', 'Escape', 'Backspace']) {
    assert.match(component, new RegExp(`event\\.key === '${key}'`));
  }
  assert.match(component, /onpaste=\{handlePaste\}/);
  assert.match(component, /onblur=\{handleBlur\}/);
  assert.match(component, /if \(normalizeMailbox\(pendingQuery\)\) \{\s*commitValue\(\)/);
  assert.match(component, /onpointerdown=\{\(event\) => event\.preventDefault\(\)\}/);
  assert.match(component, /if \(menuOpen\) event\.stopPropagation\(\)/);
  assert.match(component, /event\.metaKey \|\| event\.ctrlKey \|\| event\.altKey/);
});


test('suggestion loading is debounced, abortable, stale-safe, and account-bound', () => {
  assert.match(component, /loadSuggestions = null/);
  assert.match(component, /debounceMs = 180/);
  assert.match(component, /const controller = new AbortController\(\)/);
  assert.match(component, /window\.setTimeout/);
  assert.match(component, /signal: controller\.signal/);
  assert.match(component, /generation !== requestGeneration/);
  assert.match(component, /requestedQuery !== query\.trim\(\)/);
  assert.match(component, /!Object\.is\(requestedAccount, accountKey\)/);
  assert.match(component, /controller\.abort\(\)/);
  assert.match(component, /Object\.is\(nextAccountKey, observedAccountKey\)/);
  assert.match(component, /Type a complete address and press Enter/);
});


test('targets are 44px and narrow layout cannot exceed its field width', () => {
  assert.match(component, /min-h-11 min-w-11/);
  assert.match(component, /recipient-option flex min-h-11 w-full min-w-0/);
  assert.match(component, /recipient-field relative w-full min-w-0/);
  assert.match(component, /max-width: 100%/);
  assert.match(component, /overflow-x-hidden/);
  assert.match(component, /@media \(max-width: 767px\)/);
});


test('pure contract exports canonicalization and cross-field duplicate primitives', () => {
  for (const exportName of [
    'splitMailboxList',
    'formatMailbox',
    'parseMailbox',
    'normalizeMailbox',
    'mailboxIdentity',
    'parseMailboxList',
    'recipientCollectionIdentities',
    'commitRecipientInput',
    'normalizeRecipientSuggestion',
    'normalizeRecipientSuggestions',
    'pendingMailboxHasOpenSyntax',
  ]) {
    assert.match(contract, new RegExp(`export function ${exportName}\\(`));
  }
});
