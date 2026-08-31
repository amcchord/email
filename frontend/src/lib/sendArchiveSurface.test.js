import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const [buttonSource, composeSource, readerSource] = await Promise.all([
  readFile(new URL('../components/common/SendSplitButton.svelte', import.meta.url), 'utf8'),
  readFile(new URL('../pages/Compose.svelte', import.meta.url), 'utf8'),
  readFile(new URL('../components/email/EmailView.svelte', import.meta.url), 'utf8'),
]);

test('send options expose archive only when an exact source is supplied', () => {
  assert.match(buttonSource, /\{#if canArchiveAfterSend\}[\s\S]*Send &amp; archive/);
  assert.match(buttonSource, /The conversation stays in place if you undo, cancel, or delivery fails/);
  assert.match(buttonSource, /Archive conversation after delivery/);
  assert.match(buttonSource, /Cancellation or failed delivery leaves it where it is/);
  assert.match(buttonSource, /aria-labelledby="send-options-title"/);
  assert.match(buttonSource, /oncancel=\{handleCancel\}/);
  assert.match(buttonSource, /onkeydown=\{handleDialogKeydown\}/);
  assert.match(buttonSource, /event\.key !== 'Escape'[\s\S]*event\.stopPropagation\(\)[\s\S]*closeOptions\(\)/);
  assert.match(buttonSource, /optionsButton\.focus/);
  assert.doesNotMatch(buttonSource, /class="send-primary[\s\S]{0,500}bind:this=\{optionsButton\}/);
  assert.match(buttonSource, /bind:this=\{optionsButton\}[\s\S]{0,500}class="send-options/);
});

test('full Compose gates the action on a verified reply and keeps ordinary send unchanged', () => {
  assert.match(composeSource, /archiveSourceEmailId = \$derived\(exactSourceEmailId\(replyContext\.source_email_id\)\)/);
  assert.match(composeSource, /'compose\.sendArchive'/);
  assert.match(composeSource, /withArchiveAfterSend\(data, archiveAfterSend\)/);
  assert.match(composeSource, /delete restoreDraft\.archive_source_after_send/);
  assert.match(composeSource, /canArchiveAfterSend=\{archiveSourceEmailId !== null\}/);
  assert.match(composeSource, /onsend=\{\(\) => handleSend\(\)\}/);
});

test('inline reply uses the same exact-source payload and keyboard contract', () => {
  assert.match(readerSource, /'inbox\.sendArchive'/);
  assert.match(readerSource, /withArchiveAfterSend\(replyOwnerAtStart\.sendPayload\(\), archiveAfterSend\)/);
  assert.match(readerSource, /archiveAfterSend: event\.shiftKey/);
  assert.match(readerSource, /event\.stopPropagation\(\)/);
  assert.match(readerSource, /delete restoreDraft\.archive_source_after_send/);
  assert.match(readerSource, /canArchiveAfterSend=\{inlineReplyCanArchive\}/);
  assert.match(readerSource, /⌘⇧↵ Send &amp; archive/);
});
