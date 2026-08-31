import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = relative => readFile(new URL(relative, import.meta.url), 'utf8');

const [page, api, routes, shortcuts, topbar, layout, keyboard, palette, overlay, stores, inbox, contacts] = await Promise.all([
  read('../pages/Attachments.svelte'),
  read('./api.js'),
  read('./lazyRoutes.js'),
  read('./shortcutDefaults.js'),
  read('../components/layout/TopBar.svelte'),
  read('../components/layout/Layout.svelte'),
  read('../components/common/KeyboardShortcutHandler.svelte'),
  read('../components/common/CommandPalette.svelte'),
  read('../components/common/ShortcutOverlay.svelte'),
  read('./stores.js'),
  read('../pages/Inbox.svelte'),
  read('../pages/Contacts.svelte'),
]);

test('Attachments is second in More, lazy-loaded, and globally navigable with G X', () => {
  assert.match(routes, /attachments: Object\.freeze\(\{ label: 'Attachments', load: \(\) => import\('\.\.\/pages\/Attachments\.svelte'\) \}\)/);
  assert.match(topbar, /\{ id: 'contacts', label: 'Contacts', icon: 'users' \},\s*\{ id: 'attachments', label: 'Attachments', icon: 'paperclip' \}/);
  assert.match(layout, /'nav\.attachments': \(\) => navigateByShortcut\('attachments'\)/);
  assert.match(shortcuts, /id: 'nav\.attachments',[^\n]*key: 'g x'/);
  assert.match(keyboard, /attachments: 'attachments'/);
  assert.match(palette, /attachments: 'attachments'/);
  assert.match(overlay, /attachments: 'attachments'/);
});

test('Attachments owns exact-account abortable metadata queries and complete list states', () => {
  assert.match(api, /queryAttachments: \(payload, \{ signal \} = \{\}\) =>\s*request\('POST', '\/attachments\/query', payload, \{ signal \}\)/);
  assert.match(page, /const delay = requestedQuery \? 220 : 0/);
  assert.match(page, /listController\?\.abort\(\)/);
  assert.match(page, /available\.length === 0[\s\S]*resetSurface\(\)[\s\S]*attachmentAccountId = null/);
  assert.match(page, /const preferred =[\s\S]*resetSurface\(\);\s*attachmentAccountId = Number\(preferred\.id\)/);
  assert.match(page, /normalizeAttachmentQueryResponse\(response, \{ accountId \}\)/);
  assert.match(page, /Metadata only · previews are explicit/);
  assert.match(page, /No connected account/);
  assert.match(page, /Loading attachments/);
  assert.match(page, /Attachments unavailable/);
  assert.match(page, /No attachments found/);
  assert.match(page, /Load more/);
  assert.doesNotMatch(page, /<img|thumbnail|gravatar|https?:\/\//i);
});

test('Attachments reuses hardened explicit transfers, keyboard actions, and exact parent handoff', () => {
  for (const action of [
    'attachments.next',
    'attachments.prev',
    'attachments.preview',
    'attachments.download',
    'attachments.open',
    'attachments.search',
    'attachments.close',
  ]) {
    assert.match(page, new RegExp(`'${action.replace('.', '\\.')}'`));
  }
  assert.match(page, /<AttachmentPreview/);
  assert.match(page, /api\.previewAttachment\(transfer\.email_id, transfer\.id/);
  assert.match(page, /api\.downloadAttachment\(transfer\.email_id, transfer\.id/);
  assert.match(page, /materializeAttachmentPreview/);
  assert.match(page, /releaseAttachmentPreview/);
  assert.match(page, /saveAttachmentBlob/);
  assert.match(page, /attachmentParentIntent\.set\(intent\)/);
  assert.match(page, /contactConversationIntent\.set\(null\)[\s\S]*attachmentParentIntent\.set\(intent\)/);
  assert.match(contacts, /attachmentParentIntent\.set\(null\)[\s\S]*contactConversationIntent\.set\(intent\)/);
  assert.match(page, /min-h-11|min-w-11/);
  assert.match(page, /event\.key !== 'Enter' \|\| event\.target !== event\.currentTarget/);
  assert.match(stores, /export const attachmentParentIntent = writable\(null\)/);
  assert.equal((stores.match(/attachmentParentIntent\.set\(null\)/g) || []).length, 1);
  assert.match(inbox, /pendingAttachmentAnchorEmailId\(snapshot\.accountId\)/);
  assert.match(inbox, /exactAttachmentIntent = normalizeAttachmentParentIntent/);
  assert.match(inbox, /exactContactIntent \|\| exactAttachmentIntent\s*\? await api\.getEmail\(id\)/);
  assert.match(inbox, /attachmentParentIntent\.set\(null\)/);
});
