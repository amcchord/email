import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const statusSource = await readFile(
  new URL('../components/email/OutboundSendStatus.svelte', import.meta.url),
  'utf8',
);

test('global outbound status exposes reconciliation without an ambiguous resend control', () => {
  assert.match(statusSource, /outboundSendOperations, outboundSends/);
  assert.match(statusSource, /operation\.state === 'reconciling'/);
  assert.match(statusSource, /operation\.state === 'failed'/);
  assert.match(statusSource, /Do not resend while its status is being confirmed/);
  assert.match(statusSource, /outboundSends\.refreshOperation\(operation\)/);
  assert.doesNotMatch(statusSource, /outboundSends\.retry\(/);
  assert.doesNotMatch(statusSource, />Retry send</);
  assert.match(statusSource, /Review it before choosing Send again/);
  assert.match(statusSource, /onclick=\{dismissFailures\}/);
});

test('global outbound status queues recovery without interrupting an active composer', () => {
  assert.match(statusSource, /pendingOutboundDraftRecoveries/);
  assert.match(statusSource, /openPendingOutboundDraft/);
  assert.match(statusSource, /let composeOpen = \$derived\(\$currentPage === 'compose'\)/);
  assert.match(statusSource, /disabled=\{composeOpen\}/);
  assert.match(statusSource, /Finish or leave your current draft before reviewing it/);
});

test('global outbound status recovers an accepted durable draft after reload-time Undo', () => {
  assert.match(statusSource, /operation\.client_draft_id/);
  assert.match(statusSource, /outboundSends\.attachCallbacks\(operation/);
  assert.match(statusSource, /onSent: terminalOperation => forgetAcceptedDraft/);
  assert.match(statusSource, /onRestore: \(terminalOperation, reason\)/);
  assert.match(statusSource, /loadRetainedOutboundDraft\(/);
  assert.match(statusSource, /const draft = localDraft \|\| await api\.getComposeDraft/);
  assert.match(statusSource, /api\.getComposeDraft\(operation\.client_draft_id\)/);
  assert.match(statusSource, /restoreOutboundComposeDraft\(draft, operation, reason\)/);
  assert.match(statusSource, /composeDraftHasContent\(draft\)/);
  assert.match(statusSource, /isAuthenticatedSessionCurrent\(session\)/);
});

test('global outbound status follows authenticated generation and never reads message content', () => {
  assert.match(statusSource, /authenticatedSessionGeneration\.subscribe/);
  assert.match(statusSource, /isAuthenticatedSessionCurrent\(session\)/);
  assert.match(statusSource, /outboundSends\.resetForCurrentSession\(\)/);
  assert.match(statusSource, /outboundSends\.loadRecent\(20\)/);
  assert.doesNotMatch(statusSource, /operation\.(to|cc|bcc|subject|body_html|body_text|attachments)\b/);
  assert.doesNotMatch(statusSource, /error_message/);
});

test('scheduled management makes the confirmed-delivery archive intent visible', () => {
  assert.match(statusSource, /operation\.archive_source_after_send/);
  assert.match(statusSource, /Archive after confirmed delivery/);
});
