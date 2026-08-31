#!/usr/bin/env node

// Deterministic, local-only API for manual browser QA. It never reads Gmail,
// production configuration, credentials, or mailbox data. Run this server on
// port 8000, then run the frontend Vite server and open `/?page=inbox`.

import { createServer } from 'node:http';
import { randomUUID } from 'node:crypto';

const port = Number.parseInt(process.env.QA_API_PORT || '8000', 10);
const now = new Date('2026-08-30T14:00:00Z');
let clockMs = now.getTime();
let lostActionResponses = Number.parseInt(process.env.QA_LOST_ACTION_RESPONSES || '0', 10);
let lostLookupResponses = Number.parseInt(process.env.QA_LOST_LOOKUP_RESPONSES || '0', 10);

const generatedEmails = [
  ['Quinn Rivera', 'Design review notes', 'The updated navigation hierarchy is ready for review.'],
  ['Sam Chen', 'Monday launch checklist', 'Three items remain before the generated QA launch.'],
  ['Jordan Lee', 'Dinner next week?', 'Would Tuesday evening work for everyone?'],
  ['Morgan Patel', 'Quarterly planning packet', 'I attached the generated planning outline.'],
  ['Casey Kim', 'Your test receipt', 'This generated receipt confirms a $0.00 QA order.'],
  ['Taylor Brooks', 'Accessibility follow-up', 'Keyboard and narrow-screen checks look promising.'],
].map(([fromName, subject, snippet], index) => ({
  id: index + 101,
  account_id: 1,
  account_email: 'qa.generated@example.test',
  gmail_message_id: `generated-message-${index + 1}`,
  gmail_thread_id: `generated-thread-${index + 1}`,
  message_id_header: `<generated-${index + 1}@example.test>`,
  from_name: fromName,
  from_address: `${fromName.toLowerCase().replaceAll(' ', '.')}@example.test`,
  reply_to: `${fromName.toLowerCase().replaceAll(' ', '.')}@example.test`,
  to_addresses: [{ name: 'QA User', address: 'qa.generated@example.test' }],
  cc_addresses: [],
  subject,
  snippet,
  body_text: `${snippet}\n\nThis message was generated locally for browser testing.`,
  body_html: `<p>${snippet}</p><p>This message was generated locally for browser testing.</p>`,
  date: new Date(now.getTime() - index * 38 * 60_000).toISOString(),
  labels: ['INBOX', ...(index < 3 ? ['UNREAD'] : []), ...(index === 3 ? ['STARRED'] : [])],
  is_read: index >= 3,
  is_starred: index === 3,
  is_trash: false,
  is_spam: false,
  attachments: [],
  ai_action_items: [],
  is_subscription: false,
}));

generatedEmails.push({
  ...structuredClone(generatedEmails[0]),
  id: 107,
  gmail_message_id: 'generated-message-7',
  message_id_header: '<generated-7@example.test>',
  from_name: 'Jamie Ortiz',
  from_address: 'jamie.ortiz@example.test',
  reply_to: 'jamie.ortiz@example.test',
  subject: 'Re: Design review notes',
  snippet: 'The generated sibling message belongs to the same conversation.',
  body_text: 'The generated sibling message belongs to the same conversation.\n\nThis message was generated locally for browser testing.',
  body_html: '<p>The generated sibling message belongs to the same conversation.</p><p>This message was generated locally for browser testing.</p>',
  date: new Date(now.getTime() - 12 * 60_000).toISOString(),
  labels: ['INBOX', 'UNREAD'],
  is_read: false,
  is_starred: false,
});

generatedEmails.push({
  ...structuredClone(generatedEmails[1]),
  id: 108,
  gmail_message_id: 'generated-message-8',
  gmail_thread_id: 'generated-thread-8',
  message_id_header: '<generated-8@example.test>',
  subject: 'Generated sent-only reminder',
  snippet: 'This generated message starts outside Inbox.',
  body_text: 'This generated message starts outside Inbox.\n\nThis message was generated locally for browser testing.',
  body_html: '<p>This generated message starts outside Inbox.</p><p>This message was generated locally for browser testing.</p>',
  labels: ['SENT'],
  is_read: true,
  is_sent: true,
});

generatedEmails.push({
  ...structuredClone(generatedEmails[2]),
  id: 109,
  account_id: 2,
  account_email: 'second.generated@example.test',
  gmail_message_id: 'generated-message-9',
  gmail_thread_id: 'generated-thread-9',
  message_id_header: '<generated-9@example.test>',
  subject: 'Second account boundary check',
  snippet: 'This generated message proves that Gmail labels remain account-scoped.',
  body_text: 'This generated message proves that Gmail labels remain account-scoped.\n\nThis message was generated locally for browser testing.',
  body_html: '<p>This generated message proves that Gmail labels remain account-scoped.</p><p>This message was generated locally for browser testing.</p>',
  labels: ['INBOX', 'UNREAD'],
  is_read: false,
});

const generatedLabels = [
  { id: 11, account_id: 1, gmail_label_id: 'Label_Projects', name: 'Projects', label_type: 'user', color_bg: '#dbeafe', color_text: '#1e40af', messages_total: 0, messages_unread: 0 },
  { id: 12, account_id: 1, gmail_label_id: 'Label_Receipts', name: 'Receipts', label_type: 'user', color_bg: '#dcfce7', color_text: '#166534', messages_total: 0, messages_unread: 0 },
  { id: 13, account_id: 1, gmail_label_id: 'INBOX', name: 'Inbox', label_type: 'system', color_bg: null, color_text: null, messages_total: 0, messages_unread: 0 },
  { id: 21, account_id: 2, gmail_label_id: 'Label_Second', name: 'Second account', label_type: 'user', color_bg: '#f3e8ff', color_text: '#6b21a8', messages_total: 0, messages_unread: 0 },
];

const emails = new Map(generatedEmails.map(email => [email.id, email]));
const snapshots = new Map();
const operations = new Map();
const operationPayloads = new Map();
const snoozes = new Map();
const snoozesByIdempotency = new Map();
const audit = {
  fixture_domains: ['example.test'],
  provider_calls: 0,
  label_actions: [],
  snooze_creates: [],
  snooze_replays: [],
  snooze_reschedules: [],
  snooze_cancels: [],
  snooze_returns: [],
  clock_changes: [],
  rejected_mutations: [],
  unknown_routes: [],
};
const seededFailure = {
  request_id: '00000000-0000-4000-8000-000000000099',
  idempotency_key: '00000000-0000-4000-8000-000000000098',
  action: 'star',
  state: 'failed',
  accepted_count: 1,
  undo_until: null,
  created_at: new Date(now.getTime() - 60_000).toISOString(),
  items: [{
    id: 99,
    email_id: 106,
    account_id: 1,
    gmail_message_id: 'generated-message-6',
    sequence: 1,
    action: 'star',
    state: 'failed',
    attempt_count: 3,
    next_attempt_at: null,
    error_code: 'generated_transient_failure',
    error_message: 'Generated Gmail timeout',
    applied_at: null,
    failed_at: new Date(now.getTime() - 30_000).toISOString(),
    cancelled_at: null,
  }],
};
operations.set(seededFailure.request_id, seededFailure);

function writeJson(response, payload, status = 200) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(body),
    'Cache-Control': 'no-store',
  });
  response.end(body);
}

async function readJson(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  return chunks.length ? JSON.parse(Buffer.concat(chunks).toString('utf8')) : {};
}

function generatedClock() {
  return new Date(clockMs);
}

function isUuid(value) {
  return typeof value === 'string'
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

function isActiveSnooze(snooze) {
  return ['pending_archive', 'scheduled', 'pending_return'].includes(snooze.state);
}

function conversationEmails(value) {
  return [...emails.values()].filter(email => (
    email.account_id === value.account_id
    && email.gmail_thread_id === value.gmail_thread_id
  ));
}

function conversationKey(value) {
  const threadId = String(value.gmail_thread_id || '').trim();
  return threadId
    ? `${value.account_id}:thread:${threadId}`
    : `${value.account_id}:message:${value.id}`;
}

function conversationSummary(matches) {
  const sortedMatches = [...matches].sort((first, second) => (
    Date.parse(second.date) - Date.parse(first.date) || second.id - first.id
  ));
  const anchor = sortedMatches[0];
  const members = conversationEmails(anchor);
  const labelCounts = new Map();
  for (const member of members) {
    for (const label of member.labels || []) {
      labelCounts.set(label, (labelCounts.get(label) || 0) + 1);
    }
  }
  const labelCoverage = Object.fromEntries(
    [...labelCounts].map(([label, count]) => [label, count === members.length ? 'all' : 'some']),
  );
  const allLabels = [...labelCounts].filter(([, count]) => count === members.length).map(([label]) => label);
  const starredCount = members.filter(member => member.is_starred).length;
  const unreadCount = members.filter(member => !member.is_read).length;
  const otherPlacement = ['generated-thread-5', 'generated-thread-6', 'generated-thread-9'].includes(
    String(anchor.gmail_thread_id || '').trim(),
  );
  const placementReason = {
    'generated-thread-1': 'high_priority',
    'generated-thread-2': 'needs_reply',
    'generated-thread-3': 'direct_or_fyi',
    'generated-thread-4': 'trusted_contact',
    'generated-thread-5': 'subscription',
    'generated-thread-6': 'low_priority',
    'generated-thread-9': 'delegated_scheduling',
  }[String(anchor.gmail_thread_id || '').trim()] || 'unclassified';
  return {
    ...structuredClone(anchor),
    id: anchor.id,
    anchor_email_id: anchor.id,
    conversation_key: conversationKey(anchor),
    member_count: members.length,
    matched_count: matches.length,
    unread_count: unreadCount,
    is_read: unreadCount === 0,
    star_state: starredCount === 0 ? 'none' : (starredCount === members.length ? 'all' : 'some'),
    is_starred: starredCount > 0,
    has_attachments: members.some(member => member.has_attachments),
    labels: allLabels,
    label_coverage: labelCoverage,
    inbox_placement: otherPlacement ? 'other' : 'focused',
    inbox_placement_reason: placementReason,
  };
}

function visibleConversations(mailbox, accountId = null) {
  const groups = new Map();
  for (const email of visibleEmails(mailbox)) {
    if (Number.isInteger(accountId) && accountId > 0 && email.account_id !== accountId) continue;
    const key = conversationKey(email);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(email);
  }
  return [...groups.values()]
    .map(conversationSummary)
    .sort((first, second) => Date.parse(second.date) - Date.parse(first.date) || second.id - first.id);
}

function inboxReturnTargets(snooze) {
  return snooze.return_target_email_ids
    .map(emailId => emails.get(emailId))
    .filter(Boolean);
}

function restoreOriginalInbox(snooze) {
  for (const emailId of snooze.original_inbox_email_ids) {
    const email = emails.get(emailId);
    if (email && !email.is_trash && !email.is_spam) applyAction(email, 'unarchive');
  }
}

function returnConversationToInbox(snooze) {
  const targets = inboxReturnTargets(snooze).filter(email => !email.is_trash && !email.is_spam);
  targets.forEach(email => applyAction(email, 'unarchive'));
  return targets.length;
}

function snoozeResponse(snooze) {
  const email = emails.get(snooze.email_id);
  return {
    id: snooze.id,
    email_id: snooze.email_id,
    account_id: snooze.account_id,
    account_email: 'qa.generated@example.test',
    gmail_thread_id: snooze.gmail_thread_id,
    wake_at: snooze.wake_at,
    time_zone: snooze.time_zone,
    condition: snooze.condition,
    state: snooze.state,
    status_detail: snooze.status_detail,
    archive_required: snooze.archive_required,
    originally_in_inbox: snooze.original_inbox_email_ids.length > 0,
    conversation_message_count: snooze.conversation_email_ids.length,
    archive_action_request_id: snooze.archive_action_request_id,
    archive_undo_until: snooze.archive_undo_until,
    error_code: snooze.error_code,
    error_message: snooze.error_message,
    created_at: snooze.created_at,
    updated_at: snooze.updated_at,
    scheduled_at: snooze.scheduled_at,
    returned_at: snooze.returned_at,
    cancelled_at: snooze.cancelled_at,
    dismissed_at: snooze.dismissed_at,
    failed_at: snooze.failed_at,
    email: email ? structuredClone(email) : null,
  };
}

function processDueSnoozes() {
  for (const snooze of snoozes.values()) {
    if (snooze.state === 'pending_archive' && snooze.archive_action_request_id) {
      const operation = operations.get(snooze.archive_action_request_id);
      if (operation?.state === 'cancelled') {
        snooze.state = 'cancelled';
        snooze.status_detail = 'archive_undone';
        snooze.cancelled_at = generatedClock().toISOString();
        snooze.updated_at = snooze.cancelled_at;
      } else if (Date.parse(snooze.archive_undo_until) <= clockMs) {
        if (operation) {
          operation.state = 'applied';
          operation.items.forEach(item => {
            item.state = 'applied';
            item.next_attempt_at = null;
            item.applied_at = generatedClock().toISOString();
          });
        }
        snooze.state = 'scheduled';
        snooze.status_detail = 'scheduled';
        snooze.scheduled_at = generatedClock().toISOString();
        snooze.updated_at = snooze.scheduled_at;
      }
    }
    if (!isActiveSnooze(snooze) || Date.parse(snooze.wake_at) > clockMs) continue;
    const email = emails.get(snooze.email_id);
    snooze.updated_at = generatedClock().toISOString();
    if (!email) {
      snooze.state = 'failed';
      snooze.status_detail = 'failed';
      snooze.error_code = 'email_missing';
      snooze.error_message = 'The generated email no longer exists';
      snooze.failed_at = snooze.updated_at;
      continue;
    }
    const targets = inboxReturnTargets(snooze);
    if (!targets.length || targets.every(item => item.is_trash || item.is_spam)) {
      snooze.state = 'dismissed';
      snooze.status_detail = 'protected_mailbox';
      snooze.dismissed_at = snooze.updated_at;
      continue;
    }
    if (snooze.condition === 'if_no_reply' && snooze.generated_reply_received) {
      snooze.state = 'dismissed';
      snooze.status_detail = 'reply_received';
      snooze.dismissed_at = snooze.updated_at;
      continue;
    }
    returnConversationToInbox(snooze);
    snooze.state = 'returned';
    snooze.status_detail = 'returned_to_inbox';
    snooze.returned_at = snooze.updated_at;
    audit.snooze_returns.push({ id: snooze.id, at: snooze.updated_at, reason: 'due' });
  }
}

function validateSnoozePayload(payload) {
  const email = emails.get(Number(payload?.email_id));
  if (!email) return 'Choose a generated email';
  if (email.is_trash || email.is_spam) return 'Trash and spam cannot be snoozed';
  if (!isUuid(payload?.idempotency_key)) return 'A UUID idempotency_key is required';
  if (!['always', 'if_no_reply'].includes(payload?.condition || 'always')) {
    return 'Choose a valid reminder condition';
  }
  if (typeof payload?.time_zone !== 'string' || !payload.time_zone.trim()) {
    return 'A timezone is required';
  }
  const wakeAt = Date.parse(payload?.wake_at);
  if (!Number.isFinite(wakeAt) || wakeAt <= clockMs) return 'wake_at must be in the future';
  return null;
}

async function handleSnoozeCreate(request, response) {
  const payload = await readJson(request);
  const validationError = validateSnoozePayload(payload);
  if (validationError) {
    audit.rejected_mutations.push({ route: '/api/snoozes', reason: validationError });
    return writeJson(response, { detail: { code: 'snooze_invalid', message: validationError } }, 422);
  }
  const existing = snoozesByIdempotency.get(payload.idempotency_key);
  if (existing) {
    audit.snooze_replays.push(existing.id);
    return writeJson(response, snoozeResponse(existing), 202);
  }
  const email = emails.get(Number(payload.email_id));
  const alreadyActive = [...snoozes.values()].find(
    item => item.account_id === email.account_id
      && item.gmail_thread_id === email.gmail_thread_id
      && isActiveSnooze(item),
  );
  if (alreadyActive) {
    return writeJson(response, { detail: { code: 'snooze_conflict', message: 'This email is already snoozed' } }, 409);
  }
  const createdAt = generatedClock().toISOString();
  const conversation = conversationEmails(email);
  const originalInbox = conversation.filter(item => item.labels.includes('INBOX'));
  const archiveRequired = originalInbox.length > 0;
  const archiveRequestId = archiveRequired ? randomUUID() : null;
  let archiveUndoUntil = null;
  if (archiveRequired) {
    const operationPayload = {
      action: 'archive',
      email_ids: originalInbox.map(item => item.id),
      idempotency_key: randomUUID(),
    };
    const selected = originalInbox;
    snapshots.set(archiveRequestId, selected.map(item => structuredClone(item)));
    selected.forEach(item => applyAction(item, 'archive'));
    archiveUndoUntil = new Date(clockMs + 10_000).toISOString();
    operations.set(archiveRequestId, {
      request_id: archiveRequestId,
      idempotency_key: operationPayload.idempotency_key,
      action: 'archive',
      state: 'staged',
      accepted_count: selected.length,
      undo_until: archiveUndoUntil,
      created_at: createdAt,
      items: selected.map((item, index) => ({
        id: 2_000 + operations.size + index,
        email_id: item.id,
        account_id: item.account_id,
        gmail_message_id: item.gmail_message_id,
        sequence: 1,
        action: 'archive',
        state: 'staged',
        attempt_count: 0,
        next_attempt_at: archiveUndoUntil,
        error_code: null,
        error_message: null,
        applied_at: null,
        failed_at: null,
        cancelled_at: null,
      })),
    });
  }
  const snooze = {
    id: randomUUID(),
    idempotency_key: payload.idempotency_key,
    email_id: email.id,
    account_id: email.account_id,
    gmail_thread_id: email.gmail_thread_id,
    wake_at: new Date(payload.wake_at).toISOString(),
    time_zone: payload.time_zone,
    condition: payload.condition || 'always',
    state: archiveRequired ? 'pending_archive' : 'scheduled',
    status_detail: archiveRequired ? 'archiving' : 'scheduled',
    archive_required: archiveRequired,
    conversation_email_ids: conversation.map(item => item.id),
    original_inbox_email_ids: originalInbox.map(item => item.id),
    return_target_email_ids: originalInbox.length ? originalInbox.map(item => item.id) : [email.id],
    archive_action_request_id: archiveRequestId,
    archive_undo_until: archiveUndoUntil,
    error_code: null,
    error_message: null,
    created_at: createdAt,
    updated_at: createdAt,
    scheduled_at: archiveRequired ? null : createdAt,
    returned_at: null,
    cancelled_at: null,
    dismissed_at: null,
    failed_at: null,
    generated_reply_received: false,
  };
  snoozes.set(snooze.id, snooze);
  snoozesByIdempotency.set(snooze.idempotency_key, snooze);
  audit.snooze_creates.push({ id: snooze.id, email_id: email.id, wake_at: snooze.wake_at });
  return writeJson(response, snoozeResponse(snooze), 202);
}

function applyAction(email, action, gmailLabelId = null) {
  const labels = new Set(email.labels);
  if (action === 'mark_read') labels.delete('UNREAD');
  if (action === 'mark_unread') labels.add('UNREAD');
  if (action === 'star') labels.add('STARRED');
  if (action === 'unstar') labels.delete('STARRED');
  if (action === 'archive') labels.delete('INBOX');
  if (action === 'unarchive') labels.add('INBOX');
  if (action === 'trash') labels.add('TRASH');
  if (action === 'untrash') labels.delete('TRASH');
  if (action === 'spam') {
    labels.add('SPAM');
    labels.delete('INBOX');
  }
  if (action === 'unspam') {
    labels.delete('SPAM');
    labels.add('INBOX');
  }
  if (action === 'add_label' && gmailLabelId) labels.add(gmailLabelId);
  if (action === 'remove_label' && gmailLabelId) labels.delete(gmailLabelId);
  if (action === 'move_to_label' && gmailLabelId) {
    labels.add(gmailLabelId);
    labels.delete('INBOX');
  }
  email.labels = [...labels];
  email.is_read = !labels.has('UNREAD');
  email.is_starred = labels.has('STARRED');
  email.is_trash = labels.has('TRASH');
  email.is_spam = labels.has('SPAM');
}

function visibleEmails(mailbox) {
  const all = [...emails.values()];
  if (mailbox === 'ALL') return all.filter(email => !email.is_trash && !email.is_spam);
  if (mailbox === 'STARRED') return all.filter(email => email.is_starred && !email.is_trash && !email.is_spam);
  if (mailbox === 'TRASH') return all.filter(email => email.is_trash);
  if (mailbox === 'SPAM') return all.filter(email => email.is_spam);
  if (mailbox === 'SENT' || mailbox === 'DRAFTS') return [];
  return all.filter(email => email.labels.includes('INBOX') && !email.is_trash && !email.is_spam);
}

async function handleActionCreate(request, response) {
  const payload = await readJson(request);
  const existing = [...operations.values()].find(
    operation => operation.idempotency_key === payload.idempotency_key,
  );
  if (existing) {
    const expected = operationPayloads.get(existing.request_id);
    const received = JSON.stringify({
      action: payload.action,
      email_ids: [...(payload.email_ids || [])].map(Number).sort((a, b) => a - b),
      label_id: payload.label_id == null ? null : Number(payload.label_id),
      scope: payload.scope || 'messages',
    });
    if (expected && expected !== received) {
      audit.rejected_mutations.push({ route: '/api/emails/actions', reason: 'Idempotency key payload conflict' });
      return writeJson(response, { detail: 'Idempotency key payload conflict' }, 409);
    }
    if (lostActionResponses > 0) {
      lostActionResponses -= 1;
      return writeJson(response, { detail: 'Failed to fetch' }, 503);
    }
    return writeJson(response, existing, 202);
  }

  const labelAction = ['add_label', 'remove_label', 'move_to_label'].includes(payload.action);
  const label = labelAction
    ? generatedLabels.find(item => item.id === Number(payload.label_id))
    : null;
  if (labelAction && (!label || label.label_type !== 'user')) {
    audit.rejected_mutations.push({ route: '/api/emails/actions', reason: 'Choose an existing generated user label' });
    return writeJson(response, { detail: 'Choose an existing generated user label' }, 422);
  }
  const requested = payload.email_ids.map(id => emails.get(Number(id))).filter(Boolean);
  if (requested.length !== payload.email_ids.length) {
    audit.rejected_mutations.push({ route: '/api/emails/actions', reason: 'Choose generated emails only' });
    return writeJson(response, { detail: 'Choose generated emails only' }, 404);
  }
  if (labelAction && requested.some(email => email.account_id !== label.account_id)) {
    audit.rejected_mutations.push({ route: '/api/emails/actions', reason: 'Labels are account-specific' });
    return writeJson(response, { detail: 'Labels are account-specific' }, 422);
  }
  const expanded = new Map();
  for (const email of requested) {
    const targets = labelAction || payload.scope === 'conversations'
      ? conversationEmails(email)
      : [email];
    for (const target of targets) expanded.set(target.id, target);
  }
  const requestId = randomUUID();
  const selected = [...expanded.values()];
  snapshots.set(requestId, selected.map(email => structuredClone(email)));
  selected.forEach(email => applyAction(email, payload.action, label?.gmail_label_id));
  const createdAt = new Date();
  const operation = {
    request_id: requestId,
    idempotency_key: payload.idempotency_key || randomUUID(),
    action: payload.action,
    state: 'staged',
    accepted_count: selected.length,
    undo_until: new Date(createdAt.getTime() + 10_000).toISOString(),
    created_at: createdAt.toISOString(),
    items: selected.map((email, index) => ({
      id: 1_000 + operations.size + index,
      email_id: email.id,
      account_id: email.account_id,
      gmail_message_id: email.gmail_message_id,
      sequence: 1,
      action: payload.action,
      state: 'staged',
      attempt_count: 0,
      next_attempt_at: null,
      error_code: null,
      error_message: null,
      applied_at: null,
      failed_at: null,
      cancelled_at: null,
    })),
  };
  operation.items.forEach(item => { item.next_attempt_at = operation.undo_until; });
  operations.set(requestId, operation);
  operationPayloads.set(requestId, JSON.stringify({
    action: payload.action,
    email_ids: [...payload.email_ids].map(Number).sort((a, b) => a - b),
    label_id: payload.label_id == null ? null : Number(payload.label_id),
    scope: payload.scope || 'messages',
  }));
  if (labelAction) {
    audit.label_actions.push({
      request_id: requestId,
      action: payload.action,
      label_id: label.id,
      gmail_label_id: label.gmail_label_id,
      requested_email_ids: payload.email_ids.map(Number),
      expanded_email_ids: selected.map(email => email.id),
    });
  }
  if (lostActionResponses > 0) {
    lostActionResponses -= 1;
    return writeJson(response, { detail: 'Failed to fetch' }, 503);
  }
  return writeJson(response, operation, 202);
}

async function handleRequest(request, response) {
  const url = new URL(request.url, `http://${request.headers.host}`);
  const { pathname } = url;
  processDueSnoozes();

  if (request.method === 'GET' && pathname === '/api/auth/me') {
    return writeJson(response, { id: 1, username: 'qa-user', is_admin: false });
  }
  if (request.method === 'GET' && pathname === '/api/health') {
    return writeJson(response, { status: 'ok', version: 'generated-snooze-qa' });
  }
  if (request.method === 'GET' && pathname === '/api/auth/ui-preferences') {
    return writeJson(response, { thread_order: 'asc', theme: 'default', color_scheme: 'light' });
  }
  if (request.method === 'GET' && pathname === '/api/auth/keyboard-shortcuts') {
    return writeJson(response, { shortcuts: {} });
  }
  if (request.method === 'GET' && pathname === '/api/accounts/') {
    return writeJson(response, [
      {
        id: 1,
        email: 'qa.generated@example.test',
        display_name: 'Generated QA',
        has_calendar_scope: true,
        sync_status: { status: 'idle', last_incremental_sync: new Date().toISOString() },
        calendar_sync_status: { status: 'idle' },
      },
      {
        id: 2,
        email: 'second.generated@example.test',
        display_name: 'Second Generated QA',
        has_calendar_scope: true,
        sync_status: { status: 'idle', last_incremental_sync: new Date().toISOString() },
        calendar_sync_status: { status: 'idle' },
      },
    ]);
  }
  if (request.method === 'GET' && pathname === '/api/emails/labels/all') {
    const accountId = Number(url.searchParams.get('account_id'));
    const visible = Number.isInteger(accountId) && accountId > 0
      ? generatedLabels.filter(label => label.account_id === accountId)
      : generatedLabels;
    return writeJson(response, visible);
  }
  if (request.method === 'GET' && pathname === '/api/build-version') {
    return writeJson(response, { version: 'generated-qa' });
  }
  if (request.method === 'GET' && pathname === '/api/events/stream') {
    response.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
    });
    response.write(': generated QA stream\n\n');
    request.on('close', () => response.end());
    return;
  }
  if (request.method === 'GET' && pathname === '/api/emails/') {
    const accountId = Number(url.searchParams.get('account_id'));
    let visible = visibleEmails(url.searchParams.get('mailbox') || 'INBOX');
    if (Number.isInteger(accountId) && accountId > 0) {
      visible = visible.filter(email => email.account_id === accountId);
    }
    return writeJson(response, { emails: visible, total: visible.length, page: 1, page_size: 50 });
  }
  if (request.method === 'GET' && pathname === '/api/emails/conversations') {
    const accountId = Number(url.searchParams.get('account_id'));
    const page = Math.max(1, Number(url.searchParams.get('page') || 1));
    const pageSize = Math.max(1, Math.min(200, Number(url.searchParams.get('page_size') || 50)));
    let visible = visibleConversations(
      url.searchParams.get('mailbox') || 'INBOX',
      Number.isInteger(accountId) && accountId > 0 ? accountId : null,
    );
    const inboxPlacement = url.searchParams.get('inbox_placement');
    if (inboxPlacement === 'focused' || inboxPlacement === 'other') {
      visible = visible.filter(conversation => conversation.inbox_placement === inboxPlacement);
    }
    const offset = (page - 1) * pageSize;
    return writeJson(response, {
      conversations: visible.slice(offset, offset + pageSize),
      total: visible.length,
      page,
      page_size: pageSize,
      total_pages: visible.length ? Math.ceil(visible.length / pageSize) : 0,
    });
  }
  if (request.method === 'GET' && pathname === '/api/emails/conversations/split') {
    const accountId = Number(url.searchParams.get('account_id'));
    const page = Math.max(1, Number(url.searchParams.get('page') || 1));
    const pageSize = Math.max(1, Math.min(100, Number(url.searchParams.get('page_size') || 25)));
    const visible = visibleConversations(
      'INBOX',
      Number.isInteger(accountId) && accountId > 0 ? accountId : null,
    );
    const responseSection = placement => {
      const section = visible.filter(conversation => conversation.inbox_placement === placement);
      const offset = (page - 1) * pageSize;
      return {
        conversations: section.slice(offset, offset + pageSize),
        total: section.length,
        page,
        page_size: pageSize,
        total_pages: section.length ? Math.ceil(section.length / pageSize) : 0,
      };
    };
    const focused = responseSection('focused');
    const other = responseSection('other');
    return writeJson(response, {
      focused,
      other,
      total: focused.total + other.total,
    });
  }
  if (request.method === 'GET' && pathname === '/api/emails/actions/recent') {
    return writeJson(response, [...operations.values()].slice(-20).reverse());
  }
  if (request.method === 'GET' && pathname === '/api/compose/sends/recent') {
    return writeJson(response, { operations: [] });
  }
  if (request.method === 'GET' && pathname === '/api/compose/sends/scheduled') {
    return writeJson(response, { operations: [] });
  }
  if (request.method === 'POST' && pathname === '/api/snoozes') {
    return handleSnoozeCreate(request, response);
  }
  if (request.method === 'GET' && pathname === '/api/snoozes') {
    const state = url.searchParams.get('state') || 'active';
    const limit = Math.max(1, Math.min(200, Number(url.searchParams.get('limit') || 50)));
    const offset = Math.max(0, Number(url.searchParams.get('offset') || 0));
    let items = [...snoozes.values()];
    if (state === 'active') items = items.filter(isActiveSnooze);
    else if (state === 'cancelled') items = items.filter(item => ['cancelled', 'dismissed'].includes(item.state));
    else if (state !== 'all') items = items.filter(item => item.state === state);
    items.sort((a, b) => Date.parse(a.wake_at) - Date.parse(b.wake_at));
    return writeJson(response, {
      items: items.slice(offset, offset + limit).map(snoozeResponse),
      total: items.length,
      limit,
      offset,
    });
  }

  const snoozeItemMatch = pathname.match(/^\/api\/snoozes\/([^/]+)$/);
  if (request.method === 'GET' && snoozeItemMatch) {
    const snooze = snoozes.get(snoozeItemMatch[1]);
    return writeJson(response, snooze ? snoozeResponse(snooze) : { detail: 'Not found' }, snooze ? 200 : 404);
  }

  const snoozeIdempotencyMatch = pathname.match(/^\/api\/snoozes\/by-idempotency\/([^/]+)$/);
  if (request.method === 'GET' && snoozeIdempotencyMatch) {
    const snooze = snoozesByIdempotency.get(snoozeIdempotencyMatch[1]);
    return writeJson(response, snooze ? snoozeResponse(snooze) : { detail: 'Not found' }, snooze ? 200 : 404);
  }

  const rescheduleMatch = pathname.match(/^\/api\/snoozes\/([^/]+)\/reschedule$/);
  if (request.method === 'PATCH' && rescheduleMatch) {
    const snooze = snoozes.get(rescheduleMatch[1]);
    if (!snooze) return writeJson(response, { detail: 'Not found' }, 404);
    const payload = await readJson(request);
    const wakeAt = Date.parse(payload.wake_at);
    if (!isActiveSnooze(snooze) || !Number.isFinite(wakeAt) || wakeAt <= clockMs) {
      return writeJson(response, { detail: { code: 'snooze_conflict', message: 'Choose a future time for an active snooze' } }, 409);
    }
    snooze.wake_at = new Date(wakeAt).toISOString();
    snooze.time_zone = String(payload.time_zone || snooze.time_zone);
    snooze.updated_at = generatedClock().toISOString();
    audit.snooze_reschedules.push({ id: snooze.id, wake_at: snooze.wake_at });
    return writeJson(response, snoozeResponse(snooze));
  }

  const cancelSnoozeMatch = pathname.match(/^\/api\/snoozes\/([^/]+)\/cancel$/);
  if (request.method === 'POST' && cancelSnoozeMatch) {
    const snooze = snoozes.get(cancelSnoozeMatch[1]);
    if (!snooze) return writeJson(response, { detail: 'Not found' }, 404);
    if (isActiveSnooze(snooze)) {
      restoreOriginalInbox(snooze);
      snooze.state = 'cancelled';
      snooze.status_detail = 'cancelled';
      snooze.cancelled_at = generatedClock().toISOString();
      snooze.updated_at = snooze.cancelled_at;
    }
    audit.snooze_cancels.push({ id: snooze.id, at: generatedClock().toISOString() });
    return writeJson(response, snoozeResponse(snooze));
  }

  const returnSnoozeMatch = pathname.match(/^\/api\/snoozes\/([^/]+)\/return-now$/);
  if (request.method === 'POST' && returnSnoozeMatch) {
    const snooze = snoozes.get(returnSnoozeMatch[1]);
    if (!snooze) return writeJson(response, { detail: 'Not found' }, 404);
    const email = emails.get(snooze.email_id);
    const returnedCount = email ? returnConversationToInbox(snooze) : 0;
    if (email && returnedCount === 0) {
      snooze.state = 'dismissed';
      snooze.status_detail = 'protected_mailbox';
      snooze.dismissed_at = generatedClock().toISOString();
    } else if (email) {
      snooze.state = 'returned';
      snooze.status_detail = 'returned_now';
      snooze.returned_at = generatedClock().toISOString();
    } else {
      snooze.state = 'failed';
      snooze.status_detail = 'failed';
      snooze.error_code = 'email_missing';
      snooze.failed_at = generatedClock().toISOString();
    }
    snooze.updated_at = generatedClock().toISOString();
    audit.snooze_returns.push({ id: snooze.id, at: snooze.updated_at, reason: 'return_now' });
    return writeJson(response, snoozeResponse(snooze));
  }

  if (request.method === 'GET' && pathname === '/api/__qa/snooze-audit') {
    return writeJson(response, {
      ...audit,
      clock: generatedClock().toISOString(),
      active_snoozes: [...snoozes.values()].filter(isActiveSnooze).map(snoozeResponse),
      all_snoozes: [...snoozes.values()].map(snoozeResponse),
    });
  }
  if (request.method === 'GET' && pathname === '/api/__qa/mail-action-audit') {
    return writeJson(response, {
      ...audit,
      emails: [...emails.values()].map(email => structuredClone(email)),
      operations: [...operations.values()].map(operation => structuredClone(operation)),
    });
  }
  if (request.method === 'POST' && pathname === '/api/__qa/clock') {
    const payload = await readJson(request);
    const next = Date.parse(payload.now);
    if (!Number.isFinite(next) || next < clockMs) {
      return writeJson(response, { detail: 'Generated clock only moves forward' }, 422);
    }
    clockMs = next;
    audit.clock_changes.push(generatedClock().toISOString());
    processDueSnoozes();
    return writeJson(response, { now: generatedClock().toISOString() });
  }
  if (request.method === 'POST' && pathname === '/api/__qa/generated-reply') {
    const payload = await readJson(request);
    const snooze = snoozes.get(payload.snooze_id);
    if (!snooze) return writeJson(response, { detail: 'Not found' }, 404);
    snooze.generated_reply_received = true;
    return writeJson(response, { ok: true, snooze_id: snooze.id });
  }
  if (request.method === 'POST' && pathname === '/api/__qa/protected-mailbox') {
    const payload = await readJson(request);
    const email = emails.get(Number(payload.email_id));
    if (!email || !['trash', 'spam'].includes(payload.mailbox)) {
      return writeJson(response, { detail: 'Choose a generated email and protected mailbox' }, 422);
    }
    applyAction(email, payload.mailbox);
    return writeJson(response, { ok: true, email });
  }
  if (request.method === 'POST' && pathname === '/api/emails/actions') {
    return handleActionCreate(request, response);
  }

  const idempotencyMatch = pathname.match(/^\/api\/emails\/actions\/by-idempotency\/([^/]+)$/);
  if (request.method === 'GET' && idempotencyMatch) {
    if (lostLookupResponses > 0) {
      lostLookupResponses -= 1;
      return writeJson(response, { detail: 'Failed to fetch' }, 503);
    }
    const operation = [...operations.values()].find(
      item => item.idempotency_key === idempotencyMatch[1],
    );
    return writeJson(response, operation || { detail: 'Not found' }, operation ? 200 : 404);
  }

  const undoMatch = pathname.match(/^\/api\/emails\/actions\/([^/]+)\/undo$/);
  if (request.method === 'POST' && undoMatch) {
    const operation = operations.get(undoMatch[1]);
    if (!operation) return writeJson(response, { detail: 'Not found' }, 404);
    if (operation.state !== 'staged' || clockMs >= Date.parse(operation.undo_until)) {
      return writeJson(response, { detail: 'The generated undo window has closed' }, 409);
    }
    const before = snapshots.get(undoMatch[1]) || [];
    before.forEach(email => emails.set(email.id, email));
    operation.state = 'cancelled';
    operation.items.forEach(item => {
      item.state = 'cancelled';
      item.cancelled_at = generatedClock().toISOString();
    });
    for (const snooze of snoozes.values()) {
      if (snooze.archive_action_request_id !== operation.request_id || !isActiveSnooze(snooze)) continue;
      snooze.state = 'cancelled';
      snooze.status_detail = 'archive_undone';
      snooze.cancelled_at = generatedClock().toISOString();
      snooze.updated_at = snooze.cancelled_at;
    }
    return writeJson(response, operation);
  }

  const retryMatch = pathname.match(/^\/api\/emails\/actions\/([^/]+)\/retry$/);
  if (request.method === 'POST' && retryMatch) {
    const operation = operations.get(retryMatch[1]);
    if (!operation) return writeJson(response, { detail: 'Not found' }, 404);
    operation.state = 'retry_wait';
    operation.items.filter(item => item.state === 'failed').forEach(item => {
      item.state = 'retry_wait';
      item.next_attempt_at = new Date().toISOString();
    });
    return writeJson(response, operation);
  }

  const actionMatch = pathname.match(/^\/api\/emails\/actions\/([^/]+)$/);
  if (request.method === 'GET' && actionMatch) {
    return writeJson(response, operations.get(actionMatch[1]) || { detail: 'Not found' }, operations.has(actionMatch[1]) ? 200 : 404);
  }

  const threadMatch = pathname.match(/^\/api\/emails\/thread\/([^/]+)$/);
  if (request.method === 'GET' && threadMatch) {
    const threadId = decodeURIComponent(threadMatch[1]);
    const accountId = Number(url.searchParams.get('account_id'));
    const members = [...emails.values()]
      .filter(email => email.gmail_thread_id === threadId && email.account_id === accountId)
      .sort((first, second) => Date.parse(first.date) - Date.parse(second.date) || first.id - second.id);
    if (!members.length) return writeJson(response, { detail: 'Thread not found' }, 404);
    const participants = new Map();
    for (const email of members) {
      if (email.from_address) participants.set(email.from_address, { name: email.from_name, address: email.from_address });
      for (const recipient of email.to_addresses || []) {
        const address = typeof recipient === 'string' ? recipient : recipient.address;
        if (address) participants.set(address, typeof recipient === 'string' ? { name: null, address } : recipient);
      }
    }
    return writeJson(response, {
      thread_id: threadId,
      subject: members.at(-1)?.subject || members[0]?.subject || null,
      emails: members.map(email => structuredClone(email)),
      participants: [...participants.values()],
    });
  }

  const emailMatch = pathname.match(/^\/api\/emails\/(\d+)$/);
  if (request.method === 'GET' && emailMatch) {
    const email = emails.get(Number(emailMatch[1]));
    return writeJson(response, email || { detail: 'Not found' }, email ? 200 : 404);
  }

  audit.unknown_routes.push({ method: request.method, pathname });
  return writeJson(response, { detail: `No generated QA route for ${request.method} ${pathname}` }, 404);
}

const server = createServer((request, response) => {
  handleRequest(request, response).catch(error => {
    writeJson(response, { detail: error.message }, 500);
  });
});

server.listen(port, '127.0.0.1', () => {
  process.stdout.write(`Generated mail-action QA API listening on http://127.0.0.1:${port}\n`);
});

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
