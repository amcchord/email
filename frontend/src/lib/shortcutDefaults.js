/**
 * Central definition of ALL keyboard shortcuts in the application.
 *
 * Each shortcut has:
 *   id       – unique action identifier (e.g. "nav.flow", "inbox.archive")
 *   key      – default key combo string (e.g. "g f", "Ctrl+Enter")
 *   label    – human-readable description
 *   context  – where it is active: "global", "inbox", "flow", "compose",
 *              "calendar", "todos", "chat", "email-view", "ai-insights"
 *   category – grouping for display in the help modal / settings page
 *
 * KEY COMBO FORMAT:
 *   - Single key:       "e", "/", "?"
 *   - With modifiers:   "Ctrl+Enter", "Shift+i", "Ctrl+Shift+c"
 *   - Multi-key seq:    "g f"  (press g, then f within 1 second)
 *   - Modifier names:   Ctrl, Shift, Alt, Meta  (Ctrl maps to Cmd on Mac)
 *
 * IMPORTANT FOR FUTURE DEVELOPERS:
 *   When adding a new interactive feature, add its shortcut(s) here,
 *   register the action handler in the relevant page component, and
 *   add a data-shortcut attribute to the triggering UI element.
 *   See .cursor/rules/keyboard-shortcuts.md for the full checklist.
 */

export const SHORTCUT_DEFAULTS = [
  // ── Navigation (global) ──────────────────────────────────────────
  { id: 'nav.flow',     key: 'g f', label: 'Go to Flow',              context: 'global', category: 'Navigation' },
  { id: 'nav.inbox',    key: 'g i', label: 'Go to Inbox',             context: 'global', category: 'Navigation' },
  { id: 'nav.savedViews', key: 'g v', label: 'Go to Saved Views',      context: 'global', category: 'Navigation', keywords: ['custom split', 'search', 'folder'] },
  { id: 'nav.calendar', key: 'g l', label: 'Go to Calendar',          context: 'global', category: 'Navigation' },
  { id: 'nav.glance',   key: 'g g', label: 'Go to At a Glance',       context: 'global', category: 'Navigation' },
  { id: 'nav.contacts', key: 'g p', label: 'Go to Contacts',          context: 'global', category: 'Navigation', keywords: ['people', 'correspondents', 'relationships'] },
  { id: 'nav.attachments', key: 'g x', label: 'Go to Attachments',    context: 'global', category: 'Navigation', keywords: ['files', 'documents', 'downloads'] },
  { id: 'nav.todos',    key: 'g t', label: 'Go to Todos',             context: 'global', category: 'Navigation' },
  { id: 'nav.stats',    key: 'g s', label: 'Go to Stats',             context: 'global', category: 'Navigation' },
  { id: 'nav.insights', key: 'g a', label: 'Go to AI Insights',       context: 'global', category: 'Navigation' },
  { id: 'nav.chat',     key: 'g h', label: 'Go to Chat',              context: 'global', category: 'Navigation' },
  { id: 'nav.subscriptions', key: 'g u', label: 'Go to Subscriptions', context: 'global', category: 'Navigation' },
  { id: 'nav.settings', key: 'g ,', label: 'Go to Settings',          context: 'global', category: 'Navigation' },
  { id: 'nav.compose',  key: 'c',   label: 'Compose new email',       context: 'global', category: 'Navigation' },
  { id: 'nav.search',   key: '/',   label: 'Focus search bar',        context: 'global', category: 'Navigation' },
  { id: 'nav.commands', key: 'Ctrl+k', label: 'Open command palette', context: 'global', category: 'Navigation', keywords: ['commands', 'actions', 'jump'] },
  { id: 'nav.help',     key: '?',   label: 'Show keyboard shortcuts', context: 'global', category: 'Navigation' },
  { id: 'nav.theme',    key: '.',   label: 'Toggle dark/light theme', context: 'global', category: 'Navigation' },

  // ── Inbox / Email List ───────────────────────────────────────────
  { id: 'inbox.next',     key: 'j',       label: 'Next conversation',     context: 'inbox', category: 'Inbox' },
  { id: 'inbox.prev',     key: 'k',       label: 'Previous conversation', context: 'inbox', category: 'Inbox' },
  { id: 'inbox.open',     key: 'o',       label: 'Open conversation',     context: 'inbox', category: 'Inbox' },
  { id: 'inbox.close',    key: 'Escape',  label: 'Close conversation',    context: 'inbox', category: 'Inbox' },
  { id: 'inbox.archive',  key: 'e',       label: 'Archive',               context: 'inbox', category: 'Inbox' },
  { id: 'inbox.trash',    key: '#',       label: 'Trash',                 context: 'inbox', category: 'Inbox' },
  { id: 'inbox.star',     key: 's',       label: 'Toggle star',           context: 'inbox', category: 'Inbox' },
  { id: 'inbox.read',     key: 'Shift+i', label: 'Mark as read',          context: 'inbox', category: 'Inbox' },
  { id: 'inbox.unread',   key: 'Shift+u', label: 'Mark as unread',        context: 'inbox', category: 'Inbox' },
  { id: 'inbox.spam',     key: '!',       label: 'Report spam',           context: 'inbox', category: 'Inbox' },
  { id: 'inbox.reply',    key: 'r',       label: 'Reply',                 context: 'inbox', category: 'Inbox' },
  { id: 'inbox.sendArchive', key: 'Ctrl+Shift+Enter', label: 'Send reply & archive', context: 'inbox', category: 'Inbox', keywords: ['send and archive', 'done'] },
  { id: 'inbox.snippets', key: 'Ctrl+;', label: 'Insert personal snippet', context: 'inbox', category: 'Inbox', keywords: ['template', 'saved reply', 'canned response'] },
  { id: 'inbox.availability', key: 'Ctrl+Shift+a', label: 'Share availability', context: 'inbox', category: 'Inbox', keywords: ['calendar', 'schedule', 'times'] },
  { id: 'inbox.forward',  key: 'f',       label: 'Forward',               context: 'inbox', category: 'Inbox' },
  { id: 'inbox.snooze',   key: 'h',       label: 'Snooze / remind later', context: 'inbox', category: 'Inbox', keywords: ['remind later', 'return to inbox'] },
  { id: 'inbox.label',    key: 'l',       label: 'Apply or remove label', context: 'inbox', category: 'Inbox', keywords: ['tag', 'organize'] },
  { id: 'inbox.move',     key: 'v',       label: 'Move to label',         context: 'inbox', category: 'Inbox', keywords: ['folder', 'file'] },
  { id: 'inbox.viewMode', key: 'Shift+v', label: 'Toggle table/column',   context: 'inbox', category: 'Inbox' },
  { id: 'inbox.sidebar',  key: '[',       label: 'Toggle sidebar',        context: 'inbox', category: 'Inbox' },
  { id: 'inbox.focused',  key: 'Shift+f', label: 'Toggle Split Inbox',     context: 'inbox', category: 'Inbox' },
  { id: 'inbox.nextSection', key: 'Shift+j', label: 'Next inbox section', context: 'inbox', category: 'Inbox' },
  { id: 'inbox.prevSection', key: 'Shift+k', label: 'Previous inbox section', context: 'inbox', category: 'Inbox' },
  { id: 'inbox.toggleSelection', key: 'x', label: 'Select focused conversation', context: 'inbox', category: 'Inbox', keywords: ['bulk', 'checkbox', 'triage'] },
  { id: 'inbox.selectLoaded', key: '', label: 'Select loaded conversations', context: 'inbox', category: 'Inbox', keywords: ['bulk', 'all', 'triage'] },
  { id: 'inbox.clearSelection', key: '', label: 'Clear conversation selection', context: 'inbox', category: 'Inbox', keywords: ['bulk', 'deselect', 'triage'] },
  { id: 'inbox.swipeSettings', key: '', label: 'Customize inbox swipes', context: 'inbox', category: 'Inbox', keywords: ['touch', 'mobile', 'triage'] },
  { id: 'inbox.teachSplit', key: '', label: 'Teach Split Inbox', context: 'inbox', category: 'Inbox', keywords: ['focused', 'other', 'rule', 'train'] },
  { id: 'inbox.manageSplitRules', key: '', label: 'Manage Split Inbox rules', context: 'inbox', category: 'Inbox', keywords: ['focused', 'other', 'rule', 'train'] },
  { id: 'inbox.undo',     key: 'z',       label: 'Undo last email action', context: 'inbox', category: 'Inbox' },
  { id: 'savedViews.saveCurrent', key: '', label: 'Save current search', context: 'inbox', category: 'Saved Views', keywords: ['custom split', 'filter'] },

  // ── Flow ─────────────────────────────────────────────────────────
  { id: 'flow.next',       key: 'j',          label: 'Next item',               context: 'flow', category: 'Flow' },
  { id: 'flow.prev',       key: 'k',          label: 'Previous item',            context: 'flow', category: 'Flow' },
  { id: 'flow.nextSection', key: 'Tab',       label: 'Next section',             context: 'flow', category: 'Flow' },
  { id: 'flow.prevSection', key: 'Shift+Tab', label: 'Previous section',         context: 'flow', category: 'Flow' },
  { id: 'flow.open',       key: 'Enter',      label: 'Open selected item',       context: 'flow', category: 'Flow' },
  { id: 'flow.skip',       key: 'Shift+s',    label: 'Skip email',               context: 'flow', category: 'Flow' },
  { id: 'flow.ignore',     key: 'i',          label: 'Ignore needs-reply email', context: 'flow', category: 'Flow' },
  { id: 'flow.snooze',     key: 'h',          label: 'Snooze / remind later',     context: 'flow', category: 'Flow', keywords: ['return to inbox', 'remind me'] },
  { id: 'flow.newChat',    key: 'n',          label: 'New chat',                 context: 'flow', category: 'Flow' },
  { id: 'flow.send',       key: 'Ctrl+Enter', label: 'Send reply',               context: 'flow', category: 'Flow' },
  { id: 'flow.snippets',   key: 'Ctrl+;',     label: 'Insert personal snippet',   context: 'flow', category: 'Flow', keywords: ['template', 'saved reply', 'canned response'] },
  { id: 'flow.availability', key: 'Ctrl+Shift+a', label: 'Share availability', context: 'flow', category: 'Flow', keywords: ['calendar', 'schedule', 'times'] },
  { id: 'flow.back',       key: 'Escape',     label: 'Back to list / deselect',  context: 'flow', category: 'Flow' },
  { id: 'flow.replyOption1', key: '1',       label: 'Select reply option 1',    context: 'flow', category: 'Flow' },
  { id: 'flow.replyOption2', key: '2',       label: 'Select reply option 2',    context: 'flow', category: 'Flow' },
  { id: 'flow.replyOption3', key: '3',       label: 'Select reply option 3',    context: 'flow', category: 'Flow' },
  { id: 'flow.replyOption4', key: '4',       label: 'Select reply option 4',    context: 'flow', category: 'Flow' },
  { id: 'flow.customReply',  key: '0',       label: 'Custom reply',             context: 'flow', category: 'Flow' },

  // ── Calendar ─────────────────────────────────────────────────────
  { id: 'cal.today', key: 't', label: 'Go to today',     context: 'calendar', category: 'Calendar' },
  { id: 'cal.prev',  key: 'p', label: 'Previous period', context: 'calendar', category: 'Calendar' },
  { id: 'cal.next',  key: 'n', label: 'Next period',     context: 'calendar', category: 'Calendar' },
  { id: 'cal.month', key: 'm', label: 'Month view',      context: 'calendar', category: 'Calendar' },
  { id: 'cal.week',  key: 'w', label: 'Week view',       context: 'calendar', category: 'Calendar' },
  { id: 'cal.day',   key: 'd', label: 'Day view',        context: 'calendar', category: 'Calendar' },

  // ── Compose ──────────────────────────────────────────────────────
  { id: 'compose.send',    key: 'Ctrl+Enter',   label: 'Send email',  context: 'compose', category: 'Compose' },
  { id: 'compose.sendArchive', key: 'Ctrl+Shift+Enter', label: 'Send reply & archive', context: 'compose', category: 'Compose', keywords: ['send and archive', 'done'] },
  { id: 'compose.snippets', key: 'Ctrl+;', label: 'Insert personal snippet', context: 'compose', category: 'Compose', keywords: ['template', 'saved reply', 'canned response'] },
  { id: 'compose.availability', key: 'Ctrl+Shift+a', label: 'Share availability', context: 'compose', category: 'Compose', keywords: ['calendar', 'schedule', 'times'] },
  { id: 'compose.draft',   key: 'Ctrl+s',       label: 'Save draft',  context: 'compose', category: 'Compose' },
  { id: 'compose.discard', key: 'Escape',        label: 'Close and keep draft', context: 'compose', category: 'Compose' },
  { id: 'compose.deleteDraft', key: 'Ctrl+Shift+,', label: 'Discard draft', context: 'compose', category: 'Compose' },
  { id: 'compose.cc',      key: 'Ctrl+Shift+c', label: 'Toggle Cc',   context: 'compose', category: 'Compose' },
  { id: 'compose.bcc',     key: 'Ctrl+Shift+b', label: 'Toggle Bcc',  context: 'compose', category: 'Compose' },

  // ── Contacts ────────────────────────────────────────────────────
  { id: 'contacts.next',   key: 'j',      label: 'Next contact',      context: 'contacts', category: 'Contacts' },
  { id: 'contacts.prev',   key: 'k',      label: 'Previous contact',  context: 'contacts', category: 'Contacts' },
  { id: 'contacts.open',   key: 'Enter',  label: 'Open contact',      context: 'contacts', category: 'Contacts' },
  { id: 'contacts.email',  key: 'c',      label: 'Email contact',     context: 'contacts', category: 'Contacts' },
  { id: 'contacts.search', key: '/',      label: 'Search contacts',   context: 'contacts', category: 'Contacts' },
  { id: 'contacts.back',   key: 'Escape', label: 'Back to contacts', context: 'contacts', category: 'Contacts' },

  // ── Attachments ───────────────────────────────────────────
  { id: 'attachments.next',     key: 'j',      label: 'Next attachment',        context: 'attachments', category: 'Attachments' },
  { id: 'attachments.prev',     key: 'k',      label: 'Previous attachment',    context: 'attachments', category: 'Attachments' },
  { id: 'attachments.preview',  key: 'Enter',  label: 'Preview attachment',     context: 'attachments', category: 'Attachments' },
  { id: 'attachments.download', key: 'd',      label: 'Download attachment',    context: 'attachments', category: 'Attachments' },
  { id: 'attachments.open',     key: 'o',      label: 'Open containing email',  context: 'attachments', category: 'Attachments' },
  { id: 'attachments.search',   key: '/',      label: 'Search attachments',     context: 'attachments', category: 'Attachments' },
  { id: 'attachments.close',    key: 'Escape', label: 'Close attachment preview', context: 'attachments', category: 'Attachments' },

  // ── Todos ────────────────────────────────────────────────────────
  { id: 'todos.new',    key: 'n',     label: 'New todo',        context: 'todos', category: 'Todos' },
  { id: 'todos.next',   key: 'j',     label: 'Next todo',       context: 'todos', category: 'Todos' },
  { id: 'todos.prev',   key: 'k',     label: 'Previous todo',   context: 'todos', category: 'Todos' },
  { id: 'todos.toggle', key: 'Space', label: 'Toggle complete', context: 'todos', category: 'Todos' },
  { id: 'todos.delete', key: '#',     label: 'Delete selected', context: 'todos', category: 'Todos' },

  // ── Chat ─────────────────────────────────────────────────────────
  { id: 'chat.new',   key: 'n', label: 'New conversation',      context: 'chat', category: 'Chat' },
  { id: 'chat.next',  key: 'j', label: 'Next conversation',     context: 'chat', category: 'Chat' },
  { id: 'chat.prev',  key: 'k', label: 'Previous conversation', context: 'chat', category: 'Chat' },
  { id: 'chat.focus', key: 'i', label: 'Focus input',           context: 'chat', category: 'Chat' },
];

/**
 * Build a lookup map: id -> shortcut definition.
 */
export function getDefaultsMap() {
  const map = {};
  for (const s of SHORTCUT_DEFAULTS) {
    map[s.id] = s;
  }
  return map;
}

/**
 * Get all unique categories in display order.
 */
export function getCategories() {
  const seen = new Set();
  const cats = [];
  for (const s of SHORTCUT_DEFAULTS) {
    if (!seen.has(s.category)) {
      seen.add(s.category);
      cats.push(s.category);
    }
  }
  return cats;
}

/**
 * Get all unique contexts.
 */
export function getContexts() {
  const seen = new Set();
  for (const s of SHORTCUT_DEFAULTS) {
    seen.add(s.context);
  }
  return [...seen];
}
