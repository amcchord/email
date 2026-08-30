const SAFE_EMBEDDED_RESOURCE_PREFIX = /^(?:data:image\/(?:avif|gif|jpe?g|png|webp);base64,|cid:|about:blank(?:#|$))/i;

const RESOURCE_ATTRIBUTES = new Map([
  ['img', new Set(['src', 'srcset'])],
  ['source', new Set(['src', 'srcset'])],
  ['video', new Set(['src', 'poster'])],
  ['audio', new Set(['src'])],
  ['track', new Set(['src'])],
  ['link', new Set(['href', 'imagesrcset'])],
  ['image', new Set(['href', 'xlink:href'])],
  ['feimage', new Set(['href', 'xlink:href'])],
  ['use', new Set(['href', 'xlink:href'])],
  ['mglyph', new Set(['src'])],
]);

const CSS_URL_ATTRIBUTES = new Set([
  'clip-path', 'cursor', 'fill', 'filter', 'mask', 'marker',
  'marker-end', 'marker-mid', 'marker-start', 'stroke',
]);

const DIRECT_LOADABLE_ATTRIBUTES = new Map([
  ['img', new Set(['src', 'srcset'])],
  ['source', new Set(['src', 'srcset'])],
  ['video', new Set(['src', 'poster'])],
  ['audio', new Set(['src'])],
  ['track', new Set(['src'])],
  ['image', new Set(['href', 'xlink:href'])],
]);

export function isSafeEmbeddedResourceUrl(value) {
  const normalized = String(value ?? '').trim();
  return normalized !== '' && SAFE_EMBEDDED_RESOURCE_PREFIX.test(normalized);
}

function isLocalFragmentResourceUrl(value) {
  return /^#[^\s]*$/.test(String(value ?? '').trim());
}

function decodeCssEscapes(css) {
  return String(css ?? '').replace(
    /\\([0-9a-f]{1,6})(?:\s)?|\\([^\r\n\f])/gi,
    (_match, hex, escapedCharacter) => {
      if (!hex) return escapedCharacter;
      const codePoint = Number.parseInt(hex, 16);
      return codePoint === 0 || codePoint > 0x10FFFF
        ? '\uFFFD'
        : String.fromCodePoint(codePoint);
    },
  );
}

function unquoteCssValue(value) {
  const normalized = value.trim();
  if (normalized.length >= 2) {
    const first = normalized[0];
    const last = normalized.at(-1);
    if ((first === '"' && last === '"') || (first === "'" && last === "'")) {
      return normalized.slice(1, -1).trim();
    }
  }
  return normalized;
}

export function cssMayLoadRemoteContent(value) {
  const css = decodeCssEscapes(value);
  const urlPattern = /url\(\s*([^)]*?)\s*\)/gi;
  let match;
  while ((match = urlPattern.exec(css)) !== null) {
    const resource = unquoteCssValue(match[1]);
    if (!isSafeEmbeddedResourceUrl(resource) && !isLocalFragmentResourceUrl(resource)) return true;
  }

  const importPattern = /@import\s+(?:url\(\s*)?((?:"[^"]*"|'[^']*'|[^;\s)]*))/gi;
  while ((match = importPattern.exec(css)) !== null) {
    const resource = unquoteCssValue(match[1]);
    if (!isSafeEmbeddedResourceUrl(resource) && !isLocalFragmentResourceUrl(resource)) return true;
  }

  // CSS image-set() accepts quoted URLs without url(). Treat the whole
  // declaration as remote unless every candidate is an embedded scheme.
  const imageSetPattern = /(?:-webkit-)?image-set\(([^)]*)\)/gi;
  while ((match = imageSetPattern.exec(css)) !== null) {
    const candidates = [...match[1].matchAll(/(?:^|,)\s*(?:url\(\s*)?("[^"]*"|'[^']*'|[^,\s)]+)/gi)];
    if (candidates.some(candidate => {
      const resource = unquoteCssValue(candidate[1]);
      return !isSafeEmbeddedResourceUrl(resource) && !isLocalFragmentResourceUrl(resource);
    })) {
      return true;
    }
  }

  return false;
}

export function attributeMayLoadRemoteContent(tagName, attributeName, value) {
  const tag = String(tagName ?? '').toLowerCase();
  const attribute = String(attributeName ?? '').toLowerCase();

  if (attribute === 'style') return cssMayLoadRemoteContent(value);
  if (CSS_URL_ATTRIBUTES.has(attribute)) return cssMayLoadRemoteContent(value);
  if (attribute === 'background') return !isSafeEmbeddedResourceUrl(value);
  if (attribute === 'ping' || attribute === 'attributionsrc') {
    return String(value ?? '').trim() !== '';
  }
  // SVG and MathML use href/xlink:href across a broad and evolving set of
  // resource-bearing elements. User-activated anchors are handled separately
  // by the frame; every other external href stays fail-closed.
  const isUserActivatedLink = attribute === 'href' && ['a', 'area'].includes(tag);
  if ((attribute === 'href' || attribute === 'xlink:href') && !isUserActivatedLink) {
    return !isSafeEmbeddedResourceUrl(value) && !isLocalFragmentResourceUrl(value);
  }
  if (!RESOURCE_ATTRIBUTES.get(tag)?.has(attribute)) return false;

  // A data URL itself contains a comma, so srcset cannot be split safely with
  // ordinary string logic. Withhold every candidate set until explicit load;
  // a safe single embedded image remains available through src.
  if (attribute === 'srcset' || attribute === 'imagesrcset') {
    return String(value ?? '').trim() !== '';
  }

  return !isSafeEmbeddedResourceUrl(value);
}

/**
 * Return whether a detected remote attribute is intentionally restored by the
 * one-message direct-loading action. Keep this as a narrow allowlist: CSS,
 * navigation beacons, external SVG references, and stylesheets stay removed.
 */
function isExternalHttpResource(value, applicationOrigin) {
  const normalized = String(value ?? '').trim();
  if (!/^(?:https?:)?\/\//i.test(normalized)) return false;
  if (!applicationOrigin) return true;

  try {
    const appUrl = new URL(applicationOrigin);
    const resourceUrl = new URL(normalized, appUrl);
    return ['http:', 'https:'].includes(resourceUrl.protocol)
      && resourceUrl.hostname !== appUrl.hostname;
  } catch {
    return false;
  }
}

export function remoteAttributeCanLoadDirectly(
  tagName,
  attributeName,
  value,
  applicationOrigin = null,
) {
  const tag = String(tagName ?? '').toLowerCase();
  const attribute = String(attributeName ?? '').toLowerCase();

  const loadableAttribute = attribute === 'background'
    || (DIRECT_LOADABLE_ATTRIBUTES.get(tag)?.has(attribute) ?? false);
  if (!loadableAttribute) return false;

  const normalized = String(value ?? '').trim();
  if (attribute === 'srcset') {
    // A comma is valid inside a data URL and URL path, so this intentionally
    // rejects ambiguous candidate sets. Ordinary absolute HTTP(S) candidates
    // remain available; relative values never become same-origin app requests.
    if (!normalized || /data:/i.test(normalized)) return false;
    return normalized.split(',').every((candidate) => {
      const [resource] = candidate.trim().split(/\s+/, 1);
      return isExternalHttpResource(resource, applicationOrigin);
    });
  }
  return isExternalHttpResource(normalized, applicationOrigin);
}

export function emailContentSecurityPolicy(allowRemoteContent = false) {
  const remoteSources = allowRemoteContent ? ' https: http:' : '';
  return [
    "default-src 'none'",
    `img-src data: cid: blob:${remoteSources}`,
    `media-src data: cid: blob:${remoteSources}`,
    "style-src 'unsafe-inline'",
    "font-src data:",
    "connect-src 'none'",
    "worker-src 'none'",
    "frame-src 'none'",
    "child-src 'none'",
    "manifest-src 'none'",
    "prefetch-src 'none'",
    "object-src 'none'",
    "script-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
  ].join('; ');
}
