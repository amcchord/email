function positiveInteger(value) {
  const number = Number(value);
  return Number.isInteger(number) && number > 0 ? number : null;
}

export function isConversationSummary(item) {
  return Boolean(
    item
      && typeof item.conversation_key === 'string'
      && item.conversation_key.trim()
      && positiveInteger(item.account_id)
      && positiveInteger(item.anchor_email_id),
  );
}

export function normalizeConversationSummary(item) {
  if (!isConversationSummary(item)) {
    throw new Error('Conversation results require an owned account and anchor message');
  }

  const labels = Array.isArray(item.labels) ? [...new Set(item.labels.filter(Boolean))] : [];
  const unreadCount = Math.max(0, Number(item.unread_count) || 0);
  const memberCount = Math.max(1, Number(item.member_count) || 1);
  const starState = ['none', 'some', 'all'].includes(item.star_state)
    ? item.star_state
    : (labels.includes('STARRED') ? 'all' : 'none');

  return {
    ...item,
    id: Number(item.anchor_email_id),
    anchor_email_id: Number(item.anchor_email_id),
    account_id: Number(item.account_id),
    labels,
    unread_count: unreadCount,
    member_count: memberCount,
    matched_count: Math.max(1, Number(item.matched_count) || 1),
    star_state: starState,
    is_read: unreadCount === 0,
    is_starred: starState !== 'none',
    // Placement flags describe the newest matching anchor. Aggregate `labels`
    // is intentionally a union, so a Sent or Trash sibling must not make an
    // Inbox/search anchor look sent or protected.
    is_draft: typeof item.is_draft === 'boolean' ? item.is_draft : labels.includes('DRAFT'),
    is_sent: typeof item.is_sent === 'boolean' ? item.is_sent : labels.includes('SENT'),
    is_trash: typeof item.is_trash === 'boolean' ? item.is_trash : labels.includes('TRASH'),
    is_spam: typeof item.is_spam === 'boolean' ? item.is_spam : labels.includes('SPAM'),
    conversation_scope: true,
  };
}

export function normalizeConversationList(payload) {
  const conversations = Array.isArray(payload?.conversations) ? payload.conversations : [];
  return {
    emails: conversations.map(normalizeConversationSummary),
    total: Math.max(0, Number(payload?.total) || 0),
    page: Math.max(1, Number(payload?.page) || 1),
    page_size: Math.max(1, Number(payload?.page_size) || conversations.length || 1),
    total_pages: Math.max(0, Number(payload?.total_pages) || 0),
  };
}

export function actionScopeForEmails(emailIds, visibleEmails = []) {
  const ids = new Set((emailIds || []).map(Number));
  if (!ids.size) return null;
  const selected = visibleEmails.filter(email => ids.has(Number(email.id)));
  return selected.length === ids.size && selected.every(isConversationSummary)
    ? 'conversations'
    : null;
}

export function nextConversationFocus(emails, focusedId, removedIds) {
  const removed = new Set((removedIds || []).map(Number));
  const index = emails.findIndex(email => Number(email.id) === Number(focusedId));
  if (index < 0 || !removed.has(Number(focusedId))) return focusedId ?? null;
  const remaining = emails.filter(email => !removed.has(Number(email.id)));
  if (!remaining.length) return null;
  return remaining[Math.min(index, remaining.length - 1)]?.id ?? null;
}

export function defaultThreadMessageId(thread) {
  const messages = Array.isArray(thread?.emails) ? thread.emails : [];
  if (!messages.length) return null;
  return (messages.find(message => !message.is_read) || messages[messages.length - 1]).id;
}
