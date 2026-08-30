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
    /async function sendReply[\s\S]*await submitOutboundSend\(payload,[\s\S]*onAccepted: \(\) => \{\}[\s\S]*onRestore: \(operation, reason\) => restoreOutboundComposeDraft\(restoreDraft, operation, reason\)[\s\S]*await controllerAtStart\.markSendUncertain\(operation\);\s*releaseEditor\(\)/,
  );
  assert.match(text, /archiveAtStart[\s\S]*payload\.archive_source_after_send = true;[\s\S]*submitOutboundSend\(payload/);
  assert.doesNotMatch(text, /archiveSentReply|archiveIdempotencyKey/);
  assert.match(text, /selectedReplyEmail = \{[\s\S]*id: latestInbound\.id,[\s\S]*references_header: latestInbound\.references_header \|\| null/);
  assert.doesNotMatch(text, /async function sendReply[\s\S]*await api\.sendEmail/);
  assert.match(
    text,
    /async function sendReply[\s\S]*finally \{\s*if \(sessionIsCurrent\(\)\) \{\s*inlineReplySending = false;\s*(?:inlineReplySendMode = 'send';\s*)?await controllerAtStart\?\.markSending\(false\)/,
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
    /async function sendInlineReply[\s\S]*await submitOutboundSend\(payload,[\s\S]*onAccepted: \(\) => \{\}[\s\S]*onRestore: \(operation, reason\) => restoreOutboundComposeDraft\(restoreDraft, operation, reason\)[\s\S]*await controllerAtStart\.markSendUncertain\(operation\);\s*releaseEditor\(\)/,
  );
  assert.doesNotMatch(text, /async function sendInlineReply[\s\S]*await api\.sendEmail/);
  assert.match(
    text,
    /async function sendInlineReply[\s\S]*finally \{\s*if \(sessionIsCurrent\(\)\) \{\s*inlineReplySending = false;\s*(?:inlineReplySendMode = 'send';\s*)?await controllerAtStart\?\.markSending\(false\)/,
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

test('reply surfaces refuse navigation until the active draft is safely stored', async () => {
  const [flow, emailView, inbox] = await Promise.all([
    source('../pages/Flow.svelte'),
    source('../components/email/EmailView.svelte'),
    source('../pages/Inbox.svelte'),
  ]);

  assert.match(
    flow,
    /async function prepareFlowReplyTransition\(\)[\s\S]*before\.discardInProgress[\s\S]*before\.sendInProgress[\s\S]*await controller\.flush\(\)[\s\S]*state\?\.error\?\.phase === 'local'/,
  );
  assert.match(flow, /async function openReplyView[\s\S]*await prepareFlowReplyTransition\(\)/);
  assert.match(flow, /async function closeReplyView[\s\S]*await prepareFlowReplyTransition\(\)/);
  assert.match(flow, /async function archiveCurrentEmail[\s\S]*await prepareFlowReplyTransition\(\)/);

  assert.match(
    emailView,
    /async function prepareInlineReplyTransition\(\)[\s\S]*before\.discardInProgress[\s\S]*before\.sendInProgress[\s\S]*await controller\.flush\(\)[\s\S]*state\?\.error\?\.phase === 'local'/,
  );
  assert.match(
    emailView,
    /onGuardChange\(prepareInlineReplyTransition\);\s*return \(\) => onGuardChange\(null\)/,
  );
  assert.match(emailView, /bind:element=\{primaryReplyButton\}/);
  assert.match(
    emailView,
    /const sendReturnFocus = replyReturnFocus;[\s\S]*if \(sendReturnFocus\?\.isConnected\) sendReturnFocus\.focus\(\);\s*else primaryReplyButton\?\.focus\?\.\(\)/,
  );

  assert.match(inbox, /async function handleSelect[\s\S]*await canLeaveSelectedEmail\(\)[\s\S]*selectedEmailId\.set\(emailId\)/);
  assert.match(inbox, /async function loadEmails[\s\S]*snapshot\.key !== committedDatasetSnapshot\.key[\s\S]*await canLeaveSelectedEmail\(\)/);
  assert.match(inbox, /optimistic\.removed && !\(await canLeaveSelectedEmail\(\)\)/);
  assert.match(inbox, /onGuardChange=\{registerEmailViewTransitionGuard\}/);
});
