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
