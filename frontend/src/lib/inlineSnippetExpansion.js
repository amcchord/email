const QUERY_RE = /^(?:|[A-Za-z0-9][A-Za-z0-9_-]{0,31})$/;

function validOffset(value, maximum) {
  return Number.isInteger(value) && value >= 0 && value <= maximum;
}

function finite(value, fallback) {
  return Number.isFinite(Number(value)) ? Number(value) : fallback;
}

function clamp(value, minimum, maximum) {
  if (maximum < minimum) return minimum;
  return Math.min(maximum, Math.max(minimum, value));
}

/**
 * Detect the semicolon shortcut immediately before a collapsed caret.
 *
 * `blockStart` lets a rich-text caller identify the current text block when
 * its flattened text does not contain a newline between blocks. The returned
 * range never includes the safe leading boundary.
 */
export function detectInlineSnippetTrigger(
  value,
  { selectionStart, selectionEnd = selectionStart, blockStart = 0 } = {},
) {
  const source = String(value ?? '');
  if (
    !validOffset(selectionStart, source.length)
    || !validOffset(selectionEnd, source.length)
    || selectionStart !== selectionEnd
    || !validOffset(blockStart, selectionStart)
  ) return null;

  const caret = selectionStart;
  const semicolon = source.lastIndexOf(';', caret - 1);
  if (semicolon < blockStart || caret - semicolon > 33) return null;

  const query = source.slice(semicolon + 1, caret);
  if (!QUERY_RE.test(query)) return null;

  const atBlockStart = semicolon === blockStart;
  const precededByWhitespace = semicolon > 0 && /\s/.test(source[semicolon - 1]);
  if (!atBlockStart && !precededByWhitespace) return null;

  return Object.freeze({
    start: semicolon,
    end: caret,
    raw: source.slice(semicolon, caret),
    query,
    normalizedQuery: query.toLowerCase(),
  });
}

/**
 * Compact editor-facing form of `detectInlineSnippetTrigger`.
 *
 * The caller must already have established that the caret belongs to an
 * editable, collapsed selection. Supplying `blockStart` remains available for
 * a flattened rich-text block.
 */
export function findInlineSnippetTrigger(value, caret, { blockStart = 0 } = {}) {
  const trigger = detectInlineSnippetTrigger(value, {
    selectionStart: caret,
    selectionEnd: caret,
    blockStart,
  });
  if (!trigger) return null;
  return Object.freeze({
    from: trigger.start,
    to: trigger.end,
    token: trigger.raw,
    query: trigger.query,
    normalizedQuery: trigger.normalizedQuery,
  });
}

/**
 * Replace only the exact trigger range. A stale or malformed range fails
 * closed instead of deleting text around a moved caret.
 */
export function replaceInlineSnippetRange(value, trigger, replacement) {
  const source = String(value ?? '');
  const start = trigger?.start;
  const end = trigger?.end;
  if (
    !validOffset(start, source.length)
    || !validOffset(end, source.length)
    || end < start
  ) return null;

  const expected = String(trigger?.raw ?? '');
  if (!expected.startsWith(';') || source.slice(start, end) !== expected) return null;

  const inserted = String(replacement ?? '');
  const nextValue = source.slice(0, start) + inserted + source.slice(end);
  const caret = start + inserted.length;
  return Object.freeze({
    value: nextValue,
    selectionStart: caret,
    selectionEnd: caret,
    replaced: Object.freeze({ start, end }),
  });
}

/**
 * Editor-facing exact replacement form. `inserted` can be passed directly to
 * `HTMLTextAreaElement.setRangeText` without recomputing or trimming content.
 */
export function replaceInlineSnippetText(value, trigger, replacement) {
  const source = String(value ?? '');
  const from = trigger?.from;
  const to = trigger?.to;
  const token = String(trigger?.token ?? '');
  const result = replaceInlineSnippetRange(source, {
    start: from,
    end: to,
    raw: token,
  }, replacement);
  if (!result) return null;
  return Object.freeze({
    value: result.value,
    inserted: String(replacement ?? ''),
    caret: result.selectionStart,
    from,
    to,
  });
}

/**
 * Place a non-modal menu beside its caret while keeping every edge inside the
 * visual viewport. The menu moves above the caret when that side has more
 * useful space.
 */
export function clampInlineSnippetMenuPosition(anchorRect, viewport = {}) {
  const viewportWidth = Math.max(0, finite(viewport.width, 0));
  const viewportHeight = Math.max(0, finite(viewport.height, 0));
  const offsetLeft = finite(viewport.offsetLeft, 0);
  const offsetTop = finite(viewport.offsetTop, 0);
  const margin = 8;
  const gap = 6;
  const maximumWidth = 384;
  const maximumHeight = 320;

  const leftEdge = offsetLeft + margin;
  const rightEdge = offsetLeft + Math.max(margin, viewportWidth - margin);
  const topEdge = offsetTop + margin;
  const bottomEdge = offsetTop + Math.max(margin, viewportHeight - margin);
  const width = Math.max(0, Math.min(maximumWidth, rightEdge - leftEdge));
  const maximumViewportHeight = Math.max(0, Math.min(maximumHeight, bottomEdge - topEdge));

  const anchorLeft = finite(anchorRect?.left, leftEdge);
  const anchorTop = clamp(finite(anchorRect?.top, topEdge), topEdge, bottomEdge);
  const anchorBottom = clamp(finite(anchorRect?.bottom, anchorTop), anchorTop, bottomEdge);
  const left = clamp(anchorLeft, leftEdge, rightEdge - width);
  const below = Math.max(0, bottomEdge - (anchorBottom + gap));
  const above = Math.max(0, anchorTop - gap - topEdge);
  const usefulHeight = Math.min(176, maximumViewportHeight);
  const placement = below >= usefulHeight || below >= above ? 'below' : 'above';
  const available = placement === 'below' ? below : above;
  const maxHeight = Math.min(maximumViewportHeight, available);
  const top = placement === 'below'
    ? clamp(anchorBottom + gap, topEdge, bottomEdge - maxHeight)
    : clamp(anchorTop - gap - maxHeight, topEdge, bottomEdge - maxHeight);

  return Object.freeze({ left, top, width, maxHeight, placement });
}
