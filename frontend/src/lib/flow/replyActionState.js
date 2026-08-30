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
