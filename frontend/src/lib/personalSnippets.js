const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHORTCUT_RE = /^[a-z0-9][a-z0-9_-]{0,31}$/;

export function normalizeSnippetShortcut(value) {
  let shortcut = String(value ?? '').trim().toLowerCase();
  if (shortcut.startsWith(';')) shortcut = shortcut.slice(1).trim();
  return shortcut;
}

export function validSnippetShortcut(value) {
  return SHORTCUT_RE.test(normalizeSnippetShortcut(value));
}

export function normalizeSnippet(record) {
  if (!record || typeof record !== 'object' || Array.isArray(record)) return null;
  const snippetId = String(record.snippet_id ?? '').toLowerCase();
  const name = String(record.name ?? '').trim();
  const shortcut = normalizeSnippetShortcut(record.shortcut);
  const bodyHtml = String(record.body_html ?? '').trim();
  const bodyText = String(record.body_text ?? '').replace(/\r\n?/g, '\n').trim();
  const revision = Number(record.revision);
  if (
    !UUID_RE.test(snippetId)
    || !name
    || !validSnippetShortcut(shortcut)
    || !bodyHtml
    || !bodyText
    || !Number.isSafeInteger(revision)
    || revision <= 0
  ) return null;
  return {
    ...record,
    snippet_id: snippetId,
    name,
    shortcut,
    body_html: bodyHtml,
    body_text: bodyText,
    revision,
  };
}

export function normalizeSnippetList(response) {
  const source = Array.isArray(response) ? response : response?.snippets;
  if (!Array.isArray(source)) throw new Error('Snippets response is invalid');
  const snippets = source.map(normalizeSnippet);
  if (snippets.some(item => item === null)) throw new Error('Snippets response is invalid');
  const ids = new Set();
  const shortcuts = new Set();
  for (const snippet of snippets) {
    if (ids.has(snippet.snippet_id) || shortcuts.has(snippet.shortcut)) {
      throw new Error('Snippets response contains duplicates');
    }
    ids.add(snippet.snippet_id);
    shortcuts.add(snippet.shortcut);
  }
  return snippets;
}

function searchable(value) {
  return String(value ?? '').toLocaleLowerCase();
}

export function rankPersonalSnippets(snippets, query = '') {
  const needle = searchable(query).trim().replace(/^;/, '');
  const normalized = (Array.isArray(snippets) ? snippets : [])
    .map(normalizeSnippet)
    .filter(Boolean);

  const ranked = normalized.map(snippet => {
    if (!needle) return { snippet, rank: 5 };
    const name = searchable(snippet.name);
    const shortcut = searchable(snippet.shortcut);
    const body = searchable(snippet.body_text);
    let rank = Number.POSITIVE_INFINITY;
    if (shortcut === needle) rank = 0;
    else if (shortcut.startsWith(needle)) rank = 1;
    else if (name.startsWith(needle)) rank = 2;
    else if (shortcut.includes(needle) || name.includes(needle)) rank = 3;
    else if (body.includes(needle)) rank = 4;
    return { snippet, rank };
  }).filter(item => Number.isFinite(item.rank));

  ranked.sort((left, right) => (
    left.rank - right.rank
    || left.snippet.name.localeCompare(right.snippet.name, undefined, { sensitivity: 'base' })
    || left.snippet.shortcut.localeCompare(right.snippet.shortcut)
    || left.snippet.snippet_id.localeCompare(right.snippet.snippet_id)
  ));
  return ranked.map(item => item.snippet);
}

export function insertSnippetText(value, snippetText, selectionStart, selectionEnd) {
  const source = String(value ?? '');
  const text = String(snippetText ?? '').replace(/\r\n?/g, '\n');
  const start = Math.max(0, Math.min(source.length, Number(selectionStart) || 0));
  const end = Math.max(start, Math.min(source.length, Number(selectionEnd) || start));
  // Preserve selected text: insertion happens at its trailing caret boundary.
  const spacerBefore = end > 0 && source[end - 1] !== '\n' && text && text[0] !== '\n' ? '\n' : '';
  const spacerAfter = end < source.length && source[end] !== '\n' && text && text.at(-1) !== '\n' ? '\n' : '';
  const inserted = `${spacerBefore}${text}${spacerAfter}`;
  return {
    value: source.slice(0, end) + inserted + source.slice(end),
    caret: end + inserted.length,
  };
}

export function snippetEditorPayload({ snippetId, name, shortcut, bodyHtml, bodyText, revision }) {
  const payload = {
    name: String(name ?? '').trim().replace(/\s+/g, ' '),
    shortcut: normalizeSnippetShortcut(shortcut),
    body_html: String(bodyHtml ?? '').trim(),
    body_text: String(bodyText ?? '').replace(/\r\n?/g, '\n').trim(),
  };
  if (revision !== undefined && revision !== null) {
    payload.expected_revision = Number(revision);
  } else if (snippetId) {
    payload.snippet_id = String(snippetId);
  }
  return payload;
}

export function snippetHtmlToPlainText(html) {
  const source = String(html ?? '');
  if (typeof document !== 'undefined' && document.createElement) {
    const root = document.createElement('div');
    root.innerHTML = source;
    root.querySelectorAll('br').forEach(node => node.replaceWith('\n'));
    root.querySelectorAll('p, div, li, blockquote, pre, h1, h2, h3').forEach(node => {
      if (!node.textContent?.endsWith('\n')) node.append('\n');
    });
    return String(root.textContent || '').replace(/\u00a0/g, ' ').replace(/\n{3,}/g, '\n\n').trim();
  }
  return source
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/(p|div|li|blockquote|pre|h[1-3])>/gi, '\n')
    .replace(/<[^>]*>/g, '')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'")
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}
