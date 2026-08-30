import assert from 'node:assert/strict';
import test from 'node:test';

import {
  MAX_ACTIVE_ATTACHMENT_REQUESTS,
  canStartAttachmentDownload,
  isCurrentAttachmentRequest,
  isRetryableAttachmentError,
  safeClientFilename,
  saveAttachmentBlob,
} from './attachmentDownload.js';

test('client download filenames drop path and control characters', () => {
  assert.equal(
    safeClientFilename('../private\\report\r\n.pdf'),
    'report.pdf',
  );
  assert.equal(safeClientFilename('..'), 'attachment');
  assert.equal(safeClientFilename('safe\u202Etxt.exe'), 'safetxt.exe');
  const longName = `${'very-long-'.repeat(30)}report.pdf`;
  const boundedName = safeClientFilename(longName);
  assert.equal([...boundedName].length, 180);
  assert.equal(boundedName.endsWith('.pdf'), true);
});

test('attachment blobs use a temporary keyboard-independent browser download', () => {
  const calls = [];
  const link = {
    style: {},
    click: () => calls.push('click'),
    remove: () => calls.push('remove'),
  };
  const documentObject = {
    body: { appendChild: (node) => calls.push(['append', node]) },
    createElement: (tagName) => {
      assert.equal(tagName, 'a');
      return link;
    },
  };
  const urlObject = {
    createObjectURL: (blob) => {
      assert.equal(blob, 'generated attachment');
      return 'blob:generated-fixture';
    },
    revokeObjectURL: (url) => calls.push(['revoke', url]),
  };

  saveAttachmentBlob('generated attachment', 'notes.txt', {
    documentObject,
    urlObject,
    scheduleCleanup: (cleanup) => cleanup(),
  });

  assert.equal(link.href, 'blob:generated-fixture');
  assert.equal(link.download, 'notes.txt');
  assert.equal(link.style.display, 'none');
  assert.deepEqual(calls, [
    ['append', link],
    'click',
    'remove',
    ['revoke', 'blob:generated-fixture'],
  ]);
});

test('duplicate attachment requests are blocked while one is active', () => {
  const activeIds = new Set([83]);
  assert.equal(canStartAttachmentDownload(activeIds, 83), false);
  assert.equal(canStartAttachmentDownload(activeIds, 84), true);
  assert.equal(canStartAttachmentDownload(new Set([81, 82, 83]), 84), false);
  assert.equal(MAX_ACTIVE_ATTACHMENT_REQUESTS, 3);
});

test('attachment results become stale after the email or generation changes', () => {
  const request = { requestedEmailId: 41, requestGeneration: 3 };
  assert.equal(isCurrentAttachmentRequest({
    ...request,
    currentEmailId: 41,
    currentGeneration: 3,
  }), true);
  assert.equal(isCurrentAttachmentRequest({
    ...request,
    currentEmailId: 42,
    currentGeneration: 4,
  }), false);
  assert.equal(isCurrentAttachmentRequest({
    ...request,
    currentEmailId: 41,
    currentGeneration: 4,
  }), false);
});

test('terminal attachment failures are not presented as retryable', () => {
  for (const status of [400, 401, 403, 404, 409, 413, 422]) {
    assert.equal(isRetryableAttachmentError(status), false);
  }
  assert.equal(isRetryableAttachmentError(408), true);
  assert.equal(isRetryableAttachmentError(425), true);
  assert.equal(isRetryableAttachmentError(429), true);
  assert.equal(isRetryableAttachmentError(503), true);
  assert.equal(isRetryableAttachmentError(undefined), true);
});
