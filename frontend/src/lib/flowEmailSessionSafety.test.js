import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

async function source(relativePath) {
  return readFile(new URL(relativePath, import.meta.url), 'utf8');
}

test('Flow rejects stale thread and action completions after an identity change', async () => {
  const text = await source('../pages/Flow.svelte');

  assert.match(
    text,
    /function threadRequestIsCurrent[\s\S]*return sessionIsCurrent\(\) && isCurrentFlowThreadRequest/,
  );
  assert.match(
    text,
    /await api\.emailActions\(\[emailId\], 'archive'\);\s*if \(!sessionIsCurrent\(\)\) return;\s*showToast\('Email archived'/,
  );
  assert.match(
    text,
    /await api\.ignoreNeedsReply\(emailId\);\s*if \(!sessionIsCurrent\(\)\) return false;/,
  );
  assert.match(
    text,
    /async function ignoreCurrentEmail[\s\S]*finally \{\s*if \(sessionIsCurrent\(\)\) \{\s*ignoringReplyEmailIds = removePendingReplyId/,
  );
  assert.match(
    text,
    /await api\.snoozeNeedsReply\(emailId, duration\);\s*if \(!sessionIsCurrent\(\)\) return;/,
  );
  assert.match(
    text,
    /async function sendReply[\s\S]*await submitOutboundSend\(payload,[\s\S]*onAccepted: releaseEditor[\s\S]*onRestore: \(operation, reason\) => restoreOutboundComposeDraft\(restoreDraft, operation, reason\)/,
  );
  assert.match(
    text,
    /onSent:[\s\S]*isAuthenticatedSessionCurrent\(sendSession\)[\s\S]*archiveSentReply\(email\.id, archiveIdempotencyKey\)/,
  );
  assert.match(text, /await api\.getMailActionByIdempotency\(archiveIdempotencyKey\)/);
  assert.match(text, /selectedReplyEmail = \{[\s\S]*id: latestInbound\.id,[\s\S]*references_header: latestInbound\.references_header \|\| null/);
  assert.doesNotMatch(text, /async function sendReply[\s\S]*await api\.sendEmail/);
  assert.match(
    text,
    /async function sendReply[\s\S]*finally \{\s*if \(sessionIsCurrent\(\)\) inlineReplySending = false;/,
  );
  assert.match(
    text,
    /finally \{\s*if \(sessionIsCurrent\(\) && streamAbortController === controller\) \{\s*streamAbortController = null;/,
  );
});

test('EmailView gates attachment and message action continuations to its captured session', async () => {
  const text = await source('../components/email/EmailView.svelte');

  assert.match(
    text,
    /function previewRequestIsCurrent[\s\S]*return sessionIsCurrent\(\) && isCurrentAttachmentPreviewRequest/,
  );
  assert.match(
    text,
    /const requestIsCurrent = \(\) => \(\s*sessionIsCurrent\(\)\s*&& attachmentAbortControllers/,
  );
  assert.match(
    text,
    /await api\.unignoreNeedsReply\(email\.id\);\s*if \(!sessionIsCurrent\(\)\) return;/,
  );
  assert.match(
    text,
    /async function sendInlineReply[\s\S]*await submitOutboundSend\(payload,[\s\S]*onAccepted: releaseEditor[\s\S]*onRestore: \(operation, reason\) => restoreOutboundComposeDraft\(restoreDraft, operation, reason\)/,
  );
  assert.doesNotMatch(text, /async function sendInlineReply[\s\S]*await api\.sendEmail/);
  assert.match(
    text,
    /async function sendInlineReply[\s\S]*finally \{\s*if \(sessionIsCurrent\(\)\) inlineReplySending = false;/,
  );
  assert.match(
    text,
    /const result = await api\.unsubscribe\(email\.id\);\s*if \(!sessionIsCurrent\(\)\) return;/,
  );
  assert.match(
    text,
    /async function handleUnsubscribe[\s\S]*finally \{\s*if \(sessionIsCurrent\(\)\) unsubscribing = false;/,
  );
});
