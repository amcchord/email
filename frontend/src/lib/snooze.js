import { browserScheduleTimezone } from './remindLater.js';

function fallbackUuid() {
  const bytes = new Uint8Array(16);
  globalThis.crypto?.getRandomValues?.(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const value = [...bytes].map(byte => byte.toString(16).padStart(2, '0')).join('');
  return `${value.slice(0, 8)}-${value.slice(8, 12)}-${value.slice(12, 16)}-${value.slice(16, 20)}-${value.slice(20)}`;
}

export function snoozeIdempotencyKey() {
  return globalThis.crypto?.randomUUID?.() || fallbackUuid();
}

export function buildSnoozeRequest(emailId, {
  wakeAt,
  timeZone = browserScheduleTimezone(),
  condition = 'always',
  idempotencyKey = snoozeIdempotencyKey(),
} = {}) {
  const normalizedEmailId = Number(emailId);
  if (!Number.isSafeInteger(normalizedEmailId) || normalizedEmailId <= 0) {
    throw new Error('Choose an email to snooze.');
  }
  const wake = new Date(wakeAt);
  if (!Number.isFinite(wake.getTime())) throw new Error('Choose when this email should return.');
  if (wake.getTime() <= Date.now() + 60_000) {
    throw new Error('Choose a time at least one minute from now.');
  }
  if (!['always', 'if_no_reply'].includes(condition)) {
    throw new Error('Choose a valid reminder condition.');
  }
  if (typeof timeZone !== 'string' || !timeZone.trim()) throw new Error('A timezone is required.');
  if (typeof idempotencyKey !== 'string' || !idempotencyKey.trim()) {
    throw new Error('A snooze idempotency key is required.');
  }
  return {
    email_id: normalizedEmailId,
    wake_at: wake.toISOString(),
    time_zone: timeZone.trim(),
    condition,
    idempotency_key: idempotencyKey.trim(),
  };
}

export function snoozedRecordToEmail(record) {
  const email = record?.email || {};
  const id = Number(email.id ?? record?.email_id);
  return {
    ...email,
    id,
    account_id: email.account_id ?? record?.account_id ?? null,
    account_email: email.account_email ?? record?.account_email ?? null,
    gmail_thread_id: email.gmail_thread_id ?? record?.gmail_thread_id ?? null,
    snooze_id: record?.id ?? null,
    snooze_wake_at: record?.wake_at ?? null,
    snooze_time_zone: record?.time_zone ?? null,
    snooze_condition: record?.condition ?? 'always',
    snooze_origin: record?.origin ?? 'manual',
    snooze_state: record?.state ?? null,
    snooze_status_detail: record?.status_detail ?? null,
  };
}

export function normalizeSnoozedList(payload) {
  const items = Array.isArray(payload?.items) ? payload.items : [];
  return {
    emails: items.map(snoozedRecordToEmail).filter(email => Number.isSafeInteger(email.id) && email.id > 0),
    total: Number.isFinite(Number(payload?.total)) ? Number(payload.total) : items.length,
  };
}

export function removeSnoozedEmail(list, emailId) {
  return (Array.isArray(list) ? list : []).filter(email => email.id !== emailId);
}

export function snoozeThreadKey(value) {
  const accountId = Number(value?.account_id);
  const threadId = String(value?.gmail_thread_id ?? value?.thread_id ?? '').trim();
  if (!Number.isSafeInteger(accountId) || accountId <= 0 || !threadId) return null;
  return `${accountId}:${threadId}`;
}

export function snoozeMatchesEmail(record, email) {
  if (Number(record?.email_id) === Number(email?.id)) return true;
  const recordThreadKey = snoozeThreadKey(record);
  return recordThreadKey !== null && recordThreadKey === snoozeThreadKey(email);
}

export function partitionSnoozeConversation(emails, record) {
  const remaining = [];
  const matched = [];
  for (const [index, email] of (Array.isArray(emails) ? emails : []).entries()) {
    if (snoozeMatchesEmail(record, email)) matched.push({ email, index });
    else remaining.push(email);
  }
  return { matched, remaining };
}

export function reconcileActiveSnoozeEmails(emails, reminders, { retain = false } = {}) {
  const active = Array.isArray(reminders) ? reminders : [];
  const reconciled = [];
  let matchedCount = 0;
  for (const email of (Array.isArray(emails) ? emails : [])) {
    const reminder = active.find(item => snoozeMatchesEmail(item, email));
    if (!reminder) {
      reconciled.push(email);
      continue;
    }
    if (reminder.origin === 'automatic_follow_up') {
      // Automatic follow-ups are reminders, not mailbox-placement commands.
      // Preserve the message in Inbox-derived lists while exposing its origin.
      reconciled.push({
        ...email,
        snooze_id: reminder.id,
        snooze_wake_at: reminder.wake_at,
        snooze_time_zone: reminder.time_zone,
        snooze_condition: reminder.condition,
        snooze_origin: reminder.origin,
        snooze_state: reminder.state,
        snooze_outcome_unknown: false,
      });
      continue;
    }
    matchedCount += 1;
    if (!retain) continue;
    reconciled.push({
      ...email,
      snooze_id: reminder.id,
      snooze_wake_at: reminder.wake_at,
      snooze_time_zone: reminder.time_zone,
      snooze_condition: reminder.condition,
      snooze_origin: reminder.origin ?? 'manual',
      snooze_state: reminder.state,
      snooze_outcome_unknown: false,
    });
  }
  return { emails: reconciled, matchedCount };
}

export function isSnoozeTransportError(error) {
  return error?.name !== 'AbortError' && !Number.isFinite(Number(error?.status));
}

/**
 * Reuse one idempotency key through a lost-response retry, then resolve the
 * remaining ambiguity by key. A 404 proves neither POST committed; another
 * lookup transport failure stays explicitly unknown and must not reinsert a
 * message that the server may already have archived.
 */
export async function createSnoozeWithReconciliation(transport, payload) {
  try {
    return await transport.createSnooze(payload);
  } catch (firstError) {
    if (!isSnoozeTransportError(firstError)) throw firstError;
  }

  let retryError;
  try {
    return await transport.createSnooze(payload);
  } catch (error) {
    if (!isSnoozeTransportError(error)) throw error;
    retryError = error;
  }

  try {
    return await transport.getSnoozeByIdempotency(payload.idempotency_key);
  } catch (lookupError) {
    if (lookupError?.status === 404) throw retryError;
    const unknown = new Error('The snooze was sent, but its status is not confirmed yet.');
    unknown.code = 'snooze_outcome_unknown';
    unknown.cause = lookupError;
    throw unknown;
  }
}

function mutationUnknown(error) {
  const unknown = new Error('The reminder change was sent, but its status is not confirmed yet.');
  unknown.code = 'snooze_mutation_outcome_unknown';
  unknown.cause = error;
  return unknown;
}

export function rescheduleMatches(record, wakeAt, timeZone) {
  return Number.isFinite(Date.parse(record?.wake_at))
    && Date.parse(record.wake_at) === Date.parse(wakeAt)
    && record?.time_zone === timeZone
    && !['returned', 'cancelled', 'dismissed', 'failed'].includes(record?.state);
}

export function returnNowAccepted(record) {
  return ['pending_return', 'returned'].includes(record?.state);
}

export function cancelAccepted(record) {
  return ['pending_return', 'cancelled'].includes(record?.state);
}

/**
 * A write response may be lost after PostgreSQL commits. Read the exact
 * reminder before deciding whether an optimistic projection must roll back.
 */
export async function runSnoozeMutationWithReconciliation({
  mutate,
  lookup,
  accepted,
}) {
  try {
    return await mutate();
  } catch (error) {
    if (!isSnoozeTransportError(error)) throw error;
    let record;
    try {
      record = await lookup();
    } catch (lookupError) {
      if (isSnoozeTransportError(lookupError)) throw mutationUnknown(lookupError);
      throw error;
    }
    if (accepted(record)) return record;
    throw error;
  }
}
