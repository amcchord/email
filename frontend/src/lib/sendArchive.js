export const SEND_ARCHIVE_UNAVAILABLE_MESSAGE = 'Open a verified reply before using Send & archive.';

export function exactSourceEmailId(value) {
  return Number.isSafeInteger(value) && value > 0 ? value : null;
}

export function canArchiveAfterSend(payload) {
  return exactSourceEmailId(payload?.source_email_id) !== null;
}

/**
 * Add the durable post-send archive intent without ever inventing a source.
 * False/omitted intent is intentionally absent from the wire payload so an
 * ordinary Send remains byte-for-byte compatible with the existing client.
 */
export function withArchiveAfterSend(payload, archiveAfterSend = false) {
  const next = { ...(payload || {}) };
  delete next.archive_source_after_send;
  if (!archiveAfterSend) return next;
  if (!canArchiveAfterSend(next)) {
    const error = new Error(SEND_ARCHIVE_UNAVAILABLE_MESSAGE);
    error.code = 'send_archive_source_unavailable';
    throw error;
  }
  next.archive_source_after_send = true;
  return next;
}

export function sendArchiveAcceptedMessage({ scheduled = false } = {}) {
  return scheduled
    ? 'Scheduled; this conversation will archive only after delivery is confirmed.'
    : 'Sending; this conversation will archive only after delivery is confirmed.';
}
