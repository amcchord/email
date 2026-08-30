<script>
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { api } from '../lib/api.js';
  import { submitOutboundSend } from '../lib/outboundSend.js';
  import { restoreOutboundComposeDraft } from '../lib/outboundDraftRecovery.js';
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

  let to = $state('');
  let cc = $state('');
  let bcc = $state('');
  let subject = $state('');
  let bodyHtml = $state('');
  let showCcBcc = $state(false);
  let sending = $state(false);
  let selectedAccountId = $state(null);
  let accountList = $state([]);
  let initialContent = $state('');
  let attachments = $state([]);
  let autosaveStatus = $state('');
  let autosaveReady = $state(false);
  let fileInput = $state(null);
  let writingSurfaceReady = $state(false);
  let savingDraft = $state(false);
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
  let recipientChips = $derived(parseRecipients(to));
  let totalAttachmentBytes = $derived(attachments.reduce((sum, item) => sum + item.size, 0));
  let draftLocked = $derived(draftState.status === 'discard-pending' || draftState.status === 'discarded');

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
      attachments: attachments.map(({ size: _size, ...item }) => ({ ...item })),
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
    if (suppressLocalPersistence || !draftController || !autosaveReady || !sessionGuard?.isCurrent()) return;
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

  async function seedServerDraftIfNeeded(intent, data) {
    if (!data?.draft_revision || !data?.client_draft_id) return;
    const existing = await durableStorage.get(sessionGuard.userId, intent.client_draft_id);
    if (existing) return;
    const snapshot = {
      ...draftSnapshot(),
      account_id: Number(data.account_id),
      to: Array.isArray(data.to) ? data.to : parseRecipients(data.to),
      cc: Array.isArray(data.cc) ? data.cc : parseRecipients(data.cc),
      bcc: Array.isArray(data.bcc) ? data.bcc : parseRecipients(data.bcc),
      subject: data.subject || '',
      body_html: data.body_html || '',
      body_text: data.body_text || '',
      attachments: (data.attachments || []).map(({ size: _size, size_bytes: _bytes, ...item }) => item),
      ...composeReplyContext(data),
    };
    const now = new Date().toISOString();
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
  }

  async function openDraftIntent(data = {}) {
    if (!sessionGuard?.isCurrent() || !durableStorage) return;
    const requestGeneration = ++openingDraftGeneration;
    const suppliedClientId = data?.client_draft_id || null;
    const intent = createComposeDraftIntent(data || newComposeIntent());
    if (activeDraftKey === intent.client_draft_id && draftController) return;

    if (draftController) {
      persistLocalDraft();
      await draftController.flush();
      draftController.dispose();
      unsubscribeDraft?.();
    }
    autosaveReady = false;
    writingSurfaceReady = false;
    if (requestGeneration !== openingDraftGeneration || !sessionGuard.isCurrent()) return;

    hydrateDraftSnapshot(data);
    await seedServerDraftIfNeeded(intent, data);
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
    });
    unsubscribeDraft = draftController.subscribe(state => {
      if (requestGeneration !== openingDraftGeneration || !sessionGuard?.isCurrent()) return;
      draftState = state;
      autosaveStatus = '';
      lastPersistedFingerprint = draftFingerprint(state.snapshot);
    });
    activeDraftKey = intent.client_draft_id;
    const state = suppliedClientId
      ? await draftController.load({ clientDraftId: intent.client_draft_id, intent, initialSnapshot: draftSnapshot() })
      : await draftController.load({ intent, initialSnapshot: draftSnapshot() });
    if (requestGeneration !== openingDraftGeneration || !sessionGuard.isCurrent()) return;
    hydrateDraftSnapshot(state.snapshot);
    autosaveReady = true;
  }

  onMount(() => {
    sessionGuard = createAuthenticatedSessionGuard();
    if (!sessionGuard.isCurrent()) {
      return () => sessionGuard?.dispose();
    }
    durableStorage = createIndexedDbDraftStorage();
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
          : !draftState.canSend
            ? 'Draft is not ready to send'
            : 'Message editor is still opening',
      },
      'compose.draft': {
        run: () => handleSaveDraft(),
        isEnabled: () => !savingDraft && writingSurfaceReady,
        disabledReason: () => savingDraft ? 'Draft is already saving' : 'Message editor is still opening',
      },
      'compose.discard': () => returnToInbox(),
      'compose.deleteDraft': () => discardDraft(),
      'compose.cc': () => { showCcBcc = !showCcBcc; },
      'compose.bcc': () => { showCcBcc = !showCcBcc; },
    });

    const onlineHandler = () => draftController?.handleOnlineChange();
    window.addEventListener('online', onlineHandler);
    window.addEventListener('offline', onlineHandler);

    void (async () => {
      try {
        await migrateLegacyScopedDrafts({
          storage: durableStorage,
          localStorage,
          userId: sessionGuard.userId,
        });
        if (disposed || !sessionGuard.isCurrent()) return;
        const initialIntent = get(composeData) || newComposeIntent();
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
    const files = Array.from(event.currentTarget.files || []);
    if (!files.length) return;
    const nextTotal = totalAttachmentBytes + files.reduce((sum, file) => sum + file.size, 0);
    if (attachments.length + files.length > 10 || nextTotal > 18 * 1024 * 1024) {
      showToast('Attach up to 10 files totaling 18 MB', 'error');
      event.currentTarget.value = '';
      return;
    }
    await Promise.all(files.map(async file => {
      const importId = draftController?.beginAttachmentImport({ filename: file.name }) || crypto.randomUUID();
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
        if (!sessionGuard?.isCurrent()) return;
        if (draftController) draftController.completeAttachmentImport(importId, encoded);
        else attachments = [...attachments, encoded];
      } catch (error) {
        draftController?.failAttachmentImport(importId, error, file.name);
      }
    }));
    if (draftController && sessionGuard?.isCurrent()) {
      attachments = (draftController.getState().snapshot.attachments || []).map(normalizeDraftAttachment);
    }
    event.currentTarget.value = '';
  }

  function removeAttachment(index) {
    attachments = attachments.filter((_, itemIndex) => itemIndex !== index);
  }

  async function discardDraft() {
    if (!sessionGuard?.isCurrent() || !draftController || draftLocked) return;
    persistLocalDraft();
    await draftController.flush();
    if (!sessionGuard.isCurrent()) return;
    await draftController.discard({ delayMs: 10000 });
  }

  async function undoDiscardDraft() {
    if (!sessionGuard?.isCurrent() || !draftController) return;
    await draftController.undoDiscard();
  }

  async function returnToInbox() {
    if (!sessionGuard?.isCurrent()) return;
    persistLocalDraft();
    await draftController?.flush();
    if (!sessionGuard.isCurrent()) return;
    composeData.set(null);
    currentPage.set('inbox');
  }

  async function resolveDraftConflict() {
    if (draftState.status !== 'conflict' || !draftController) return;
    const useServer = window.confirm(
      'This draft changed elsewhere. Choose OK to use the provider version, or Cancel to keep and resync this version.',
    );
    try {
      const state = await draftController.resolveConflict(useServer ? 'server' : 'local');
      if (useServer && state?.snapshot) hydrateDraftSnapshot(state.snapshot);
    } catch (error) {
      showToast(error?.message || 'The draft versions could not be reconciled', 'error');
    }
  }

  async function handleSend() {
    if (sending || !writingSurfaceReady || !draftState.canSend || !sessionGuard?.isCurrent()) return false;
    if (!to.trim()) {
      showToast('Please add recipients', 'error');
      return false;
    }
    if (!selectedAccountId) {
      showToast('Please select an account', 'error');
      return false;
    }

    persistLocalDraft();
    await draftController?.markSending(true);
    if (!sessionGuard.isCurrent()) return false;
    const sendSession = captureAuthenticatedSession();
    const capturedDraftKey = draftController?.clientDraftId || activeDraftKey;
    const capturedDraftRevision = draftController?.revision || 0;
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
      void durableStorage?.delete(sessionGuard.userId, capturedDraftKey);
      composeData.set(null);
      currentPage.set('inbox');
    };

    sending = true;
    try {
      const data = {
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

      const composeIntent = get(composeData);
      const restoreDraft = {
        ...data,
        draft_key: composeIntent?.draft_key,
        client_draft_id: capturedDraftKey,
        attachments: attachments.map(item => ({ ...item })),
      };
      const restoreEditor = (operation, reason) => (
        restoreOutboundComposeDraft(restoreDraft, operation, reason)
      );

      const operation = await submitOutboundSend(data, {
        onAccepted: releaseEditor,
        onRestore: restoreEditor,
      });
      if (!sessionGuard.isCurrent()) return false;
      // Even if the acceptance response was lost, this logical send now owns
      // its idempotency key. Leave status reconciliation to the global monitor
      // instead of exposing a second Send action for the same message.
      if (operation) releaseEditor();
      return true;
    } catch (err) {
      if (sessionGuard?.isCurrent()) showToast(err.message, 'error');
      return false;
    } finally {
      if (sessionGuard?.isCurrent()) {
        sending = false;
        await draftController?.markSending(false);
      }
    }
  }

  async function handleSaveDraft() {
    if (!selectedAccountId || savingDraft || !writingSurfaceReady || !sessionGuard?.isCurrent()) return false;
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
          onretry={() => draftController?.retry()}
          onundo={undoDiscardDraft}
          onreview={resolveDraftConflict}
          compact={true}
        />
      {/if}
      <Button size="sm" onclick={discardDraft} disabled={draftLocked || !draftController}>Discard</Button>
      <Button size="sm" onclick={handleSaveDraft} disabled={savingDraft || !writingSurfaceReady || draftLocked}>
        {savingDraft ? 'Saving…' : 'Save Draft'}
      </Button>
      <Button variant="primary" size="sm" onclick={handleSend} disabled={sending || !writingSurfaceReady || !draftState.canSend}>
        {#if sending}
          Sending...
        {:else}
          Send
        {/if}
      </Button>
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
                  <button onclick={() => removeRecipient(address)} aria-label="Remove recipient {address}"><Icon name="x" size={11} /></button>
                </span>
              {/each}
            </div>
          {/if}
        </div>
        {#if !showCcBcc}
          <button
            onclick={() => showCcBcc = true}
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
            disabled={draftLocked || draftState.importingAttachments?.length > 0}
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
                  <button onclick={() => removeAttachment(index)} aria-label="Remove attachment {attachment.filename}"><Icon name="x" size={12} /></button>
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
          onReady={() => { writingSurfaceReady = true; }}
          placeholder="Write your message..."
          autofocus={true}
          ariaLabel="Message body"
          surface="compose"
        />
      {/key}
    </div>
  </div>
</div>

<style>
  @media (max-width: 767px) {
    .compose-header {
      padding: 0.5rem;
      gap: 0.5rem;
      flex-wrap: wrap;
    }
    .compose-header h2,
    .autosave-label,
    .sender-context {
      display: none;
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
