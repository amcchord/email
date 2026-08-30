import { writable } from 'svelte/store';
import { api } from './api.js';
import { captureAuthEpoch, isAuthEpochCurrent } from './authSession.js';
import { showToast } from './toasts.js';
import { formatScheduledDelivery } from './sendLater.js';

export const OUTBOUND_SEND_STATES = Object.freeze([
  'staged',
  'processing',
  'retry_wait',
  'reconciling',
  'sent',
  'failed',
  'cancelled',
]);

export const OUTBOUND_SEND_TERMINAL_STATES = Object.freeze([
  'sent',
  'failed',
  'cancelled',
]);

const VALID_STATES = new Set(OUTBOUND_SEND_STATES);
const TERMINAL_STATES = new Set(OUTBOUND_SEND_TERMINAL_STATES);
const POLLED_STATES = new Set(['staged', 'processing', 'retry_wait', 'reconciling']);

function safeText(value, limit = 500) {
  return typeof value === 'string' ? value.slice(0, limit) : null;
}

function safeDate(value) {
  if (typeof value !== 'string') return null;
  return Number.isFinite(Date.parse(value)) ? value : null;
}

function safePositiveInteger(value) {
  const candidate = Number(value);
  return Number.isSafeInteger(candidate) && candidate > 0 ? candidate : null;
}

function safeUuid(value) {
  const candidate = typeof value === 'string' ? value.toLowerCase() : '';
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(candidate)
    ? candidate
    : null;
}

function defaultSessionKey(snapshot) {
  return `${snapshot?.generation ?? 'unknown'}:${snapshot?.userId ?? 'anonymous'}`;
}

function outboundSessionChangedError() {
  const error = new Error('Authentication session changed during email send');
  error.name = 'AbortError';
  error.code = 'auth_session_changed';
  return error;
}

function isSessionChangeError(error) {
  return error?.code === 'auth_session_changed'
    || error?.code === 'auth_logout_in_progress';
}

export function secureOutboundSendKey(
  randomUUID = globalThis.crypto?.randomUUID?.bind(globalThis.crypto),
) {
  if (!randomUUID) throw new Error('Secure random UUID support is required');
  const key = randomUUID();
  if (typeof key !== 'string' || !key.trim()) {
    throw new Error('Secure random UUID support returned an invalid key');
  }
  return key;
}

export function isUnknownOutboundSendError(error) {
  const status = Number(error?.status);
  return error instanceof TypeError
    || error?.name === 'TimeoutError'
    || /network|failed to fetch|connection|timed out|timeout/i.test(error?.message || '')
    || status === 408
    || status === 425
    || status === 429
    || status >= 500;
}

export function remainingOutboundUndoMs(operation, now = Date.now()) {
  if (operation?.state !== 'staged') return 0;
  const deadline = Date.parse(operation?.undo_until || '');
  if (!Number.isFinite(deadline)) return 0;
  return Math.max(0, deadline - now);
}

export function canUndoOutboundSend(operation, now = Date.now()) {
  return Boolean(operation?.send_id)
    && operation?.can_undo !== false
    && remainingOutboundUndoMs(operation, now) > 0;
}

export function isScheduledOutboundSend(operation) {
  return Boolean(operation?.scheduled_for);
}

export function normalizeOutboundSendOperation(raw, { fallbackKey = null } = {}) {
  const source = raw && typeof raw === 'object' ? raw : {};
  const sendId = source.send_id ?? source.id ?? null;
  const idempotencyKey = safeText(source.idempotency_key, 128) || safeText(fallbackKey, 128);
  const rawState = typeof source.state === 'string' ? source.state : '';
  const hasServerIdentity = sendId !== null && sendId !== undefined && String(sendId).length > 0;
  // A state without a server identity cannot prove that the server accepted
  // the request. Keep it in the explicit do-not-resend reconciliation state.
  const state = VALID_STATES.has(rawState) && hasServerIdentity
    ? rawState
    : 'reconciling';

  return Object.freeze({
    send_id: hasServerIdentity ? sendId : null,
    idempotency_key: idempotencyKey,
    account_id: safePositiveInteger(source.account_id),
    source_email_id: safePositiveInteger(source.source_email_id),
    client_draft_id: safeUuid(source.client_draft_id),
    state,
    scheduled_for: safeDate(source.scheduled_for),
    schedule_timezone: safeText(source.schedule_timezone, 64),
    execute_after: safeDate(source.execute_after),
    undo_until: safeDate(source.undo_until),
    next_attempt_at: safeDate(source.next_attempt_at),
    created_at: safeDate(source.created_at),
    updated_at: safeDate(source.updated_at),
    sent_at: safeDate(source.sent_at),
    failed_at: safeDate(source.failed_at),
    cancelled_at: safeDate(source.cancelled_at),
    attempt_count: Math.max(0, Number.isFinite(Number(source.attempt_count))
      ? Math.trunc(Number(source.attempt_count))
      : 0),
    max_attempts: Math.max(0, Number.isFinite(Number(source.max_attempts))
      ? Math.trunc(Number(source.max_attempts))
      : 0),
    can_undo: typeof source.can_undo === 'boolean'
      ? source.can_undo
      : state === 'staged',
    can_cancel: typeof source.can_cancel === 'boolean' ? source.can_cancel : false,
    can_send_now: typeof source.can_send_now === 'boolean' ? source.can_send_now : false,
    can_retry: typeof source.can_retry === 'boolean'
      ? source.can_retry
      : false,
    error_code: safeText(source.error_code, 96),
    error_message: safeText(source.error_message, 500),
    client_only: !hasServerIdentity,
  });
}

function operationIdentity(operation) {
  if (operation?.send_id !== null && operation?.send_id !== undefined) {
    return `send:${operation.send_id}`;
  }
  if (operation?.idempotency_key) return `key:${operation.idempotency_key}`;
  return null;
}

function operationTime(operation) {
  return Date.parse(operation?.updated_at || operation?.created_at || '') || 0;
}

function callbackSafely(callback, ...args) {
  if (typeof callback !== 'function') return;
  try {
    const result = callback(...args);
    // Callbacks may be async, but delivery durability must never depend on
    // them. Absorb rejections just as we absorb synchronous callback errors.
    if (result && typeof result.then === 'function') void result.catch(() => {});
  } catch {
    // A caller callback is an enhancement over the durable controller. Its
    // failure must never interrupt polling, reconciliation, or another callback.
  }
}

/**
 * Own one authenticated user's outbound-send lifecycle independently of any
 * Compose, Flow, or reader component instance.
 */
export function createOutboundSendController({
  transport,
  captureSession = captureAuthEpoch,
  isSessionCurrent = isAuthEpochCurrent,
  sessionKey = defaultSessionKey,
  notify = showToast,
  randomUUID = globalThis.crypto?.randomUUID?.bind(globalThis.crypto),
  now = Date.now,
  schedule = globalThis.setTimeout,
  cancel = globalThis.clearTimeout,
  pollIntervalMs = 2_500,
  maxCreateReplays = 2,
  operationLimit = 120,
} = {}) {
  if (!transport?.create || !transport?.lookupByIdempotency || !transport?.get) {
    throw new Error('Outbound send transport is incomplete');
  }

  const stateStore = writable([]);
  let operations = [];
  let ownedSession = captureSession();
  let pollTimer = null;
  let pollPromise = null;
  let destroyed = false;
  const records = new Map();
  const announced = new Set();

  function publish(nextOperations = operations) {
    operations = [...nextOperations]
      .sort((left, right) => operationTime(right) - operationTime(left))
      .slice(0, operationLimit);
    stateStore.set(operations);
  }

  function clearPollTimer() {
    if (pollTimer !== null) cancel(pollTimer);
    pollTimer = null;
  }

  function resetInternal(nextSession = captureSession()) {
    clearPollTimer();
    records.clear();
    announced.clear();
    pollPromise = null;
    ownedSession = nextSession;
    publish([]);
  }

  function ensureSession() {
    const current = captureSession();
    if (sessionKey(current) !== sessionKey(ownedSession)) resetInternal(current);
    return ownedSession;
  }

  function assertCurrent(session) {
    if (!destroyed && isSessionCurrent(session)) return;
    if (!destroyed) ensureSession();
    throw outboundSessionChangedError();
  }

  function findOperation(target) {
    if (target && typeof target === 'object') {
      const normalized = normalizeOutboundSendOperation(target);
      const identity = operationIdentity(normalized);
      if (identity) {
        return operations.find(operation => operationIdentity(operation) === identity) || normalized;
      }
    }
    return operations.find(operation => String(operation.send_id) === String(target)) || null;
  }

  function replaceOperation(operation) {
    const identity = operationIdentity(operation);
    const next = operations.filter(existing => {
      if (identity && operationIdentity(existing) === identity) return false;
      return !(
        operation.idempotency_key
        && existing.idempotency_key === operation.idempotency_key
      );
    });
    next.push(operation);
    publish(next);
  }

  function recordFor(operation) {
    return operation?.idempotency_key
      ? records.get(operation.idempotency_key)
      : null;
  }

  function announceOnce(operation, kind, callback) {
    const identity = operationIdentity(operation) || operation?.idempotency_key;
    if (!identity) return;
    const key = `${identity}:${kind}`;
    if (announced.has(key)) return;
    announced.add(key);
    callback();
  }

  function announceUndo(operation, record) {
    const undoMs = remainingOutboundUndoMs(operation, now());
    if (undoMs <= 0 || !operation.send_id) return;
    const session = record?.session || ensureSession();
    announceOnce(operation, 'undo', () => {
      notify('Email queued to send', 'info', undoMs, {
        actionLabel: 'Undo',
        onAction: async () => {
          try {
            await undo(operation.send_id);
          } catch (error) {
            if (!isSessionChangeError(error) && isSessionCurrent(session)) {
              notify(error?.message || 'Could not undo this email send', 'error');
            }
          }
        },
        dismissLabel: 'Dismiss send confirmation',
      });
      if (record) record.undoOffered = true;
    });
  }

  function announceScheduled(operation, record) {
    if (!operation.send_id || !operation.scheduled_for) return;
    const session = record?.session || ensureSession();
    announceOnce(operation, 'scheduled', () => {
      notify(
        `Email scheduled for ${formatScheduledDelivery(operation.scheduled_for, operation.schedule_timezone || undefined)}`,
        'success',
        6_000,
        operation.can_cancel ? {
          actionLabel: 'Cancel',
          onAction: async () => {
            try {
              await cancelScheduled(operation.send_id);
            } catch (error) {
              if (!isSessionChangeError(error) && isSessionCurrent(session)) {
                notify(error?.message || 'Could not cancel this scheduled email', 'error');
              }
            }
          },
          dismissLabel: 'Dismiss schedule confirmation',
        } : undefined,
      );
    });
  }

  function notifyReconciling(operation) {
    announceOnce(operation, 'reconciling', () => {
      notify('Confirming send status — do not resend this email', 'info', 6_000);
    });
  }

  function handleOperation(operation, { announceLifecycle = false } = {}) {
    replaceOperation(operation);
    const record = recordFor(operation);
    if (record) {
      assertCurrent(record.session);
      const fingerprint = `${operation.send_id ?? 'pending'}:${operation.state}:${operation.updated_at ?? ''}`;
      if (record.lastFingerprint !== fingerprint) {
        record.lastFingerprint = fingerprint;
        callbackSafely(record.callbacks.onStateChange, operation);
        assertCurrent(record.session);
      }
      if (!record.accepted && operation.send_id) {
        record.accepted = true;
        callbackSafely(record.callbacks.onAccepted, operation);
        assertCurrent(record.session);
      }
    }

    if (announceLifecycle && record && operation.state === 'staged') {
      if (isScheduledOutboundSend(operation)) announceScheduled(operation, record);
      else announceUndo(operation, record);
    } else if (announceLifecycle && operation.state === 'reconciling') {
      notifyReconciling(operation);
    }

    if (TERMINAL_STATES.has(operation.state)) {
      if (record) assertCurrent(record.session);
      if (announceLifecycle || record) {
        announceOnce(operation, operation.state, () => {
          if (operation.state === 'sent') {
            callbackSafely(record?.callbacks.onSent, operation);
            if (record) assertCurrent(record.session);
            notify('Email sent', 'success');
          } else if (operation.state === 'cancelled') {
            const hasRestore = typeof record?.callbacks.onRestore === 'function';
            callbackSafely(record?.callbacks.onRestore, operation, 'cancelled');
            if (record) assertCurrent(record.session);
            notify(
              hasRestore ? 'Send cancelled; recovering draft' : 'Send cancelled',
              'success',
            );
          } else {
            const hasRestore = typeof record?.callbacks.onRestore === 'function';
            callbackSafely(record?.callbacks.onRestore, operation, 'failed');
            if (record) assertCurrent(record.session);
            notify(
              operation.error_message
                || (hasRestore
                  ? 'Email could not be sent; recovering draft'
                  : 'Email could not be sent'),
              'error',
            );
          }
        });
      }
      if (operation.idempotency_key) records.delete(operation.idempotency_key);
    }

    schedulePollIfNeeded();
    return operation;
  }

  function operationPollDelay(operation) {
    if (!POLLED_STATES.has(operation.state)) return Number.POSITIVE_INFINITY;
    if (operation.state === 'staged' && isScheduledOutboundSend(operation)) {
      const untilDue = Date.parse(operation.execute_after || '') - now();
      if (Number.isFinite(untilDue) && untilDue > 10_000) {
        return Math.max(pollIntervalMs, Math.min(15 * 60_000, untilDue - 5_000));
      }
    }
    return pollIntervalMs;
  }

  function hasPollableOperation() {
    return operations.some(operation => Number.isFinite(operationPollDelay(operation)));
  }

  function schedulePollIfNeeded() {
    if (destroyed || pollTimer !== null || !hasPollableOperation()) return;
    const session = ensureSession();
    const delay = Math.min(...operations.map(operationPollDelay));
    pollTimer = schedule(() => {
      pollTimer = null;
      void poll(session).catch(() => {
        // Session changes and transient poll failures are intentionally quiet.
        // The current session's monitor will schedule its own authoritative read.
      });
    }, delay);
  }

  async function lookupOwnedOperation(idempotencyKey, session) {
    try {
      const raw = await transport.lookupByIdempotency(idempotencyKey);
      assertCurrent(session);
      return normalizeOutboundSendOperation(raw, { fallbackKey: idempotencyKey });
    } catch (error) {
      assertCurrent(session);
      if (error?.status === 404) return null;
      throw error;
    }
  }

  async function submit(payload, callbacks = {}) {
    const session = ensureSession();
    assertCurrent(session);
    const idempotencyKey = secureOutboundSendKey(randomUUID);
    const record = {
      callbacks: callbacks && typeof callbacks === 'object' ? callbacks : {},
      session,
      accepted: false,
      lastFingerprint: null,
      undoOffered: false,
    };
    records.set(idempotencyKey, record);

    let lastError = null;
    for (let replay = 0; replay <= maxCreateReplays; replay += 1) {
      try {
        const raw = await transport.create(payload, idempotencyKey);
        assertCurrent(session);
        const operation = normalizeOutboundSendOperation(raw, { fallbackKey: idempotencyKey });
        return handleOperation(operation, { announceLifecycle: true });
      } catch (error) {
        assertCurrent(session);
        if (isSessionChangeError(error)) throw error;
        if (!isUnknownOutboundSendError(error)) {
          records.delete(idempotencyKey);
          throw error;
        }
        lastError = error;
      }

      try {
        const existing = await lookupOwnedOperation(idempotencyKey, session);
        if (existing) return handleOperation(existing, { announceLifecycle: true });
      } catch (lookupError) {
        assertCurrent(session);
        if (isSessionChangeError(lookupError)) throw lookupError;
        lastError = lookupError;
      }
    }

    assertCurrent(session);
    const placeholder = normalizeOutboundSendOperation({
      idempotency_key: idempotencyKey,
      state: 'reconciling',
      created_at: new Date(now()).toISOString(),
      error_code: 'send_outcome_unknown',
      error_message: 'Send status is still being confirmed.',
    });
    record.lastError = lastError;
    handleOperation(placeholder, { announceLifecycle: true });
    return placeholder;
  }

  async function refreshOperation(target, { announceLifecycle = true } = {}) {
    const session = ensureSession();
    assertCurrent(session);
    const operation = findOperation(target);
    if (!operation) return null;

    let raw;
    if (operation.send_id !== null) {
      raw = await transport.get(operation.send_id);
    } else if (operation.idempotency_key) {
      const result = await lookupOwnedOperation(operation.idempotency_key, session);
      if (!result) return operation;
      raw = result;
    } else {
      return operation;
    }
    assertCurrent(session);
    return handleOperation(
      normalizeOutboundSendOperation(raw, { fallbackKey: operation.idempotency_key }),
      { announceLifecycle },
    );
  }

  async function poll(session = ensureSession()) {
    if (destroyed) return [];
    assertCurrent(session);
    if (pollPromise) return pollPromise;
    const targets = operations.filter(operation => POLLED_STATES.has(operation.state));
    let trackedPoll;
    trackedPoll = Promise.allSettled(targets.map(operation =>
      refreshOperation(operation, { announceLifecycle: Boolean(recordFor(operation)) })
    )).finally(() => {
      if (pollPromise === trackedPoll) pollPromise = null;
      if (!destroyed && isSessionCurrent(session)) schedulePollIfNeeded();
    });
    pollPromise = trackedPoll;
    return trackedPoll;
  }

  async function loadRecent(limit = 20) {
    const session = ensureSession();
    assertCurrent(session);
    if (!transport.listRecent) return [];
    const result = await transport.listRecent(limit);
    assertCurrent(session);
    const rawOperations = Array.isArray(result)
      ? result
      : (Array.isArray(result?.sends) ? result.sends : (result?.operations || []));
    for (const raw of rawOperations) {
      const operation = normalizeOutboundSendOperation(raw);
      handleOperation(operation, { announceLifecycle: false });
      // Rehydrate only the still-actionable server deadline. Historical
      // terminal states remain silent when the global monitor mounts.
      if (canUndoOutboundSend(operation, now()) && !isScheduledOutboundSend(operation)) {
        announceUndo(operation, recordFor(operation));
      }
    }
    schedulePollIfNeeded();
    return operations;
  }

  async function loadScheduled(limit = 60) {
    const session = ensureSession();
    assertCurrent(session);
    if (!transport.listScheduled) return [];
    const result = await transport.listScheduled(limit);
    assertCurrent(session);
    const rawOperations = Array.isArray(result) ? result : [];
    for (const raw of rawOperations) {
      handleOperation(normalizeOutboundSendOperation(raw), { announceLifecycle: false });
    }
    schedulePollIfNeeded();
    return rawOperations.map(raw => normalizeOutboundSendOperation(raw));
  }

  async function undo(sendId) {
    const session = ensureSession();
    assertCurrent(session);
    const operation = findOperation(sendId);
    if (!operation || !canUndoOutboundSend(operation, now())) {
      notify('The Undo Send window has closed', 'info');
      return null;
    }
    if (!transport.undo) throw new Error('Undo Send is not available');
    const raw = await transport.undo(operation.send_id);
    assertCurrent(session);
    return handleOperation(
      normalizeOutboundSendOperation(raw, { fallbackKey: operation.idempotency_key }),
      { announceLifecycle: true },
    );
  }

  async function retry(sendId) {
    const session = ensureSession();
    assertCurrent(session);
    const operation = findOperation(sendId);
    if (!operation?.send_id) throw new Error('Send operation is not available to retry');
    if (!operation.can_retry) throw new Error('This email send cannot be retried');
    if (!transport.retry) throw new Error('Email send retry is not available');
    const raw = await transport.retry(operation.send_id);
    assertCurrent(session);
    const next = normalizeOutboundSendOperation(raw, { fallbackKey: operation.idempotency_key });
    if (next.idempotency_key && !records.has(next.idempotency_key)) {
      records.set(next.idempotency_key, {
        callbacks: {},
        session,
        accepted: true,
        lastFingerprint: null,
        undoOffered: false,
      });
    }
    handleOperation(next, { announceLifecycle: false });
    notify('Email send queued to retry', 'success');
    return next;
  }

  async function cancelScheduled(sendId) {
    const session = ensureSession();
    assertCurrent(session);
    const operation = findOperation(sendId);
    if (!operation?.send_id || !operation.can_cancel || !isScheduledOutboundSend(operation)) {
      notify('This scheduled email can no longer be cancelled', 'info');
      return null;
    }
    if (!transport.cancelScheduled) throw new Error('Scheduled-send cancellation is unavailable');
    const raw = await transport.cancelScheduled(operation.send_id);
    assertCurrent(session);
    return handleOperation(
      normalizeOutboundSendOperation(raw, { fallbackKey: operation.idempotency_key }),
      { announceLifecycle: true },
    );
  }

  async function sendScheduledNow(sendId) {
    const session = ensureSession();
    assertCurrent(session);
    const operation = findOperation(sendId);
    if (!operation?.send_id || !operation.can_send_now || !isScheduledOutboundSend(operation)) {
      notify('This scheduled email can no longer be sent early', 'info');
      return null;
    }
    if (!transport.sendScheduledNow) throw new Error('Send now is unavailable');
    const raw = await transport.sendScheduledNow(operation.send_id);
    assertCurrent(session);
    const next = handleOperation(
      normalizeOutboundSendOperation(raw, { fallbackKey: operation.idempotency_key }),
      { announceLifecycle: false },
    );
    notify('Sending scheduled email now', 'info', 4_000);
    return next;
  }

  function getLatestReversible() {
    ensureSession();
    return operations.find(operation => canUndoOutboundSend(operation, now())) || null;
  }

  function resetForCurrentSession() {
    ensureSession();
    return operations;
  }

  function attachCallbacks(operation, callbacks = {}) {
    const session = ensureSession();
    assertCurrent(session);
    if (!operation?.idempotency_key || records.has(operation.idempotency_key)) return false;
    records.set(operation.idempotency_key, {
      callbacks,
      session,
      accepted: Boolean(operation.send_id),
      lastFingerprint: null,
      undoOffered: false,
    });
    return true;
  }

  function destroy() {
    destroyed = true;
    clearPollTimer();
    records.clear();
    announced.clear();
    publish([]);
  }

  return {
    subscribe: stateStore.subscribe,
    submit,
    loadRecent,
    loadScheduled,
    refreshOperation,
    poll,
    undo,
    cancelScheduled,
    sendScheduledNow,
    retry,
    getLatestReversible,
    attachCallbacks,
    resetForCurrentSession,
    destroy,
  };
}

const singletonTransport = {
  create: (payload, idempotencyKey) => api.sendEmail(payload, idempotencyKey),
  listRecent: (limit) => api.listRecentOutboundSends(limit),
  listScheduled: (limit) => api.listScheduledOutboundSends(limit),
  lookupByIdempotency: (idempotencyKey) =>
    api.getOutboundSendByIdempotency(idempotencyKey),
  get: (sendId) => api.getOutboundSend(sendId),
  undo: (sendId) => api.undoOutboundSend(sendId),
  cancelScheduled: (sendId) => api.cancelScheduledOutboundSend(sendId),
  sendScheduledNow: (sendId) => api.sendScheduledOutboundNow(sendId),
  retry: (sendId) => api.retryOutboundSend(sendId),
};

export const outboundSends = createOutboundSendController({ transport: singletonTransport });
export const outboundSendOperations = { subscribe: outboundSends.subscribe };
export const submitOutboundSend = (payload, callbacks = {}) =>
  outboundSends.submit(payload, callbacks);
export const undoLatestOutboundSend = () => {
  const operation = outboundSends.getLatestReversible();
  return operation ? outboundSends.undo(operation.send_id) : Promise.resolve(null);
};
