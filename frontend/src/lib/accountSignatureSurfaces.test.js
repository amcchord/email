import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import {
  accountSignatureFor,
  effectiveSignatureSnapshot,
  normalizeCompositionKind,
  normalizeSignatureMode,
  normalizeSignatureSnapshot,
  signatureDefaultIncluded,
  signatureDraftFields,
  signatureSnapshotAfterModeChange,
  signatureSnapshotFromPolicy,
} from './accountSignatures.js';
import { composeDraftHasContent, newComposeIntent } from './composeDraft.js';

const policy = Object.freeze({
  account_id: 7,
  account_email: 'sender@example.test',
  enabled: true,
  include_on_new: true,
  include_on_replies: false,
  include_on_forwards: true,
  body_html: '<p>Generated signature</p>',
  body_text: 'Generated signature',
  revision: 4,
  sanitizer_version: 1,
});

function randomUUID() {
  return '10000000-0000-4000-8000-000000000001';
}

test('signature policy resolution is account- and composition-aware', () => {
  assert.equal(accountSignatureFor([policy], '7'), policy);
  assert.equal(accountSignatureFor([policy], 8), null);
  assert.equal(signatureDefaultIncluded(policy, 'new'), true);
  assert.equal(signatureDefaultIncluded(policy, 'reply'), false);
  assert.equal(signatureDefaultIncluded(policy, 'forward'), true);
  assert.equal(normalizeCompositionKind('unknown'), 'new');
  assert.equal(normalizeSignatureMode('unknown', 'disabled'), 'disabled');
});

test('signature snapshots preserve immutable content and fail closed when unavailable', () => {
  const snapshot = signatureSnapshotFromPolicy(policy);
  assert.deepEqual(snapshot, {
    applied: true,
    account_id: 7,
    policy_revision: 4,
    body_html: '<p>Generated signature</p>',
    body_text: 'Generated signature',
    content_hash: '',
    sanitizer_version: 1,
  });
  assert.equal(signatureSnapshotFromPolicy({ ...policy, body_html: '', body_text: '' }), null);
  assert.equal(normalizeSignatureSnapshot({ ...snapshot, body_text: '' }), null);
  const suppressed = normalizeSignatureSnapshot({ ...snapshot, applied: false });
  assert.equal(suppressed.applied, false);
  assert.equal(effectiveSignatureSnapshot({
    initialized: true,
    mode: 'enabled',
    compositionKind: 'reply',
    policy,
    snapshot: suppressed,
  }).applied, true);
  assert.equal(effectiveSignatureSnapshot({
    initialized: false,
    mode: 'default',
    compositionKind: 'new',
    policy,
    snapshot,
  }), null);
  assert.equal(effectiveSignatureSnapshot({
    initialized: true,
    mode: 'disabled',
    compositionKind: 'new',
    policy,
    snapshot,
  }), null);
  assert.equal(effectiveSignatureSnapshot({
    initialized: true,
    mode: 'default',
    compositionKind: 'reply',
    policy,
    snapshot,
  }), null);
});

test('a frozen signature survives live-policy changes through Remove and Restore', () => {
  const frozenRevisionFour = {
    applied: true,
    account_id: 7,
    policy_revision: 4,
    body_html: '<p>Frozen revision four</p>',
    body_text: 'Frozen revision four',
    content_hash: 'c'.repeat(64),
    sanitizer_version: 1,
  };
  const clearedRevisionFive = {
    ...policy,
    enabled: false,
    body_html: '',
    body_text: '',
    revision: 5,
  };

  const removed = signatureSnapshotAfterModeChange({
    mode: 'disabled',
    policy: clearedRevisionFive,
    snapshot: frozenRevisionFour,
  });
  assert.equal(effectiveSignatureSnapshot({
    initialized: true,
    mode: 'default',
    compositionKind: 'new',
    policy: clearedRevisionFive,
    snapshot: frozenRevisionFour,
  }).policy_revision, 4);
  assert.equal(effectiveSignatureSnapshot({
    initialized: true,
    mode: 'default',
    compositionKind: 'new',
    policy: clearedRevisionFive,
    snapshot: { ...frozenRevisionFour, applied: false },
  }), null);
  assert.equal(effectiveSignatureSnapshot({
    initialized: true,
    mode: 'disabled',
    compositionKind: 'new',
    policy: clearedRevisionFive,
    snapshot: removed,
  }), null);

  const restored = signatureSnapshotAfterModeChange({
    mode: 'enabled',
    policy: clearedRevisionFive,
    snapshot: removed,
  });
  assert.equal(restored.policy_revision, 4);
  assert.equal(restored.body_text, 'Frozen revision four');
  assert.equal(effectiveSignatureSnapshot({
    initialized: true,
    mode: 'enabled',
    compositionKind: 'new',
    policy: clearedRevisionFive,
    snapshot: restored,
  }).body_text, 'Frozen revision four');
});

test('an authoritative frozen unsigned snapshot is not replaced by later policy content', () => {
  const frozenUnsigned = normalizeSignatureSnapshot({
    applied: false,
    account_id: 7,
    policy_revision: 0,
    body_html: '',
    body_text: '',
    content_hash: 'd'.repeat(64),
    sanitizer_version: 1,
  });
  assert.equal(frozenUnsigned.applied, false);
  assert.equal(frozenUnsigned.body_html, '');
  assert.equal(effectiveSignatureSnapshot({
    initialized: true,
    mode: 'default',
    compositionKind: 'new',
    policy,
    snapshot: frozenUnsigned,
  }), null);
  assert.equal(signatureSnapshotAfterModeChange({
    mode: 'default',
    policy,
    snapshot: frozenUnsigned,
  }).policy_revision, 0);
});

test('wire fields are normalized while signatures alone never make a draft nonblank', () => {
  assert.deepEqual(signatureDraftFields({
    compositionKind: 'forward',
    mode: 'enabled',
    quotedHtml: '<blockquote>Earlier</blockquote>',
    quotedText: 'Earlier',
  }), {
    composition_kind: 'forward',
    signature_mode: 'enabled',
    quoted_html: '<blockquote>Earlier</blockquote>',
    quoted_text: 'Earlier',
  });
  assert.equal(composeDraftHasContent({
    signature_mode: 'enabled',
    signature_snapshot: signatureSnapshotFromPolicy(policy),
    signature_initialized: true,
  }), false);
  assert.equal(composeDraftHasContent({ quoted_text: 'Earlier message' }), true);
  const intent = newComposeIntent({}, { randomUUID });
  assert.equal(intent.composition_kind, 'new');
  assert.equal(intent.signature_mode, 'default');
  assert.equal(intent.signature_initialized, true);
});

test('all writing surfaces use the shared policy API and signature control', async () => {
  for (const relativePath of [
    '../pages/Compose.svelte',
    '../components/email/EmailView.svelte',
    '../pages/Flow.svelte',
  ]) {
    const source = await readFile(new URL(relativePath, import.meta.url), 'utf8');
    assert.match(source, /api\.listAccountSignatures\(\)/);
    assert.match(source, /<SignatureControl/);
    assert.match(source, /signatureMode|signatureDraftFields|signature_mode:/);
    assert.match(source, /signatureSnapshot|signature_snapshot:/);
    assert.match(source, /signatureInitialized|signature_initialized:/);
    assert.match(source, /signaturePoliciesFailed && signatureUnsignedAcknowledged/);
    assert.match(source, /onretry=\{loadSignaturePolicies\}/);
    assert.match(source, /oncontinueunsigned=\{handleContinueWithoutSignature\}/);
    assert.match(source, /signatureReady/);
    assert.doesNotMatch(source, /signatureMode = signaturePoliciesFailed \? 'disabled' : 'default'/);
  }
});

test('signature policy failures require an explicit retry or unsigned acknowledgement', async () => {
  const source = await readFile(new URL('../components/email/SignatureControl.svelte', import.meta.url), 'utf8');
  assert.match(source, /Signature settings are unavailable/);
  assert.match(source, /Continue unsigned/);
  assert.match(source, /onclick=\{\(\) => onretry\?\.\(\)\}/);
  assert.match(source, /onclick=\{\(\) => oncontinueunsigned\?\.\(\)\}/);
  assert.match(source, /role=\{unsignedAcknowledged \? 'status' : 'alert'\}/);
});

test('forward handoff keeps the original message out of editable body fields', async () => {
  const source = await readFile(new URL('../components/email/EmailView.svelte', import.meta.url), 'utf8');
  const forwardHandler = source.match(/function handleForward\(\) \{([\s\S]*?)\n  \}/)?.[1] || '';
  assert.match(forwardHandler, /composition_kind: 'forward'/);
  assert.match(forwardHandler, /body_html: ''/);
  assert.match(forwardHandler, /body_text: ''/);
  assert.match(forwardHandler, /quoted_html:/);
  assert.match(forwardHandler, /quoted_text:/);
});
