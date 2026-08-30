import { safeClientFilename } from './attachmentDownload.js';

export const MAX_CLIENT_TEXT_PREVIEW_BYTES = 1024 * 1024;
export const MAX_CLIENT_IMAGE_PREVIEW_BYTES = 12 * 1024 * 1024;
export const MAX_CLIENT_PDF_PREVIEW_BYTES = 25 * 1024 * 1024;

const PREVIEW_MIME_KIND = new Map([
  ['application/pdf', 'pdf'],
  ['image/jpeg', 'image'],
  ['image/png', 'image'],
  ['image/webp', 'image'],
  ['text/plain', 'text'],
  ['text/csv', 'text'],
  ['text/markdown', 'text'],
  ['application/json', 'text'],
]);

const EXTENSION_KIND = new Map([
  ['pdf', 'pdf'],
  ['jpg', 'image'],
  ['jpeg', 'image'],
  ['png', 'image'],
  ['webp', 'image'],
  ['txt', 'text'],
  ['csv', 'text'],
  ['md', 'text'],
  ['log', 'text'],
  ['json', 'text'],
]);

const ACTIVE_EXTENSIONS = new Set([
  'app', 'apk', 'bat', 'cmd', 'com', 'dmg', 'exe', 'hta', 'html', 'htm',
  'iso', 'jar', 'js', 'jse', 'lnk', 'msi', 'msp', 'pkg', 'ps1', 'reg',
  'scr', 'svg', 'vbs', 'vbe', 'wsf', 'xhtml', 'xml',
  'docm', 'dotm', 'xlsm', 'xltm', 'pptm', 'potm', 'ppam',
]);

const ARCHIVE_EXTENSIONS = new Set([
  '7z', 'bz2', 'cab', 'gz', 'rar', 'tar', 'tgz', 'xz', 'zip',
]);

const ARCHIVE_MIMES = new Set([
  'application/gzip',
  'application/vnd.rar',
  'application/x-7z-compressed',
  'application/x-rar-compressed',
  'application/x-tar',
  'application/zip',
]);

const ACTIVE_MIMES = new Set([
  'application/hta',
  'application/javascript',
  'application/vnd.microsoft.portable-executable',
  'application/x-dosexec',
  'application/x-msdownload',
  'application/xhtml+xml',
  'image/svg+xml',
  'text/html',
  'text/javascript',
]);

const VERIFIED_KIND_MIMES = {
  image: new Set(['image/jpeg', 'image/png']),
  pdf: new Set(['application/pdf']),
  text: new Set(['text/plain']),
};

function normalizedMime(contentType) {
  return String(contentType || '').split(';', 1)[0].trim().toLowerCase();
}

function filenameExtension(filename) {
  const safeName = safeClientFilename(filename).toLowerCase();
  const dotIndex = safeName.lastIndexOf('.');
  return dotIndex > 0 && dotIndex < safeName.length - 1
    ? safeName.slice(dotIndex + 1)
    : '';
}

export function attachmentPreviewHint(attachment) {
  const extension = filenameExtension(attachment?.filename);
  if (ACTIVE_EXTENSIONS.has(extension) || ARCHIVE_EXTENSIONS.has(extension)) return null;

  const mimeKind = PREVIEW_MIME_KIND.get(normalizedMime(attachment?.content_type));
  const extensionKind = EXTENSION_KIND.get(extension);
  if (mimeKind && extensionKind && mimeKind !== extensionKind) return null;
  return mimeKind || extensionKind || null;
}

export function attachmentTypeLabel(attachment) {
  const mime = normalizedMime(attachment?.content_type);
  const extension = filenameExtension(attachment?.filename);
  const labels = {
    pdf: 'PDF document',
    image: 'Image',
    text: 'Text document',
  };
  const kind = PREVIEW_MIME_KIND.get(mime) || EXTENSION_KIND.get(extension);
  if (kind) return labels[kind];
  if (ARCHIVE_EXTENSIONS.has(extension) || ARCHIVE_MIMES.has(mime)) return 'Compressed archive';
  if (extension) return `${extension.toUpperCase()} file`;
  return 'File';
}

export function attachmentSafetyNotice(attachment) {
  const extension = filenameExtension(attachment?.filename);
  const mime = normalizedMime(attachment?.content_type);
  const mimeKind = PREVIEW_MIME_KIND.get(mime);
  const extensionKind = EXTENSION_KIND.get(extension);

  if (ACTIVE_EXTENSIONS.has(extension) || ACTIVE_MIMES.has(mime)) {
    return {
      tone: 'danger',
      label: 'Potentially unsafe file',
      detail: 'This file type may run code. Open it only if you expected it.',
      requiresConfirmation: true,
    };
  }
  if (ARCHIVE_EXTENSIONS.has(extension) || ARCHIVE_MIMES.has(mime)) {
    return {
      tone: 'caution',
      label: 'Compressed archive',
      detail: 'Inspect its contents before opening anything inside.',
      requiresConfirmation: true,
    };
  }
  if (mimeKind && extensionKind && mimeKind !== extensionKind) {
    return {
      tone: 'danger',
      label: 'File type mismatch',
      detail: 'The filename and reported file type do not agree.',
      requiresConfirmation: true,
    };
  }
  if (!attachmentPreviewHint(attachment)) {
    return {
      tone: 'neutral',
      label: 'Preview unavailable',
      detail: 'Download this file only if you recognize the sender and expected it.',
      requiresConfirmation: false,
    };
  }
  return null;
}

function previewSizeLimit(kind) {
  if (kind === 'text') return MAX_CLIENT_TEXT_PREVIEW_BYTES;
  if (kind === 'image') return MAX_CLIENT_IMAGE_PREVIEW_BYTES;
  if (kind === 'pdf') return MAX_CLIENT_PDF_PREVIEW_BYTES;
  return 0;
}

export async function materializeAttachmentPreview(
  result,
  {
    expectedKind = null,
    urlObject = globalThis.URL,
  } = {},
) {
  const kind = result?.kind;
  const blob = result?.blob;
  const contentType = normalizedMime(result?.contentType || blob?.type);
  if (
    !blob
    || (expectedKind && kind !== expectedKind)
    || !VERIFIED_KIND_MIMES[kind]?.has(contentType)
  ) {
    const error = new Error('The preview response did not match a safe renderer');
    error.status = 415;
    throw error;
  }
  if (blob.size <= 0 || blob.size > previewSizeLimit(kind)) {
    const error = new Error('The preview response exceeded the browser preview limit');
    error.status = 413;
    throw error;
  }

  if (kind === 'text') {
    return {
      blob,
      kind,
      text: await blob.text(),
      truncated: Boolean(result.truncated),
      objectUrl: null,
    };
  }
  if (kind === 'pdf') {
    return {
      blob,
      kind,
      text: '',
      truncated: false,
      objectUrl: null,
    };
  }
  if (!urlObject?.createObjectURL) {
    throw new Error('Previews are unavailable in this browser');
  }
  return {
    blob,
    kind,
    text: '',
    truncated: false,
    objectUrl: urlObject.createObjectURL(blob),
  };
}

export function releaseAttachmentPreview(preview, { urlObject = globalThis.URL } = {}) {
  if (preview?.objectUrl && urlObject?.revokeObjectURL) {
    urlObject.revokeObjectURL(preview.objectUrl);
  }
}

export function isCurrentAttachmentPreviewRequest({
  requestedEmailId,
  requestedAttachmentId,
  requestedGeneration,
  currentEmailId,
  currentAttachmentId,
  currentGeneration,
}) {
  return requestedEmailId === currentEmailId
    && requestedAttachmentId === currentAttachmentId
    && requestedGeneration === currentGeneration;
}
