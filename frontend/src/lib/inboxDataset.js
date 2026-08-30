export function createLatestRequestGuard() {
  let latestRequest = 0;

  return {
    begin() {
      latestRequest += 1;
      return latestRequest;
    },

    isCurrent(requestId) {
      return requestId === latestRequest;
    },

    invalidate() {
      latestRequest += 1;
    },
  };
}

export function inboxDatasetKey({
  mailbox = 'INBOX',
  accountId = null,
  search = '',
  smartFilter = null,
  hideIgnored = false,
  pageSize = null,
} = {}) {
  return JSON.stringify([
    mailbox,
    accountId,
    search,
    smartFilter?.type ?? null,
    smartFilter?.value ?? null,
    Boolean(hideIgnored),
    pageSize,
  ]);
}

export function canActOnInboxEmails({
  authoritative = false,
  emailIds = [],
  visibleEmailIds = [],
  selectedEmailId = null,
  selectedDetailId = null,
} = {}) {
  if (!authoritative || emailIds.length === 0) return false;

  const visibleIds = new Set(visibleEmailIds);
  const directOpenId = selectedEmailId !== null && selectedEmailId === selectedDetailId
    ? selectedDetailId
    : null;

  return emailIds.every(emailId => visibleIds.has(emailId) || emailId === directOpenId);
}
