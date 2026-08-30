import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

test('app-managed provider drafts reopen with stable identity while unknown drafts stay read-only', async () => {
  const source = await readFile(new URL('../components/email/EmailView.svelte', import.meta.url), 'utf8');

  assert.match(source, /await api\.getComposeDraftByEmail\(email\.id\)/);
  assert.match(source, /client_draft_id: detail\.client_draft_id/);
  assert.match(source, /draft_revision: detail\.revision/);
  assert.match(source, /draft_state: detail\.state/);
  assert.match(source, /This provider draft was not created by this app, so it remains read-only here\./);
  assert.match(source, /\{openingManagedDraft \? 'Opening…' : 'Edit draft'\}/);
});
