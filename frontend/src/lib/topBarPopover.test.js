import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const topBarSource = await readFile(
  new URL('../components/layout/TopBar.svelte', import.meta.url),
  'utf8',
);
const layoutSource = await readFile(
  new URL('../components/layout/Layout.svelte', import.meta.url),
  'utf8',
);

test('full-viewport TopBar backdrops stay transparent on hover', () => {
  assert.equal(
    topBarSource.match(/class="topbar-backdrop fixed inset-0 z-40/g)?.length,
    2,
  );
  assert.match(
    topBarSource,
    /header button:not\(\.topbar-backdrop\):not\(\.tab-active\):not\(\.tab-inactive\):hover/,
  );
  assert.match(
    topBarSource,
    /\.topbar-backdrop:hover\s*\{[^}]*background:\s*transparent;/s,
  );
});

test('More menu is positioned by its trigger instead of the full primary navigation', () => {
  const moreTriggerBlock = topBarSource.match(
    /    <div class="more-trigger relative flex items-center shrink-0">([\s\S]*?)\n    <\/div>\n  <\/nav>/,
  )?.[1];
  assert.ok(moreTriggerBlock, 'the More trigger should own its positioning wrapper');
  assert.match(
    moreTriggerBlock,
    /bind:this=\{moreButton\}[\s\S]*?\{#if moreMenuOpen\}[\s\S]*?bind:this=\{moreMenu\}[\s\S]*?class="more-menu absolute left-0 top-full/,
  );
  assert.match(
    topBarSource,
    /\.more-menu\s*\{\s*position:\s*fixed;\s*top:\s*3\.25rem;\s*left:\s*0\.5rem;\s*right:\s*0\.5rem;/s,
  );
});

test('At a Glance is a preloadable primary tab with responsive tablet labels', () => {
  assert.match(
    topBarSource,
    /\{ id: 'at-a-glance', label: 'At a Glance', icon: 'monitor', shortcut: 'nav\.glance' \}/,
  );
  assert.match(topBarSource, /onpointerenter=\{\(\) => warmRoute\(tab\.id\)\}/);
  assert.match(topBarSource, /onfocus=\{\(\) => warmRoute\(tab\.id\)\}/);
  assert.match(topBarSource, /aria-current=\{\$currentPage === tab\.id \? 'page' : undefined\}/);
  assert.match(topBarSource, /data-shortcut=\{tab\.shortcut\}/);
  assert.match(
    topBarSource,
    /@media \(min-width: 768px\) and \(max-width: 1023px\)\s*\{[\s\S]*?\.primary-tab-label\s*\{\s*display:\s*none;/,
  );
  assert.match(layoutSource, /'nav\.glance':\s*\(\) => navigateByShortcut\('at-a-glance'\)/);
});
