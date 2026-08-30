export const REMOVAL_ACTIONS = new Set(['archive', 'trash', 'untrash', 'spam', 'unspam']);

export function actionPastTense(action, count = 1) {
  const subject = count === 1 ? 'Email' : `${count} emails`;
  const labels = {
    archive: `${subject} archived`,
    trash: `${subject} moved to trash`,
    untrash: `${subject} restored from trash`,
    spam: `${subject} marked as spam`,
    unspam: `${subject} marked as not spam`,
    mark_read: `${subject} marked as read`,
    mark_unread: `${subject} marked as unread`,
    star: `${subject} starred`,
    unstar: `${subject} unstarred`,
  };
  return labels[action] || `${subject} updated`;
}

export function actionRemovesFromMailbox(action, mailbox) {
  if (action === 'archive') return mailbox === 'INBOX';
  if (action === 'trash') return mailbox !== 'TRASH';
  if (action === 'untrash') return mailbox === 'TRASH';
  if (action === 'spam') return mailbox !== 'SPAM';
  if (action === 'unspam') return mailbox === 'SPAM';
  return false;
}

export function applyEmailAction(email, action) {
  const labels = new Set(Array.isArray(email.labels) ? email.labels : []);

  switch (action) {
    case 'mark_read': labels.delete('UNREAD'); break;
    case 'mark_unread': labels.add('UNREAD'); break;
    case 'star': labels.add('STARRED'); break;
    case 'unstar': labels.delete('STARRED'); break;
    case 'trash': labels.add('TRASH'); break;
    case 'untrash': labels.delete('TRASH'); break;
    case 'spam':
      labels.add('SPAM');
      labels.delete('INBOX');
      break;
    case 'unspam':
      labels.delete('SPAM');
      labels.add('INBOX');
      break;
    case 'archive': labels.delete('INBOX'); break;
    default: return email;
  }

  return {
    ...email,
    labels: [...labels],
    is_read: !labels.has('UNREAD'),
    is_starred: labels.has('STARRED'),
    is_trash: labels.has('TRASH'),
    is_spam: labels.has('SPAM'),
  };
}

export function optimisticInboxAction({ emails, selectedId, emailIds, action, mailbox }) {
  const targetIds = new Set(emailIds);
  const selectedIndex = emails.findIndex(email => email.id === selectedId);
  const remove = actionRemovesFromMailbox(action, mailbox);
  const nextEmails = remove
    ? emails.filter(email => !targetIds.has(email.id))
    : emails.map(email => targetIds.has(email.id) ? applyEmailAction(email, action) : email);

  let nextSelectedId = selectedId;
  if (remove && selectedId !== null && targetIds.has(selectedId)) {
    if (nextEmails.length === 0) {
      nextSelectedId = null;
    } else {
      const nextIndex = Math.min(Math.max(selectedIndex, 0), nextEmails.length - 1);
      nextSelectedId = nextEmails[nextIndex].id;
    }
  }

  return { emails: nextEmails, selectedId: nextSelectedId, removed: remove };
}

export function captureInboxAction(emails, selectedId, emailIds) {
  const targetIds = new Set(emailIds);
  return {
    selectedId,
    items: emails
      .map((email, index) => ({ email, index }))
      .filter(item => targetIds.has(item.email.id)),
  };
}

export function restoreInboxAction(currentEmails, snapshot) {
  const originals = new Map(snapshot.items.map(item => [item.email.id, item]));
  const restored = currentEmails.map(email => originals.get(email.id)?.email || email);

  for (const item of [...snapshot.items].sort((a, b) => a.index - b.index)) {
    if (restored.some(email => email.id === item.email.id)) continue;
    restored.splice(Math.min(item.index, restored.length), 0, item.email);
  }
  return restored;
}

export function idempotencyKey(randomUUID = globalThis.crypto?.randomUUID?.bind(globalThis.crypto)) {
  if (!randomUUID) throw new Error('Secure random UUID support is required');
  return randomUUID();
}

export function remainingUndoMs(undoUntil, now = Date.now()) {
  const deadline = Date.parse(undoUntil);
  if (!Number.isFinite(deadline)) return 0;
  return Math.max(0, deadline - now);
}

export function canUndoAction(operation, now = Date.now()) {
  return operation?.state === 'staged' && remainingUndoMs(operation.undo_until, now) > 0;
}
