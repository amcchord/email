import DOMPurify from 'dompurify';

/**
 * Sanitize HTML for safe rendering. Preserves email-safe tags and attributes
 * (styles, layout, images, links) while stripping scripts and event handlers.
 */
export function sanitizeHtml(html) {
  if (!html) return '';
  return DOMPurify.sanitize(html, {
    ADD_TAGS: ['style', 'link'],
    ADD_ATTR: [
      'target', 'class', 'style', 'align', 'valign',
      'width', 'height', 'bgcolor', 'background', 'border',
      'cellpadding', 'cellspacing', 'colspan', 'rowspan',
    ],
    WHOLE_DOCUMENT: false,
    ALLOW_DATA_ATTR: false,
  });
}

/**
 * Sanitize markdown-rendered HTML. More restrictive than email sanitization
 * since markdown output has a smaller set of expected tags.
 */
export function sanitizeMarkdown(html) {
  if (!html) return '';
  return DOMPurify.sanitize(html);
}
