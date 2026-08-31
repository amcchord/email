export const INBOX_SECTIONS = Object.freeze(['focused', 'other']);

const REASON_LABELS = Object.freeze({
  high_priority: 'High priority',
  needs_reply: 'Needs reply',
  trusted_contact: 'Trusted contact',
  delegated_scheduling: 'Delegated scheduling',
  subscription: 'Subscription',
  low_priority: 'Low priority',
  unclassified: 'New mail',
  direct_or_fyi: 'Direct or FYI',
});

export function placementReasonLabel(reason) {
  return REASON_LABELS[reason] || '';
}

export function isSplitInboxActive(snapshot = {}) {
  return Boolean(
    snapshot.hideIgnored
      && snapshot.mailbox === 'INBOX'
      && !snapshot.search
      && !snapshot.smartFilter,
  );
}

export function normalizeInboxSectionResult(result, placement) {
  if (!INBOX_SECTIONS.includes(placement)) {
    throw new Error('Inbox section must be Focused or Other');
  }
  const emails = (result?.emails || []).map(email => {
    if (email?.inbox_placement !== placement) {
      throw new Error('Split Inbox placement did not match the requested section');
    }
    return email;
  });
  return {
    ...result,
    emails,
    total: Math.max(0, Number(result?.total) || 0),
  };
}

export function combineInboxSections(focused, other) {
  const sectionTotals = {
    focused: Math.max(0, Number(focused?.total) || 0),
    other: Math.max(0, Number(other?.total) || 0),
  };
  const page = Math.max(1, Number(focused?.page || other?.page) || 1);
  const hasMore = [focused, other].some(result => {
    const pageSize = Math.max(1, Number(result?.page_size) || 1);
    return (page * pageSize) < Math.max(0, Number(result?.total) || 0);
  });
  const emails = [...(focused?.emails || []), ...(other?.emails || [])];
  const identities = new Set();
  for (const email of emails) {
    const identity = String(email?.conversation_key || `message:${email?.id ?? ''}`);
    if (identities.has(identity)) {
      throw new Error('Split Inbox returned the same conversation in both sections');
    }
    identities.add(identity);
  }
  return {
    emails,
    total: sectionTotals.focused + sectionTotals.other,
    page,
    page_size: Math.max(1, Number(focused?.page_size || other?.page_size) || 1),
    sectionTotals,
    hasMore,
  };
}

export function mergeInboxSectionPages(existing = [], incoming = []) {
  const byPlacement = placement => {
    const seen = new Set();
    return [...existing, ...incoming].filter(email => {
      if (email?.inbox_placement !== placement || seen.has(email.id)) return false;
      seen.add(email.id);
      return true;
    });
  };
  return [...byPlacement('focused'), ...byPlacement('other')];
}

export function nextInboxSectionFocus(emails = [], focusedId = null, direction = 1) {
  const populated = INBOX_SECTIONS.filter(placement =>
    emails.some(email => email?.inbox_placement === placement));
  if (!populated.length) return null;

  const current = emails.find(email => Number(email.id) === Number(focusedId));
  const currentPlacement = current?.inbox_placement;
  let targetPlacement;
  if (!populated.includes(currentPlacement)) {
    targetPlacement = direction >= 0 ? populated[0] : populated[populated.length - 1];
  } else {
    const index = populated.indexOf(currentPlacement);
    targetPlacement = populated[(index + (direction >= 0 ? 1 : -1) + populated.length) % populated.length];
  }
  return emails.find(email => email?.inbox_placement === targetPlacement)?.id ?? null;
}

export function adjustInboxSectionTotals(totals, emails = [], delta = -1) {
  if (!totals) return null;
  const next = { focused: Number(totals.focused) || 0, other: Number(totals.other) || 0 };
  for (const email of emails) {
    const placement = email?.inbox_placement;
    if (!INBOX_SECTIONS.includes(placement)) continue;
    next[placement] = Math.max(0, next[placement] + delta);
  }
  return next;
}
