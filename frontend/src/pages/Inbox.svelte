<script>
  import { onMount, untrack } from 'svelte';
  import { get } from 'svelte/store';
  import { api } from '../lib/api.js';
  import {
    emails, emailsLoading, emailsTotal, currentPageNum,
    currentMailbox, selectedEmailId, selectedAccountId,
    searchQuery, showToast, pageSize, viewMode, smartFilter,
  } from '../lib/stores.js';
  import EmailList from '../components/email/EmailList.svelte';
  import EmailTable from '../components/email/EmailTable.svelte';
  import EmailView from '../components/email/EmailView.svelte';

  let selectedEmail = $state(null);
  let emailLoading = $state(false);
  let loadingMore = $state(false);
  let mounted = $state(false);
  let hasMore = $state(false);

  // Resizable panel splits (persisted)
  let columnListWidth = $state(parseInt(localStorage.getItem('columnListWidth') || '380', 10));
  let tableTopPct = $state(parseInt(localStorage.getItem('tableTopPct') || '45', 10));
  let panelDragging = $state(false);
  let containerEl = $state(null);

  onMount(() => {
    mounted = true;
    loadEmails(false);
  });

  $effect(() => {
    void $currentMailbox;
    void $selectedAccountId;
    void $searchQuery;
    void $smartFilter;
    if (!mounted) return;
    currentPageNum.set(1);
    selectedEmailId.set(null);
    selectedEmail = null;
    untrack(() => { loadEmails(false); });
  });

  $effect(() => {
    const eid = $selectedEmailId;
    if (eid) {
      untrack(() => { loadEmail(eid); });
    } else {
      selectedEmail = null;
    }
  });

  async function loadEmails(append) {
    if (append) { loadingMore = true; } else { emailsLoading.set(true); }
    try {
      const params = {
        mailbox: get(currentMailbox),
        page: get(currentPageNum),
        page_size: get(pageSize),
      };
      const acctId = get(selectedAccountId);
      if (acctId) params.account_id = acctId;
      const sq = get(searchQuery);
      if (sq) params.search = sq;
      const sf = get(smartFilter);
      if (sf) {
        if (sf.type === 'needs_reply') {
          params.needs_reply = true;
        } else if (sf.type === 'ai_category') {
          params.ai_category = sf.value;
        } else if (sf.type === 'ai_email_type') {
          params.ai_email_type = sf.value;
        }
      }
      const result = await api.listEmails(params);
      if (append) {
        emails.update(existing => {
          const existingIds = new Set(existing.map(e => e.id));
          const newOnes = result.emails.filter(e => !existingIds.has(e.id));
          return [...existing, ...newOnes];
        });
      } else {
        emails.set(result.emails);
      }
      emailsTotal.set(result.total);
      const currentPage = get(currentPageNum);
      const ps = get(pageSize);
      hasMore = (currentPage * ps) < result.total;
    } catch (err) {
      if (err.message !== 'Unauthorized') showToast(err.message, 'error');
    }
    emailsLoading.set(false);
    loadingMore = false;
  }

  function handleLoadMore() {
    if (loadingMore || !hasMore) return;
    currentPageNum.set(get(currentPageNum) + 1);
    loadEmails(true);
  }

  async function loadEmail(id) {
    emailLoading = true;
    try {
      selectedEmail = await api.getEmail(id);
      if (!selectedEmail.is_read) {
        await api.emailActions([id], 'mark_read');
        emails.update(list => list.map(e => e.id === id ? { ...e, is_read: true } : e));
      }
    } catch (err) { showToast(err.message, 'error'); }
    emailLoading = false;
  }

  async function handleAction(action, emailIds) {
    try {
      await api.emailActions(emailIds, action);
      showToast(`${action.replace('_', ' ')} applied`, 'success');
      currentPageNum.set(1);
      await loadEmails(false);
      if (action === 'trash' || action === 'spam' || action === 'archive') selectedEmailId.set(null);
    } catch (err) { showToast(err.message, 'error'); }
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

<div class="h-full flex" class:select-none={panelDragging}>
  {#if $viewMode === 'table'}
    <!-- Table view: vertical split (table on top, preview below) -->
    <div class="flex flex-col w-full h-full overflow-hidden" bind:this={containerEl}>
      <div class="overflow-hidden" style="flex: {$selectedEmailId ? '0 0 ' + tableTopPct + '%' : '1 1 auto'}; min-height: 150px">
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
          onSelect={(id) => selectedEmailId.set(id)}
          onAction={handleAction}
          onLoadMore={handleLoadMore}
        />
      </div>
      {#if $selectedEmailId}
        <!-- Vertical drag handle -->
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div
          class="shrink-0 flex items-center justify-center cursor-row-resize group"
          style="height: 7px; background: var(--bg-secondary); border-top: 1px solid var(--border-color); border-bottom: 1px solid var(--border-color)"
          onmousedown={startVResize}
        >
          <div class="w-10 h-1 rounded-full transition-colors group-hover:bg-accent-500" style="background: var(--border-color)"></div>
        </div>
        <div class="flex-1 min-h-0 overflow-hidden">
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
      class="flex flex-col overflow-hidden shrink-0"
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
        onSelect={(id) => selectedEmailId.set(id)}
        onAction={handleAction}
        onLoadMore={handleLoadMore}
      />
    </div>
    {#if $selectedEmailId}
      <!-- Horizontal drag handle -->
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div
        class="shrink-0 flex items-center justify-center cursor-col-resize group"
        style="width: 7px; background: var(--bg-secondary); border-left: 1px solid var(--border-color); border-right: 1px solid var(--border-color)"
        onmousedown={startHResize}
      >
        <div class="h-10 w-1 rounded-full transition-colors group-hover:bg-accent-500" style="background: var(--border-color)"></div>
      </div>
      <div class="flex-1 min-w-0 overflow-hidden">
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
