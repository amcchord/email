export function safeClientFilename(filename) {
  const leafName = String(filename || 'attachment').replaceAll('\\', '/').split('/').pop();
  const cleaned = [...leafName]
    .filter((character) => !/\p{C}/u.test(character))
    .join('')
    .trim();
  return cleaned && cleaned !== '.' && cleaned !== '..' ? cleaned : 'attachment';
}

export function canStartAttachmentDownload(activeIds, attachmentId) {
  return !activeIds.has(attachmentId);
}

export function isCurrentAttachmentRequest({
  requestedEmailId,
  requestGeneration,
  currentEmailId,
  currentGeneration,
}) {
  return requestedEmailId === currentEmailId && requestGeneration === currentGeneration;
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
