import DOMPurify from 'dompurify';

// Email and AI output are display surfaces, never interactive documents.
// Explicitly deny active/clobbering elements even if a future DOMPurify
// default becomes more permissive.
const FORBIDDEN_ACTIVE_TAGS = [
  'script', 'iframe', 'object', 'embed', 'form', 'input', 'button',
  'textarea', 'select', 'option', 'template', 'base', 'meta',
];

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
    FORBID_TAGS: FORBIDDEN_ACTIVE_TAGS,
    FORBID_ATTR: ['srcdoc'],
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
  return DOMPurify.sanitize(html, {
    FORBID_TAGS: FORBIDDEN_ACTIVE_TAGS,
    FORBID_ATTR: ['srcdoc'],
  });
}
