<script>
  import { onMount, tick } from 'svelte';
  import { get } from 'svelte/store';
  import { api } from '../lib/api.js';
  import { submitOutboundSend } from '../lib/outboundSend.js';
  import {
    outboundRecoveryDraft,
    restoreOutboundComposeDraft,
  } from '../lib/outboundDraftRecovery.js';
  import {
    accounts,
    captureAuthenticatedSession,
    composeData,
    createAuthenticatedSessionGuard,
    currentPage,
    isAuthenticatedSessionCurrent,
    selectedAccountId as globalSelectedAccountId,
    showToast,
  } from '../lib/stores.js';
  import { registerActions } from '../lib/shortcutStore.js';
  import {
    composeLastAccountStorageKey,
    composeReplyContext,
    createComposeDraftIntent,
    ensureComposeDraftIntent,
    isComposeDraftUuid,
    knownServerRevisionRequiresRefresh,
    newComposeIntent,
  } from '../lib/composeDraft.js';
  import {
    createIndexedDbDraftStorage,
    migrateLegacyScopedDrafts,
  } from '../lib/draftStorage.js';
  import { createDraftSessionController } from '../lib/draftSession.js';
  import Button from '../components/common/Button.svelte';
  import Icon from '../components/common/Icon.svelte';
  import DeferredRichEditor from '../components/email/DeferredRichEditor.svelte';
  import DraftStatus from '../components/email/DraftStatus.svelte';
  import SendSplitButton from '../components/common/SendSplitButton.svelte';
  import SnippetPicker from '../components/email/SnippetPicker.svelte';
  import {
    exactSourceEmailId,
    sendArchiveAcceptedMessage,
    withArchiveAfterSend,
  } from '../lib/sendArchive.js';

  let to = $state('');
  let cc = $state('');
  let bcc = $state('');
  let subject = $state('');
  let bodyHtml = $state('');
  let showCcBcc = $state(false);
  let sending = $state(false);
  let sendMode = $state('send');
  let selectedAccountId = $state(null);
  let accountList = $state([]);
  let initialContent = $state('');
  let attachments = $state([]);
  let autosaveStatus = $state('');
  let autosaveReady = $state(false);
  let fileInput = $state(null);
  let writingSurfaceReady = $state(false);
  let editorHandle = $state.raw(null);
  let snippetPickerOpen = $state(false);
  let savingDraft = $state(false);
  let conflictDialogOpen = $state(false);
  let conflictDialog = $state(null);
  let conflictCancelButton = $state(null);
  let conflictFallbackFocus = $state(null);
  let conflictTrigger = null;
  let activeDraftKey = $state(null);
  let draftState = $state({ status: 'pristine', canSend: false, snapshot: {} });
  let draftController = $state.raw(null);
  let durableStorage = null;
  let unsubscribeDraft = null;
  let lastPersistedFingerprint = '';
  let openingDraftGeneration = 0;
  let editorRevision = $state(0);
  let replyContext = $state({ in_reply_to: null, references: null, thread_id: null, source_email_id: null });
  let suppressLocalPersistence = false;
  let sessionGuard = null;

  let senderAccount = $derived(accountList.find(account => account.id === Number(selectedAccountId)) || null);
  let archiveSourceEmailId = $derived(exactSourceEmailId(replyContext.source_email_id));
  let recipientChips = $derived(parseRecipients(to));
  let totalAttachmentBytes = $derived(attachments.reduce((sum, item) => sum + item.size, 0));
  let draftLocked = $derived(
    sending
    || draftState.status === 'discard-pending'
    || draftState.status === 'discarded'
    || draftState.status === 'conflict'
    || draftState.sending
    || draftState.discardInProgress
    || draftState.sendInProgress,
  );

  function parseRecipients(value) {
    return (value || '').split(/[;,]/).map(item => item.trim()).filter(Boolean);
  }

  function recipientFieldValue(value) {
    return Array.isArray(value) ? value.join(', ') : String(value || '');
  }

  function chooseSender(list, contextAccountId = null) {
    if (!list.length) return null;
    const lastAccountKey = composeLastAccountStorageKey(sessionGuard?.userId);
    const savedId = Number(lastAccountKey ? localStorage.getItem(lastAccountKey) : null);
    const preferredId = contextAccountId || get(globalSelectedAccountId) || savedId;
    return list.find(account => account.id === Number(preferredId))?.id
      || list.find(account => /primary/i.test(account.description || ''))?.id
      || list.find(account => account.email.endsWith('@mcchord.net'))?.id
      || list[0].id;
  }

  function draftSnapshot() {
    return {
      account_id: Number(selectedAccountId) || null,
      to: parseRecipients(to),
      cc: parseRecipients(cc),
      bcc: parseRecipients(bcc),
      subject,
      body_html: bodyHtml,
      body_text: bodyHtml.replace(/<[^>]*>/g, ''),
      is_draft: true,
      attachments: attachments.map(item => ({ ...item })),
      in_reply_to: replyContext.in_reply_to,
      references: replyContext.references,
      thread_id: replyContext.thread_id,
      source_email_id: replyContext.source_email_id,
    };
  }

  function draftFingerprint(draft) {
    if (!draft || typeof draft !== 'object') return null;
    return JSON.stringify(draft);
  }

  function persistLocalDraft(draft = draftSnapshot()) {
    if (
      suppressLocalPersistence
      || !draftController
      || !autosaveReady
      || draftLocked
      || !sessionGuard?.isCurrent()
    ) return;
    const fingerprint = draftFingerprint(draft);
    if (!fingerprint || fingerprint === lastPersistedFingerprint) return;
    try {
      draftController.update(draft);
      lastPersistedFingerprint = fingerprint;
    } catch (error) {
      autosaveStatus = error?.message || 'Local autosave unavailable';
    }
  }

  function normalizeDraftAttachment(item = {}) {
    return {
      ...(item.attachment_id ? { attachment_id: item.attachment_id } : {}),
      filename: item.filename || 'attachment',
      content_type: item.content_type || 'application/octet-stream',
      data_base64: item.data_base64 || '',
      size: Number(item.size ?? item.size_bytes) || 0,
    };
  }

  function hydrateDraftSnapshot(draft = {}) {
    suppressLocalPersistence = true;
    to = recipientFieldValue(draft.to);
    cc = recipientFieldValue(draft.cc);
    bcc = recipientFieldValue(draft.bcc);
    subject = draft.subject || '';
    bodyHtml = draft.body_html || '';
    initialContent = bodyHtml;
    attachments = Array.isArray(draft.attachments)
      ? draft.attachments.map(normalizeDraftAttachment)
      : [];
    if (Number.isSafeInteger(Number(draft.account_id)) && Number(draft.account_id) > 0) {
      selectedAccountId = Number(draft.account_id);
    }
    replyContext = composeReplyContext(draft);
    showCcBcc = Boolean(cc || bcc);
    lastPersistedFingerprint = draftFingerprint(draftSnapshot());
    editorRevision += 1;
    queueMicrotask(() => { suppressLocalPersistence = false; });
  }

  async function seedServerDraftIfNeeded(intent, data, requestGeneration) {
    if (!data?.draft_revision || !data?.client_draft_id) return;
    if (requestGeneration !== openingDraftGeneration || !sessionGuard?.isCurrent()) return false;
    const existing = await durableStorage.get(sessionGuard.userId, intent.client_draft_id);
    if (requestGeneration !== openingDraftGeneration || !sessionGuard?.isCurrent()) return false;
    if (existing) return true;
    const snapshot = {
      ...draftSnapshot(),
      account_id: Number(data.account_id),
      to: Array.isArray(data.to) ? data.to : parseRecipients(data.to),
      cc: Array.isArray(data.cc) ? data.cc : parseRecipients(data.cc),
      bcc: Array.isArray(data.bcc) ? data.bcc : parseRecipients(data.bcc),
      subject: data.subject || '',
      body_html: data.body_html || '',
      body_text: data.body_text || '',
      attachments: (data.attachments || []).map(normalizeDraftAttachment),
      ...composeReplyContext(data),
    };
    const now = new Date().toISOString();
    if (requestGeneration !== openingDraftGeneration || !sessionGuard?.isCurrent()) return false;
    await durableStorage.put({
      user_id: sessionGuard.userId,
      client_draft_id: intent.client_draft_id,
      intent_key: intent.intent_key,
      draft_key: intent.draft_key,
      revision: Number(data.draft_revision),
      mutation_id: crypto.randomUUID(),
      synced_revision: Number(data.synced_revision || data.draft_revision),
      status: data.draft_state === 'synced' ? 'synced' : 'local-only',
      snapshot,
      server: { state: data.draft_state || 'synced', revision: Number(data.synced_revision || data.draft_revision) },
      error: null,
      conflict: null,
      tombstone: null,
      created_at: data.created_at || now,
      updated_at: data.updated_at || now,
    });
    return requestGeneration === openingDraftGeneration && sessionGuard?.isCurrent();
  }

  async function openDraftIntent(data = {}) {
    if (!sessionGuard?.isCurrent() || !durableStorage) return;
    const requestGeneration = ++openingDraftGeneration;
    const suppliedClientId = data?.client_draft_id || null;
    const recoverySourceClientId = isComposeDraftUuid(data?.recovery_source_client_draft_id)
      ? data.recovery_source_client_draft_id.toLowerCase()
      : null;
    const intent = ensureComposeDraftIntent(data);
    if (activeDraftKey === intent.client_draft_id && draftController) return;

    if (draftController) {
      persistLocalDraft();
      await draftController.flush();
      draftController.dispose();
      unsubscribeDraft?.();
    }
    autosaveReady = false;
    writingSurfaceReady = false;
    editorHandle = null;
    if (requestGeneration !== openingDraftGeneration || !sessionGuard.isCurrent()) return;

    hydrateDraftSnapshot(data);
    const seedCurrent = await seedServerDraftIfNeeded(intent, data, requestGeneration);
    if (seedCurrent === false || requestGeneration !== openingDraftGeneration || !sessionGuard.isCurrent()) return;
    draftController = createDraftSessionController({
      userId: sessionGuard.userId,
      storage: durableStorage,
      api,
      discardDelayMs: 10000,
      captureSession: captureAuthenticatedSession,
      isSessionCurrent: isAuthenticatedSessionCurrent,
      onDiscard: () => {
        if (!sessionGuard?.isCurrent()) return;
        suppressLocalPersistence = true;
        composeData.set(null);
        currentPage.set('inbox');
      },
      onSendAccepted: () => {
        if (requestGeneration !== openingDraftGeneration || !sessionGuard?.isCurrent()) return;
        suppressLocalPersistence = true;
        composeData.set(null);
        currentPage.set('inbox');
      },
      onSendTerminal: ({ snapshot, operation }) => {
        if (requestGeneration !== openingDraftGeneration || !sessionGuard?.isCurrent()) return;
        const priorDraftId = draftController?.clientDraftId;
        suppressLocalPersistence = true;
        composeData.set(outboundRecoveryDraft(snapshot, operation));
        if (priorDraftId) void durableStorage?.delete(sessionGuard.userId, priorDraftId);
      },
    });
    unsubscribeDraft = draftController.subscribe(state => {
      if (requestGeneration !== openingDraftGeneration || !sessionGuard?.isCurrent()) return;
      draftState = state;
      autosaveStatus = '';
      lastPersistedFingerprint = draftFingerprint(state.snapshot);
    });
    activeDraftKey = intent.client_draft_id;
    if (data?.client_draft_id !== intent.client_draft_id) composeData.set(intent);
    let state = suppliedClientId
      ? await draftController.load({ clientDraftId: intent.client_draft_id, intent, initialSnapshot: draftSnapshot() })
      : await draftController.load({ intent, initialSnapshot: draftSnapshot() });
    if (requestGeneration !== openingDraftGeneration || !sessionGuard.isCurrent()) return;
    if (data?.refresh_server_draft === true
      || (suppliedClientId && knownServerRevisionRequiresRefresh(data, state))) {
      await draftController.refresh();
      if (requestGeneration !== openingDraftGeneration || !sessionGuard.isCurrent()) return;
      state = draftController.getState();
    }
    activeDraftKey = state.clientDraftId || intent.client_draft_id;
    hydrateDraftSnapshot(state.snapshot);
    if (recoverySourceClientId && recoverySourceClientId !== activeDraftKey) {
      await durableStorage.delete(sessionGuard.userId, recoverySourceClientId);
      if (requestGeneration !== openingDraftGeneration || !sessionGuard.isCurrent()) return;
    }
    composeData.set({
      ...intent,
      ...state.snapshot,
      client_draft_id: activeDraftKey,
      intent_key: state.intentKey || intent.intent_key,
    });
    autosaveReady = true;
  }

  onMount(() => {
    sessionGuard = createAuthenticatedSessionGuard();
    if (!sessionGuard.isCurrent()) {
      return () => sessionGuard?.dispose();
    }
    let unsubCompose = null;
    let disposed = false;

    const unsubAccounts = accounts.subscribe(v => {
      if (!sessionGuard?.isCurrent()) return;
      accountList = v;
      if (v.length > 0 && !selectedAccountId) {
        selectedAccountId = chooseSender(v, get(composeData)?.account_id);
      }
    });

    // Register keyboard shortcut actions for the Compose page
    const cleanupShortcuts = registerActions({
      'compose.send': {
        run: () => handleSend(),
        isEnabled: () => !sending && writingSurfaceReady && draftState.canSend,
        disabledReason: () => sending
          ? 'Email is already sending'
          : draftState.status === 'offline'
            ? 'Reconnect to send'
          : !draftState.canSend
            ? 'Draft is not ready to send'
            : 'Message editor is still opening',
      },
      'compose.sendArchive': {
        run: () => handleSend(null, { archiveAfterSend: true }),
        isEnabled: () => (
          !sending
          && writingSurfaceReady
          && draftState.canSend
          && archiveSourceEmailId !== null
        ),
        disabledReason: () => {
          if (archiveSourceEmailId === null) return 'Open a verified reply first';
          if (sending) return 'Email is already sending';
          if (draftState.status === 'offline') return 'Reconnect to send';
          if (!draftState.canSend) return 'Draft is not ready to send';
          return 'Message editor is still opening';
        },
      },
      'compose.draft': {
        run: () => handleSaveDraft(),
        isEnabled: () => (
          !savingDraft
          && writingSurfaceReady
          && Boolean(draftController)
          && !draftLocked
          && !autosaveStatus
        ),
        disabledReason: () => {
          if (draftState.status === 'conflict') return 'Review the conflicting draft versions first';
          if (draftLocked) return 'Draft editing is locked while its state is being confirmed';
          if (autosaveStatus || !draftController) return 'Durable draft storage is unavailable';
          return savingDraft ? 'Draft is already saving' : 'Message editor is still opening';
        },
      },
      'compose.snippets': {
        run: () => { snippetPickerOpen = true; },
        isEnabled: () => writingSurfaceReady && Boolean(editorHandle) && !draftLocked,
        disabledReason: () => draftLocked
          ? 'Draft editing is locked while its state is being confirmed'
          : 'Message editor is still opening',
      },
      'compose.discard': () => returnToInbox(),
      'compose.deleteDraft': {
        run: () => discardDraft(),
        isEnabled: () => !draftLocked && (draftState.importingAttachments?.length || 0) === 0,
        disabledReason: () => draftLocked
          ? 'Draft editing is locked while its state is being confirmed'
          : 'Wait for attachments to finish importing',
      },
      'compose.cc': () => { showCcBcc = !showCcBcc; },
      'compose.bcc': () => { showCcBcc = !showCcBcc; },
    });

    const onlineHandler = () => draftController?.handleOnlineChange();
    window.addEventListener('online', onlineHandler);
    window.addEventListener('offline', onlineHandler);

    void (async () => {
      try {
        durableStorage = createIndexedDbDraftStorage();
        await migrateLegacyScopedDrafts({
          storage: durableStorage,
          localStorage,
          userId: sessionGuard.userId,
        });
        if (disposed || !sessionGuard.isCurrent()) return;
        const initialIntent = get(composeData) || newComposeIntent();
        if (!get(composeData)) composeData.set(initialIntent);
        await openDraftIntent(initialIntent);
        if (disposed || !sessionGuard.isCurrent()) return;
        unsubCompose = composeData.subscribe(data => {
          if (!data || !sessionGuard?.isCurrent()) return;
          if (data.client_draft_id === activeDraftKey) return;
          void openDraftIntent(data);
        });
      } catch (error) {
        if (sessionGuard?.isCurrent()) {
          autosaveStatus = 'Durable draft storage is unavailable';
          showToast(error?.message || autosaveStatus, 'error');
        }
      }
    })();

    return () => {
      disposed = true;
      openingDraftGeneration += 1;
      if (autosaveReady) persistLocalDraft();
      void draftController?.flush();
      unsubscribeDraft?.();
      draftController?.dispose();
      unsubAccounts();
      unsubCompose?.();
      window.removeEventListener('online', onlineHandler);
      window.removeEventListener('offline', onlineHandler);
      composeData.set(null);
      cleanupShortcuts();
      void durableStorage?.close();
      sessionGuard?.dispose();
    };
  });

  function handleEditorUpdate(html) {
    bodyHtml = html;
  }

  function handleEditorReady(handle) {
    editorHandle = handle || null;
    writingSurfaceReady = true;
  }

  function insertPersonalSnippet(snippet) {
    const inserted = editorHandle?.insertHtml?.(snippet?.body_html);
    if (!inserted) {
      showToast('Place the cursor in the message before inserting a snippet.', 'error');
      return false;
    }
    showToast(`Inserted “${snippet.name}”`, 'success');
    return true;
  }

  function focusInitialRecipient(node) {
    const frame = requestAnimationFrame(() => {
      const active = document.activeElement;
      const focusIsLost = !active
        || active === document.body
        || active.matches?.('main')
        || !active.isConnected;
      if (!to.trim() && focusIsLost) node.focus({ preventScroll: true });
    });
    return { destroy: () => cancelAnimationFrame(frame) };
  }

  $effect(() => {
    if (!autosaveReady) return;
    const draft = draftSnapshot();
    suppressLocalPersistence = false;
    persistLocalDraft(draft);
  });

  $effect(() => {
    const lastAccountKey = composeLastAccountStorageKey(sessionGuard?.userId);
    if (selectedAccountId && lastAccountKey && sessionGuard?.isCurrent()) {
      localStorage.setItem(lastAccountKey, String(selectedAccountId));
    }
  });

  function removeRecipient(address) {
    to = parseRecipients(to).filter(item => item !== address).join(', ');
  }

  async function addAttachments(event) {
    const input = event.currentTarget;
    const files = Array.from(input.files || []);
    if (!files.length) return;
    const ownerController = draftController;
    const ownerDraftId = ownerController?.clientDraftId || null;
    const ownerGeneration = openingDraftGeneration;
    const stillOwnsImport = () => (
      sessionGuard?.isCurrent()
      && draftController === ownerController
      && ownerController?.clientDraftId === ownerDraftId
      && openingDraftGeneration === ownerGeneration
    );
    if (!ownerController || !ownerDraftId) {
      input.value = '';
      return;
    }
    const nextTotal = totalAttachmentBytes + files.reduce((sum, file) => sum + file.size, 0);
    if (attachments.length + files.length > 10 || nextTotal > 18 * 1024 * 1024) {
      showToast('Attach up to 10 files totaling 18 MB', 'error');
      input.value = '';
      return;
    }
    await Promise.all(files.map(async file => {
      const importId = ownerController.beginAttachmentImport({ filename: file.name });
      try {
        const encoded = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve({
            attachment_id: importId,
            filename: file.name,
            content_type: file.type || 'application/octet-stream',
            data_base64: String(reader.result).split(',')[1] || '',
            size: file.size,
          });
          reader.onerror = () => reject(reader.error || new Error(`Could not read ${file.name}`));
          reader.readAsDataURL(file);
        });
        if (!stillOwnsImport()) return;
        ownerController.completeAttachmentImport(importId, encoded);
      } catch (error) {
        if (stillOwnsImport()) ownerController.failAttachmentImport(importId, error, file.name);
      }
    }));
    if (stillOwnsImport()) {
      attachments = (ownerController.getState().snapshot.attachments || []).map(normalizeDraftAttachment);
    }
    input.value = '';
  }

  function removeAttachment(index) {
    attachments = attachments.filter((_, itemIndex) => itemIndex !== index);
  }

  async function discardDraft() {
    if (
      !sessionGuard?.isCurrent()
      || !draftController
      || draftLocked
      || (draftState.importingAttachments?.length || 0) > 0
    ) return;
    persistLocalDraft();
    await draftController.flush();
    if (!sessionGuard.isCurrent()) return;
    await draftController.discard({ delayMs: 10000 });
  }

  async function undoDiscardDraft() {
    if (!sessionGuard?.isCurrent() || !draftController) return;
    await draftController.undoDiscard();
  }

  function retryDraftStatus() {
    const attachmentErrors = draftState.attachmentErrors || [];
    if (attachmentErrors.length > 0) {
      for (const error of attachmentErrors) draftController?.clearAttachmentError(error.id);
      fileInput?.click();
      return;
    }
    void draftController?.retry();
  }

  async function returnToInbox() {
    if (!sessionGuard?.isCurrent()) return;
    persistLocalDraft();
    await draftController?.flush();
    if (!sessionGuard.isCurrent()) return;
    composeData.set(null);
    currentPage.set('inbox');
  }

  function conflictPreview(snapshot = {}) {
    const text = String(snapshot.body_text || snapshot.body_html || '')
      .replace(/<[^>]*>/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
    return text.slice(0, 240) || 'No message body';
  }

  async function reviewDraftConflict(event) {
    if (draftState.status !== 'conflict') return;
    conflictTrigger = event?.currentTarget || document.activeElement;
    conflictDialogOpen = true;
    await tick();
    conflictCancelButton?.focus();
  }

  async function closeConflictDialog() {
    conflictDialogOpen = false;
    await tick();
    const restoreTarget = conflictTrigger?.isConnected ? conflictTrigger : conflictFallbackFocus;
    if (restoreTarget?.isConnected) restoreTarget.focus({ preventScroll: true });
    conflictTrigger = null;
  }

  function handleConflictDialogKeydown(event) {
    if (event.key === 'Escape') {
      event.preventDefault();
      void closeConflictDialog();
      return;
    }
    if (event.key !== 'Tab' || !conflictDialog) return;
    const focusable = [...conflictDialog.querySelectorAll('button:not([disabled])')];
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  async function resolveDraftConflict(choice) {
    if (choice === 'cancel') {
      await closeConflictDialog();
      return;
    }
    if (draftState.status !== 'conflict' || !draftController) return;
    try {
      const state = await draftController.resolveConflict(choice);
      if (choice === 'server' && state?.snapshot) hydrateDraftSnapshot(state.snapshot);
      await closeConflictDialog();
    } catch (error) {
      showToast(error?.message || 'The draft versions could not be reconciled', 'error');
    }
  }

  async function handleSend(schedule = null, { archiveAfterSend = false } = {}) {
    if (sending || !writingSurfaceReady || !draftState.canSend || !sessionGuard?.isCurrent()) return false;
    if (archiveAfterSend && archiveSourceEmailId === null) {
      showToast('Open a verified reply before using Send & archive.', 'error');
      return false;
    }
    if (!to.trim()) {
      showToast('Please add recipients', 'error');
      return false;
    }
    if (!selectedAccountId) {
      showToast('Please select an account', 'error');
      return false;
    }

    persistLocalDraft();
    sending = true;
    sendMode = schedule ? 'schedule' : (archiveAfterSend ? 'archive' : 'send');
    try {
      await draftController?.markSending(true);
    } catch (err) {
      sending = false;
      await draftController?.markSending(false);
      if (sessionGuard?.isCurrent()) showToast(err.message, 'error');
      return false;
    }
    if (!sessionGuard.isCurrent()) {
      sending = false;
      return false;
    }
    const sendSession = captureAuthenticatedSession();
    const capturedDraftKey = draftController?.clientDraftId || activeDraftKey;
    const capturedDraftRevision = draftController?.revision || 0;
    const capturedDraftStorage = durableStorage;
    const capturedDraftUserId = sessionGuard.userId;
    let editorReleased = false;
    const releaseEditor = () => {
      if (editorReleased || !isAuthenticatedSessionCurrent(sendSession)) return;
      editorReleased = true;
      if (!sessionGuard?.isCurrent()) return;
      if (
        draftController?.clientDraftId !== capturedDraftKey
        || draftController?.revision !== capturedDraftRevision
      ) {
        showToast('Message queued; newer edits are still saved as a draft', 'info');
        return;
      }
      suppressLocalPersistence = true;
      composeData.set(null);
      currentPage.set('inbox');
    };
    try {
      let data = {
        account_id: selectedAccountId,
        to: parseRecipients(to),
        cc: parseRecipients(cc),
        bcc: parseRecipients(bcc),
        subject: subject,
        body_html: bodyHtml,
        body_text: bodyHtml.replace(/<[^>]*>/g, ''),
        attachments: attachments.map(({ size, ...item }) => item),
        client_draft_id: capturedDraftKey,
        draft_revision: capturedDraftRevision,
      };

      if (replyContext.in_reply_to) data.in_reply_to = replyContext.in_reply_to;
      if (replyContext.references) data.references = replyContext.references;
      if (replyContext.thread_id) data.thread_id = replyContext.thread_id;
      if (replyContext.source_email_id) data.source_email_id = replyContext.source_email_id;
      data = withArchiveAfterSend(data, archiveAfterSend);

      const composeIntent = get(composeData);
      const restoreDraft = {
        ...data,
        draft_key: composeIntent?.draft_key,
        client_draft_id: capturedDraftKey,
        attachments: attachments.map(item => ({ ...item })),
      };
      // Send & archive is an explicit one-shot action, never a recovered-draft
      // default after Undo, cancellation, or delivery failure.
      delete restoreDraft.archive_source_after_send;
      if (schedule?.scheduledFor) {
        data.scheduled_for = schedule.scheduledFor;
        data.schedule_timezone = schedule.scheduleTimezone;
      }
      const restoreEditor = async (operation, reason) => {
        return restoreOutboundComposeDraft(restoreDraft, operation, reason);
      };
      const forgetSentDraft = () => (
        capturedDraftStorage?.delete(capturedDraftUserId, capturedDraftKey)
      );

      const operation = await submitOutboundSend(data, {
        onAccepted: acceptedOperation => {
          if (archiveAfterSend && isAuthenticatedSessionCurrent(sendSession)) {
            showToast(
              sendArchiveAcceptedMessage({ scheduled: Boolean(schedule?.scheduledFor) }),
              'info',
              6000,
            );
          }
          releaseEditor(acceptedOperation);
        },
        onSent: forgetSentDraft,
        onRestore: restoreEditor,
      });
      if (!sessionGuard.isCurrent()) return false;
      // Even if the acceptance response was lost, this logical send now owns
      // its idempotency key. Leave status reconciliation to the global monitor
      // instead of exposing a second Send action for the same message.
      if (operation?.send_id) releaseEditor();
      else if (operation) await draftController?.markSendUncertain(operation);
      return true;
    } catch (err) {
      if (sessionGuard?.isCurrent()) showToast(err.message, 'error');
      return false;
    } finally {
      if (sessionGuard?.isCurrent()) {
        sending = false;
        sendMode = 'send';
        await draftController?.markSending(false);
      }
    }
  }

  async function handleSaveDraft() {
    if (
      !selectedAccountId
      || !draftController
      || autosaveStatus
      || draftLocked
      || savingDraft
      || !writingSurfaceReady
      || !sessionGuard?.isCurrent()
    ) return false;
    savingDraft = true;
    try {
      persistLocalDraft();
      await draftController?.flush();
      if (!sessionGuard.isCurrent()) return false;
      const state = draftController?.getState();
      if (state?.status === 'failed') throw new Error(state.error?.message || 'Draft sync failed');
      showToast(state?.status === 'synced' ? 'Draft saved' : 'Draft is safe and syncing', 'success');
      return true;
    } catch (err) {
      if (sessionGuard?.isCurrent()) showToast(err.message, 'error');
      return false;
    } finally {
      if (sessionGuard?.isCurrent()) savingDraft = false;
    }
  }
</script>

<div class="h-full w-full min-w-0 overflow-x-hidden flex flex-col" style="background: var(--bg-secondary)">
  <!-- Header -->
  <div class="compose-header min-h-14 flex items-center justify-between px-6 border-b shrink-0" style="border-color: var(--border-color)">
    <div class="flex items-center gap-3">
      <button
        onclick={returnToInbox}
        class="p-1.5 rounded-md transition-fast"
        style="color: var(--text-secondary)"
        aria-label="Back to inbox; keep draft"
      >
        <Icon name="arrow-left" size={20} />
      </button>
      <h2 class="text-base font-semibold" style="color: var(--text-primary)">New Message</h2>
    </div>
    <div class="flex items-center gap-2">
      {#if autosaveStatus}
        <span class="autosave-label text-[11px]" role="alert" style="color: var(--status-error)">{autosaveStatus}</span>
      {:else}
        <DraftStatus
          state={draftState}
          onretry={retryDraftStatus}
          onundo={undoDiscardDraft}
          onreview={reviewDraftConflict}
          compact={true}
        />
      {/if}
      <Button
        size="sm"
        onclick={discardDraft}
        disabled={draftLocked || !draftController || draftState.importingAttachments?.length > 0}
      >Discard</Button>
      <Button
        size="sm"
        onclick={handleSaveDraft}
        disabled={savingDraft || !writingSurfaceReady || draftLocked || !draftController || Boolean(autosaveStatus)}
      >
        {savingDraft ? 'Saving…' : 'Save Draft'}
      </Button>
      <SnippetPicker
        bind:open={snippetPickerOpen}
        disabled={draftLocked || !writingSurfaceReady}
        shortcutId="compose.snippets"
        oninsert={insertPersonalSnippet}
      />
      <SendSplitButton
        compact={true}
        disabled={!writingSurfaceReady || !draftState.canSend}
        busy={sending}
        busyLabel={sendMode === 'schedule' ? 'Scheduling…' : 'Sending…'}
        onsend={() => handleSend()}
        canArchiveAfterSend={archiveSourceEmailId !== null}
        onsendarchive={() => handleSend(null, { archiveAfterSend: true })}
        onschedule={schedule => handleSend(schedule, { archiveAfterSend: schedule.archiveAfterSend })}
      />
    </div>
  </div>

  <!-- Form -->
  <div class="flex-1 overflow-y-auto flex flex-col">
    <div class="border-b shrink-0" style="border-color: var(--border-color)">
      <!-- From -->
      {#if accountList.length > 0}
        <div class="compose-field flex items-center min-w-0 px-6 min-h-10 border-b" style="border-color: var(--border-subtle)">
          <label for="compose-from" class="text-sm w-16 shrink-0" style="color: var(--text-secondary)">From</label>
          <select
            id="compose-from"
            bind:value={selectedAccountId}
            disabled={Boolean(replyContext.source_email_id) || draftLocked}
            class="w-0 min-w-0 flex-1 h-full text-sm outline-none border-0"
            style="background: transparent; color: var(--text-primary)"
          >
            {#each accountList as acct}
              <option value={acct.id}>{acct.short_label ? `${acct.short_label} — ` : acct.description ? `${acct.description} — ` : ''}{acct.email}</option>
            {/each}
          </select>
          {#if senderAccount}
            <span class="sender-context text-[11px] px-2 py-1 rounded-full shrink-0" style="background: var(--bg-tertiary); color: var(--text-secondary)">
              Sending as {senderAccount.short_label || senderAccount.description || senderAccount.email.split('@')[0]}
            </span>
          {/if}
        </div>
      {/if}

      <!-- To -->
      <div class="compose-field flex items-start px-6 min-h-10 py-1 border-b" style="border-color: var(--border-subtle)">
        <label for="compose-to" class="text-sm w-16 shrink-0" style="color: var(--text-secondary)">To</label>
        <div class="flex-1 min-w-0">
          <input
            type="text"
            id="compose-to"
            bind:this={conflictFallbackFocus}
            bind:value={to}
            readonly={draftLocked}
            use:focusInitialRecipient
            placeholder="recipient@example.com"
            class="w-full h-8 text-sm outline-none"
            style="background: transparent; color: var(--text-primary)"
            aria-describedby="recipient-help"
          />
          {#if recipientChips.length > 0}
            <div class="flex flex-wrap gap-1 pb-1" id="recipient-help">
              {#each recipientChips as address}
                <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px]" style="background: var(--bg-tertiary); color: var(--text-secondary)">
                  {address}
                  <button disabled={draftLocked} onclick={() => removeRecipient(address)} aria-label="Remove recipient {address}"><Icon name="x" size={11} /></button>
                </span>
              {/each}
            </div>
          {/if}
        </div>
        {#if !showCcBcc}
          <button
            onclick={() => showCcBcc = true}
            disabled={draftLocked}
            class="text-xs"
            style="color: var(--text-tertiary)"
          >Cc/Bcc</button>
        {/if}
      </div>

      <!-- Cc/Bcc -->
      {#if showCcBcc}
        <div class="compose-field flex items-center px-6 h-10 border-b" style="border-color: var(--border-subtle)">
          <label for="compose-cc" class="text-sm w-16 shrink-0" style="color: var(--text-secondary)">Cc</label>
          <input
            type="text"
            id="compose-cc"
            bind:value={cc}
            readonly={draftLocked}
            class="flex-1 h-full text-sm outline-none"
            style="background: transparent; color: var(--text-primary)"
          />
        </div>
        <div class="compose-field flex items-center px-6 h-10 border-b" style="border-color: var(--border-subtle)">
          <label for="compose-bcc" class="text-sm w-16 shrink-0" style="color: var(--text-secondary)">Bcc</label>
          <input
            type="text"
            id="compose-bcc"
            bind:value={bcc}
            readonly={draftLocked}
            class="flex-1 h-full text-sm outline-none"
            style="background: transparent; color: var(--text-primary)"
          />
        </div>
      {/if}

      <!-- Subject -->
      <div class="compose-field flex items-center px-6 h-10" style="border-color: var(--border-subtle)">
        <label for="compose-subject" class="text-sm w-16 shrink-0" style="color: var(--text-secondary)">Subject</label>
        <input
          type="text"
          id="compose-subject"
          bind:value={subject}
          readonly={draftLocked}
          placeholder="Subject"
          class="flex-1 h-full text-sm outline-none"
          style="background: transparent; color: var(--text-primary)"
        />
      </div>

      <div class="compose-field flex items-start gap-2 px-6 py-2 border-t" style="border-color: var(--border-subtle)">
        <label for="compose-files" class="text-sm w-16 shrink-0 pt-1" style="color: var(--text-secondary)">Files</label>
        <div class="flex-1 min-w-0">
          <input id="compose-files" bind:this={fileInput} type="file" multiple class="hidden" onchange={addAttachments} />
          <button
            onclick={() => fileInput?.click()}
            disabled={draftLocked || !draftController || draftState.importingAttachments?.length > 0}
            class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-xs font-medium"
            style="border-color: var(--border-color); color: var(--text-secondary)"
          >
            <Icon name="paperclip" size={14} /> Attach files
          </button>
          {#if attachments.length > 0}
            <div class="flex flex-wrap gap-1.5 mt-2">
              {#each attachments as attachment, index}
                <span class="inline-flex items-center gap-1.5 max-w-full px-2 py-1 rounded-md text-xs" style="background: var(--bg-tertiary); color: var(--text-secondary)">
                  <span class="truncate max-w-[220px]">{attachment.filename}</span>
                  <span class="text-[10px] opacity-70">{Math.ceil(attachment.size / 1024)} KB</span>
                  <button disabled={draftLocked} onclick={() => removeAttachment(index)} aria-label="Remove attachment {attachment.filename}"><Icon name="x" size={12} /></button>
                </span>
              {/each}
              <span class="text-[10px] self-center" style="color: var(--text-tertiary)">{(totalAttachmentBytes / 1024 / 1024).toFixed(1)} of 18 MB</span>
            </div>
            <p class="mt-1 text-[10px]" style="color: var(--text-tertiary)">
              Attachments are stored with this draft and restored when you return.
            </p>
          {/if}
        </div>
      </div>
    </div>

    <!-- Rich Editor Body -->
    <div class:pointer-events-none={draftLocked} class:opacity-60={draftLocked} class="flex-1 min-h-0">
      {#key editorRevision}
        <DeferredRichEditor
          content={initialContent}
          onUpdate={handleEditorUpdate}
          onReady={handleEditorReady}
          placeholder="Write your message..."
          autofocus={true}
          ariaLabel="Message body"
          surface="compose"
        />
      {/key}
    </div>
  </div>
</div>

{#if conflictDialogOpen}
  <div class="fixed inset-0 z-50 flex items-center justify-center p-4" role="presentation">
    <button
      class="absolute inset-0 bg-black/40"
      aria-label="Close draft comparison"
      onclick={() => resolveDraftConflict('cancel')}
    ></button>
    <div
      bind:this={conflictDialog}
      class="relative w-full max-w-2xl rounded-xl border p-5 shadow-2xl"
      style="background: var(--bg-primary); border-color: var(--border-color)"
      role="dialog"
      aria-modal="true"
      aria-labelledby="draft-conflict-title"
      tabindex="-1"
      onkeydown={handleConflictDialogKeydown}
    >
      <h3 id="draft-conflict-title" class="text-base font-semibold" style="color: var(--text-primary)">Choose the version to keep</h3>
      <p class="mt-1 text-sm" style="color: var(--text-secondary)">Nothing changes until you choose. Cancel closes this comparison.</p>
      <div class="mt-4 grid gap-3 sm:grid-cols-2">
        <article class="rounded-lg border p-3" style="border-color: var(--border-color)">
          <h4 class="text-xs font-semibold uppercase tracking-wide" style="color: var(--text-tertiary)">This device · revision {draftState.revision}</h4>
          <p class="mt-2 text-sm font-medium" style="color: var(--text-primary)">{draftState.snapshot?.subject || '(No subject)'}</p>
          <p class="mt-1 text-sm" style="color: var(--text-secondary)">{conflictPreview(draftState.snapshot)}</p>
        </article>
        <article class="rounded-lg border p-3" style="border-color: var(--border-color)">
          <h4 class="text-xs font-semibold uppercase tracking-wide" style="color: var(--text-tertiary)">Server · revision {draftState.conflict?.server_revision || 'newer'}</h4>
          <p class="mt-2 text-sm font-medium" style="color: var(--text-primary)">{draftState.conflict?.server_snapshot?.subject || '(No subject)'}</p>
          <p class="mt-1 text-sm" style="color: var(--text-secondary)">{conflictPreview(draftState.conflict?.server_snapshot)}</p>
        </article>
      </div>
      <div class="mt-5 flex flex-wrap justify-end gap-2">
        <Button bind:element={conflictCancelButton} onclick={() => resolveDraftConflict('cancel')}>Cancel</Button>
        <Button onclick={() => resolveDraftConflict('local')}>Keep this version</Button>
        <Button
          variant="primary"
          disabled={!draftState.conflict?.server_snapshot}
          onclick={() => resolveDraftConflict('server')}
        >Use server version</Button>
      </div>
    </div>
  </div>
{/if}

<style>
  @media (max-width: 767px) {
    .compose-header {
      padding: 0.5rem;
      gap: 0.5rem;
      flex-wrap: wrap;
    }
    .compose-header h2,
    .sender-context {
      display: none;
    }
    .autosave-label {
      flex: 1 1 100%;
      order: 3;
      text-align: center;
      white-space: normal;
    }
    .compose-field {
      padding-left: 0.75rem;
      padding-right: 0.75rem;
    }
    .compose-field > label {
      width: 3.25rem;
    }

    :global(.compose-header button) {
      min-height: 2.75rem;
    }
  }
</style>
