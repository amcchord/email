import { createDraftSessionController } from './draftSession.js';
import { normalizeFollowUpReminderMode } from './followUpReminders.js';

function positiveInteger(value) {
  const number = Number(value);
  return Number.isSafeInteger(number) && number > 0 ? number : null;
}

export function durableReplyIntent({ accountId, sourceEmailId } = {}) {
  const account = positiveInteger(accountId);
  const source = positiveInteger(sourceEmailId);
  if (!account || !source) throw new TypeError('A verified reply account and source email are required');
  const key = `reply:${account}:${source}`;
  return Object.freeze({ intent_key: key, draft_key: key });
}

export function replyBodyText(bodyHtml = '') {
  return String(bodyHtml || '')
    .replace(/<br\s*\/?>/giu, '\n')
    .replace(/<\/p\s*>/giu, '\n')
    .replace(/<[^>]*>/gu, '')
    .replace(/&nbsp;/giu, ' ')
    .replace(/&amp;/giu, '&')
    .replace(/&lt;/giu, '<')
    .replace(/&gt;/giu, '>')
    .replace(/&quot;/giu, '"')
    .replace(/&#39;/giu, "'")
    .replace(/\n{3,}/gu, '\n\n')
    .trim();
}

export function replyTextHtml(bodyText = '') {
  const escaped = String(bodyText || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
  return escaped ? `<p>${escaped.replaceAll('\n', '<br>')}</p>` : '';
}

export function durableReplySnapshot(envelope = {}, {
  bodyHtml = '',
  bodyText = null,
  followUpReminder = 'default',
  followUpTimeZone = null,
} = {}) {
  const accountId = positiveInteger(envelope.account_id);
  const sourceEmailId = positiveInteger(envelope.source_email_id);
  if (!accountId || !sourceEmailId) {
    throw new TypeError('Durable replies require exact owned source provenance');
  }
  return Object.freeze({
    account_id: accountId,
    to: [...(envelope.to || [])],
    cc: [...(envelope.cc || [])],
    bcc: [...(envelope.bcc || [])],
    subject: String(envelope.subject || ''),
    body_html: String(bodyHtml || ''),
    body_text: bodyText === null ? replyBodyText(bodyHtml) : String(bodyText || ''),
    in_reply_to: envelope.in_reply_to || null,
    references: envelope.references || null,
    thread_id: envelope.thread_id || null,
    source_email_id: sourceEmailId,
    follow_up_reminder: normalizeFollowUpReminderMode(followUpReminder),
    follow_up_time_zone: followUpTimeZone || null,
    attachments: [],
  });
}

function snapshotFromDraftResponse(response = {}) {
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
    follow_up_reminder: normalizeFollowUpReminderMode(response.follow_up_reminder),
    follow_up_time_zone: response.follow_up_time_zone || null,
    attachments: response.attachments || [],
  };
}

function rebaseReplyEnvelope(saved = {}, authoritative = {}) {
  return {
    ...saved,
    account_id: authoritative.account_id,
    to: [...(authoritative.to || [])],
    cc: [...(authoritative.cc || [])],
    bcc: [...(authoritative.bcc || [])],
    subject: String(saved.subject || authoritative.subject || ''),
    in_reply_to: authoritative.in_reply_to || null,
    references: authoritative.references || null,
    thread_id: authoritative.thread_id || null,
    source_email_id: authoritative.source_email_id,
    attachments: [...(saved.attachments || [])],
  };
}

function replyEnvelopeChanged(left = {}, right = {}) {
  const keys = [
    'account_id', 'to', 'cc', 'bcc', 'in_reply_to', 'references',
    'thread_id', 'source_email_id',
  ];
  return keys.some(key => JSON.stringify(left?.[key] ?? null) !== JSON.stringify(right?.[key] ?? null));
}

/**
 * Open one reply writing session across Reader, Flow, and full Compose.
 * Local IndexedDB wins for offline recovery. When it has no record, the exact
 * owned-source lookup discovers the same server UUID on another device.
 */
export function createDurableReplyController({
  userId,
  storage,
  api,
  envelope,
  captureSession,
  isSessionCurrent,
  onAnnouncement,
  onDiscard,
  onUndoDiscard,
  onSendAccepted,
  onSendTerminal,
  controllerFactory = createDraftSessionController,
} = {}) {
  const ownerUserId = String(userId ?? '');
  const intent = durableReplyIntent({
    accountId: envelope?.account_id,
    sourceEmailId: envelope?.source_email_id,
  });
  const controllerApi = { ...api };
  if (typeof api?.saveDraft === 'function') {
    controllerApi.saveDraft = async function saveReplyDraft(payload) {
      try {
        return await api.saveDraft(payload);
      } catch (error) {
        if (
          (error?.code === 'draft_source_exists' || error?.detail?.code === 'draft_source_exists')
          && typeof api?.getComposeDraftBySource === 'function'
        ) {
          try {
            const winner = await api.getComposeDraftBySource(
              envelope.source_email_id,
              envelope.account_id,
            );
            if (winner?.client_draft_id && winner.client_draft_id !== payload.client_draft_id) {
              error.detail = {
                ...(error.detail || {}),
                server_revision: Number(winner.revision || 0),
                server_snapshot: snapshotFromDraftResponse(winner),
                source_client_draft_id: winner.client_draft_id,
                source_server_draft: winner,
              };
            }
          } catch {
            // Preserve the original fail-closed conflict when the exact owned
            // source cannot be resolved safely.
          }
        }
        throw error;
      }
    };
  }
  const controller = controllerFactory({
    userId,
    storage,
    api: controllerApi,
    captureSession,
    isSessionCurrent,
    onAnnouncement,
    onDiscard,
    onUndoDiscard,
    onSendAccepted,
    onSendTerminal,
  });

  function captureOpenSession() {
    const session = typeof captureSession === 'function'
      ? captureSession()
      : { userId: ownerUserId };
    assertOpenSession(session);
    return session;
  }

  function assertOpenSession(session) {
    const sessionOwner = String(session?.userId ?? '');
    const current = typeof isSessionCurrent !== 'function' || isSessionCurrent(session);
    if (!sessionOwner || sessionOwner !== ownerUserId || !current) {
      const error = new Error('Authenticated session changed while opening the reply');
      error.code = 'draft_session_changed';
      throw error;
    }
  }

  async function loadAndRebase(options, initialSnapshot, openSession) {
    assertOpenSession(openSession);
    await controller.load(options);
    assertOpenSession(openSession);
    const state = controller.getState();
    if (
      state.clientDraftId
      && !state.sendInProgress
      && !state.discardInProgress
      && !['conflict', 'discard-pending', 'discarded'].includes(state.status)
    ) {
      const rebased = rebaseReplyEnvelope(state.snapshot, initialSnapshot);
      if (replyEnvelopeChanged(state.snapshot, rebased)) controller.update(rebased);
    }
    return controller.getState();
  }

  async function open(initialSnapshot = durableReplySnapshot(envelope)) {
    const openSession = captureOpenSession();
    const local = await storage.findByIntent(userId, intent.intent_key);
    assertOpenSession(openSession);
    if (local?.client_draft_id) {
      return loadAndRebase({
        clientDraftId: local.client_draft_id,
        intent,
        initialSnapshot,
      }, initialSnapshot, openSession);
    }

    let remote = null;
    if (typeof api?.getComposeDraftBySource === 'function') {
      try {
        remote = await api.getComposeDraftBySource(
          envelope.source_email_id,
          envelope.account_id,
        );
      } catch (error) {
        assertOpenSession(openSession);
        const status = Number(error?.status);
        const unavailable = !Number.isFinite(status) || status >= 500;
        if (error?.status !== 404 && !unavailable) throw error;
      }
    }
    assertOpenSession(openSession);
    return loadAndRebase({
      ...(remote?.client_draft_id ? { clientDraftId: remote.client_draft_id } : {}),
      intent,
      initialSnapshot,
    }, initialSnapshot, openSession);
  }

  return Object.freeze({
    intent,
    controller,
    open,
    snapshot: (bodyHtml, bodyText = null, followUp = {}) => durableReplySnapshot(envelope, {
      bodyHtml,
      bodyText,
      followUpReminder: followUp.followUpReminder,
      followUpTimeZone: followUp.followUpTimeZone,
    }),
    composeData() {
      const state = controller.getState();
      return {
        ...state.snapshot,
        client_draft_id: state.clientDraftId,
        draft_revision: state.revision,
        draft_state: state.status,
        draft_key: `client:${state.clientDraftId}`,
        intent_key: intent.intent_key,
      };
    },
    sendPayload() {
      const state = controller.getState();
      if (!state.clientDraftId || !Number.isSafeInteger(state.revision) || state.revision < 1) {
        throw new Error('Reply draft must be saved before sending');
      }
      return {
        ...state.snapshot,
        attachments: [],
        client_draft_id: state.clientDraftId,
        draft_revision: state.revision,
      };
    },
  });
}
