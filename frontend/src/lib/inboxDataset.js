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

/**
 * Preserve a cross-screen "open this message" intent until the first
 * authoritative Inbox dataset is ready. Inbox clears selection whenever its
 * result shape changes, so a cold lazy mount otherwise erases an id supplied
 * by Flow, Todos, or Insights before the detail request can begin.
 */
export function createInitialDirectOpenGuard() {
  let pendingEmailId = null;
  let initialDatasetCommitted = false;

  return {
    capture(emailId) {
      if (initialDatasetCommitted || pendingEmailId !== null) return pendingEmailId;
      const candidate = Number(emailId);
      if (Number.isSafeInteger(candidate) && candidate > 0) pendingEmailId = candidate;
      return pendingEmailId;
    },

    commit(authoritative) {
      if (!authoritative) return null;
      initialDatasetCommitted = true;
      const emailId = pendingEmailId;
      pendingEmailId = null;
      return emailId;
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

export function normalizeInboxDatasetSnapshot({
  mailbox = 'INBOX',
  accountId = null,
  search = '',
  smartFilter = null,
  hideIgnored = false,
  pageSize = null,
  page = 1,
} = {}) {
  const normalizedSearch = String(search || '').trim();
  const searching = normalizedSearch.length > 0;
  const snapshot = {
    mailbox: searching ? 'ALL' : mailbox,
    accountId,
    search: normalizedSearch,
    smartFilter: searching ? null : smartFilter,
    hideIgnored: searching ? false : Boolean(hideIgnored),
    pageSize,
    page,
  };
  snapshot.key = inboxDatasetKey(snapshot);
  return snapshot;
}

export function createDatasetActionReconciler({ isCurrent, refresh }) {
  let requestedVersion = 0;
  let completedVersion = 0;
  let targetKey = null;
  let running = null;
  let disposed = false;

  async function drain() {
    while (!disposed && completedVersion < requestedVersion) {
      const version = requestedVersion;
      const key = targetKey;
      if (isCurrent(key)) await refresh(key);
      completedVersion = version;
    }
  }

  return {
    request(key) {
      if (disposed || !isCurrent(key)) return Promise.resolve(false);
      requestedVersion += 1;
      targetKey = key;
      if (!running) {
        running = Promise.resolve()
          .then(drain)
          .finally(() => { running = null; });
      }
      return running;
    },

    dispose() {
      disposed = true;
    },
  };
}

export function selectedBooleanState(items, selectedIds, field) {
  const ids = selectedIds instanceof Set ? selectedIds : new Set(selectedIds || []);
  if (ids.size === 0) return null;
  const selected = items.filter(item => ids.has(item.id));
  if (selected.length !== ids.size) return null;
  const state = Boolean(selected[0]?.[field]);
  return selected.every(item => Boolean(item[field]) === state) ? state : null;
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
