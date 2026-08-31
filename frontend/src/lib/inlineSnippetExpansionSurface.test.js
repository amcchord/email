import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';


const [component, contract] = await Promise.all([
  readFile(new URL('../components/email/InlineSnippetMenu.svelte', import.meta.url), 'utf8'),
  readFile(new URL('./inlineSnippetExpansion.js', import.meta.url), 'utf8'),
]);


test('inline menu is non-modal, anchored, keyboard-contained, and stale-session safe', () => {
  assert.match(component, /active = null/);
  assert.match(component, /menuId = 'inline-snippet-menu'/);
  assert.match(component, /api\.listPersonalSnippets\(\)/);
  assert.match(component, /snippets = \[\];[\s\S]*loading = true/);
  assert.match(component, /normalizeSnippetList\(response\)/);
  assert.match(component, /rankPersonalSnippets\(snippets, query\)/);
  assert.match(component, /generation !== requestGeneration/);
  assert.match(component, /isAuthenticatedSessionCurrent\(session\)/);
  assert.match(component, /role="listbox"/);
  assert.match(component, /role="option"/);
  assert.match(component, /min-h-11/);
  assert.match(component, /event\.metaKey \|\| event\.ctrlKey \|\| event\.altKey/);
  for (const key of ['ArrowDown', 'ArrowUp', 'Enter', 'Tab', 'Escape']) {
    assert.match(component, new RegExp(`event\\.key === '${key}'`));
  }
  assert.match(component, /onpointerdown=\{\(event\) => handleOptionPointerDown/);
  assert.match(component, /event\.preventDefault\(\);[\s\S]*chooseSnippet\(snippet\)/);
  assert.doesNotMatch(component, /aria-modal/);
});


test('pure contract owns safe trigger detection, exact replacement, and viewport clamping', () => {
  assert.match(contract, /export function detectInlineSnippetTrigger\(/);
  assert.match(contract, /export function findInlineSnippetTrigger\(/);
  assert.match(contract, /selectionStart !== selectionEnd/);
  assert.match(contract, /semicolon === blockStart/);
  assert.match(contract, /precededByWhitespace/);
  assert.match(contract, /export function replaceInlineSnippetRange\(/);
  assert.match(contract, /export function replaceInlineSnippetText\(/);
  assert.match(contract, /source\.slice\(start, end\) !== expected/);
  assert.match(contract, /export function clampInlineSnippetMenuPosition\(/);
  assert.match(contract, /placement = below >= usefulHeight \|\| below >= above \? 'below' : 'above'/);
});
