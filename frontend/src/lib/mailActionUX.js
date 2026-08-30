export const REMOVAL_ACTIONS = new Set(['archive', 'trash', 'untrash', 'spam', 'unspam']);

export function actionPastTense(action, count = 1, labelName = '') {
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
    add_label: `${subject} labeled${labelName ? ` ${labelName}` : ''}`,
    remove_label: `${labelName || 'Label'} removed from ${subject.toLowerCase()}`,
    move_to_label: `${subject} moved${labelName ? ` to ${labelName}` : ''}`,
  };
  return labels[action] || `${subject} updated`;
}

export function actionRemovesFromMailbox(action, mailbox, gmailLabelId = null) {
  if (action === 'move_to_label') return mailbox === 'INBOX';
  if (action === 'remove_label') return Boolean(gmailLabelId) && mailbox === gmailLabelId;
  if (action === 'archive') return mailbox === 'INBOX';
  if (action === 'trash') return mailbox !== 'TRASH';
  if (action === 'untrash') return mailbox === 'TRASH';
  if (action === 'spam') return mailbox !== 'SPAM';
  if (action === 'unspam') return mailbox === 'SPAM';
  return false;
}

export function applyEmailAction(email, action, { gmailLabelId = null } = {}) {
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
    case 'add_label':
      if (!gmailLabelId) return email;
      labels.add(gmailLabelId);
      break;
    case 'remove_label':
      if (!gmailLabelId) return email;
      labels.delete(gmailLabelId);
      break;
    case 'move_to_label':
      if (!gmailLabelId) return email;
      labels.add(gmailLabelId);
      labels.delete('INBOX');
      break;
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

export function optimisticInboxAction({ emails, selectedId, emailIds, action, mailbox, gmailLabelId = null }) {
  const targetIds = new Set(emailIds);
  const selectedIndex = emails.findIndex(email => email.id === selectedId);
  const remove = actionRemovesFromMailbox(action, mailbox, gmailLabelId);
  const nextEmails = remove
    ? emails.filter(email => !targetIds.has(email.id))
    : emails.map(email => targetIds.has(email.id)
      ? applyEmailAction(email, action, { gmailLabelId })
      : email);

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

function sameLabels(first, second) {
  const a = new Set(Array.isArray(first) ? first : []);
  const b = new Set(Array.isArray(second) ? second : []);
  return a.size === b.size && [...a].every(label => b.has(label));
}

export function rollbackEmailAction(current, original, action, { gmailLabelId = null } = {}) {
  const projected = applyEmailAction(original, action, { gmailLabelId });
  if (sameLabels(current.labels, projected.labels)) return original;

  const beforeLabels = new Set(Array.isArray(original.labels) ? original.labels : []);
  const afterLabels = new Set(Array.isArray(projected.labels) ? projected.labels : []);
  const desiredLabels = new Set(Array.isArray(current.labels) ? current.labels : []);
  const changedLabels = new Set([...beforeLabels, ...afterLabels]);
  for (const label of changedLabels) {
    if (beforeLabels.has(label) === afterLabels.has(label)) continue;
    if (beforeLabels.has(label)) desiredLabels.add(label);
    else desiredLabels.delete(label);
  }

  const labels = [
    ...(original.labels || []).filter(label => desiredLabels.has(label)),
    ...(current.labels || []).filter(
      label => desiredLabels.has(label) && !(original.labels || []).includes(label),
    ),
  ];
  for (const label of desiredLabels) {
    if (!labels.includes(label)) labels.push(label);
  }
  return {
    ...current,
    labels,
    is_read: !desiredLabels.has('UNREAD'),
    is_starred: desiredLabels.has('STARRED'),
    is_trash: desiredLabels.has('TRASH'),
    is_spam: desiredLabels.has('SPAM'),
  };
}

export function restoreInboxAction(
  currentEmails,
  snapshot,
  action = null,
  reinsertMissing = true,
  actionOptions = {},
) {
  const originals = new Map(snapshot.items.map(item => [item.email.id, item]));
  const restored = currentEmails.map(email => {
    const original = originals.get(email.id)?.email;
    if (!original) return email;
    return action ? rollbackEmailAction(email, original, action, actionOptions) : original;
  });

  for (const item of [...snapshot.items].sort((a, b) => a.index - b.index)) {
    if (restored.some(email => email.id === item.email.id)) continue;
    if (!reinsertMissing) continue;
    restored.splice(Math.min(item.index, restored.length), 0, item.email);
  }
  return restored;
}

export function createMailActionSubmissionQueue() {
  const tails = new Map();

  function enqueue(emailIds, submit) {
    const ids = [...new Set(emailIds)];
    const blockers = [...new Set(ids.map(id => tails.get(id)).filter(Boolean))];
    let tailGate = Promise.resolve();
    let releaseTail = null;
    const queueControl = {
      hold() {
        if (releaseTail) return releaseTail;
        let release;
        tailGate = new Promise(resolve => { release = resolve; });
        let released = false;
        releaseTail = () => {
          if (released) return;
          released = true;
          release();
        };
        return releaseTail;
      },
    };
    const result = Promise.allSettled(blockers)
      .then(() => submit(queueControl));
    let tail;
    tail = result
      .catch(() => undefined)
      .then(() => tailGate)
      .finally(() => {
        for (const id of ids) {
          if (tails.get(id) === tail) tails.delete(id);
        }
      });
    for (const id of ids) tails.set(id, tail);
    return result;
  }

  return { enqueue };
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

export function isMailActionNetworkError(error) {
  return error instanceof TypeError || /network|failed to fetch/i.test(error?.message || '');
}

export function failedMailActionRequestIds(operations = []) {
  return new Set(
    operations
      .filter(operation => operation.items?.some(item => item.state === 'failed'))
      .map(operation => operation.request_id),
  );
}

export function hasNewFailedMailActions(operations, observedRequestIds = new Set()) {
  return [...failedMailActionRequestIds(operations)]
    .some(requestId => !observedRequestIds.has(requestId));
}
