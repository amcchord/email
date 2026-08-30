import DOMPurify from 'dompurify';
import {
  attributeMayLoadRemoteContent,
  cssMayLoadRemoteContent,
  remoteAttributeCanLoadDirectly,
} from './remoteContent.js';

// Email and AI output are display surfaces, never interactive documents.
// Explicitly deny active/clobbering elements even if a future DOMPurify
// default becomes more permissive.
const FORBIDDEN_ACTIVE_TAGS = [
  'script', 'iframe', 'object', 'embed', 'form', 'input', 'button',
  'textarea', 'select', 'option', 'template', 'base', 'meta',
];

const EMAIL_SANITIZE_OPTIONS = {
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
};

function createNetworkLockedSanitizer(html) {
  if (typeof document === 'undefined' || !document.documentElement) return undefined;

  const frame = document.createElement('iframe');
  frame.hidden = true;
  frame.tabIndex = -1;
  frame.setAttribute('aria-hidden', 'true');
  frame.setAttribute('sandbox', 'allow-same-origin');
  frame.setAttribute('referrerpolicy', 'no-referrer');
  document.documentElement.append(frame);

  const lockedDocument = frame.contentDocument;
  if (!lockedDocument || !frame.contentWindow) {
    frame.remove();
    return null;
  }

  lockedDocument.open();
  lockedDocument.write(`<!doctype html><html><head>
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data: cid: blob:; media-src data: cid: blob:; style-src 'unsafe-inline'; font-src data:; connect-src 'none'; frame-src 'none'; object-src 'none'; script-src 'none'; base-uri 'none'; form-action 'none'">
    <meta name="referrer" content="no-referrer">
    <meta http-equiv="x-dns-prefetch-control" content="off">
  </head><body></body></html>`);
  lockedDocument.close();

  // Parse in a detached template owned by the CSP-locked document. This keeps
  // browser preload scanners behind a no-network policy before DOMPurify sees
  // sender-controlled markup.
  const template = lockedDocument.createElement('template');
  const root = lockedDocument.createElement('div');
  template.content.append(root);
  root.innerHTML = html;

  return {
    frame,
    root,
    purifier: DOMPurify(frame.contentWindow),
  };
}

function replaceUnavailableImages(root) {
  root.querySelectorAll('img').forEach((image) => {
    const source = image.getAttribute('src')?.trim() ?? '';
    const hasDisplaySource = source !== '' || image.hasAttribute('srcset');
    const unresolvedCid = /^cid:/i.test(source);
    if (hasDisplaySource && !unresolvedCid) return;

    const alternative = image.getAttribute('alt')?.trim() ?? '';
    const label = unresolvedCid ? 'Inline image unavailable' : 'Remote image blocked';
    const placeholder = root.ownerDocument.createElement('span');
    placeholder.className = 'remote-image-placeholder';
    placeholder.setAttribute('role', 'img');
    placeholder.setAttribute('aria-label', alternative ? `${label}: ${alternative}` : label);
    placeholder.textContent = alternative ? `${label}: ${alternative}` : label;
    image.replaceWith(placeholder);
  });
}

function sanitizeWithRemoteContentPolicy(html, {
  allowRemoteContent = false,
  stripDocumentStyles = false,
} = {}) {
  if (!html) {
    return { html: '', remoteResourceCount: 0, directLoadableResourceCount: 0 };
  }

  let remoteResourceCount = 0;
  let directLoadableResourceCount = 0;
  const locked = createNetworkLockedSanitizer(html);
  if (locked === null) {
    // A browser that cannot establish the no-network parsing context fails
    // closed instead of parsing sender HTML in the application document.
    return { html: '', remoteResourceCount: 1, directLoadableResourceCount: 0 };
  }
  const purifier = locked?.purifier ?? DOMPurify;
  const inspectElement = (node, data) => {
    if (data.tagName === 'style' && cssMayLoadRemoteContent(node.textContent)) {
      remoteResourceCount += 1;
      // Remote CSS can fan out into imports, fonts, cursors, filters, and
      // images. Keep it blocked even during the direct one-message opt-in.
      node.remove();
    }
  };
  const inspectAttribute = (node, data) => {
    if (!attributeMayLoadRemoteContent(node.nodeName, data.attrName, data.attrValue)) return;
    remoteResourceCount += 1;
    const canLoadDirectly = remoteAttributeCanLoadDirectly(
      node.nodeName,
      data.attrName,
      data.attrValue,
      typeof window === 'undefined' ? null : window.location.origin,
    );
    if (canLoadDirectly) directLoadableResourceCount += 1;
    if (!allowRemoteContent || !canLoadDirectly) data.keepAttr = false;
  };

  purifier.addHook('uponSanitizeElement', inspectElement);
  purifier.addHook('uponSanitizeAttribute', inspectAttribute);
  try {
    const options = {
      ...EMAIL_SANITIZE_OPTIONS,
      FORBID_TAGS: stripDocumentStyles
        ? [...FORBIDDEN_ACTIVE_TAGS, 'style', 'link', 'svg', 'math']
        : FORBIDDEN_ACTIVE_TAGS,
      FORBID_ATTR: stripDocumentStyles
        ? ['srcdoc', 'style', 'background']
        : ['srcdoc'],
    };
    let sanitized;
    if (locked) {
      purifier.sanitize(locked.root, { ...options, IN_PLACE: true });
      replaceUnavailableImages(locked.root);
      sanitized = locked.root.innerHTML;
    } else {
      sanitized = purifier.sanitize(html, options);
    }
    return { html: sanitized, remoteResourceCount, directLoadableResourceCount };
  } finally {
    purifier.removeHook('uponSanitizeElement', inspectElement);
    purifier.removeHook('uponSanitizeAttribute', inspectAttribute);
    locked?.frame.remove();
  }
}

/**
 * Sanitize HTML for safe rendering. Preserves email-safe tags and attributes
 * (styles, layout, images, links) while stripping scripts and event handlers.
 */
export function sanitizeHtml(html) {
  if (!html) return '';
  return DOMPurify.sanitize(html, EMAIL_SANITIZE_OPTIONS);
}

/**
 * Prepare received email HTML for an isolated reader frame. Remote resources
 * are removed unless the user explicitly opts in for this message.
 */
export function sanitizeEmailHtml(html, { allowRemoteContent = false } = {}) {
  return sanitizeWithRemoteContentPolicy(html, { allowRemoteContent });
}

/**
 * Prepare received/quoted HTML before it enters the app-document composer.
 * Stylesheets and sender-authored CSS are removed as well as remote resources.
 */
export function sanitizeComposeHtml(html) {
  return sanitizeWithRemoteContentPolicy(html, {
    allowRemoteContent: false,
    stripDocumentStyles: true,
  }).html;
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
