import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';


const [picker, inlineMenu, manager, admin, compose, reader, flow, rich, deferred, shortcuts] = await Promise.all([
  readFile(new URL('../components/email/SnippetPicker.svelte', import.meta.url), 'utf8'),
  readFile(new URL('../components/email/InlineSnippetMenu.svelte', import.meta.url), 'utf8'),
  readFile(new URL('./admin/WritingPreferences.svelte', import.meta.url), 'utf8'),
  readFile(new URL('../pages/Admin.svelte', import.meta.url), 'utf8'),
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
  assert.match(picker, /function handleDialogKeydown\(event\) \{\s*\/\/[\s\S]*event\.stopPropagation\(\)/);
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
  assert.match(manager, /createSnippetId = editing \? null : crypto\.randomUUID\(\)/);
  assert.match(manager, /snippetId: editing\?\.snippet_id \|\| createSnippetId/);
  assert.doesNotMatch(manager, /snippetId: editing\?\.snippet_id \|\| crypto\.randomUUID\(\)/);
  assert.match(admin, /id: 'writing', label: 'Writing', adminOnly: false/);
  assert.match(admin, /activeTab === 'writing'[\s\S]*<WritingPreferences \/>/);
});


test('all three writing surfaces use the shared picker and exact editor bridges', () => {
  assert.match(compose, /'compose\.snippets'/);
  assert.match(compose, /capturePersonalSnippetSelection\(\)[\s\S]*snippetPickerOpen = true/);
  assert.match(compose, /<SnippetPicker[\s\S]*oninsert=\{insertPersonalSnippet\}/);
  assert.match(reader, /'inbox\.snippets'/);
  assert.match(reader, /snippetSelection = \{[\s\S]*start: editor\.selectionStart[\s\S]*end: editor\.selectionEnd/);
  assert.match(reader, /insertSnippetText/);
  assert.match(flow, /'flow\.snippets'/);
  assert.match(flow, /capturePersonalSnippetSelection\(\)[\s\S]*snippetPickerOpen = true/);
  assert.match(flow, /replyEditorHandle\?\.insertHtml/);
  assert.match(rich, /savedInsertionPoint \?\? editor\.state\.selection\.to/);
  assert.match(rich, /const safeHtml = sanitizeComposeHtml\(String\(html \|\| ''\)\)/);
  assert.match(rich, /setTextSelection\(insertionPoint\)[\s\S]*insertContent\(safeHtml\)/);
  assert.match(deferred, /const safeHtml = sanitizeComposeHtml\(String\(html \|\| ''\)\)/);
  assert.match(deferred, /Preserve selected draft content/);
  assert.match(shortcuts, /id: 'compose\.snippets', key: 'Ctrl\+;'/);
  assert.match(shortcuts, /id: 'inbox\.snippets', key: 'Ctrl\+;'/);
  assert.match(shortcuts, /id: 'flow\.snippets',\s+key: 'Ctrl\+;'/);
});


test('inline semicolon expansion shares one keyboard-owned exact-range contract', () => {
  assert.match(picker, /type ; in the message/);
  assert.match(inlineMenu, /role="listbox"/);
  assert.match(inlineMenu, /event\.metaKey \|\| event\.ctrlKey \|\| event\.altKey/);
  assert.match(inlineMenu, /event\.key === 'Escape'/);
  assert.match(inlineMenu, /event\.key === 'Enter' \|\| event\.key === 'Tab'/);
  assert.match(inlineMenu, /isAuthenticatedSessionCurrent\(session\)/);
  assert.match(deferred, /inlineSnippets = false/);
  assert.match(deferred, /replaceFallbackInlineSnippet/);
  assert.match(deferred, /document\.execCommand\('insertHTML'/);
  assert.match(deferred, /if \(!inserted\) return false/);
  assert.doesNotMatch(deferred, /range\.deleteContents\(\)/);
  assert.match(deferred, /<InlineSnippetMenu/);
  assert.match(rich, /ed\.isActive\('link'\) \|\| ed\.isActive\('code'\) \|\| ed\.isActive\('codeBlock'\)/);
  assert.match(rich, /leaf => leaf\.type\.name === 'hardBreak' \? '\\n' : '\\ufffc'/);
  assert.match(rich, /deleteRange\(\{ from: trigger\.from, to: trigger\.to \}\)[\s\S]*insertContent\(safeHtml\)/);
  assert.match(rich, /handleKeyDown: \(_view, event\) => Boolean\(onInlineSnippetKeydown\?\.\(event\)\)/);
  assert.match(compose, /surface="compose"[\s\S]*inlineSnippets=\{true\}/);
  assert.match(flow, /surface="flow-reply"[\s\S]*inlineSnippets=\{true\}/);
  assert.match(reader, /<InlineSnippetMenu[\s\S]*menuId="inline-snippets-reader"/);
  assert.match(reader, /replaceInlineSnippetText/);
  assert.match(reader, /document\.execCommand\?\.\([\s\S]*'insertText'/);
  assert.match(reader, /if \(!insertedWithNativeUndo\) return false/);
  assert.doesNotMatch(reader, /setRangeText\(/);
  assert.match(reader, /inlineSnippetMenuHandle\?\.handleKeydown\?\.\(event\)/);
  assert.doesNotMatch(manager, /inlineSnippets=\{true\}/);
});
