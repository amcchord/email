export function addPendingReplyId(pendingIds, emailId) {
  const ids = Array.isArray(pendingIds) ? pendingIds : [];
  if (emailId == null || ids.includes(emailId)) return ids;
  return [...ids, emailId];
}

export function removePendingReplyId(pendingIds, emailId) {
  const ids = Array.isArray(pendingIds) ? pendingIds : [];
  return ids.filter(id => id !== emailId);
}

export function capturedReplyStillActive(mutatedEmailId, activeEmailId) {
  return mutatedEmailId != null && mutatedEmailId === activeEmailId;
}

/**
 * Thread responses follow the user's display order. Centralize selection of
 * the newest message so reply headers never accidentally target the oldest
 * message when threads are displayed newest-first.
 */
export function newestThreadMessage(messages, order = 'newest_first') {
  const list = Array.isArray(messages) ? messages : [];
  if (list.length === 0) return null;
  return order === 'newest_first' ? list[0] : list[list.length - 1];
}

export function replyDraftAccountKey(email) {
  const accountId = Number(email?.account_id);
  if (Number.isSafeInteger(accountId) && accountId > 0) return `id:${accountId}`;
  const accountEmail = typeof email?.account_email === 'string'
    ? email.account_email.trim().toLowerCase()
    : '';
  return accountEmail ? `email:${accountEmail}` : '';
}

export function flowReplyDraftKey(email) {
  if (!email) return null;
  const accountKey = email.reply_draft_account_key || replyDraftAccountKey(email);
  return [accountKey, email.gmail_thread_id || '', email.id || ''].join(':');
}

/**
 * Keep a delayed thread response scoped to the exact Flow reply that opened
 * it. Generation prevents same-id reopen races while identity/source checks
 * prevent cross-message reply headers from being mixed.
 */
export function isCurrentFlowThreadRequest({
  requestedGeneration,
  currentGeneration,
  replyViewOpen,
  requestedEmailId = null,
  activeEmailId = null,
  requestedThreadId = null,
  activeThreadId = null,
  requestedSource = null,
  activeSource = null,
}) {
  if (requestedGeneration !== currentGeneration || !replyViewOpen) return false;
  if (requestedEmailId !== null && requestedEmailId !== activeEmailId) return false;
  if (requestedThreadId !== null && requestedThreadId !== activeThreadId) return false;
  if (requestedSource !== null && requestedSource !== activeSource) return false;
  return true;
}

/**
 * Remove the captured message from needs-reply state without changing a newer
 * selection. This is intentionally pure so delayed mutation completion can be
 * proven independently of the Flow component.
 */
export function reconcileNeedsReplyRemoval({
  emails,
  total,
  removedId,
  activeEmailId,
  activeIndex = 0,
}) {
  const list = Array.isArray(emails) ? emails : [];
  const removedIndex = list.findIndex(email => email.id === removedId);
  if (removedIndex < 0) {
    return {
      emails: list,
      total,
      activeEmailId,
      activeIndex,
      removed: false,
    };
  }

  const remaining = list.filter(email => email.id !== removedId);
  const nextTotal = Math.max(0, Number(total || 0) - 1);
  if (remaining.length === 0) {
    const externalReplyStillActive = activeEmailId != null && activeEmailId !== removedId;
    return {
      emails: remaining,
      total: nextTotal,
      activeEmailId: externalReplyStillActive ? activeEmailId : null,
      activeIndex: externalReplyStillActive ? activeIndex : -1,
      removed: true,
    };
  }

  if (activeEmailId != null && activeEmailId !== removedId) {
    const preservedIndex = remaining.findIndex(email => email.id === activeEmailId);
    if (preservedIndex >= 0) {
      return {
        emails: remaining,
        total: nextTotal,
        activeEmailId,
        activeIndex: preservedIndex,
        removed: true,
      };
    }
  }

  const nextIndex = Math.min(Math.max(removedIndex, 0), remaining.length - 1);
  return {
    emails: remaining,
    total: nextTotal,
    activeEmailId: remaining[nextIndex].id,
    activeIndex: nextIndex,
    removed: true,
  };
}
