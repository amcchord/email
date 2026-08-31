import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import {
  accountSignatureIsDirty,
  accountSignaturePayload,
  accountSignatureSummary,
  normalizeAccountSignature,
  normalizeAccountSignatureList,
  signatureHtmlToPlainText,
  validateAccountSignature,
} from './accountSignatures.js';


const persisted = {
  account_id: 17,
  account_email: 'writer@example.test',
  enabled: true,
  include_on_new: true,
  include_on_replies: true,
  include_on_forwards: false,
  body_html: '<p>Writer Name<br>Example Co.</p>',
  body_text: 'Writer Name\nExample Co.',
  revision: 4,
  sanitizer_version: 1,
};


test('normalizes strict account signatures and rejects malformed or duplicate lists', () => {
  assert.deepEqual(normalizeAccountSignature(persisted), persisted);
  assert.equal(normalizeAccountSignature({ ...persisted, enabled: 'true' }), null);
  assert.equal(normalizeAccountSignature({ ...persisted, sanitizer_version: 0 }), null);
  assert.equal(normalizeAccountSignature({ ...persisted, body_text: '' }), null);
  assert.equal(normalizeAccountSignatureList({ accounts: [persisted], total: 1 }).accounts[0].account_id, 17);
  assert.throws(
    () => normalizeAccountSignatureList({ accounts: [persisted, persisted], total: 2 }),
    /duplicate accounts/,
  );
  assert.throws(() => normalizeAccountSignatureList({ accounts: [persisted], total: 2 }), /total/);
});


test('revision-zero records default off without inventing signature content', () => {
  assert.deepEqual(normalizeAccountSignature({
    account_id: 23,
    account_email: 'new@example.test',
    revision: 0,
  }), {
    account_id: 23,
    account_email: 'new@example.test',
    enabled: false,
    include_on_new: true,
    include_on_replies: true,
    include_on_forwards: true,
    body_html: '',
    body_text: '',
    revision: 0,
    sanitizer_version: 1,
  });
});


test('payloads sanitize rich content and derive a coherent plain fallback', () => {
  const sanitizeHtml = value => value.replace(/<script[^>]*>[\s\S]*?<\/script>/gi, '');
  assert.deepEqual(accountSignaturePayload({
    ...persisted,
    body_html: '<p>Writer Name<br>Example Co.</p><script>unsafe()</script>',
  }, { sanitizeHtml }), {
    enabled: true,
    include_on_new: true,
    include_on_replies: true,
    include_on_forwards: false,
    body_html: '<p>Writer Name<br>Example Co.</p>',
    body_text: 'Writer Name\nExample Co.',
    expected_revision: 4,
  });
  assert.equal(signatureHtmlToPlainText('<p>Hello<br>there</p><p>Again</p>'), 'Hello\nthere\nAgain');
  assert.equal(accountSignaturePayload({
    ...persisted,
    enabled: false,
    body_html: '<p><br></p>',
    body_text: '',
  }).body_html, '');
});


test('validation, dirty state, and effective summaries preserve explicit settings', () => {
  assert.equal(validateAccountSignature({ ...persisted, body_html: '', body_text: '' }), 'Write signature content before enabling it.');
  assert.equal(validateAccountSignature({
    ...persisted,
    include_on_new: false,
    include_on_replies: false,
    include_on_forwards: false,
  }), 'Choose at least one message type for this signature.');
  assert.equal(accountSignatureIsDirty(persisted, { ...persisted, account_email: 'renamed@example.test' }), false);
  assert.equal(accountSignatureIsDirty(persisted, { ...persisted, include_on_forwards: true }), true);
  assert.equal(accountSignatureSummary(persisted), 'On for new messages, replies');
  assert.equal(accountSignatureSummary({ ...persisted, enabled: false }), 'Off — no signature is added automatically');
});


test('settings surface is ordered, rich, explicit, session-safe, and touch sized', async () => {
  const [component, writing] = await Promise.all([
    readFile(new URL('./admin/SignaturePreferences.svelte', import.meta.url), 'utf8'),
    readFile(new URL('./admin/WritingPreferences.svelte', import.meta.url), 'utf8'),
  ]);
  assert.match(component, /DeferredRichEditor/);
  assert.match(component, /sanitizeComposeHtml/);
  assert.match(component, /captureAuthenticatedSession\(\)/);
  assert.match(component, /isAuthenticatedSessionCurrent\(session\)/);
  assert.match(component, /api\.listAccountSignatures\(\)/);
  assert.match(component, /api\.replaceAccountSignature\(editing\.account_id, payload\)/);
  assert.match(component, /role="dialog"/);
  assert.match(component, /role="switch"/);
  assert.match(component, /min-h-11/);
  assert.match(component, /@media \(max-width: 767px\)/);
  assert.match(component, /changed elsewhere[\s\S]*Reload latest/);
  assert.match(writing, /<FollowUpPreferences \/>[\s\S]*<SignaturePreferences \/>[\s\S]*Personal snippets/);
});
