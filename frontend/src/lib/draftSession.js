import {
  composeDraftHasContent,
  createComposeDraftIntent,
  normalizeComposeDraftUserId,
} from './composeDraft.js';
import {
  cloneDraftValue,
  draftStorageNamespace,
} from './draftStorage.js';

export const DRAFT_SESSION_STATES = Object.freeze([
  'pristine',
  'dirty',
  'local-only',
  'saving',
  'synced',
  'offline',
  'reconciling',
  'failed',
  'conflict',
  'discard-pending',
  'discarded',
]);

const VALID_STATES = new Set(DRAFT_SESSION_STATES);

function defaultRandomUuid() {
  if (typeof globalThis.crypto?.randomUUID === 'function') return globalThis.crypto.randomUUID();
  throw new Error('Secure random UUID generation is unavailable');
}

function defaultTimers() {
  return {
    setTimeout: (callback, delay) => globalThis.setTimeout(callback, delay),
    clearTimeout: timer => globalThis.clearTimeout(timer),
  };
}

function timestamp(now) {
  const value = now();
  return value instanceof Date ? value.toISOString() : new Date(value).toISOString();
}

function errorMessage(error, fallback = 'Draft synchronization failed') {
  return typeof error?.message === 'string' && error.message.trim() ? error.message : fallback;
}

function isNotFound(error) {
  return error?.status === 404 || error?.code === 'draft_not_found';
}

function isConflict(error) {
  return error?.status === 409 || error?.code === 'draft_conflict';
}

function isAmbiguous(error) {
  if (error?.ambiguous === true) return true;
  if (error?.name === 'TypeError' || error?.name === 'TimeoutError') return true;
  if (!Number.isFinite(Number(error?.status))) return true;
  return Number(error.status) >= 500;
}

function serverDraftState(response) {
  return String(response?.state || '').replaceAll('_', '-').toLowerCase();
}

function serverDiscardDeadline(response, fallback) {
  const value = response?.discard_undo_until || response?.discard_at || response?.undo_until
    || response?.execute_after || fallback;
  const parsed = new Date(value || 0);
  return Number.isNaN(parsed.getTime()) ? fallback : parsed.toISOString();
}

function emptyAttachmentGate() {
  return { importing: [], errors: [] };
}

function persistentRecord(record) {
  const { session: _session, ...persistent } = record;
  return persistent;
}

function publicState(record, attachmentGate, sending, announcement = null) {
  if (!record) {
    return Object.freeze({
      status: 'pristine',
      clientDraftId: null,
      revision: 0,
      mutationId: null,
      storageNamespace: null,
      snapshot: {},
      importingAttachments: [],
      attachmentErrors: [],
      canSend: false,
      canUndoDiscard: false,
      sending: false,
      announcement,
    });
  }
  const importing = cloneDraftValue(attachmentGate.importing);
  const errors = cloneDraftValue(attachmentGate.errors);
  const blockedStatus = record.status === 'discard-pending'
    || record.status === 'discarded'
    || record.status === 'conflict';
  return Object.freeze({
    status: record.status,
    clientDraftId: record.client_draft_id,
    revision: record.revision,
    mutationId: record.mutation_id,
    storageNamespace: record.storage_namespace,
    intentKey: record.intent_key,
    snapshot: cloneDraftValue(record.snapshot || {}),
    server: cloneDraftValue(record.server || {}),
    error: cloneDraftValue(record.error || null),
    conflict: cloneDraftValue(record.conflict || null),
    importingAttachments: importing,
    attachmentErrors: errors,
    canSend: !sending && !blockedStatus && importing.length === 0 && errors.length === 0,
    canUndoDiscard: Boolean(record.tombstone)
      && record.status !== 'discarded'
      && record.tombstone.can_undo !== false,
    sending,
    updatedAt: record.updated_at,
    syncedRevision: record.synced_revision || 0,
    announcement,
  });
}

export function draftStatusView(state = {}) {
  const importing = state.importingAttachments || [];
  const attachmentErrors = state.attachmentErrors || [];
  if (attachmentErrors.length > 0) {
    const filename = attachmentErrors[0].filename || 'attachment';
    return {
      message: `Couldn’t add ${filename}`,
      tone: 'error',
      role: 'alert',
      live: 'assertive',
      retry: true,
      undo: false,
      review: false,
    };
  }
  if (importing.length > 0) {
    const count = importing.length;
    return {
      message: `Adding ${count} attachment${count === 1 ? '' : 's'}…`,
      tone: 'neutral',
      role: 'status',
      live: 'polite',
      retry: false,
      undo: false,
      review: false,
    };
  }
  const views = {
    pristine: ['Draft', 'muted', 'status', 'off'],
    dirty: ['Unsaved changes', 'muted', 'status', 'off'],
    'local-only': ['Saved on this device', 'neutral', 'status', 'off'],
    saving: ['Saving draft…', 'neutral', 'status', 'off'],
    synced: [state.server?.account_email ? `Saved to ${state.server.account_email}` : 'Draft saved', 'success', 'status', 'off'],
    offline: ['Saved on this device · will sync when online', 'warning', 'status', 'polite'],
    reconciling: ['Checking draft status… Don’t save again.', 'warning', 'status', 'polite'],
    failed: ['Couldn’t sync draft. Your local copy is safe.', 'error', 'alert', 'assertive'],
    conflict: ['This draft changed elsewhere.', 'warning', 'alert', 'assertive'],
    'discard-pending': ['Draft discarded', 'warning', 'status', 'polite'],
    discarded: ['Draft discarded', 'muted', 'status', 'polite'],
  };
  const [message, tone, role, live] = views[state.status] || views.pristine;
  return {
    message,
    tone,
    role,
    live,
    retry: state.status === 'failed',
    undo: state.status === 'discard-pending' || Boolean(state.canUndoDiscard),
    review: state.status === 'conflict',
  };
}

function recordFromServer(record, response, acknowledgedRevision) {
  const responseClientId = response?.client_draft_id || response?.clientDraftId;
  if (responseClientId && responseClientId !== record.client_draft_id) {
    throw Object.assign(new Error('Draft response identity did not match the active draft'), {
      code: 'draft_identity_mismatch',
    });
  }
  const responseRevision = Number(response?.revision ?? acknowledgedRevision);
  if (!Number.isSafeInteger(responseRevision) || responseRevision < acknowledgedRevision) {
    throw Object.assign(new Error('Draft response revision was stale'), { code: 'draft_stale_response' });
  }
  return {
    draft_id: response?.draft_id ?? response?.server_draft_id ?? record.server?.draft_id ?? null,
    revision: Number(response?.server_revision ?? responseRevision),
    account_email: response?.account_email ?? record.server?.account_email ?? null,
    mutation_id: response?.mutation_id ?? record.mutation_id,
    updated_at: response?.updated_at ?? null,
  };
}

function snapshotFromServerResponse(response = {}) {
  return {
    account_id: response.account_id,
    to: response.to || [],
    cc: response.cc || [],
    bcc: response.bcc || [],
    subject: response.subject || '',
    body_html: response.body_html || '',
    body_text: response.body_text || '',
    in_reply_to: response.in_reply_to || null,
    references: response.references || null,
    thread_id: response.thread_id || null,
    source_email_id: response.source_email_id || null,
    attachments: response.attachments || [],
  };
}

/**
 * Reusable durable draft lifecycle for Compose, Inbox reply, and Flow reply.
 * The server API may be the app API object directly or a small adapter exposing
 * saveDraft, lookupDraft, discardDraft, and undoDiscard.
 */
export function createDraftSession({
  userId,
  storage,
  api = {},
  debounceMs = 650,
  pollMs = 1000,
  discardDelayMs = 5000,
  randomUUID = defaultRandomUuid,
  now = () => Date.now(),
  timers = defaultTimers(),
  isOnline = () => globalThis.navigator?.onLine !== false,
  captureSession = () => null,
  isSessionCurrent = () => true,
  onAnnouncement = () => {},
  onDiscard = () => {},
  onUndoDiscard = () => {},
} = {}) {
  const safeUserId = normalizeComposeDraftUserId(userId);
  if (!safeUserId) throw new TypeError('A valid authenticated user is required');
  if (!storage?.get || !storage?.put) throw new TypeError('A draft storage adapter is required');

  const listeners = new Set();
  let active = null;
  let attachmentGate = emptyAttachmentGate();
  let sending = false;
  let disposed = false;
  let generation = 0;
  let debounceTimer = null;
  let discardTimer = null;
  let pollTimer = null;
  let lastAnnouncementKey = '';
  let latestState = publicState(null, attachmentGate, sending);

  function putRecord(record) {
    return storage.put(persistentRecord(record));
  }

  function currentAuthority(capturedGeneration, capturedSession, draftId = null) {
    return !disposed
      && capturedGeneration === generation
      && isSessionCurrent(capturedSession)
      && (!draftId || active?.client_draft_id === draftId);
  }

  function announceForStatus(status, detail = '') {
    const meaningful = new Set(['offline', 'reconciling', 'failed', 'conflict', 'discard-pending', 'discarded']);
    if (!meaningful.has(status)) return null;
    const key = `${active?.client_draft_id}:${status}:${detail}`;
    if (key === lastAnnouncementKey) return null;
    lastAnnouncementKey = key;
    const announcement = { id: randomUUID(), status, message: draftStatusView({ ...latestState, status }).message };
    onAnnouncement(announcement);
    return announcement;
  }

  function publish(status = active?.status, detail = '') {
    if (active && status && VALID_STATES.has(status)) active.status = status;
    const announcement = active ? announceForStatus(active.status, detail) : null;
    latestState = publicState(active, attachmentGate, sending, announcement);
    for (const listener of listeners) listener(latestState);
    return latestState;
  }

  function clearDebounce() {
    if (debounceTimer !== null) timers.clearTimeout(debounceTimer);
    debounceTimer = null;
  }

  function clearDiscardTimer() {
    if (discardTimer !== null) timers.clearTimeout(discardTimer);
    discardTimer = null;
  }

  function clearPollTimer() {
    if (pollTimer !== null) timers.clearTimeout(pollTimer);
    pollTimer = null;
  }

  function scheduleFlush(delay = debounceMs) {
    clearDebounce();
    const scheduledGeneration = generation;
    const scheduledSession = active?.session;
    const draftId = active?.client_draft_id;
    debounceTimer = timers.setTimeout(() => {
      debounceTimer = null;
      if (!currentAuthority(scheduledGeneration, scheduledSession, draftId)) return;
      void flush();
    }, delay);
  }

  function activate(record, session) {
    clearDebounce();
    clearDiscardTimer();
    clearPollTimer();
    generation += 1;
    active = record;
    active.session = session;
    attachmentGate = emptyAttachmentGate();
    sending = false;
    lastAnnouncementKey = '';
    return generation;
  }

  function baseRecord(intent, snapshot, session) {
    const createdAt = timestamp(now);
    const hasContent = composeDraftHasContent(snapshot);
    return {
      user_id: safeUserId,
      client_draft_id: intent.client_draft_id,
      intent_key: intent.intent_key,
      draft_key: intent.draft_key,
      storage_namespace: draftStorageNamespace(safeUserId, intent.intent_key),
      revision: hasContent ? 1 : 0,
      mutation_id: hasContent ? randomUUID() : null,
      synced_revision: 0,
      status: hasContent ? 'local-only' : 'pristine',
      snapshot: cloneDraftValue(snapshot || {}),
      server: {},
      error: null,
      conflict: null,
      tombstone: null,
      created_at: createdAt,
      updated_at: createdAt,
      session,
    };
  }

  async function create({ intent, initialSnapshot = {} } = {}) {
    if (disposed) throw new Error('Draft session is disposed');
    if (!intent?.intent_key) throw new TypeError('An explicit draft intent key is required');
    const resolvedIntent = createComposeDraftIntent(intent, { randomUUID });
    const session = captureSession();
    const record = baseRecord(resolvedIntent, initialSnapshot, session);
    const createdGeneration = activate(record, session);
    await putRecord(record);
    if (!currentAuthority(createdGeneration, session, record.client_draft_id)) return latestState;
    publish(record.status);
    if (record.revision > 0) scheduleFlush();
    return latestState;
  }

  async function load({ clientDraftId = null, intent = null, initialSnapshot = {} } = {}) {
    if (disposed) throw new Error('Draft session is disposed');
    if (!clientDraftId && !intent?.intent_key) throw new TypeError('Draft ID or explicit intent is required');
    const session = captureSession();
    const loaded = clientDraftId
      ? await storage.get(safeUserId, clientDraftId)
      : await storage.findByIntent?.(safeUserId, intent.intent_key);
    if (!isSessionCurrent(session)) return latestState;
    if (!loaded) return create({ intent: { ...intent, client_draft_id: clientDraftId }, initialSnapshot });

    if (loaded.status === 'saving' || loaded.status === 'reconciling' || loaded.status === 'dirty') {
      loaded.status = isOnline() ? 'local-only' : 'offline';
    }
    const loadedGeneration = activate(loaded, session);
    publish(loaded.status);
    if (loaded.status === 'discard-pending') {
      const remaining = new Date(loaded.tombstone?.deadline || 0).getTime() - new Date(now()).getTime();
      if (remaining > 0) armDiscard(remaining);
      else void reconcileDiscard(loadedGeneration, session, loaded.client_draft_id);
    } else if (loaded.status === 'local-only' || loaded.status === 'offline') {
      if (isOnline()) scheduleFlush(0);
    }
    return latestState;
  }

  function update(snapshot) {
    if (!active || disposed) throw new Error('No active draft');
    if (active.status === 'discard-pending' || active.status === 'discarded') {
      throw new Error('Discarded draft cannot be edited');
    }
    active.snapshot = cloneDraftValue(snapshot || {});
    active.revision += 1;
    active.mutation_id = randomUUID();
    active.updated_at = timestamp(now);
    active.error = null;
    if (active.status !== 'conflict') active.conflict = null;
    publish(active.status === 'conflict' ? 'conflict' : 'dirty');
    scheduleFlush();
    return latestState;
  }

  function beginAttachmentImport({ id = randomUUID(), filename = 'attachment' } = {}) {
    if (!active) throw new Error('No active draft');
    attachmentGate.importing = [
      ...attachmentGate.importing.filter(item => item.id !== id),
      { id, filename },
    ];
    attachmentGate.errors = attachmentGate.errors.filter(item => item.id !== id);
    publish();
    return id;
  }

  function completeAttachmentImport(id, attachment) {
    if (!active) throw new Error('No active draft');
    attachmentGate.importing = attachmentGate.importing.filter(item => item.id !== id);
    attachmentGate.errors = attachmentGate.errors.filter(item => item.id !== id);
    const snapshot = cloneDraftValue(active.snapshot || {});
    snapshot.attachments = [...(snapshot.attachments || []), cloneDraftValue(attachment)];
    return update(snapshot);
  }

  function failAttachmentImport(id, error, filename = 'attachment') {
    if (!active) throw new Error('No active draft');
    const importing = attachmentGate.importing.find(item => item.id === id);
    attachmentGate.importing = attachmentGate.importing.filter(item => item.id !== id);
    attachmentGate.errors = [
      ...attachmentGate.errors.filter(item => item.id !== id),
      { id, filename: importing?.filename || filename, message: errorMessage(error, 'Attachment import failed') },
    ];
    publish();
    return latestState;
  }

  function clearAttachmentError(id) {
    attachmentGate.errors = attachmentGate.errors.filter(item => item.id !== id);
    publish();
    return latestState;
  }

  async function callLookup(record) {
    if (typeof api.lookupDraft === 'function') {
      return api.lookupDraft({
        clientDraftId: record.client_draft_id,
        mutationId: record.mutation_id,
        revision: record.revision,
      });
    }
    if (typeof api.getComposeDraft === 'function') return api.getComposeDraft(record.client_draft_id);
    return null;
  }

  function scheduleRefresh(delay = pollMs) {
    clearPollTimer();
    const capturedGeneration = generation;
    const capturedSession = active?.session;
    const draftId = active?.client_draft_id;
    pollTimer = timers.setTimeout(() => {
      pollTimer = null;
      if (!currentAuthority(capturedGeneration, capturedSession, draftId)) return;
      void refresh();
    }, delay);
  }

  async function applyAck(response, request, capturedGeneration, capturedSession) {
    if (disposed || !isSessionCurrent(capturedSession)) return;
    const stored = await storage.get(safeUserId, request.clientDraftId);
    if (!stored || stored.status === 'discarded') return;
    const activeIsSame = currentAuthority(capturedGeneration, capturedSession, request.clientDraftId);
    const next = activeIsSame && active.revision > stored.revision
      ? persistentRecord(cloneDraftValue(active))
      : stored;
    const server = recordFromServer(next, response, request.revision);
    const responseState = serverDraftState(response) || 'synced';
    server.state = responseState;
    next.server = server;
    if (responseState === 'synced') {
      next.synced_revision = Math.max(next.synced_revision || 0, request.revision);
    }
    next.error = null;
    next.conflict = null;
    if (next.revision !== request.revision) next.status = 'local-only';
    else if (responseState === 'synced') next.status = 'synced';
    else if (responseState === 'reconciling') next.status = 'reconciling';
    else if (responseState === 'failed') {
      next.status = 'failed';
      next.error = {
        phase: 'server',
        message: response?.error_message || 'Draft synchronization failed',
        retryable: response?.can_retry !== false,
      };
    } else if (responseState === 'discard-pending') next.status = 'discard-pending';
    else if (responseState === 'discarded') next.status = 'discarded';
    else next.status = 'saving';
    next.updated_at = timestamp(now);
    await putRecord(next);

    if (!currentAuthority(capturedGeneration, capturedSession, request.clientDraftId)) return;
    active.server = server;
    active.synced_revision = next.synced_revision;
    active.error = null;
    active.conflict = null;
    if (active.revision !== request.revision) {
      publish('local-only');
      scheduleFlush(0);
    } else if (responseState === 'synced') {
      publish('synced', String(request.revision));
    } else if (responseState === 'failed') {
      active.error = next.error;
      publish('failed', String(request.revision));
    } else if (responseState === 'reconciling') {
      publish('reconciling', String(request.revision));
      scheduleRefresh();
    } else if (responseState === 'discard-pending' || responseState === 'discarded') {
      await applyDiscardResponse(response, capturedGeneration, capturedSession, request.clientDraftId);
    } else {
      publish('saving');
      scheduleRefresh();
    }
  }

  async function applyConflict(error, request, capturedGeneration, capturedSession) {
    if (disposed || !isSessionCurrent(capturedSession)) return;
    const conflict = cloneDraftValue(error?.detail || error?.conflict || {
      message: errorMessage(error, 'Draft changed elsewhere'),
    });
    const stored = await storage.get(safeUserId, request.clientDraftId);
    if (stored) {
      stored.status = 'conflict';
      stored.conflict = conflict;
      stored.error = null;
      await putRecord(stored);
    }
    if (!currentAuthority(capturedGeneration, capturedSession, request.clientDraftId)) return;
    active.conflict = conflict;
    active.error = null;
    publish('conflict', String(request.revision));
  }

  async function syncActive(capturedGeneration, capturedSession, request) {
    const payload = {
      client_draft_id: request.clientDraftId,
      intent_key: request.intentKey,
      revision: request.revision,
      mutation_id: request.mutationId,
      server_draft_id: request.serverDraftId,
      server_revision: request.serverRevision,
      ...cloneDraftValue(request.snapshot),
    };
    try {
      const response = await api.saveDraft(payload);
      await applyAck(response || {}, request, capturedGeneration, capturedSession);
    } catch (error) {
      if (isConflict(error)) {
        try {
          const found = await callLookup({
            client_draft_id: request.clientDraftId,
            mutation_id: request.mutationId,
            revision: request.revision,
          });
          if (found && Number(found.revision || 0) >= request.revision) {
            error.detail = {
              server_revision: Number(found.revision),
              server_snapshot: snapshotFromServerResponse(found),
            };
          }
        } catch {
          // The local version remains authoritative in the conflict UI when
          // the provider-side detail cannot be fetched safely.
        }
        await applyConflict(error, request, capturedGeneration, capturedSession);
        return;
      }
      if (!isAmbiguous(error)) {
        if (!currentAuthority(capturedGeneration, capturedSession, request.clientDraftId)) return;
        active.error = { phase: 'server', message: errorMessage(error), retryable: true };
        await putRecord({ ...active, status: 'failed' });
        publish('failed', String(request.revision));
        return;
      }

      if (currentAuthority(capturedGeneration, capturedSession, request.clientDraftId)) {
        publish('reconciling', String(request.revision));
      }
      try {
        const found = await callLookup({
          client_draft_id: request.clientDraftId,
          mutation_id: request.mutationId,
          revision: request.revision,
        });
        const foundMutation = found?.mutation_id ?? found?.mutationId;
        const foundRevision = Number(found?.revision || 0);
        if (found && (foundMutation === request.mutationId || foundRevision >= request.revision)) {
          await applyAck(found, request, capturedGeneration, capturedSession);
          return;
        }
      } catch (lookupError) {
        if (!isNotFound(lookupError) && !isAmbiguous(lookupError)) error = lookupError;
      }
      if (!currentAuthority(capturedGeneration, capturedSession, request.clientDraftId)) return;
      active.error = {
        phase: 'reconcile',
        message: errorMessage(error, 'Draft status could not be confirmed'),
        retryable: true,
      };
      await putRecord({ ...active, status: 'failed' });
      publish('failed', String(request.revision));
    }
  }

  async function flush() {
    if (!active || disposed) return latestState;
    clearDebounce();
    if (active.status === 'discard-pending' || active.status === 'discarded' || active.status === 'conflict') {
      return latestState;
    }
    const capturedGeneration = generation;
    const capturedSession = active.session;
    const draftId = active.client_draft_id;
    try {
      if (!currentAuthority(capturedGeneration, capturedSession, draftId)) return latestState;
      if (!composeDraftHasContent(active.snapshot)) {
        active.status = 'pristine';
        await putRecord(active);
        if (currentAuthority(capturedGeneration, capturedSession, draftId)) publish('pristine');
        return latestState;
      }
      active.status = 'local-only';
      await putRecord(active);
    } catch (error) {
      if (!currentAuthority(capturedGeneration, capturedSession, draftId)) return latestState;
      active.error = { phase: 'local', message: errorMessage(error, 'Local draft storage failed'), retryable: true };
      publish('failed', String(active.revision));
      return latestState;
    }
    if (!currentAuthority(capturedGeneration, capturedSession, draftId)) return latestState;
    if (!isOnline()) {
      active.status = 'offline';
      await putRecord(active);
      publish('offline', String(active.revision));
      return latestState;
    }
    if (typeof api.saveDraft !== 'function') {
      publish('local-only');
      return latestState;
    }

    const request = {
      clientDraftId: active.client_draft_id,
      intentKey: active.intent_key,
      revision: active.revision,
      mutationId: active.mutation_id,
      snapshot: cloneDraftValue(active.snapshot),
      serverDraftId: active.server?.draft_id || null,
      serverRevision: active.server?.revision || 0,
    };
    publish('saving');
    await syncActive(capturedGeneration, capturedSession, request);
    return latestState;
  }

  async function refresh() {
    if (!active || disposed) return latestState;
    const capturedGeneration = generation;
    const capturedSession = active.session;
    const draftId = active.client_draft_id;
    try {
      const response = await callLookup(active);
      if (!response || !currentAuthority(capturedGeneration, capturedSession, draftId)) return latestState;
      const responseRevision = Number(response.revision || 0);
      const responseMutation = response.mutation_id || response.mutationId;
      if (
        responseRevision > active.revision
        || (responseRevision === active.revision && responseMutation && responseMutation !== active.mutation_id)
      ) {
        const conflictError = new Error('Draft changed elsewhere');
        conflictError.status = 409;
        conflictError.detail = {
          server_revision: responseRevision,
          server_snapshot: snapshotFromServerResponse(response),
        };
        await applyConflict(conflictError, {
          clientDraftId: draftId,
          revision: active.revision,
        }, capturedGeneration, capturedSession);
        return latestState;
      }
      const request = {
        clientDraftId: draftId,
        intentKey: active.intent_key,
        revision: Math.min(Number(response.revision || active.revision), active.revision),
        mutationId: response.mutation_id || active.mutation_id,
        snapshot: cloneDraftValue(active.snapshot),
        serverDraftId: active.server?.draft_id || null,
        serverRevision: active.server?.revision || 0,
      };
      await applyAck(response, request, capturedGeneration, capturedSession);
    } catch (error) {
      if (!currentAuthority(capturedGeneration, capturedSession, draftId)) return latestState;
      if (isNotFound(error) || isAmbiguous(error)) {
        publish('reconciling', String(active.revision));
        scheduleRefresh();
      } else {
        active.error = { phase: 'refresh', message: errorMessage(error), retryable: true };
        await putRecord({ ...active, status: 'failed' });
        publish('failed', String(active.revision));
      }
    }
    return latestState;
  }

  async function retry() {
    if (!active || (active.status !== 'failed' && active.status !== 'offline')) return latestState;
    if (active.tombstone && String(active.error?.phase || '').includes('discard')) {
      const capturedGeneration = generation;
      const capturedSession = active.session;
      const draftId = active.client_draft_id;
      publish('reconciling', `discard:${active.tombstone.mutation_id || ''}`);
      try {
        if (active.tombstone.server_pending || active.tombstone.server_outcome_unknown) {
          return reconcileDiscard(capturedGeneration, capturedSession, draftId);
        }
        const response = await callDiscard(draftId, active.tombstone.mutation_id);
        return applyDiscardResponse(response, capturedGeneration, capturedSession, draftId);
      } catch (error) {
        if (!currentAuthority(capturedGeneration, capturedSession, draftId)) return latestState;
        active.error = { phase: 'discard', message: errorMessage(error), retryable: true };
        await putRecord({ ...active, status: 'failed' });
        publish('failed', `discard:${active.tombstone.mutation_id || ''}`);
        return latestState;
      }
    }
    active.error = null;
    publish('local-only');
    return flush();
  }

  async function resolveConflict(choice) {
    if (!active || active.status !== 'conflict') return latestState;
    if (choice === 'server') {
      const serverSnapshot = active.conflict?.server_snapshot;
      if (!serverSnapshot) throw new Error('Server draft content is unavailable');
      active.snapshot = cloneDraftValue(serverSnapshot);
      active.revision = Math.max(active.revision, Number(active.conflict?.server_revision || 0));
    } else if (choice !== 'local') {
      throw new TypeError('Conflict choice must be local or server');
    }
    active.revision += 1;
    active.mutation_id = randomUUID();
    active.conflict = null;
    active.error = null;
    publish('dirty');
    return flush();
  }

  function armDiscard(delay) {
    clearDiscardTimer();
    const capturedGeneration = generation;
    const capturedSession = active.session;
    const draftId = active.client_draft_id;
    discardTimer = timers.setTimeout(() => {
      discardTimer = null;
      void reconcileDiscard(capturedGeneration, capturedSession, draftId);
    }, Math.max(0, delay));
  }

  async function applyDiscardResponse(response, capturedGeneration, capturedSession, draftId) {
    if (!currentAuthority(capturedGeneration, capturedSession, draftId)) return latestState;
    const responseState = serverDraftState(response);
    if (responseState === 'discarded') {
      return finalizeAuthoritativeDiscard(response, capturedGeneration, capturedSession, draftId);
    }
    if (responseState !== 'discard-pending') {
      if (['pending', 'syncing', 'reconciling', 'synced'].includes(responseState)) {
        return restoreDiscardAfterUndo(response, capturedGeneration, capturedSession, draftId);
      }
      throw new Error(`Unexpected discard state: ${responseState || 'missing'}`);
    }
    const fallbackDeadline = active.tombstone?.deadline
      || new Date(new Date(now()).getTime() + discardDelayMs).toISOString();
    const deadline = serverDiscardDeadline(response, fallbackDeadline);
    active.tombstone = {
      ...(active.tombstone || {}),
      deadline,
      server_pending: true,
      can_undo: response.can_undo_discard !== false,
      mutation_id: response.mutation_id || active.mutation_id,
    };
    active.server = {
      ...(active.server || {}),
      state: responseState,
      revision: Number(response.synced_revision || response.revision || active.server?.revision || 0),
    };
    active.error = null;
    await putRecord({ ...active, status: 'discard-pending' });
    if (!currentAuthority(capturedGeneration, capturedSession, draftId)) return latestState;
    publish('discard-pending', deadline);
    const remaining = new Date(deadline).getTime() - new Date(now()).getTime();
    armDiscard(Math.max(0, remaining));
    return latestState;
  }

  async function callDiscard(draftId, mutationId) {
    if (typeof api.discardDraft === 'function') {
      return api.discardDraft({ clientDraftId: draftId, mutationId });
    }
    if (typeof api.discardComposeDraft === 'function') {
      return api.discardComposeDraft(draftId, mutationId);
    }
    return null;
  }

  async function discard({ delayMs = discardDelayMs } = {}) {
    if (!active || active.status === 'discarded') return latestState;
    clearDebounce();
    clearPollTimer();
    const capturedGeneration = generation;
    const capturedSession = active.session;
    const draftId = active.client_draft_id;
    const mutationId = randomUUID();
    const deadline = new Date(new Date(now()).getTime() + Math.max(0, delayMs)).toISOString();
    const priorStatus = active.status;
    active.revision += 1;
    active.mutation_id = mutationId;
    active.tombstone = {
      deadline,
      prior_status: priorStatus,
      requested_at: timestamp(now),
      can_undo: true,
      server_pending: false,
      mutation_id: mutationId,
    };
    active.status = 'discard-pending';
    active.updated_at = timestamp(now);
    await putRecord(active);
    publish('discard-pending', deadline);
    try {
      const response = await callDiscard(draftId, mutationId);
      if (!response) {
        // A purely local draft has no provider mutation to confirm.
        armDiscard(delayMs);
        return latestState;
      }
      await applyDiscardResponse(response, capturedGeneration, capturedSession, draftId);
    } catch (error) {
      if (!currentAuthority(capturedGeneration, capturedSession, draftId)) return latestState;
      if (isAmbiguous(error)) {
        active.tombstone.server_outcome_unknown = true;
        await putRecord(active);
        publish('reconciling', `discard:${mutationId}`);
        await reconcileDiscard(capturedGeneration, capturedSession, draftId);
      } else {
        active.error = { phase: 'discard', message: errorMessage(error), retryable: true };
        await putRecord({ ...active, status: 'failed' });
        publish('failed', `discard:${mutationId}`);
      }
    }
    return latestState;
  }

  async function reconcileDiscard(
    capturedGeneration = generation,
    capturedSession = active?.session,
    draftId = active?.client_draft_id,
  ) {
    if (!active || !currentAuthority(capturedGeneration, capturedSession, draftId)) return latestState;
    if (!active.tombstone?.server_pending && typeof api.getComposeDraft !== 'function' && typeof api.lookupDraft !== 'function') {
      return finalizeAuthoritativeDiscard(
        { state: 'discarded', discarded_at: timestamp(now), local_only: true },
        capturedGeneration,
        capturedSession,
        draftId,
      );
    }
    publish('reconciling', `discard:${active.tombstone?.mutation_id || ''}`);
    try {
      const response = await callLookup(active);
      if (!response) throw new Error('Draft discard status is unavailable');
      return applyDiscardResponse(response, capturedGeneration, capturedSession, draftId);
    } catch (error) {
      if (!currentAuthority(capturedGeneration, capturedSession, draftId)) return latestState;
      active.error = {
        phase: 'discard-reconcile',
        message: errorMessage(error, 'Draft discard status could not be confirmed'),
        retryable: true,
      };
      await putRecord({ ...active, status: 'failed' });
      publish('failed', `discard:${active.tombstone?.mutation_id || ''}`);
      return latestState;
    }
  }

  async function finalizeAuthoritativeDiscard(
    response,
    capturedGeneration = generation,
    capturedSession = active?.session,
    draftId = active?.client_draft_id,
  ) {
    if (!active || !currentAuthority(capturedGeneration, capturedSession, draftId)) return latestState;
    clearDiscardTimer();
    const discardedSnapshot = cloneDraftValue(active.snapshot);
    active.status = 'discarded';
    active.snapshot = {};
    active.tombstone = {
      ...(active.tombstone || {}),
      can_undo: false,
      finalized_at: response?.discarded_at || timestamp(now),
    };
    active.server = { ...(active.server || {}), state: 'discarded' };
    active.error = null;
    active.updated_at = timestamp(now);
    await putRecord(active);
    publish('discarded', active.mutation_id);
    onDiscard({ clientDraftId: draftId, snapshot: discardedSnapshot });
    return latestState;
  }

  async function restoreDiscardAfterUndo(response, capturedGeneration, capturedSession, draftId) {
    if (!currentAuthority(capturedGeneration, capturedSession, draftId)) return false;
    clearDiscardTimer();
    const restoredStatus = active.tombstone?.prior_status === 'synced' ? 'synced' : 'local-only';
    active.tombstone = null;
    const responseState = serverDraftState(response);
    active.server = {
      ...(active.server || {}),
      state: responseState || active.server?.state,
      revision: Number(response?.synced_revision || response?.revision || active.server?.revision || 0),
    };
    active.status = !isOnline()
      ? 'offline'
      : (responseState === 'synced' ? 'synced' : restoredStatus);
    active.error = null;
    active.updated_at = timestamp(now);
    await putRecord(active);
    publish(active.status, `undo:${active.revision}`);
    onUndoDiscard({ clientDraftId: active.client_draft_id, snapshot: cloneDraftValue(active.snapshot) });
    return true;
  }

  async function undoDiscard() {
    if (!active || !active.tombstone || active.status === 'discarded') return false;
    const capturedGeneration = generation;
    const capturedSession = active.session;
    const draftId = active.client_draft_id;
    const mutationId = randomUUID();
    if (!active.tombstone.server_pending && !active.tombstone.server_outcome_unknown) {
      return restoreDiscardAfterUndo({}, capturedGeneration, capturedSession, draftId);
    }
    publish('reconciling', `undo:${mutationId}`);
    try {
      let response = null;
      if (typeof api.undoDiscard === 'function') {
        response = await api.undoDiscard({ clientDraftId: draftId, mutationId });
      } else if (typeof api.undoComposeDraftDiscard === 'function') {
        response = await api.undoComposeDraftDiscard(draftId, mutationId);
      }
      if (!response) throw new Error('Draft discard Undo is unavailable');
      if (serverDraftState(response) === 'discarded') {
        await finalizeAuthoritativeDiscard(response, capturedGeneration, capturedSession, draftId);
        return false;
      }
      return restoreDiscardAfterUndo(response, capturedGeneration, capturedSession, draftId);
    } catch (error) {
      if (!currentAuthority(capturedGeneration, capturedSession, draftId)) return false;
      if (isAmbiguous(error) || error?.status === 409) {
        await reconcileDiscard(capturedGeneration, capturedSession, draftId);
      } else {
        active.error = { phase: 'undo-discard', message: errorMessage(error), retryable: true };
        await putRecord({ ...active, status: 'failed' });
        publish('failed', `undo:${mutationId}`);
      }
      return false;
    }
  }

  async function markSending(value = true) {
    if (!active) return latestState;
    if (value) await flush();
    sending = Boolean(value);
    publish();
    return latestState;
  }

  function handleOnlineChange() {
    if (!active || disposed) return;
    if (isOnline() && (active.status === 'offline' || active.status === 'failed')) void retry();
    else if (!isOnline() && active.status !== 'discard-pending' && active.status !== 'discarded') {
      publish('offline', String(active.revision));
    }
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    generation += 1;
    clearDebounce();
    clearDiscardTimer();
    clearPollTimer();
    listeners.clear();
  }

  return Object.freeze({
    subscribe(listener) {
      listeners.add(listener);
      listener(latestState);
      return () => listeners.delete(listener);
    },
    getState: () => latestState,
    get clientDraftId() { return active?.client_draft_id || null; },
    get revision() { return active?.revision || 0; },
    get storageNamespace() { return active?.storage_namespace || null; },
    create,
    load,
    update,
    flush,
    refresh,
    retry,
    resolveConflict,
    beginAttachmentImport,
    completeAttachmentImport,
    failAttachmentImport,
    clearAttachmentError,
    discard,
    undoDiscard,
    markSending,
    handleOnlineChange,
    dispose,
  });
}

export const createDraftSessionController = createDraftSession;
