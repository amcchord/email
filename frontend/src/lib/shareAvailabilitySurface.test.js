import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';


const [picker, compose, reader, flow, apiClient, shortcuts] = await Promise.all([
  readFile(new URL('../components/email/AvailabilityPicker.svelte', import.meta.url), 'utf8'),
  readFile(new URL('../pages/Compose.svelte', import.meta.url), 'utf8'),
  readFile(new URL('../components/email/EmailView.svelte', import.meta.url), 'utf8'),
  readFile(new URL('../pages/Flow.svelte', import.meta.url), 'utf8'),
  readFile(new URL('./api.js', import.meta.url), 'utf8'),
  readFile(new URL('./shortcutDefaults.js', import.meta.url), 'utf8'),
]);


test('shared picker exposes the frozen accessible controls and complete non-mutating states', () => {
  for (const label of [
    'Share availability',
    'Calendars to check',
    'Date range',
    'Meeting length',
    'Workday starts',
    'Workday ends',
    'Include weekends',
    'Time zone',
    'Check availability',
    'Available times',
    'Insert selected times',
  ]) assert.match(picker, new RegExp(label));
  assert.match(picker, /role="dialog"/);
  assert.match(picker, /aria-modal="true"/);
  assert.match(picker, /event\.key === 'Escape'/);
  assert.match(picker, /event\.key !== 'Tab'/);
  assert.match(picker, /returnFocus\.focus/);
  assert.match(picker, /Checking saved calendars/);
  assert.match(picker, /Retry/);
  assert.match(picker, /No times fit these settings/);
  assert.match(picker, /Calendar coverage is incomplete/);
  assert.match(picker, /@media \(max-width: 767px\)/);
  assert.match(picker, /align-items: flex-end/);
});


test('picker guards auth, request generation, settings generation, and sender identity', () => {
  assert.match(picker, /captureAuthenticatedSession\(\)/);
  assert.match(picker, /isAuthenticatedSessionCurrent\(session\)/);
  assert.match(picker, /generation !== requestGeneration/);
  assert.match(picker, /configurationAtStart !== configurationGeneration/);
  assert.match(picker, /senderAtStart !== senderId/);
  assert.match(picker, /selectedScopeIsCurrent\(accountIdsAtStart\)/);
  assert.match(picker, /currentSenderId === observedSenderId/);
  assert.match(picker, /resetPicker\(\);[\s\S]*if \(open\) void closePicker\(\)/);
  assert.match(picker, /disabled=\{Number\(account\.id\) === senderId\}/);
  assert.doesNotMatch(picker, /localStorage|sessionStorage|URLSearchParams|location\.search/);
});


test('compose, reader, and flow share exact shortcuts and preserve their editor insertion contracts', () => {
  assert.match(apiClient, /getCalendarAvailability:[\s\S]*request\('POST', '\/calendar\/availability', payload, \{ signal \}\)/);
  for (const [surface, source] of [
    ['compose', compose],
    ['inbox', reader],
    ['flow', flow],
  ]) {
    assert.match(source, new RegExp(`'${surface}\\.availability'`));
    assert.match(source, /<AvailabilityPicker/);
    assert.match(shortcuts, new RegExp(`id: '${surface}\\.availability', key: 'Ctrl\\+Shift\\+a'`));
  }
  assert.match(compose, /captureAvailabilitySelection\(\)[\s\S]*rememberSelection/);
  assert.match(compose, /sanitizeComposeHtml[\s\S]*editorHandle\?\.insertHtml/);
  assert.match(flow, /captureAvailabilitySelection\(\)[\s\S]*rememberSelection/);
  assert.match(flow, /sanitizeComposeHtml[\s\S]*replyEditorHandle\?\.insertHtml/);
  assert.match(reader, /availabilitySelection = \{ caret: editor\.selectionEnd \}/);
  assert.match(reader, /document\.execCommand\?\.[\s\S]*'insertText'/);
  assert.match(reader, /persistInlineReply\(\)/);
});
