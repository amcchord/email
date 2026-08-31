import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';


const [picker, manager, compose, reader, flow, rich, deferred, shortcuts] = await Promise.all([
  readFile(new URL('../components/email/SnippetPicker.svelte', import.meta.url), 'utf8'),
  readFile(new URL('./admin/WritingPreferences.svelte', import.meta.url), 'utf8'),
  readFile(new URL('../pages/Compose.svelte', import.meta.url), 'utf8'),
  readFile(new URL('../components/email/EmailView.svelte', import.meta.url), 'utf8'),
  readFile(new URL('../pages/Flow.svelte', import.meta.url), 'utf8'),
  readFile(new URL('../components/email/RichEditor.svelte', import.meta.url), 'utf8'),
  readFile(new URL('../components/email/DeferredRichEditor.svelte', import.meta.url), 'utf8'),
  readFile(new URL('./shortcutDefaults.js', import.meta.url), 'utf8'),
]);


test('one accessible picker owns loading, empty, error, keyboard, and narrow states', () => {
  assert.match(picker, /role="dialog"/);
  assert.match(picker, /role="listbox"/);
  assert.match(picker, /aria-activedescendant/);
  assert.match(picker, /event\.key === 'ArrowDown'/);
  assert.match(picker, /event\.key === 'Escape'[\s\S]*event\.stopPropagation/);
  assert.match(picker, /Snippets could not be loaded|Snippets could not be loaded|Retry/);
  assert.match(picker, /@media \(max-width: 767px\)/);
  assert.match(picker, /Manage snippets/);
});


test('writing settings preserve dirty and destructive content behind confirmation', () => {
  assert.match(manager, /Personal snippets/);
  assert.match(manager, /Create your first snippet/);
  assert.match(manager, /Discard your unsaved changes/);
  assert.match(manager, /Delete .*Existing drafts will keep their inserted text/s);
  assert.match(manager, /DeferredRichEditor/);
  assert.match(manager, /role="dialog"/);
});


test('all three writing surfaces use the shared picker and exact editor bridges', () => {
  assert.match(compose, /'compose\.snippets'/);
  assert.match(compose, /<SnippetPicker[\s\S]*oninsert=\{insertPersonalSnippet\}/);
  assert.match(reader, /'inbox\.snippets'/);
  assert.match(reader, /insertSnippetText/);
  assert.match(flow, /'flow\.snippets'/);
  assert.match(flow, /replyEditorHandle\?\.insertHtml/);
  assert.match(rich, /setTextSelection\(insertionPoint\)[\s\S]*insertContent\(safeHtml\)/);
  assert.match(deferred, /Preserve selected draft content/);
  assert.match(shortcuts, /id: 'compose\.snippets', key: 'Ctrl\+;'/);
  assert.match(shortcuts, /id: 'inbox\.snippets', key: 'Ctrl\+;'/);
  assert.match(shortcuts, /id: 'flow\.snippets',\s+key: 'Ctrl\+;'/);
});
