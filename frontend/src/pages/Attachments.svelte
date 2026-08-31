<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import {
    accounts,
    accountsLoadError,
    attachmentParentIntent,
    contactConversationIntent,
    createAuthenticatedSessionGuard,
    currentMailbox,
    currentPage,
    searchQuery,
    selectedAccountId,
    selectedEmailId,
    showToast,
    smartFilter,
  } from '../lib/stores.js';
  import { registerActions, commandPaletteOpen, helpModalOpen } from '../lib/shortcutStore.js';
  import {
    attachmentParentAnchorForAccount,
    attachmentTransferItem,
    createAttachmentParentIntent,
    createAttachmentQueryPayload,
    formatAttachmentLibraryDate,
    formatAttachmentLibrarySize,
    normalizeAttachmentQueryResponse,
  } from '../lib/attachmentLibrary.js';
  import {
    MAX_ACTIVE_ATTACHMENT_REQUESTS,
    canStartAttachmentDownload,
    isRetryableAttachmentError,
    safeClientFilename,
    saveAttachmentBlob,
  } from '../lib/attachmentDownload.js';
  import {
    attachmentPreviewHint,
    attachmentSafetyNotice,
    attachmentTypeLabel,
    materializeAttachmentPreview,
    releaseAttachmentPreview,
  } from '../lib/attachmentPreview.js';
  import AttachmentPreview from '../components/email/AttachmentPreview.svelte';
  import Icon from '../components/common/Icon.svelte';

  const kindOptions = Object.freeze([
    { id: 'all', label: 'All types' },
    { id: 'document', label: 'Documents' },
    { id: 'image', label: 'Images' },
    { id: 'archive', label: 'Archives' },
    { id: 'other', label: 'Other' },
  ]);
  const directionOptions = Object.freeze([
    { id: 'all', label: 'Received & sent' },
    { id: 'received', label: 'Received' },
    { id: 'sent', label: 'Sent' },
  ]);

  let sessionGuard = null;
  let attachmentAccountId = $state(null);
  let query = $state('');
  let kind = $state('all');
  let direction = $state('all');
  let items = $state([]);
  let nextCursor = $state(null);
  let hasMore = $state(false);
  let listLoading = $state(false);
  let loadingMore = $state(false);
  let listError = $state('');
  let retryVersion = $state(0);
  let listGeneration = 0;
  let listController = null;
  let surfaceGeneration = 0;
  let selectedIndex = $state(-1);
  let searchInput = $state(null);
  let statusMessage = $state('');

  let attachmentPreview = $state(null);
  let attachmentPreviewReturnFocus = $state(null);
  let previewGeneration = 0;
  let transferControllers = new Map();
  let activeTransferKeys = $state(new Set());

  let activeAccounts = $derived(
    $accounts.filter(account => account?.is_active !== false && Number.isSafeInteger(Number(account?.id)))
  );
  let selectedItem = $derived(selectedIndex >= 0 ? items[selectedIndex] || null : null);
  let transferItems = $derived(items.map(item => attachmentTransferItem(item, {
    accountId: attachmentAccountId,
  })));

  function accountLabel(account) {
    return account?.short_label || account?.description || account?.email || 'Connected account';
  }

  function transferKey(attachment) {
    return `${Number(attachment?.email_id)}:${Number(attachment?.id ?? attachment?.attachment_id)}`;
  }

  function itemIdentity(item) {
    return `${item.email_id}:${item.attachment_id}`;
  }

  function senderLabel(item) {
    if (item.is_sent) return 'Sent by me';
    return item.sender_name || item.sender_address || 'Unknown sender';
  }

  function subjectLabel(item) {
    return item.subject || 'No subject';
  }

  function resultSummary() {
    if (listLoading && items.length === 0) return 'Loading attachments';
    if (listError && items.length === 0) return 'Attachments unavailable';
    if (items.length === 0) return 'No attachments';
    return `${items.length.toLocaleString()} ${items.length === 1 ? 'attachment' : 'attachments'}${hasMore ? ' loaded' : ''}`;
  }

  function previewState(attachment, mode, extras = {}) {
    return {
      attachment,
      mode,
      displayName: safeClientFilename(attachment.filename),
      typeLabel: attachmentTypeLabel(attachment),
      sizeLabel: formatAttachmentLibrarySize(attachment.size_bytes),
      notice: attachmentSafetyNotice(attachment),
      preview: null,
      error: null,
      downloadMode: null,
      downloadError: null,
      ...extras,
    };
  }

  function abortTransfers() {
    for (const controller of transferControllers.values()) controller.abort();
    transferControllers.clear();
    activeTransferKeys = new Set();
  }

  function releaseCurrentPreview() {
    releaseAttachmentPreview(attachmentPreview?.preview);
  }

  function closePreview() {
    previewGeneration += 1;
    const key = attachmentPreview ? transferKey(attachmentPreview.attachment) : null;
    transferControllers.get(key)?.abort();
    if (key) transferControllers.delete(key);
    if (key && activeTransferKeys.has(key)) {
      const next = new Set(activeTransferKeys);
      next.delete(key);
      activeTransferKeys = next;
    }
    releaseCurrentPreview();
    attachmentPreview = null;
  }

  function resetSurface() {
    surfaceGeneration += 1;
    listGeneration += 1;
    listController?.abort();
    listController = null;
    abortTransfers();
    closePreview();
    items = [];
    nextCursor = null;
    hasMore = false;
    selectedIndex = -1;
    statusMessage = '';
  }

  function changeAccount(event) {
    const nextId = Number(event.currentTarget.value);
    if (!Number.isSafeInteger(nextId) || nextId < 1 || nextId === attachmentAccountId) return;
    resetSurface();
    attachmentAccountId = nextId;
    selectedAccountId.set(nextId);
  }

  function changeQuery(event) {
    resetSurface();
    query = event.currentTarget.value;
  }

  function changeKind(event) {
    resetSurface();
    kind = event.currentTarget.value;
  }

  function changeDirection(event) {
    resetSurface();
    direction = event.currentTarget.value;
  }

  function retryList() {
    retryVersion += 1;
  }

  function focusRow(index) {
    if (items.length === 0) return;
    const bounded = Math.max(0, Math.min(index, items.length - 1));
    selectedIndex = bounded;
    requestAnimationFrame(() => {
      document.querySelector(`[data-attachment-index="${bounded}"]`)?.focus({ preventScroll: true });
    });
  }

  function moveSelection(delta) {
    if (items.length === 0 || attachmentPreview) return;
    const start = selectedIndex < 0 ? (delta > 0 ? -1 : 0) : selectedIndex;
    focusRow((start + delta + items.length) % items.length);
  }

  function originalItemForTransfer(attachment) {
    return items.find(item => (
      Number(item.email_id) === Number(attachment?.email_id)
      && Number(item.attachment_id) === Number(attachment?.id ?? attachment?.attachment_id)
      && Number(item.account_id) === Number(attachmentAccountId)
    )) || null;
  }

  function transferIsCurrent(attachment, requestedSurfaceGeneration) {
    return Boolean(
      sessionGuard?.isCurrent()
      && requestedSurfaceGeneration === surfaceGeneration
      && Number(attachment.account_id) === Number(attachmentAccountId)
      && originalItemForTransfer(attachment)
    );
  }

  async function openPreviewFor(attachment, returnFocusTarget = null) {
    const original = originalItemForTransfer(attachment) || attachment;
    const transfer = original.attachment_id
      ? attachmentTransferItem(original, { accountId: attachmentAccountId })
      : attachment;
    if (!transferIsCurrent(transfer, surfaceGeneration)) return;
    const index = items.findIndex(item => itemIdentity(item) === `${transfer.email_id}:${transfer.id}`);
    if (index >= 0) selectedIndex = index;
    if (returnFocusTarget instanceof HTMLElement) attachmentPreviewReturnFocus = returnFocusTarget;
    commandPaletteOpen.set(false);
    helpModalOpen.set(false);

    const previousKey = attachmentPreview ? transferKey(attachmentPreview.attachment) : null;
    transferControllers.get(previousKey)?.abort();
    if (previousKey) transferControllers.delete(previousKey);
    if (previousKey && activeTransferKeys.has(previousKey)) {
      const next = new Set(activeTransferKeys);
      next.delete(previousKey);
      activeTransferKeys = next;
    }
    releaseCurrentPreview();

    const requestedSurfaceGeneration = surfaceGeneration;
    const requestedPreviewGeneration = ++previewGeneration;
    const hint = attachmentPreviewHint(transfer);
    if (!hint) {
      attachmentPreview = previewState(transfer, 'unsupported');
      return;
    }

    const key = transferKey(transfer);
    if (!canStartAttachmentDownload(activeTransferKeys, key)) {
      attachmentPreview = previewState(transfer, 'error', {
        error: {
          retryable: true,
          message: activeTransferKeys.has(key)
            ? 'This attachment is already being transferred.'
            : `Wait for one of the ${MAX_ACTIVE_ATTACHMENT_REQUESTS} active transfers to finish.`,
        },
      });
      return;
    }

    const controller = new AbortController();
    transferControllers.set(key, controller);
    activeTransferKeys = new Set(activeTransferKeys).add(key);
    attachmentPreview = previewState(transfer, 'loading');
    try {
      const result = await api.previewAttachment(transfer.email_id, transfer.id, {
        signal: controller.signal,
      });
      const preview = await materializeAttachmentPreview(result, { expectedKind: hint });
      if (
        controller.signal.aborted
        || requestedPreviewGeneration !== previewGeneration
        || !transferIsCurrent(transfer, requestedSurfaceGeneration)
      ) {
        releaseAttachmentPreview(preview);
        return;
      }
      if (preview.kind === 'pdf') {
        releaseAttachmentPreview(preview);
        preview.blob = null;
        preview.objectUrl = null;
        preview.sourceUrl = api.attachmentPreviewUrl(transfer.email_id, transfer.id);
      }
      attachmentPreview = previewState(transfer, 'ready', { preview });
    } catch (error) {
      if (
        error?.name !== 'AbortError'
        && requestedPreviewGeneration === previewGeneration
        && transferIsCurrent(transfer, requestedSurfaceGeneration)
      ) {
        attachmentPreview = previewState(transfer, 'error', {
          notice: error?.status === 415
            ? {
                tone: 'danger',
                label: 'File contents could not be verified',
                detail: 'The attachment bytes did not match the expected preview type. Download only if you expected this file.',
                requiresConfirmation: true,
              }
            : attachmentSafetyNotice(transfer),
          error: {
            retryable: isRetryableAttachmentError(error?.status),
            message: error?.message || 'The preview could not be prepared.',
          },
        });
      }
    } finally {
      if (transferControllers.get(key) === controller) transferControllers.delete(key);
      if (activeTransferKeys.has(key)) {
        const next = new Set(activeTransferKeys);
        next.delete(key);
        activeTransferKeys = next;
      }
    }
  }

  function previewSelected() {
    if (!selectedItem) return;
    const row = document.querySelector(`[data-attachment-index="${selectedIndex}"]`);
    return openPreviewFor(
      attachmentTransferItem(selectedItem, { accountId: attachmentAccountId }),
      row,
    );
  }

  async function downloadAttachment(attachment, confirmed = false, returnFocusTarget = null) {
    const original = originalItemForTransfer(attachment) || attachment;
    const transfer = original.attachment_id
      ? attachmentTransferItem(original, { accountId: attachmentAccountId })
      : attachment;
    const requestedSurfaceGeneration = surfaceGeneration;
    if (!transferIsCurrent(transfer, requestedSurfaceGeneration)) return;
    const safetyNotice = attachmentSafetyNotice(transfer)
      || (attachmentPreview?.attachment?.id === transfer.id ? attachmentPreview.notice : null);
    if (safetyNotice?.requiresConfirmation && !confirmed) {
      if (returnFocusTarget instanceof HTMLElement) attachmentPreviewReturnFocus = returnFocusTarget;
      commandPaletteOpen.set(false);
      helpModalOpen.set(false);
      releaseCurrentPreview();
      previewGeneration += 1;
      attachmentPreview = previewState(transfer, 'confirm', { notice: safetyNotice });
      return;
    }

    const key = transferKey(transfer);
    if (!canStartAttachmentDownload(activeTransferKeys, key)) {
      const message = activeTransferKeys.has(key)
        ? 'This attachment is already being transferred.'
        : `Wait for one of the ${MAX_ACTIVE_ATTACHMENT_REQUESTS} active transfers to finish.`;
      if (attachmentPreview?.attachment?.id === transfer.id) {
        attachmentPreview = { ...attachmentPreview, downloadMode: 'error', downloadError: message };
      } else {
        statusMessage = message;
      }
      return;
    }

    const controller = new AbortController();
    transferControllers.set(key, controller);
    activeTransferKeys = new Set(activeTransferKeys).add(key);
    statusMessage = `Downloading ${safeClientFilename(transfer.filename)}…`;
    if (attachmentPreview?.attachment?.id === transfer.id) {
      attachmentPreview = { ...attachmentPreview, downloadMode: 'loading', downloadError: null };
    }
    let succeeded = false;
    try {
      const blob = await api.downloadAttachment(transfer.email_id, transfer.id, {
        signal: controller.signal,
      });
      if (controller.signal.aborted || !transferIsCurrent(transfer, requestedSurfaceGeneration)) return;
      saveAttachmentBlob(blob, transfer.filename);
      succeeded = true;
      statusMessage = `Download started for ${safeClientFilename(transfer.filename)}.`;
      if (attachmentPreview?.attachment?.id === transfer.id) {
        attachmentPreview = { ...attachmentPreview, downloadMode: 'success', downloadError: null };
      }
    } catch (error) {
      if (error?.name !== 'AbortError' && transferIsCurrent(transfer, requestedSurfaceGeneration)) {
        const message = `Couldn’t download ${safeClientFilename(transfer.filename)}. ${error?.message || 'Try again.'}`;
        statusMessage = message;
        if (attachmentPreview?.attachment?.id === transfer.id) {
          attachmentPreview = { ...attachmentPreview, downloadMode: 'error', downloadError: message };
        } else {
          showToast(message, 'error');
        }
      }
    } finally {
      if (transferControllers.get(key) === controller) transferControllers.delete(key);
      if (activeTransferKeys.has(key)) {
        const next = new Set(activeTransferKeys);
        next.delete(key);
        activeTransferKeys = next;
      }
    }
    if (confirmed && succeeded && attachmentPreview?.attachment?.id === transfer.id) closePreview();
  }

  function downloadSelected() {
    if (!selectedItem) return;
    const row = document.querySelector(`[data-attachment-index="${selectedIndex}"]`);
    return downloadAttachment(
      attachmentTransferItem(selectedItem, { accountId: attachmentAccountId }),
      false,
      row,
    );
  }

  function openParent(item = selectedItem) {
    if (!item || !attachmentAccountId) return;
    const intent = createAttachmentParentIntent(item, { accountId: attachmentAccountId });
    // Validate immediately before publishing the one-shot handoff.
    attachmentParentAnchorForAccount(intent, attachmentAccountId);
    selectedAccountId.set(intent.account_id);
    currentMailbox.set('ALL');
    searchQuery.set('');
    smartFilter.set(null);
    contactConversationIntent.set(null);
    attachmentParentIntent.set(intent);
    selectedEmailId.set(intent.email_id);
    currentPage.set('inbox');
  }

  async function loadAttachments({ append = false } = {}) {
    if (!attachmentAccountId || !sessionGuard?.isCurrent()) return;
    const accountId = attachmentAccountId;
    const requestedQuery = query.trim();
    const requestedKind = kind;
    const requestedDirection = direction;
    const cursor = append ? nextCursor : null;
    if (append && (!cursor || !hasMore || loadingMore)) return;
    const requestedSurfaceGeneration = surfaceGeneration;
    const generation = ++listGeneration;
    const controller = new AbortController();
    listController?.abort();
    listController = controller;
    if (append) loadingMore = true;
    else {
      listLoading = true;
      listError = '';
    }
    try {
      const payload = createAttachmentQueryPayload({
        accountId,
        query: requestedQuery,
        kind: requestedKind,
        direction: requestedDirection,
        cursor,
        pageSize: 50,
      });
      const response = await api.queryAttachments(payload, { signal: controller.signal });
      if (
        controller.signal.aborted
        || generation !== listGeneration
        || requestedSurfaceGeneration !== surfaceGeneration
        || !sessionGuard?.isCurrent()
      ) return;
      const normalized = normalizeAttachmentQueryResponse(response, { accountId });
      if (append) {
        const existing = new Set(items.map(itemIdentity));
        if (normalized.items.some(item => existing.has(itemIdentity(item)))) {
          throw new TypeError('Attachment pages overlapped unexpectedly.');
        }
        items = [...items, ...normalized.items];
      } else {
        items = [...normalized.items];
        selectedIndex = items.length > 0 ? 0 : -1;
      }
      nextCursor = normalized.next_cursor;
      hasMore = normalized.has_more;
    } catch (error) {
      if (
        error?.name === 'AbortError'
        || generation !== listGeneration
        || requestedSurfaceGeneration !== surfaceGeneration
        || !sessionGuard?.isCurrent()
      ) return;
      if (append) {
        statusMessage = error?.message || 'More attachments could not be loaded.';
      } else {
        items = [];
        nextCursor = null;
        hasMore = false;
        selectedIndex = -1;
        listError = error?.message || 'Attachments could not be loaded.';
      }
    } finally {
      if (generation === listGeneration && requestedSurfaceGeneration === surfaceGeneration) {
        listLoading = false;
        loadingMore = false;
      }
      if (listController === controller) listController = null;
    }
  }

  onMount(() => {
    sessionGuard = createAuthenticatedSessionGuard();
    const cleanupActions = registerActions({
      'attachments.next': {
        run: () => moveSelection(1),
        isEnabled: () => items.length > 0 && !listLoading && !attachmentPreview,
        disabledReason: 'Wait for an attachment list',
      },
      'attachments.prev': {
        run: () => moveSelection(-1),
        isEnabled: () => items.length > 0 && !listLoading && !attachmentPreview,
        disabledReason: 'Wait for an attachment list',
      },
      'attachments.preview': {
        run: previewSelected,
        isEnabled: () => Boolean(selectedItem) && !listLoading && !attachmentPreview,
        disabledReason: 'Select an attachment first',
      },
      'attachments.download': {
        run: downloadSelected,
        isEnabled: () => Boolean(selectedItem) && !listLoading && !attachmentPreview,
        disabledReason: 'Select an attachment first',
      },
      'attachments.open': {
        run: () => openParent(),
        isEnabled: () => Boolean(selectedItem) && !listLoading && !attachmentPreview,
        disabledReason: 'Select an attachment first',
      },
      'attachments.search': () => {
        searchInput?.focus({ preventScroll: true });
        searchInput?.select();
      },
      'attachments.close': {
        run: closePreview,
        isEnabled: () => Boolean(attachmentPreview),
        disabledReason: 'No attachment preview is open',
      },
    });
    requestAnimationFrame(() => searchInput?.focus({ preventScroll: true }));
    return () => {
      cleanupActions();
      listGeneration += 1;
      surfaceGeneration += 1;
      listController?.abort();
      listController = null;
      abortTransfers();
      releaseCurrentPreview();
      sessionGuard?.dispose();
      sessionGuard = null;
    };
  });

  $effect(() => {
    const available = activeAccounts;
    if (available.length === 0) {
      if (attachmentAccountId !== null || items.length > 0 || attachmentPreview) {
        resetSurface();
      }
      attachmentAccountId = null;
      return;
    }
    if (available.some(account => Number(account.id) === Number(attachmentAccountId))) return;
    const preferred = available.find(account => Number(account.id) === Number($selectedAccountId)) || available[0];
    resetSurface();
    attachmentAccountId = Number(preferred.id);
    selectedAccountId.set(Number(preferred.id));
  });

  $effect(() => {
    const accountId = attachmentAccountId;
    const requestedQuery = query.trim();
    void kind;
    void direction;
    void retryVersion;
    if (!accountId || !sessionGuard?.isCurrent()) return undefined;
    const delay = requestedQuery ? 220 : 0;
    const timer = window.setTimeout(() => { void loadAttachments(); }, delay);
    return () => window.clearTimeout(timer);
  });
</script>

<div class="attachments-page h-full min-h-0 flex flex-col" style="background: var(--bg-primary)">
  <header class="attachments-header shrink-0 border-b px-4 py-4 md:px-5" style="border-color: var(--border-color); background: var(--bg-secondary)">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold" style="color: var(--text-primary)">Attachments</h1>
        <p class="mt-1 text-sm" style="color: var(--text-secondary)">
          Find files in one connected account without loading their contents.
        </p>
      </div>
      <span class="min-h-11 inline-flex items-center rounded-full border px-3 text-xs" style="border-color: var(--border-color); color: var(--text-secondary)">
        Metadata only · previews are explicit
      </span>
    </div>

    <div class="attachment-controls mt-4 grid gap-3">
      <label class="min-w-0 text-xs font-semibold" style="color: var(--text-secondary)">
        Account
        <select
          class="mt-1 min-h-11 w-full rounded-xl border px-3 text-sm"
          style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
          value={attachmentAccountId ?? ''}
          onchange={changeAccount}
          disabled={activeAccounts.length === 0}
        >
          {#each activeAccounts as account}
            <option value={account.id}>{accountLabel(account)} · {account.email}</option>
          {/each}
        </select>
      </label>
      <label class="min-w-0 text-xs font-semibold" style="color: var(--text-secondary)">
        Search metadata
        <div class="relative mt-1">
          <Icon name="search" size={16} class="pointer-events-none absolute left-3 top-3.5" />
          <input
            bind:this={searchInput}
            class="min-h-11 w-full rounded-xl border py-2 pl-10 pr-3 text-sm"
            style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
            placeholder="Filename, subject, or sender"
            aria-label="Search attachment metadata"
            maxlength="256"
            value={query}
            oninput={changeQuery}
            disabled={!attachmentAccountId}
            data-shortcut="attachments.search"
          />
        </div>
      </label>
      <label class="min-w-0 text-xs font-semibold" style="color: var(--text-secondary)">
        Type
        <select
          class="mt-1 min-h-11 w-full rounded-xl border px-3 text-sm"
          style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
          value={kind}
          onchange={changeKind}
          disabled={!attachmentAccountId}
        >
          {#each kindOptions as option}<option value={option.id}>{option.label}</option>{/each}
        </select>
      </label>
      <label class="min-w-0 text-xs font-semibold" style="color: var(--text-secondary)">
        Direction
        <select
          class="mt-1 min-h-11 w-full rounded-xl border px-3 text-sm"
          style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
          value={direction}
          onchange={changeDirection}
          disabled={!attachmentAccountId}
        >
          {#each directionOptions as option}<option value={option.id}>{option.label}</option>{/each}
        </select>
      </label>
    </div>
  </header>

  <section class="min-h-0 flex-1 overflow-y-auto" aria-labelledby="attachment-results-heading">
    <div class="sticky top-0 z-10 flex min-h-11 items-center justify-between border-b px-4" style="border-color: var(--border-color); background: var(--bg-secondary)">
      <h2 id="attachment-results-heading" class="text-xs font-semibold uppercase tracking-wide" style="color: var(--text-tertiary)">{resultSummary()}</h2>
      {#if listLoading && items.length > 0}<span role="status" class="text-xs" style="color: var(--text-secondary)">Updating…</span>{/if}
    </div>

    {#if !attachmentAccountId}
      <div class="mx-auto max-w-md p-8 text-center">
        <Icon name="paperclip" size={30} class="mx-auto mb-3" />
        <h2 class="font-semibold" style="color: var(--text-primary)">No connected account</h2>
        <p class="mt-1 text-sm" style="color: var(--text-secondary)">{$accountsLoadError || 'Connect an email account to browse attachment metadata.'}</p>
      </div>
    {:else if listLoading && items.length === 0}
      <div class="mx-auto grid w-full max-w-5xl gap-2 p-3" role="status" aria-label="Loading attachments">
        {#each Array(7) as _}<div class="h-20 animate-pulse rounded-xl" style="background: var(--bg-tertiary)"></div>{/each}
      </div>
    {:else if listError && items.length === 0}
      <div class="mx-auto max-w-md p-8 text-center" role="alert">
        <Icon name="alert-circle" size={30} class="mx-auto mb-3" />
        <h2 class="font-semibold" style="color: var(--text-primary)">Attachments unavailable</h2>
        <p class="mt-1 text-sm" style="color: var(--text-secondary)">{listError}</p>
        <button type="button" class="mt-4 min-h-11 rounded-lg border px-4 text-sm font-semibold" style="border-color: var(--border-color)" onclick={retryList}>Retry</button>
      </div>
    {:else if items.length === 0}
      <div class="mx-auto max-w-md p-8 text-center">
        <Icon name="file-minus" size={30} class="mx-auto mb-3" />
        <h2 class="font-semibold" style="color: var(--text-primary)">No attachments found</h2>
        <p class="mt-1 text-sm" style="color: var(--text-secondary)">
          {query || kind !== 'all' || direction !== 'all'
            ? 'Try a different metadata search or filter.'
            : 'This account has no non-inline attachments in synchronized mail yet.'}
        </p>
      </div>
    {:else}
      <div role="listbox" aria-label="Attachments" aria-live="polite" class="mx-auto grid min-w-0 w-full max-w-5xl gap-2 p-3">
        {#each items as item, index (itemIdentity(item))}
          <div
            role="option"
            aria-selected={selectedIndex === index}
            data-attachment-index={index}
            tabindex={selectedIndex === index ? 0 : -1}
            class="attachment-row min-h-20 min-w-0 w-full rounded-xl border px-3 py-2"
            class:attachment-row-active={selectedIndex === index}
            onfocus={() => { selectedIndex = index; }}
            onkeydown={(event) => {
              if (event.key !== 'Enter' || event.target !== event.currentTarget) return;
              event.preventDefault();
              event.stopPropagation();
              selectedIndex = index;
              void openPreviewFor(attachmentTransferItem(item, { accountId: attachmentAccountId }), event.currentTarget);
            }}
            onclick={(event) => {
              selectedIndex = index;
              void openPreviewFor(attachmentTransferItem(item, { accountId: attachmentAccountId }), event.currentTarget);
            }}
          >
            <div class="flex min-w-0 items-center gap-3">
              <span class="flex size-11 shrink-0 items-center justify-center rounded-xl" aria-hidden="true" style="background: var(--bg-tertiary); color: var(--text-secondary)">
                <Icon name={item.content_type.startsWith('image/') ? 'image' : 'file-text'} size={20} />
              </span>
              <span class="min-w-0 flex-1">
                <span class="block truncate text-sm font-semibold" title={safeClientFilename(item.filename)} style="color: var(--text-primary)">{safeClientFilename(item.filename)}</span>
                <span class="block truncate text-xs" title={subjectLabel(item)} style="color: var(--text-secondary)">{subjectLabel(item)}</span>
                <span class="mt-0.5 block truncate text-[11px]" style="color: var(--text-tertiary)">{senderLabel(item)} · {formatAttachmentLibraryDate(item.message_date)} · {formatAttachmentLibrarySize(item.size_bytes)}</span>
              </span>
              <span class="attachment-row-actions flex shrink-0 items-center gap-1">
                <button
                  type="button"
                  class="min-h-11 min-w-11 rounded-lg"
                  aria-label="Download {safeClientFilename(item.filename)}"
                  title="Download"
                  onclick={(event) => {
                    event.stopPropagation();
                    selectedIndex = index;
                    void downloadAttachment(attachmentTransferItem(item, { accountId: attachmentAccountId }), false, event.currentTarget);
                  }}
                ><Icon name="download" size={17} /></button>
                <button
                  type="button"
                  class="min-h-11 min-w-11 rounded-lg"
                  aria-label="Open email containing {safeClientFilename(item.filename)}"
                  title="Open containing email"
                  onclick={(event) => { event.stopPropagation(); selectedIndex = index; openParent(item); }}
                ><Icon name="mail" size={17} /></button>
              </span>
            </div>
          </div>
        {/each}
      </div>

      {#if hasMore}
        <div class="flex justify-center px-4 pb-6">
          <button type="button" class="min-h-11 rounded-xl border px-5 text-sm font-semibold disabled:opacity-50" style="border-color: var(--border-color)" disabled={loadingMore} onclick={() => { void loadAttachments({ append: true }); }}>
            {loadingMore ? 'Loading…' : 'Load more'}
          </button>
        </div>
      {/if}
    {/if}
  </section>

  {#if statusMessage}
    <div class="shrink-0 border-t px-4 py-2 text-xs" role="status" aria-live="polite" style="border-color: var(--border-color); color: var(--text-secondary); background: var(--bg-secondary)">{statusMessage}</div>
  {/if}
</div>

{#if attachmentPreview}
  <AttachmentPreview
    viewerState={attachmentPreview}
    attachments={transferItems}
    returnFocusTarget={attachmentPreviewReturnFocus}
    onclose={closePreview}
    onselect={openPreviewFor}
    onretry={openPreviewFor}
    ondownload={downloadAttachment}
  />
{/if}

<style>
  .attachment-controls {
    grid-template-columns: minmax(13rem, 0.9fr) minmax(16rem, 1.6fr) minmax(10rem, 0.65fr) minmax(10rem, 0.65fr);
  }

  .attachment-row {
    box-sizing: border-box;
    cursor: pointer;
    max-width: 100%;
    overflow: hidden;
    border-color: var(--border-color);
    background: var(--bg-secondary);
  }

  .attachment-row:hover,
  .attachment-row:focus-visible,
  .attachment-row-active {
    background: var(--bg-hover);
  }

  .attachment-row-active {
    border-color: var(--color-accent-500);
    box-shadow: inset 3px 0 var(--color-accent-500);
  }

  .attachment-row-actions button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--text-secondary);
  }

  .attachment-row-actions button:hover,
  .attachment-row-actions button:focus-visible {
    background: var(--bg-tertiary);
    color: var(--text-primary);
  }

  @media (max-width: 900px) {
    .attachment-controls { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }

  @media (max-width: 520px) {
    .attachments-header { padding-inline: 12px; }
    .attachment-controls { grid-template-columns: minmax(0, 1fr); }
    .attachment-row-actions { align-self: stretch; }
    .attachment-row { padding-inline: 10px; }
  }
</style>
