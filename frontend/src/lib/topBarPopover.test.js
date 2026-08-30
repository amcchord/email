import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const topBarSource = await readFile(
  new URL('../components/layout/TopBar.svelte', import.meta.url),
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
