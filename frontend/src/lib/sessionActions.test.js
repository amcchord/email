import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import {
  captureAuthEpoch,
  isAuthEpochCurrent,
  transitionAuthEpoch,
} from './authSession.js';
import { createToastController } from './toasts.js';

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

async function source(relativePath) {
  return readFile(new URL(relativePath, import.meta.url), 'utf8');
}

test('a pending user A action cannot add a toast after user B takes over', async () => {
  transitionAuthEpoch({ id: 501 });
  const requestEpoch = captureAuthEpoch();
  const pending = deferred();
  const toastController = createToastController({ schedule: () => 1, cancel: () => {} });
  const seen = [];
  const unsubscribe = toastController.subscribe(items => {
    seen.splice(0, seen.length, ...items);
  });

  const completion = pending.promise.then(message => {
    if (!isAuthEpochCurrent(requestEpoch)) return;
    toastController.show(message, 'success', 0);
  });

  transitionAuthEpoch({ id: 502 });
  toastController.clear();
  pending.resolve('Generated A action completed');
  await completion;

  assert.deepEqual(seen, []);
  unsubscribe();
  transitionAuthEpoch(null);
});

test('AI Insights gates post-await actions and polling by authenticated session', async () => {
  const text = await source('../pages/AIInsights.svelte');
  assert.match(text, /sessionGuard = createAuthenticatedSessionGuard\(\)/);
  assert.match(text, /const result = await api\.triggerAutoCategorize\(days\);\s*if \(!sessionIsCurrent\(\)\) return;\s*showToast/);
  assert.match(text, /const result = await api\.deleteAIAnalyses\(rebuildDays\);\s*if \(!sessionIsCurrent\(\)\) return;\s*showToast/);
  assert.match(text, /const result = await api\.unsubscribe\(emailId, \{ preview: true \}\);\s*if \(!sessionIsCurrent\(\)\) return;/);
  assert.doesNotMatch(text, /api\.unsubscribe\(emailId, (?:true|false)\)/);
  assert.match(text, /processingFinishedTimer = setTimeout\([\s\S]*if \(sessionIsCurrent\(\)\) processingJustFinished = false/);
});

test('Subscriptions gates previews and destructive completions by authenticated session', async () => {
  const text = await source('../pages/Subscriptions.svelte');
  assert.match(text, /const result = await api\.getEmail\(sender\.sample_email_id\);\s*if \(!sessionIsCurrent\(\) \|\| previewSender !== sender\) return;/);
  assert.match(text, /await api\.blockSender\(target\.sample_email_id\);\s*if \(!sessionIsCurrent\(\) \|\| unsubTarget !== target\) return;/);
  assert.match(text, /const result = await api\.bulkUnsubscribe[\s\S]*if \(!sessionIsCurrent\(\)\) return;\s*bulkResults = result/);
  assert.match(text, /function onBulkStreamComplete\(status\)[\s\S]*if \(status !== 'success'\)[\s\S]*bulkUrlQueue = \[\];[\s\S]*return;/);
});

test('Admin suppresses stale notifications, redirects, timers, and preference writes', async () => {
  const text = await source('../pages/Admin.svelte');
  assert.match(text, /showToast as showGlobalToast/);
  assert.match(text, /const sessionGuard = createAuthenticatedSessionGuard\(\)/);
  assert.match(text, /function showToast\(\.\.\.args\) \{\s*if \(!sessionIsCurrent\(\)\) return null;/);
  assert.match(text, /const result = await api\.startOAuth\(\);\s*if \(!sessionIsCurrent\(\)\) return;\s*window\.location\.href/);
  assert.match(text, /const data = await api\.getUIPreferences\(\);\s*if \(!sessionIsCurrent\(\)\) return;\s*threadOrder\.set/);
  assert.match(text, /setTimeout\(\(\) => \{\s*if \(sessionIsCurrent\(\)\) forceSyncPoll\(\);/);
  assert.match(text, /onDestroy\(\(\) => \{\s*sessionGuard\.dispose\(\);/);
});

test('Chat export and shortcut overlay clean up at the session boundary', async () => {
  const chat = await source('../pages/Chat.svelte');
  assert.match(chat, /async function downloadPDF\(\) \{\s*if \(!renderedContent \|\| pdfGenerating \|\| !sessionIsCurrent\(\)\) return;/);
  assert.match(chat, /await import\('jspdf'\);\s*if \(!sessionIsCurrent\(\)\) return;/);
  assert.match(chat, /await new Promise[\s\S]*if \(!sessionIsCurrent\(\)\) return;\s*\n\s*const canvas = await html2canvas/);
  assert.match(chat, /const canvas = await html2canvas[\s\S]*if \(!sessionIsCurrent\(\)\) return;/);
  assert.match(chat, /pdfExportContainer\?\.remove\(\);\s*pdfExportContainer = null;/);

  const shortcuts = await source('../components/common/KeyboardShortcutHandler.svelte');
  assert.match(shortcuts, /import \{ onDestroy \} from 'svelte'/);
  assert.match(shortcuts, /onDestroy\(\(\) => \{\s*clearPending\(\);[\s\S]*clearTimeout\(altHoldTimer\);[\s\S]*overlayVisible\.set\(false\);/);
});
