<script>
  import { onDestroy, onMount, untrack } from 'svelte';
  import { get } from 'svelte/store';
  import { api } from '../lib/api.js';
  import {
    emails, emailsLoading, emailsTotal, currentPageNum,
    currentMailbox, selectedEmailId, selectedAccountId,
    searchQuery, showToast, pageSize, viewMode, smartFilter,
    hideIgnored, sidebarCollapsed,
  } from '../lib/stores.js';
  import { registerActions } from '../lib/shortcutStore.js';
  import { lastEvent } from '../lib/realtime.js';
  import { canActOnInboxEmails, createLatestRequestGuard, inboxDatasetKey } from '../lib/inboxDataset.js';
  import EmailList from '../components/email/EmailList.svelte';
  import EmailTable from '../components/email/EmailTable.svelte';
  import EmailView from '../components/email/EmailView.svelte';
  import Icon from '../components/common/Icon.svelte';

  let selectedEmail = $state(null);
  let emailLoading = $state(false);
  let loadingMore = $state(false);
  let mounted = $state(false);
  let hasMore = $state(false);
  let datasetAuthoritative = $state(false);
  let datasetUpdating = $state(false);
  let datasetError = $state(false);
  let selectionEpoch = $state(0);
  let narrowViewport = $state(window.matchMedia('(max-width: 767px)').matches);
  let useTableLayout = $derived($viewMode === 'table' && !narrowViewport);

  const listRequests = createLatestRequestGuard();
  const emailRequests = createLatestRequestGuard();
  let requestedDatasetKey = null;
  let committedDatasetKey = null;

  // Resizable panel splits (persisted)
  let columnListWidth = $state(parseInt(localStorage.getItem('columnListWidth') || '380', 10));
  let tableTopPct = $state(parseInt(localStorage.getItem('tableTopPct') || '45', 10));
  let panelDragging = $state(false);
  let containerEl = $state(null);

  onMount(() => {
    mounted = true;
    const narrowViewportQuery = window.matchMedia('(max-width: 767px)');
    const updateNarrowViewport = () => {
      narrowViewport = narrowViewportQuery.matches;
    };
    updateNarrowViewport();
    narrowViewportQuery.addEventListener('change', updateNarrowViewport);

    // Register keyboard shortcut actions for the inbox
    const cleanupShortcuts = registerActions({
      'inbox.next': () => navigateEmails(1),
      'inbox.prev': () => navigateEmails(-1),
      'inbox.open': () => { /* email opens on selection via the effect */ },
      'inbox.archive': () => {
        if ($selectedEmailId) handleAction('archive', [$selectedEmailId]);
      },
      'inbox.trash': () => {
        if ($selectedEmailId) handleAction('trash', [$selectedEmailId]);
      },
      'inbox.star': () => {
        if ($selectedEmailId) handleAction('star', [$selectedEmailId]);
      },
      'inbox.read': () => {
        if ($selectedEmailId) handleAction('mark_read', [$selectedEmailId]);
      },
      'inbox.unread': () => {
        if ($selectedEmailId) handleAction('mark_unread', [$selectedEmailId]);
      },
      'inbox.spam': () => {
        if ($selectedEmailId) handleAction('spam', [$selectedEmailId]);
      },
      'inbox.reply': () => {
        // Handled by EmailView internally if open
      },
      'inbox.forward': () => {
        // Handled by EmailView internally if open
      },
      'inbox.viewMode': () => {
        const current = get(viewMode);
        const next = current === 'table' ? 'column' : 'table';
        viewMode.set(next);
        localStorage.setItem('viewMode', next);
      },
      'inbox.sidebar': () => {
        sidebarCollapsed.update(v => !v);
      },
      'inbox.focused': () => {
        hideIgnored.update(v => !v);
      },
    });

    return () => {
      cleanupShortcuts();
      narrowViewportQuery.removeEventListener('change', updateNarrowViewport);
    };
  });

  onDestroy(() => {
    // Requests are guarded per component instance. Invalidate them before this
    // instance disappears so a late response cannot write into the shared
    // inbox stores after a newly mounted Inbox has committed newer results.
    mounted = false;
    listRequests.invalidate();
    emailRequests.invalidate();
    selectionEpoch += 1;
    datasetAuthoritative = false;
    datasetUpdating = false;
    selectedEmailId.set(null);
    selectedEmail = null;
    emailLoading = false;
    loadingMore = false;
    emailsLoading.set(false);
  });

  function navigateEmails(direction) {
    if (!datasetAuthoritative) return;
    const list = get(emails);
    if (!list || list.length === 0) return;
    const currentId = get(selectedEmailId);
    const currentIdx = list.findIndex(e => e.id === currentId);
    let nextIdx;
    if (currentIdx === -1) {
      nextIdx = direction > 0 ? 0 : list.length - 1;
    } else {
      nextIdx = currentIdx + direction;
    }
    if (nextIdx >= 0 && nextIdx < list.length) {
      selectedEmailId.set(list[nextIdx].id);
    }
  }

  $effect(() => {
    const snapshot = {
      mailbox: $currentMailbox,
      accountId: $selectedAccountId,
      search: $searchQuery,
      smartFilter: $smartFilter,
      hideIgnored: $hideIgnored,
      pageSize: $pageSize,
      page: 1,
    };
    snapshot.key = inboxDatasetKey(snapshot);

    if (!mounted) return;
    if (snapshot.key === requestedDatasetKey) return;
    requestedDatasetKey = snapshot.key;
    currentPageNum.set(1);
    untrack(() => { loadEmails(false, snapshot); });
  });

  $effect(() => {
    const eid = $selectedEmailId;
    const canLoad = datasetAuthoritative;
    emailRequests.invalidate();
    if (eid && canLoad) {
      untrack(() => { loadEmail(eid); });
    } else {
      selectedEmail = null;
      emailLoading = false;
    }
  });

  $effect(() => {
    const evt = $lastEvent;
    if (!evt || !mounted) return;
    if (evt.type === 'new_emails' || evt.type === 'emails_updated') {
      untrack(() => { refreshDataset(); });
    }
  });

  function currentDatasetSnapshot(page = get(currentPageNum)) {
    const snapshot = {
      mailbox: get(currentMailbox),
      accountId: get(selectedAccountId),
      search: get(searchQuery),
      smartFilter: get(smartFilter),
      hideIgnored: get(hideIgnored),
      pageSize: get(pageSize),
      page,
    };
    snapshot.key = inboxDatasetKey(snapshot);
    return snapshot;
  }

  function invalidateInboxSelection() {
    selectionEpoch += 1;
    selectedEmailId.set(null);
    selectedEmail = null;
    emailRequests.invalidate();
    emailLoading = false;
  }

  function refreshDataset() {
    if (!mounted) return Promise.resolve(false);
    currentPageNum.set(1);
    return loadEmails(false, currentDatasetSnapshot(1));
  }

  async function loadEmails(append, snapshot = currentDatasetSnapshot()) {
    if (!mounted) return false;
    const requestId = listRequests.begin();
    if (append) {
      loadingMore = true;
    } else {
      datasetAuthoritative = false;
      datasetUpdating = true;
      datasetError = false;
      emailsLoading.set(true);
      loadingMore = false;
      invalidateInboxSelection();
    }

    try {
      const sf = snapshot.smartFilter;
      let result;

      if (sf && sf.type === 'needs_reply_ignored') {
        const paginationParams = { page: snapshot.page, page_size: snapshot.pageSize };
        result = await api.getNeedsReplyIgnored(paginationParams);
      } else if (sf && sf.type === 'needs_reply_snoozed') {
        const paginationParams = { page: snapshot.page, page_size: snapshot.pageSize };
        result = await api.getNeedsReplySnoozed(paginationParams);
      } else {
        const params = {
          mailbox: snapshot.mailbox,
          page: snapshot.page,
          page_size: snapshot.pageSize,
        };
        const acctId = snapshot.accountId;
        if (acctId) params.account_id = acctId;
        const sq = snapshot.search;
        if (sq) params.search = sq;
        if (sf) {
          if (sf.type === 'needs_reply') {
            params.needs_reply = true;
          } else if (sf.type === 'ai_category') {
            params.ai_category = sf.value;
          } else if (sf.type === 'ai_email_type') {
            params.ai_email_type = sf.value;
          }
        }
        if (snapshot.hideIgnored) {
          params.exclude_ai_category = 'can_ignore';
        }
        result = await api.listEmails(params);
      }

      if (!listRequests.isCurrent(requestId)) return false;

      if (append) {
        emails.update(existing => {
          const existingIds = new Set(existing.map(e => e.id));
          const newOnes = result.emails.filter(e => !existingIds.has(e.id));
          return [...existing, ...newOnes];
        });
      } else {
        emails.set(result.emails);
        committedDatasetKey = snapshot.key;
        datasetAuthoritative = true;
        datasetError = false;
      }
      emailsTotal.set(result.total);
      hasMore = (snapshot.page * snapshot.pageSize) < result.total;
      return true;
    } catch (err) {
      if (!listRequests.isCurrent(requestId)) return false;
      if (err.message !== 'Unauthorized') showToast(err.message, 'error');
      if (!append) {
        datasetError = true;
        if (committedDatasetKey === snapshot.key) {
          datasetAuthoritative = true;
        } else {
          emails.set([]);
          emailsTotal.set(0);
          hasMore = false;
        }
      }
      return false;
    } finally {
      if (listRequests.isCurrent(requestId)) {
        if (!append) {
          emailsLoading.set(false);
          datasetUpdating = false;
        }
        loadingMore = false;
      }
    }
  }

  async function handleRestoreFromIgnored(emailId) {
    if (!canActOnEmails([emailId])) return;
    const actionEpoch = selectionEpoch;
    try {
      await api.unignoreNeedsReply(emailId);
      if (actionEpoch !== selectionEpoch) return;
      showToast('Restored to needs reply', 'success');
      emails.update(list => list.filter(e => e.id !== emailId));
      emailsTotal.update(t => Math.max(0, t - 1));
      if (get(selectedEmailId) === emailId) {
        selectedEmailId.set(null);
        selectedEmail = null;
      }
    } catch (err) {
      if (actionEpoch === selectionEpoch) showToast(err.message, 'error');
    }
  }

  async function handleRestoreFromSnoozed(emailId) {
    if (!canActOnEmails([emailId])) return;
    const actionEpoch = selectionEpoch;
    try {
      await api.unsnoozeNeedsReply(emailId);
      if (actionEpoch !== selectionEpoch) return;
      showToast('Unsnooze — restored to needs reply', 'success');
      emails.update(list => list.filter(e => e.id !== emailId));
      emailsTotal.update(t => Math.max(0, t - 1));
      if (get(selectedEmailId) === emailId) {
        selectedEmailId.set(null);
        selectedEmail = null;
      }
    } catch (err) {
      if (actionEpoch === selectionEpoch) showToast(err.message, 'error');
    }
  }

  async function handleLoadMore() {
    if (!datasetAuthoritative || datasetUpdating || loadingMore || !hasMore) return;
    const previousPage = get(currentPageNum);
    const nextPage = previousPage + 1;
    currentPageNum.set(nextPage);
    const loaded = await loadEmails(true, currentDatasetSnapshot(nextPage));
    if (!loaded && mounted && get(currentPageNum) === nextPage) {
      currentPageNum.set(previousPage);
    }
  }

  async function loadEmail(id) {
    const requestId = emailRequests.begin();
    emailLoading = true;
    try {
      const result = await api.getEmail(id);
      if (!isCurrentEmailRequest(requestId, id)) return;
      selectedEmail = result;
      if (!result.is_read) {
        await api.emailActions([id], 'mark_read');
        if (!isCurrentEmailRequest(requestId, id)) return;
        emails.update(list => list.map(e => e.id === id ? { ...e, is_read: true } : e));
      }
    } catch (err) {
      if (emailRequests.isCurrent(requestId)) showToast(err.message, 'error');
    } finally {
      if (emailRequests.isCurrent(requestId)) emailLoading = false;
    }
  }

  function isCurrentEmailRequest(requestId, emailId) {
    return emailRequests.isCurrent(requestId)
      && datasetAuthoritative
      && get(selectedEmailId) === emailId;
  }

  function handleSelect(emailId) {
    if (!datasetAuthoritative) return;
    if (!get(emails).some(email => email.id === emailId)) return;
    selectedEmailId.set(emailId);
  }

  function canActOnEmails(emailIds, notify = true) {
    const canAct = canActOnInboxEmails({
      authoritative: mounted && datasetAuthoritative,
      emailIds,
      visibleEmailIds: get(emails).map(email => email.id),
      selectedEmailId: get(selectedEmailId),
      selectedDetailId: selectedEmail?.id ?? null,
    });

    if (!canAct && notify) {
      showToast('Wait for the current inbox results before applying actions', 'info');
    }
    return canAct;
  }

  async function handleAction(action, emailIds) {
    if (!canActOnEmails(emailIds)) return;
    const actionEpoch = selectionEpoch;
    try {
      await api.emailActions(emailIds, action);
      if (actionEpoch !== selectionEpoch) return;
      showToast(`${action.replace('_', ' ')} applied`, 'success');
      await refreshDataset();
      if (action === 'trash' || action === 'spam' || action === 'archive') selectedEmailId.set(null);
    } catch (err) {
      if (actionEpoch === selectionEpoch) showToast(err.message, 'error');
    }
  }

  // --- Horizontal resize (column view: list | preview) ---
  function startHResize(e) {
    e.preventDefault();
    panelDragging = true;
    const startX = e.clientX;
    const startW = columnListWidth;

    function onMove(ev) {
      const delta = ev.clientX - startX;
      columnListWidth = Math.max(280, Math.min(startW + delta, 800));
    }
    function onUp() {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      panelDragging = false;
      localStorage.setItem('columnListWidth', String(columnListWidth));
    }
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }

  // --- Vertical resize (table view: table / preview) ---
  function startVResize(e) {
    e.preventDefault();
    panelDragging = true;
    const startY = e.clientY;
    const startPct = tableTopPct;

    function onMove(ev) {
      if (!containerEl) return;
      const rect = containerEl.getBoundingClientRect();
      const totalH = rect.height;
      const delta = ev.clientY - startY;
      const deltaPct = (delta / totalH) * 100;
      tableTopPct = Math.max(20, Math.min(startPct + deltaPct, 80));
    }
    function onUp() {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      panelDragging = false;
      localStorage.setItem('tableTopPct', String(Math.round(tableTopPct)));
    }
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }
</script>

<div class="inbox-page h-full flex flex-col" class:select-none={panelDragging} aria-busy={datasetUpdating}>
  {#if $smartFilter?.type === 'needs_reply_ignored' || $smartFilter?.type === 'needs_reply_snoozed'}
    <div class="flex items-center gap-2 px-4 py-2 border-b" style="background: var(--bg-tertiary); border-color: var(--border-color)">
      <Icon name={$smartFilter.type === 'needs_reply_ignored' ? 'eye-off' : 'clock'} size={14} />
      <span class="text-xs font-medium" style="color: var(--text-secondary)">
        {$smartFilter.type === 'needs_reply_ignored' ? 'Ignored needs-reply emails' : 'Snoozed needs-reply emails'}
      </span>
      {#if $selectedEmailId}
        <button
          onclick={() => {
            if ($smartFilter.type === 'needs_reply_ignored') {
              handleRestoreFromIgnored($selectedEmailId);
            } else {
              handleRestoreFromSnoozed($selectedEmailId);
            }
          }}
          class="ml-auto flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium transition-fast border"
          disabled={!datasetAuthoritative}
          style="border-color: var(--border-color); color: var(--text-secondary)"
        >
          <Icon name="rotate-ccw" size={12} />
          {$smartFilter.type === 'needs_reply_ignored' ? 'Unignore' : 'Unsnooze'}
        </button>
      {/if}
    </div>
  {/if}
  {#if datasetUpdating}
    <div
      class="flex items-center gap-2 px-4 py-2 border-b shrink-0"
      style="background: var(--bg-tertiary); border-color: var(--border-color); color: var(--text-secondary)"
      role="status"
      aria-live="polite"
    >
      <div class="w-3.5 h-3.5 border-2 rounded-full animate-spin shrink-0" style="border-color: var(--border-color); border-top-color: var(--color-accent-500)"></div>
      <span class="text-xs font-medium">Updating inbox…</span>
      <span class="text-xs hidden sm:inline" style="color: var(--text-tertiary)">Actions will be available when these results finish loading.</span>
    </div>
  {:else if datasetError}
    <div
      class="flex items-center gap-2 px-4 py-2 border-b shrink-0"
      style="background: var(--bg-tertiary); border-color: var(--border-color); color: var(--text-secondary)"
      role="alert"
    >
      <Icon name="alert-circle" size={14} />
      <span class="text-xs font-medium">
        {datasetAuthoritative ? 'Could not refresh. Showing previous results.' : 'Inbox results could not be updated.'}
      </span>
      <button
        onclick={refreshDataset}
        class="ml-auto px-2.5 py-1 rounded-md border text-xs font-medium"
        style="border-color: var(--border-color); color: var(--color-accent-600)"
      >
        Try again
      </button>
    </div>
  {/if}
  <div class="inbox-split flex-1 min-h-0 flex">
  {#if useTableLayout}
    <!-- Table view: vertical split (table on top, preview below) -->
    <div class="flex flex-col w-full h-full overflow-hidden" bind:this={containerEl}>
      <div class="email-list-pane overflow-hidden" class:mobile-hidden={Boolean($selectedEmailId)} style="flex: {$selectedEmailId ? '0 0 ' + tableTopPct + '%' : '1 1 auto'}; min-height: 150px">
        <EmailTable
          emails={$emails}
          loading={$emailsLoading}
          {loadingMore}
          {hasMore}
          total={$emailsTotal}
          selectedId={$selectedEmailId}
          mailbox={$currentMailbox}
          searchActive={!!$searchQuery}
          searchTerm={$searchQuery}
          loadFailed={datasetError && !datasetAuthoritative}
          actionsDisabled={!datasetAuthoritative}
          {selectionEpoch}
          onSelect={handleSelect}
          onAction={handleAction}
          onLoadMore={handleLoadMore}
        />
      </div>
      {#if $selectedEmailId}
        <!-- Vertical drag handle -->
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div
          class="email-resize-handle shrink-0 flex items-center justify-center cursor-row-resize group"
          style="height: 7px; background: var(--bg-secondary); border-top: 1px solid var(--border-color); border-bottom: 1px solid var(--border-color)"
          onmousedown={startVResize}
        >
          <div class="w-10 h-1 rounded-full transition-colors group-hover:bg-accent-500" style="background: var(--border-color)"></div>
        </div>
        <div class="email-preview-pane flex-1 min-h-0 overflow-hidden">
          <EmailView
            email={selectedEmail}
            loading={emailLoading}
            onAction={handleAction}
            onClose={() => selectedEmailId.set(null)}
          />
        </div>
      {/if}
    </div>
  {:else}
    <!-- Column view: horizontal split (list on left, preview on right) -->
    <div
      class="email-list-pane flex flex-col overflow-hidden shrink-0"
      class:mobile-hidden={Boolean($selectedEmailId)}
      style="border-right: 1px solid var(--border-color); width: {$selectedEmailId ? columnListWidth + 'px' : '100%'}; min-width: {$selectedEmailId ? '280px' : 'auto'}"
    >
      <EmailList
        emails={$emails}
        loading={$emailsLoading}
        {loadingMore}
        {hasMore}
        total={$emailsTotal}
        selectedId={$selectedEmailId}
        mailbox={$currentMailbox}
        searchActive={!!$searchQuery}
        searchTerm={$searchQuery}
        loadFailed={datasetError && !datasetAuthoritative}
        actionsDisabled={!datasetAuthoritative}
        {selectionEpoch}
        onSelect={handleSelect}
        onAction={handleAction}
        onLoadMore={handleLoadMore}
      />
    </div>
    {#if $selectedEmailId}
      <!-- Horizontal drag handle -->
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div
        class="email-resize-handle shrink-0 flex items-center justify-center cursor-col-resize group"
        style="width: 7px; background: var(--bg-secondary); border-left: 1px solid var(--border-color); border-right: 1px solid var(--border-color)"
        onmousedown={startHResize}
      >
        <div class="h-10 w-1 rounded-full transition-colors group-hover:bg-accent-500" style="background: var(--border-color)"></div>
      </div>
      <div class="email-preview-pane flex-1 min-w-0 overflow-hidden">
        <EmailView
          email={selectedEmail}
          loading={emailLoading}
          onAction={handleAction}
          onClose={() => selectedEmailId.set(null)}
        />
      </div>
    {/if}
  {/if}
  </div>
</div>

<style>
  @media (max-width: 767px) {
    .email-list-pane {
      width: 100% !important;
      min-width: 0 !important;
      min-height: 0 !important;
      border-right: 0 !important;
      flex: 1 1 auto !important;
    }
    .email-preview-pane {
      width: 100%;
      flex: 1 1 auto;
    }
    .email-resize-handle,
    .mobile-hidden {
      display: none !important;
    }
  }
</style>
