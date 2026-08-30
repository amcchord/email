function timeValue(value) {
  const parsed = Date.parse(value || '');
  return Number.isFinite(parsed) ? parsed : 0;
}

function snapshotSummary(snapshot = {}) {
  const body = String(snapshot.body_text || '')
    .replace(/\s+/gu, ' ')
    .trim()
    .slice(0, 180);
  return {
    to: Array.isArray(snapshot.to) ? snapshot.to.slice(0, 3) : [],
    subject: String(snapshot.subject || ''),
    body_preview: body,
    thread_id: snapshot.thread_id || null,
    source_email_id: Number(snapshot.source_email_id) || null,
    account_id: Number(snapshot.account_id) || null,
    attachment_count: Array.isArray(snapshot.attachments) ? snapshot.attachments.length : 0,
  };
}

function rowFromLocal(local) {
  return {
    client_draft_id: local.client_draft_id,
    revision: Number(local.revision || 0),
    synced_revision: Number(local.synced_revision || 0),
    state: local.status || 'local-only',
    updated_at: local.updated_at,
    created_at: local.created_at,
    ...snapshotSummary(local.snapshot),
    local: true,
    server: false,
    server_revision: 0,
    conflict: local.status === 'conflict',
    sending: Boolean(local.send_tombstone) || local.status === 'reconciling' && local.error?.phase === 'send-reconcile',
  };
}

function rowFromServer(server) {
  return {
    ...server,
    revision: Number(server.revision || 0),
    synced_revision: Number(server.synced_revision || 0),
    to: Array.isArray(server.to) ? server.to.slice(0, 3) : [],
    local: false,
    server: true,
    server_revision: Number(server.revision || 0),
    conflict: false,
    sending: server.state === 'sending',
  };
}

export function mergeRecentDrafts(localRecords = [], serverRecords = [], accounts = []) {
  const accountMap = new Map(accounts.map(account => [Number(account.id), account]));
  const merged = new Map();
  for (const server of serverRecords || []) {
    if (!server?.client_draft_id || server.state === 'discarded') continue;
    merged.set(server.client_draft_id, rowFromServer(server));
  }
  for (const local of localRecords || []) {
    if (!local?.client_draft_id || local.status === 'discarded') continue;
    const existing = merged.get(local.client_draft_id);
    const localRow = rowFromLocal(local);
    if (!existing) {
      merged.set(local.client_draft_id, localRow);
      continue;
    }
    const preferLocal = localRow.revision >= existing.revision;
    const visible = preferLocal ? localRow : existing;
    merged.set(local.client_draft_id, {
      ...visible,
      local: true,
      server: true,
      server_revision: existing.revision,
      conflict: localRow.conflict || existing.revision > localRow.revision,
      changed_elsewhere: existing.revision > localRow.revision,
      sending: localRow.sending || existing.sending,
      updated_at: timeValue(existing.updated_at) > timeValue(localRow.updated_at)
        ? existing.updated_at
        : localRow.updated_at,
    });
  }
  return [...merged.values()]
    .map(row => ({ ...row, account: accountMap.get(Number(row.account_id)) || null }))
    .sort((left, right) => {
      const conflict = Number(Boolean(right.conflict)) - Number(Boolean(left.conflict));
      return conflict || timeValue(right.updated_at) - timeValue(left.updated_at)
        || String(right.client_draft_id).localeCompare(String(left.client_draft_id));
    });
}

export function recentDraftTitle(row = {}) {
  return String(row.subject || '').trim() || (row.source_email_id ? 'Reply draft' : '(No subject)');
}

export function recentDraftRecipients(row = {}) {
  return Array.isArray(row.to) && row.to.length ? row.to.join(', ') : 'No recipients';
}

export function recentDraftComposeData(row = {}) {
  const clientDraftId = String(row.client_draft_id || '');
  const accountId = Number(row.account_id);
  const sourceEmailId = Number(row.source_email_id);
  const isReply = Number.isSafeInteger(accountId) && accountId > 0
    && Number.isSafeInteger(sourceEmailId) && sourceEmailId > 0;
  return {
    client_draft_id: clientDraftId,
    draft_key: `client:${clientDraftId}`,
    intent_key: isReply
      ? `reply:${accountId}:${sourceEmailId}`
      : `route:${clientDraftId}`,
    known_server_revision: Number(row.server_revision || 0),
  };
}
