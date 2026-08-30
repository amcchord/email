import { get, writable } from 'svelte/store';
import { captureAuthEpoch, isAuthEpochCurrent } from './authSession.js';
import { composeData, currentPage } from './stores.js';

const pendingStore = writable([]);
let pendingRecoveries = [];

function publishPendingRecoveries() {
  pendingStore.set(pendingRecoveries.map(({ session: _session, ...recovery }) => recovery));
}

function queuePendingRecovery(draft, session) {
  const recovery = {
    id: draft.draft_key,
    draft,
    recovered_at: new Date().toISOString(),
    session,
  };
  pendingRecoveries = [
    ...pendingRecoveries.filter(existing => existing.id !== recovery.id),
    recovery,
  ].slice(-5);
  publishPendingRecoveries();
}

export const pendingOutboundDraftRecoveries = { subscribe: pendingStore.subscribe };

export function resetOutboundDraftRecoveries() {
  pendingRecoveries = [];
  publishPendingRecoveries();
}

export function openPendingOutboundDraft(recoveryId) {
  if (get(currentPage) === 'compose') return false;
  const recovery = pendingRecoveries.find(candidate => candidate.id === recoveryId);
  if (!recovery || !isAuthEpochCurrent(recovery.session)) {
    pendingRecoveries = pendingRecoveries.filter(candidate => candidate.id !== recoveryId);
    publishPendingRecoveries();
    return false;
  }
  pendingRecoveries = pendingRecoveries.filter(candidate => candidate.id !== recoveryId);
  publishPendingRecoveries();
  composeData.set(recovery.draft);
  currentPage.set('compose');
  return true;
}

function recoveryIdentity(operation) {
  const raw = operation?.send_id || operation?.idempotency_key || 'unknown';
  return String(raw).replace(/[^a-zA-Z0-9._-]/g, '_').slice(0, 128) || 'unknown';
}

export function outboundRecoveryDraft(draft, operation) {
  return {
    ...(draft && typeof draft === 'object' ? draft : {}),
    draft_key: `outbound-recovery:${recoveryIdentity(operation)}`,
  };
}

/**
 * Open a recovered send as its own Compose intent. If another composer is
 * already open, queue the recovery instead of interrupting or overwriting the
 * user's current draft. Every handoff remains scoped to its auth epoch.
 */
export function createOutboundDraftRestorer({
  getPage,
  setPage,
  setDraft,
  captureSession,
  isSessionCurrent,
  queueDraft = () => {},
} = {}) {
  return (draft, operation, reason = 'failed') => {
    const session = captureSession();
    if (!isSessionCurrent(session)) return false;
    const recovered = outboundRecoveryDraft(draft, operation);
    const openRecovered = () => {
      if (!isSessionCurrent(session)) return;
      setDraft(recovered);
      setPage('compose');
    };

    if (getPage() === 'compose' || reason !== 'cancelled') {
      queueDraft(recovered, session);
    } else {
      openRecovered();
    }
    return true;
  };
}

export const restoreOutboundComposeDraft = createOutboundDraftRestorer({
  getPage: () => get(currentPage),
  setPage: page => currentPage.set(page),
  setDraft: draft => composeData.set(draft),
  captureSession: captureAuthEpoch,
  isSessionCurrent: isAuthEpochCurrent,
  queueDraft: queuePendingRecovery,
});
