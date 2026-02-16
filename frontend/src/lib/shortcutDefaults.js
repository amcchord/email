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
  { id: 'nav.calendar', key: 'g l', label: 'Go to Calendar',          context: 'global', category: 'Navigation' },
  { id: 'nav.todos',    key: 'g t', label: 'Go to Todos',             context: 'global', category: 'Navigation' },
  { id: 'nav.stats',    key: 'g s', label: 'Go to Stats',             context: 'global', category: 'Navigation' },
  { id: 'nav.insights', key: 'g a', label: 'Go to AI Insights',       context: 'global', category: 'Navigation' },
  { id: 'nav.chat',     key: 'g h', label: 'Go to Chat',              context: 'global', category: 'Navigation' },
  { id: 'nav.settings', key: 'g ,', label: 'Go to Settings',          context: 'global', category: 'Navigation' },
  { id: 'nav.compose',  key: 'c',   label: 'Compose new email',       context: 'global', category: 'Navigation' },
  { id: 'nav.search',   key: '/',   label: 'Focus search bar',        context: 'global', category: 'Navigation' },
  { id: 'nav.help',     key: '?',   label: 'Show keyboard shortcuts', context: 'global', category: 'Navigation' },
  { id: 'nav.theme',    key: '.',   label: 'Toggle dark/light theme', context: 'global', category: 'Navigation' },

  // ── Inbox / Email List ───────────────────────────────────────────
  { id: 'inbox.next',     key: 'j',       label: 'Next email',            context: 'inbox', category: 'Inbox' },
  { id: 'inbox.prev',     key: 'k',       label: 'Previous email',        context: 'inbox', category: 'Inbox' },
  { id: 'inbox.open',     key: 'o',       label: 'Open selected email',   context: 'inbox', category: 'Inbox' },
  { id: 'inbox.select',   key: 'x',       label: 'Toggle select',         context: 'inbox', category: 'Inbox' },
  { id: 'inbox.archive',  key: 'e',       label: 'Archive',               context: 'inbox', category: 'Inbox' },
  { id: 'inbox.trash',    key: '#',       label: 'Trash',                 context: 'inbox', category: 'Inbox' },
  { id: 'inbox.star',     key: 's',       label: 'Toggle star',           context: 'inbox', category: 'Inbox' },
  { id: 'inbox.read',     key: 'Shift+i', label: 'Mark as read',          context: 'inbox', category: 'Inbox' },
  { id: 'inbox.unread',   key: 'Shift+u', label: 'Mark as unread',        context: 'inbox', category: 'Inbox' },
  { id: 'inbox.spam',     key: '!',       label: 'Report spam',           context: 'inbox', category: 'Inbox' },
  { id: 'inbox.reply',    key: 'r',       label: 'Reply',                 context: 'inbox', category: 'Inbox' },
  { id: 'inbox.forward',  key: 'f',       label: 'Forward',               context: 'inbox', category: 'Inbox' },
  { id: 'inbox.viewMode', key: 'v',       label: 'Toggle table/column',   context: 'inbox', category: 'Inbox' },
  { id: 'inbox.sidebar',  key: '[',       label: 'Toggle sidebar',        context: 'inbox', category: 'Inbox' },
  { id: 'inbox.focused',  key: 'Shift+f', label: 'Toggle focused filter', context: 'inbox', category: 'Inbox' },

  // ── Email View ───────────────────────────────────────────────────
  { id: 'email.reply',   key: 'r',       label: 'Reply',             context: 'email-view', category: 'Email View' },
  { id: 'email.forward', key: 'f',       label: 'Forward',           context: 'email-view', category: 'Email View' },
  { id: 'email.archive', key: 'e',       label: 'Archive',           context: 'email-view', category: 'Email View' },
  { id: 'email.trash',   key: '#',       label: 'Trash',             context: 'email-view', category: 'Email View' },
  { id: 'email.star',    key: 's',       label: 'Toggle star',       context: 'email-view', category: 'Email View' },
  { id: 'email.close',   key: 'Escape',  label: 'Close email view',  context: 'email-view', category: 'Email View' },
  { id: 'email.popout',  key: 'Shift+p', label: 'Pop out to window', context: 'email-view', category: 'Email View' },

  // ── Flow ─────────────────────────────────────────────────────────
  { id: 'flow.next',       key: 'j',          label: 'Next item',               context: 'flow', category: 'Flow' },
  { id: 'flow.prev',       key: 'k',          label: 'Previous item',            context: 'flow', category: 'Flow' },
  { id: 'flow.nextSection', key: 'Tab',       label: 'Next section',             context: 'flow', category: 'Flow' },
  { id: 'flow.prevSection', key: 'Shift+Tab', label: 'Previous section',         context: 'flow', category: 'Flow' },
  { id: 'flow.open',       key: 'Enter',      label: 'Open selected item',       context: 'flow', category: 'Flow' },
  { id: 'flow.skip',       key: 'Shift+s',    label: 'Skip email',               context: 'flow', category: 'Flow' },
  { id: 'flow.ignore',     key: 'i',          label: 'Ignore needs-reply email', context: 'flow', category: 'Flow' },
  { id: 'flow.snooze',     key: 'z',          label: 'Snooze needs-reply email', context: 'flow', category: 'Flow' },
  { id: 'flow.newChat',    key: 'n',          label: 'New chat',                 context: 'flow', category: 'Flow' },
  { id: 'flow.send',       key: 'Ctrl+Enter', label: 'Send reply',               context: 'flow', category: 'Flow' },
  { id: 'flow.back',       key: 'Escape',     label: 'Back to list / deselect',  context: 'flow', category: 'Flow' },

  // ── Calendar ─────────────────────────────────────────────────────
  { id: 'cal.today', key: 't', label: 'Go to today',     context: 'calendar', category: 'Calendar' },
  { id: 'cal.prev',  key: 'p', label: 'Previous period', context: 'calendar', category: 'Calendar' },
  { id: 'cal.next',  key: 'n', label: 'Next period',     context: 'calendar', category: 'Calendar' },
  { id: 'cal.month', key: 'm', label: 'Month view',      context: 'calendar', category: 'Calendar' },
  { id: 'cal.week',  key: 'w', label: 'Week view',       context: 'calendar', category: 'Calendar' },
  { id: 'cal.day',   key: 'd', label: 'Day view',        context: 'calendar', category: 'Calendar' },

  // ── Compose ──────────────────────────────────────────────────────
  { id: 'compose.send',    key: 'Ctrl+Enter',   label: 'Send email',  context: 'compose', category: 'Compose' },
  { id: 'compose.draft',   key: 'Ctrl+s',       label: 'Save draft',  context: 'compose', category: 'Compose' },
  { id: 'compose.discard', key: 'Escape',        label: 'Discard / close', context: 'compose', category: 'Compose' },
  { id: 'compose.cc',      key: 'Ctrl+Shift+c', label: 'Toggle Cc',   context: 'compose', category: 'Compose' },
  { id: 'compose.bcc',     key: 'Ctrl+Shift+b', label: 'Toggle Bcc',  context: 'compose', category: 'Compose' },

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
