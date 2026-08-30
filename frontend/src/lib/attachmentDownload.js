export const MAX_ACTIVE_ATTACHMENT_REQUESTS = 3;

export function safeClientFilename(filename) {
  const leafName = String(filename || 'attachment').replaceAll('\\', '/').split('/').pop();
  const cleaned = [...leafName]
    .filter((character) => !/\p{C}/u.test(character))
    .join('')
    .trim();
  if (!cleaned || cleaned === '.' || cleaned === '..') return 'attachment';
  const characters = [...cleaned];
  if (characters.length <= 180) return cleaned;

  const dotIndex = cleaned.lastIndexOf('.');
  const rawSuffix = dotIndex > 0 ? cleaned.slice(dotIndex) : '';
  const suffix = [...rawSuffix].slice(0, 24).join('');
  const stemLength = Math.max(1, 180 - [...suffix].length);
  return `${characters.slice(0, stemLength).join('')}${suffix}`;
}

export function canStartAttachmentDownload(
  activeIds,
  attachmentId,
  maxActive = MAX_ACTIVE_ATTACHMENT_REQUESTS,
) {
  return !activeIds.has(attachmentId) && activeIds.size < maxActive;
}

export function isCurrentAttachmentRequest({
  requestedEmailId,
  requestGeneration,
  currentEmailId,
  currentGeneration,
}) {
  return requestedEmailId === currentEmailId && requestGeneration === currentGeneration;
}

export function isRetryableAttachmentError(status) {
  if (!Number.isInteger(status)) return true;
  return [408, 425, 429].includes(status) || status >= 500;
}

export function saveAttachmentBlob(
  blob,
  filename,
  {
    documentObject = globalThis.document,
    urlObject = globalThis.URL,
    scheduleCleanup = (cleanup) => setTimeout(cleanup, 1000),
  } = {},
) {
  if (!documentObject?.body || !urlObject?.createObjectURL) {
    throw new Error('Downloads are unavailable in this browser');
  }

  const objectUrl = urlObject.createObjectURL(blob);
  const link = documentObject.createElement('a');
  link.href = objectUrl;
  link.download = safeClientFilename(filename);
  link.style.display = 'none';
  documentObject.body.appendChild(link);
  link.click();
  link.remove();

  const cleanup = () => urlObject.revokeObjectURL(objectUrl);
  if (typeof scheduleCleanup === 'function') scheduleCleanup(cleanup);
  else setTimeout(cleanup, 1000);
}
