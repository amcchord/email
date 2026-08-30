import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

test('DraftStatus renders controlled announcements and accessible recovery actions', async () => {
  const source = await readFile(new URL('../components/email/DraftStatus.svelte', import.meta.url), 'utf8');

  assert.match(source, /role=\{view\.role\}/);
  assert.match(source, /aria-live=\{view\.live\}/);
  assert.match(source, /aria-atomic="true"/);
  assert.match(source, /data-draft-state=\{state\.status \|\| 'pristine'\}/);
  assert.match(source, /view\.retry && onretry[\s\S]*>Retry</);
  assert.match(source, /view\.undo && onundo[\s\S]*>Undo</);
  assert.match(source, /view\.review && onreview[\s\S]*>Review versions</);
  assert.match(source, /min-height: 2\.75rem/);
});
