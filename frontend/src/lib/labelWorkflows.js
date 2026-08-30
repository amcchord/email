const LABEL_ACTIONS = new Set(['add_label', 'remove_label', 'move_to_label']);

export function isLabelAction(action) {
  return LABEL_ACTIONS.has(action);
}

function positiveId(value) {
  const id = Number(value);
  return Number.isInteger(id) && id > 0 ? id : null;
}

export function resolveLabelAccount(emails = [], accounts = []) {
  if (!emails.length) {
    return { state: 'unknown', accountId: null, accountEmail: '', message: 'Select at least one email.' };
  }

  const byEmail = new Map(
    accounts
      .filter(account => positiveId(account?.id) && account?.email)
      .map(account => [String(account.email).trim().toLowerCase(), account]),
  );
  const resolved = emails.map(email => {
    const directId = positiveId(email?.account_id);
    if (directId) {
      const account = accounts.find(candidate => positiveId(candidate?.id) === directId);
      return { id: directId, email: account?.email || email?.account_email || '' };
    }
    const account = byEmail.get(String(email?.account_email || '').trim().toLowerCase());
    return account ? { id: positiveId(account.id), email: account.email } : null;
  });

  if (resolved.some(account => !account?.id)) {
    return {
      state: 'unknown',
      accountId: null,
      accountEmail: '',
      message: 'The account for this selection could not be confirmed. Refresh and try again.',
    };
  }
  const accountIds = new Set(resolved.map(account => account.id));
  if (accountIds.size !== 1) {
    return {
      state: 'mixed',
      accountId: null,
      accountEmail: '',
      message: 'Labels belong to one Gmail account. Select emails from a single account to continue.',
    };
  }
  return {
    state: 'single',
    accountId: resolved[0].id,
    accountEmail: resolved[0].email || '',
    message: '',
  };
}

export function normalizeUserLabels(labels = [], accountId = null) {
  const expectedAccountId = positiveId(accountId);
  const seen = new Set();
  return labels
    .filter(label => {
      const id = positiveId(label?.id);
      const labelAccountId = positiveId(label?.account_id);
      const gmailId = String(label?.gmail_label_id || '').trim();
      const name = String(label?.name || '').trim();
      if (!id || !labelAccountId || label?.label_type !== 'user' || !gmailId || !name) return false;
      if (expectedAccountId && labelAccountId !== expectedAccountId) return false;
      if (seen.has(id)) return false;
      seen.add(id);
      return true;
    })
    .sort((a, b) => String(a.name).localeCompare(String(b.name), undefined, { sensitivity: 'base' }));
}

export function mergeLabelCatalog(current = [], fetched = [], accountId) {
  const id = positiveId(accountId);
  if (!id) return current;
  return [
    ...current.filter(label => positiveId(label?.account_id) !== id),
    ...fetched.filter(label => positiveId(label?.account_id) === id),
  ];
}

export function labelMembership(emails = [], gmailLabelId) {
  if (!emails.length || !gmailLabelId) return 'none';
  if (emails.length === 1 && emails[0]?.conversation_scope) {
    return conversationLabelCoverage(emails[0], gmailLabelId);
  }
  const count = emails.filter(email => (
    Array.isArray(email?.labels) && email.labels.includes(gmailLabelId)
  )).length;
  if (count === 0) return 'none';
  return count === emails.length ? 'all' : 'some';
}

export function conversationLabelCoverage(email, gmailLabelId) {
  if (!email || !gmailLabelId) return 'none';
  const coverage = email.label_coverage;
  let state = null;
  if (coverage && !Array.isArray(coverage) && typeof coverage === 'object') {
    state = coverage[gmailLabelId];
  } else if (Array.isArray(coverage)) {
    const entry = coverage.find(item => (
      item?.gmail_label_id === gmailLabelId || item?.label_id === gmailLabelId
    ));
    state = entry?.coverage || entry?.state;
  }
  if (state === 'all' || state === 'some' || state === 'none') return state;
  return Array.isArray(email.labels) && email.labels.includes(gmailLabelId) ? 'all' : 'none';
}

export function labelActionForMode(mode, membership) {
  if (mode === 'move') return 'move_to_label';
  return membership === 'all' ? 'remove_label' : 'add_label';
}

export function safeLabelColor(value, fallback) {
  const color = String(value || '').trim();
  return /^#[0-9a-f]{3,8}$/i.test(color) ? color : fallback;
}

export function visibleUserLabels(email, labels = [], accounts = [], limit = 2) {
  const account = resolveLabelAccount(email ? [email] : [], accounts);
  if (account.state !== 'single') return { labels: [], overflow: 0 };
  const applied = new Set(Array.isArray(email?.labels) ? email.labels : []);
  const matching = normalizeUserLabels(labels, account.accountId)
    .filter(label => applied.has(label.gmail_label_id))
    .map(label => ({
      ...label,
      coverage: conversationLabelCoverage(email, label.gmail_label_id),
    }));
  const count = Math.max(0, Number(limit) || 0);
  return { labels: matching.slice(0, count), overflow: Math.max(0, matching.length - count) };
}

function accountIdentity(email) {
  const id = positiveId(email?.account_id);
  return id ? `id:${id}` : `email:${String(email?.account_email || '').trim().toLowerCase()}`;
}

export function expandVisibleLabelTargets(selectedIds = [], visibleEmails = []) {
  const expanded = new Set(selectedIds);
  const anchors = visibleEmails.filter(email => expanded.has(email.id));
  const threadKeys = new Set(
    anchors
      .filter(email => email.gmail_thread_id)
      .map(email => `${accountIdentity(email)}|${email.gmail_thread_id}`),
  );
  for (const email of visibleEmails) {
    if (!email.gmail_thread_id) continue;
    if (threadKeys.has(`${accountIdentity(email)}|${email.gmail_thread_id}`)) expanded.add(email.id);
  }
  return [...expanded];
}
