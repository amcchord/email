import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

async function source(relativePath) {
  return readFile(new URL(relativePath, import.meta.url), 'utf8');
}

test('Chat and Flow cancel streams and reject stale session events', async () => {
  for (const relativePath of ['../pages/Chat.svelte', '../pages/Flow.svelte']) {
    const text = await source(relativePath);
    assert.match(text, /createAuthenticatedSessionGuard/);
    assert.match(text, /streamAbortController\?\.abort\(\)/);
    assert.match(text, /api\.chatStream\([\s\S]*signal:\s*controller\.signal/);
    assert.match(text, /await reader\.cancel\(\)\.catch/);
    assert.match(text, /function handleSSEEvent\([^)]*\)\s*\{\s*if \(!sessionIsCurrent\(\)\) return;/);
  }
});

test('unsubscribe completion is suppressed after session teardown', async () => {
  const text = await source('../components/email/UnsubscribeViewer.svelte');
  assert.match(text, /sessionGuard = createAuthenticatedSessionGuard\(\)/);
  assert.match(text, /sessionGuard\.dispose\(\);\s*if \(_abortController\)/);
  assert.match(text, /if \(sessionGuard\?\.isCurrent\(\)\) onComplete\(currentStatus\)/);
});

test('cancelled or failed bulk unsubscribe cannot continue the queue', async () => {
  const text = await source('../pages/Subscriptions.svelte');
  assert.match(text, /function onBulkStreamComplete\(status\)[\s\S]*if \(status !== 'success'\)/);
  assert.match(text, /if \(bulkContinuationTimer\)[\s\S]*clearTimeout\(bulkContinuationTimer\)/);
  assert.match(text, /bulkInProgress = false;[\s\S]*bulkUrlQueue = \[\];[\s\S]*bulkCurrentUrlIdx = -1;[\s\S]*return;/);
  assert.match(text, /status === 'cancelled'[\s\S]*Bulk unsubscribe stopped/);
});
