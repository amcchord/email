import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const pageUrl = new URL('../pages/AtAGlance.svelte', import.meta.url);

test('At a Glance surface stays read-only and hands management to Settings', async () => {
  const source = await readFile(pageUrl, 'utf8');
  assert.match(source, /getAtAGlanceExperience/);
  assert.match(source, /atAGlancePreviewPngUrl/);
  assert.match(source, /\?page=admin&tab=terminals/);
  assert.match(source, /createAuthenticatedSessionGuard/);
  assert.match(source, /requestGeneration !== loadGeneration/);

  for (const forbidden of [
    'requestPort',
    'navigator.serial',
    'updateTerminal(',
    'deleteTerminal(',
    'revokeTerminal',
    'regenerateTerminal',
    'rotateDisplay',
  ]) {
    assert.equal(source.includes(forbidden), false, `page must not include ${forbidden}`);
  }
});

test('At a Glance source includes loading, empty, partial, preview-error, and battery states', async () => {
  const source = await readFile(pageUrl, 'utf8');
  assert.match(source, /Loading At a Glance/);
  assert.match(source, /No display views are available yet/);
  assert.match(source, /Some live status could not be refreshed/);
  assert.match(source, /Preview could not be rendered/);
  assert.match(source, /predicted charging needs/);
});

