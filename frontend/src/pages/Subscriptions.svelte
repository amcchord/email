<script>
  import { onMount } from 'svelte';
  import Icon from '../components/common/Icon.svelte';
  import EmailView from '../components/email/EmailView.svelte';
  import UnsubscribeViewer from '../components/email/UnsubscribeViewer.svelte';
  import { api } from '../lib/api.js';
  import { showToast } from '../lib/stores.js';

  let loading = $state(true);
  let senders = $state([]);
  let totalSenders = $state(0);
  let page = $state(1);
  let pageSize = 50;

  let statusFilter = $state('all');
  let searchQuery = $state('');
  let sortBy = $state('count');
  let searchTimeout = $state(null);

  let selected = $state(new Set());
  let selectAll = $state(false);

  // Email preview state
  let previewSender = $state(null);
  let previewEmail = $state(null);
  let previewLoading = $state(false);
  let dividerY = $state(null);
  let isDragging = $state(false);

  // Unsubscribe modal state
  let showUnsubModal = $state(false);
  let unsubTarget = $state(null);
  let unsubMarkSpam = $state(true);
  let unsubInProgress = $state(false);
  let unsubStreamEmailId = $state(null);

  // Bulk progress
  let bulkInProgress = $state(false);
  let bulkResults = $state(null);
  let bulkUrlQueue = $state([]);
  let bulkCurrentUrlIdx = $state(-1);

  async function loadSubscriptions() {
    loading = true;
    try {
      const data = await api.getSubscriptions({
        page,
        page_size: pageSize,
        status: statusFilter,
        search: searchQuery,
        sort: sortBy,
      });
      senders = data.senders || [];
      totalSenders = data.total || 0;
    } catch (err) {
      showToast('Failed to load subscriptions: ' + err.message, 'error');
    }
    loading = false;
  }

  onMount(() => {
    loadSubscriptions();
    const saved = localStorage.getItem('subs_divider_y');
    if (saved) {
      dividerY = parseInt(saved, 10);
    }
  });

  function onSearchInput(e) {
    if (searchTimeout) clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
      searchQuery = e.target.value;
      page = 1;
      loadSubscriptions();
    }, 300);
  }

  function setStatusFilter(s) {
    statusFilter = s;
    page = 1;
    selected = new Set();
    selectAll = false;
    loadSubscriptions();
  }

  function setSortBy(s) {
    sortBy = s;
    page = 1;
    loadSubscriptions();
  }

  function toggleSelect(e, emailId) {
    e.stopPropagation();
    const next = new Set(selected);
    if (next.has(emailId)) {
      next.delete(emailId);
    } else {
      next.add(emailId);
    }
    selected = next;
    selectAll = next.size === senders.length;
  }

  function toggleSelectAll() {
    if (selectAll) {
      selected = new Set();
      selectAll = false;
    } else {
      selected = new Set(senders.map(s => s.sample_email_id));
      selectAll = true;
    }
  }

  async function selectSender(sender) {
    if (previewSender?.domain === sender.domain && previewEmail) return;
    previewSender = sender;
    previewEmail = null;
    previewLoading = true;
    try {
      previewEmail = await api.getEmail(sender.sample_email_id);
    } catch (err) {
      showToast('Failed to load email preview', 'error');
    }
    previewLoading = false;
  }

  function closePreview() {
    previewSender = null;
    previewEmail = null;
  }

  function openUnsubscribe(e, sender) {
    e.stopPropagation();
    unsubTarget = sender;
    unsubMarkSpam = true;
    unsubInProgress = false;
    unsubStreamEmailId = null;
    showUnsubModal = true;
  }

  async function confirmUnsubscribe() {
    if (!unsubTarget) return;
    unsubInProgress = true;

    const info = unsubTarget.unsubscribe_info;
    const hasEmail = info && info.email;
    const hasUrl = info && info.url;

    if (!hasEmail && !hasUrl) {
      showToast('No unsubscribe method available for this sender', 'error');
      unsubInProgress = false;
      return;
    }

    if (hasEmail) {
      try {
        const result = await api.unsubscribe(unsubTarget.sample_email_id, {
          markSpam: unsubMarkSpam,
        });
        if (result.email_sent) {
          showToast(`Unsubscribe email sent for ${unsubTarget.from_name}`, 'success');
          unsubTarget.unsubscribe_status = 'success';
          unsubTarget.unsubscribed_at = new Date().toISOString();
        } else if (result.email_error) {
          showToast(`Failed: ${result.email_error}`, 'error');
        }
        unsubInProgress = false;
        if (!hasUrl) {
          showUnsubModal = false;
          loadSubscriptions();
          return;
        }
      } catch (err) {
        showToast('Unsubscribe failed: ' + err.message, 'error');
        unsubInProgress = false;
        if (!hasUrl) return;
      }
    }

    if (hasUrl) {
      unsubStreamEmailId = unsubTarget.sample_email_id;
    }
  }

  async function confirmBlock() {
    if (!unsubTarget) return;
    unsubInProgress = true;
    try {
      await api.blockSender(unsubTarget.sample_email_id);
      showToast(`Blocked ${unsubTarget.from_name || unsubTarget.domain} and marked as spam`, 'success');
      showUnsubModal = false;
      unsubInProgress = false;
      loadSubscriptions();
    } catch (err) {
      showToast('Block failed: ' + err.message, 'error');
      unsubInProgress = false;
    }
  }

  function onStreamComplete(status) {
    unsubInProgress = false;
    if (status === 'success') {
      showToast(`Unsubscribed from ${unsubTarget?.from_name || 'sender'}`, 'success');
      loadSubscriptions();
    }
  }

  function closeModal() {
    showUnsubModal = false;
    unsubTarget = null;
    unsubStreamEmailId = null;
    unsubInProgress = false;
    if (bulkCurrentUrlIdx >= 0) {
      bulkUrlQueue = [];
      bulkCurrentUrlIdx = -1;
    }
  }

  async function bulkUnsubscribe() {
    if (selected.size === 0) return;
    bulkInProgress = true;
    bulkResults = null;

    try {
      const result = await api.bulkUnsubscribe([...selected], { markSpam: true });
      bulkResults = result;

      if (result.successful > 0) {
        showToast(`Unsubscribed from ${result.successful} sender(s) via email`, 'success');
      }

      const urlItems = (result.results || []).filter(r => r.needs_browser);
      if (urlItems.length > 0) {
        bulkUrlQueue = urlItems.map(r => r.email_id);
        bulkCurrentUrlIdx = 0;
        showUnsubModal = true;
        unsubTarget = senders.find(s => s.sample_email_id === bulkUrlQueue[0]) || { from_name: 'Sender' };
        unsubStreamEmailId = bulkUrlQueue[0];
        unsubMarkSpam = true;
      } else {
        bulkInProgress = false;
        selected = new Set();
        selectAll = false;
        loadSubscriptions();
      }
    } catch (err) {
      showToast('Bulk unsubscribe failed: ' + err.message, 'error');
      bulkInProgress = false;
    }
  }

  function onBulkStreamComplete(status) {
    if (bulkCurrentUrlIdx < bulkUrlQueue.length - 1) {
      bulkCurrentUrlIdx++;
      const nextId = bulkUrlQueue[bulkCurrentUrlIdx];
      unsubTarget = senders.find(s => s.sample_email_id === nextId) || { from_name: 'Sender' };
      unsubStreamEmailId = null;
      setTimeout(() => {
        unsubStreamEmailId = nextId;
      }, 500);
    } else {
      bulkInProgress = false;
      bulkUrlQueue = [];
      bulkCurrentUrlIdx = -1;
      showToast('Bulk unsubscribe complete', 'success');
      selected = new Set();
      selectAll = false;
      loadSubscriptions();
    }
  }

  function getMethodLabel(info) {
    if (!info) return 'None';
    if (info.method === 'both') return 'Email + URL';
    if (info.method === 'email') return 'Email';
    if (info.method === 'url') return 'URL';
    return 'Unknown';
  }

  function getMethodColor(info) {
    if (!info) return 'var(--text-tertiary)';
    if (info.method === 'both') return 'var(--status-success)';
    if (info.method === 'email') return '#6366f1';
    if (info.method === 'url') return 'var(--color-accent-500)';
    return 'var(--text-tertiary)';
  }

  function formatDate(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    const now = new Date();
    const diff = now - d;
    const days = Math.floor(diff / 86400000);
    if (days === 0) return 'Today';
    if (days === 1) return 'Yesterday';
    if (days < 7) return `${days}d ago`;
    if (days < 30) return `${Math.floor(days / 7)}w ago`;
    if (days < 365) return `${Math.floor(days / 30)}mo ago`;
    return d.toLocaleDateString();
  }

  function faviconUrl(domain) {
    return `https://www.google.com/s2/favicons?domain=${domain}&sz=32`;
  }

  // Resizable divider
  function startDrag(e) {
    isDragging = true;
    const startY = e.clientY;
    const container = e.target.closest('.subs-split');
    const startHeight = container.querySelector('.subs-list').offsetHeight;

    function onMove(ev) {
      const delta = ev.clientY - startY;
      const newH = Math.max(200, Math.min(startHeight + delta, window.innerHeight - 200));
      dividerY = newH;
      localStorage.setItem('subs_divider_y', String(newH));
    }
    function onUp() {
      isDragging = false;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    }
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }

  let totalPages = $derived(Math.ceil(totalSenders / pageSize));
  let listHeight = $derived(previewSender ? (dividerY || 400) : null);
</script>

<div class="subs-split h-full flex flex-col" style="background: var(--bg-primary)">
  {#if loading && senders.length === 0}
    <div class="flex items-center justify-center h-full">
      <div class="w-6 h-6 border-2 rounded-full animate-spin" style="border-color: var(--border-color); border-top-color: var(--color-accent-500)"></div>
    </div>
  {:else}
    <!-- Sender List -->
    <div
      class="subs-list overflow-y-auto shrink-0"
      style="{listHeight ? `height: ${listHeight}px` : 'flex: 1'}"
    >
      <div class="max-w-5xl mx-auto p-6 pb-2">
        <!-- Header -->
        <div class="flex items-center justify-between mb-5">
          <div>
            <h2 class="text-xl font-bold" style="color: var(--text-primary)">Subscriptions</h2>
            <p class="text-sm mt-0.5" style="color: var(--text-tertiary)">
              {totalSenders} subscription{totalSenders !== 1 ? 's' : ''} detected
            </p>
          </div>
          {#if selected.size > 0}
            <button
              onclick={bulkUnsubscribe}
              disabled={bulkInProgress}
              class="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white transition-all"
              style="background: var(--status-error); opacity: {bulkInProgress ? 0.6 : 1}"
            >
              {#if bulkInProgress}
                <div class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
              {:else}
                <Icon name="bell-off" size={16} />
              {/if}
              Unsubscribe from {selected.size}
            </button>
          {/if}
        </div>

        <!-- Filters -->
        <div class="flex flex-wrap items-center gap-3 mb-4">
          <div class="flex rounded-lg overflow-hidden border" style="border-color: var(--border-color)">
            {#each [['all', 'All'], ['active', 'Active'], ['unsubscribed', 'Unsubscribed']] as [val, label]}
              <button
                onclick={() => setStatusFilter(val)}
                class="px-3 py-1.5 text-xs font-medium transition-all"
                style="background: {statusFilter === val ? 'var(--color-accent-500)' : 'var(--bg-secondary)'}; color: {statusFilter === val ? 'white' : 'var(--text-secondary)'}"
              >
                {label}
              </button>
            {/each}
          </div>

          <div class="relative flex-1 min-w-[200px] max-w-xs">
            <div class="absolute left-3 top-1/2 -translate-y-1/2" style="color: var(--text-tertiary)">
              <Icon name="search" size={14} />
            </div>
            <input
              type="text"
              placeholder="Search senders..."
              oninput={onSearchInput}
              class="w-full pl-9 pr-3 py-1.5 text-sm rounded-lg border outline-none transition-all"
              style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-primary)"
            />
          </div>

          <div class="flex items-center gap-1.5">
            <span class="text-xs" style="color: var(--text-tertiary)">Sort:</span>
            <select
              onchange={(e) => setSortBy(e.target.value)}
              value={sortBy}
              class="text-xs px-2 py-1.5 rounded-lg border outline-none"
              style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-secondary)"
            >
              <option value="count">Most emails</option>
              <option value="date">Most recent</option>
              <option value="name">Name A-Z</option>
            </select>
          </div>
        </div>

        <!-- Select All -->
        {#if senders.length > 0}
          <div class="flex items-center gap-3 mb-2 px-1">
            <label class="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={selectAll} onchange={toggleSelectAll} class="w-4 h-4 rounded accent-amber-500" />
              <span class="text-xs font-medium" style="color: var(--text-tertiary)">Select all</span>
            </label>
            {#if selected.size > 0}
              <span class="text-xs" style="color: var(--color-accent-600)">{selected.size} selected</span>
            {/if}
          </div>
        {/if}

        <!-- Sender Cards -->
        <div class="space-y-1.5">
          {#each senders as sender (sender.domain)}
            {@const isSelected = selected.has(sender.sample_email_id)}
            {@const isUnsubscribed = sender.unsubscribed_at != null}
            {@const isActive = previewSender?.domain === sender.domain}
            <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
            <div
              class="group rounded-xl border transition-all duration-150 cursor-pointer"
              style="background: {isActive ? 'var(--bg-tertiary)' : 'var(--bg-secondary)'}; border-color: {isActive ? 'var(--color-accent-400)' : isSelected ? 'var(--color-accent-400)' : 'var(--border-color)'}; {isActive ? 'box-shadow: 0 0 0 1px var(--color-accent-400)' : isSelected ? 'box-shadow: 0 0 0 1px var(--color-accent-400)' : ''}"
              onclick={() => selectSender(sender)}
            >
              <div class="flex items-center gap-3 px-4 py-2.5">
                <!-- Checkbox -->
                <input
                  type="checkbox"
                  checked={isSelected}
                  onchange={(e) => toggleSelect(e, sender.sample_email_id)}
                  class="w-4 h-4 rounded accent-amber-500 shrink-0 cursor-pointer"
                  disabled={isUnsubscribed}
                  onclick={(e) => e.stopPropagation()}
                />

                <!-- Favicon -->
                <div class="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 overflow-hidden" style="background: var(--bg-tertiary)">
                  <img
                    src={faviconUrl(sender.domain)}
                    alt=""
                    class="w-4 h-4"
                    onerror={(e) => { e.target.style.display = 'none'; e.target.parentElement.innerHTML = '<span style=\"color: var(--text-tertiary); font-size: 12px; font-weight: 600\">' + (sender.from_name || sender.domain)[0].toUpperCase() + '</span>'; }}
                  />
                </div>

                <!-- Sender Info -->
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-2">
                    <span class="text-sm font-semibold truncate" style="color: var(--text-primary)">
                      {sender.from_name || sender.domain}
                    </span>
                    {#if isUnsubscribed && sender.unsubscribe_method === 'block'}
                      <span class="text-[10px] font-medium px-1.5 py-0.5 rounded-full" style="background: color-mix(in srgb, var(--status-error) 15%, transparent); color: var(--status-error)">
                        Blocked
                      </span>
                    {:else if isUnsubscribed}
                      <span class="text-[10px] font-medium px-1.5 py-0.5 rounded-full" style="background: color-mix(in srgb, var(--status-success) 15%, transparent); color: var(--status-success)">
                        Unsubscribed
                      </span>
                    {/if}
                    {#if sender.marked_spam && sender.unsubscribe_method !== 'block'}
                      <span class="text-[10px] font-medium px-1.5 py-0.5 rounded-full" style="background: color-mix(in srgb, var(--status-warning) 15%, transparent); color: var(--status-warning)">
                        Spam
                      </span>
                    {/if}
                  </div>
                  <div class="flex items-center gap-2 mt-0.5">
                    <span class="text-xs truncate" style="color: var(--text-tertiary)">{sender.domain}</span>
                    {#if sender.latest_subject}
                      <span class="text-xs truncate hidden sm:block" style="color: var(--text-tertiary)">&mdash; {sender.latest_subject}</span>
                    {/if}
                  </div>
                </div>

                <!-- Metadata -->
                <div class="flex items-center gap-3 shrink-0">
                  <div class="text-right hidden sm:block">
                    <div class="text-sm font-bold tabular-nums" style="color: var(--text-primary)">{sender.count}</div>
                    <div class="text-[10px]" style="color: var(--text-tertiary)">email{sender.count !== 1 ? 's' : ''}</div>
                  </div>

                  <div class="text-right hidden md:block" style="min-width: 60px">
                    <div class="text-xs font-medium" style="color: var(--text-secondary)">{formatDate(sender.latest_date)}</div>
                  </div>

                  <div
                    class="text-[10px] font-semibold px-2 py-1 rounded-md hidden lg:block"
                    style="background: color-mix(in srgb, {getMethodColor(sender.unsubscribe_info)} 12%, var(--bg-tertiary)); color: {getMethodColor(sender.unsubscribe_info)}"
                  >
                    {getMethodLabel(sender.unsubscribe_info)}
                  </div>

                  {#if !isUnsubscribed}
                    <button
                      onclick={(e) => openUnsubscribe(e, sender)}
                      class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all hover:opacity-90"
                      style="background: var(--status-error); color: white"
                    >
                      <Icon name="bell-off" size={13} />
                      <span class="hidden sm:inline">Unsubscribe</span>
                    </button>
                  {:else}
                    <div class="flex items-center gap-1 px-2 py-1.5 text-xs" style="color: var(--status-success)">
                      <Icon name="check" size={13} />
                    </div>
                  {/if}
                </div>
              </div>

              {#if isUnsubscribed && sender.emails_received_after > 0}
                <div class="px-4 pb-2 pt-0">
                  <div class="text-[11px] flex items-center gap-1.5 px-3 py-1.5 rounded-md" style="background: color-mix(in srgb, var(--status-warning) 10%, var(--bg-tertiary)); color: var(--status-warning)">
                    <Icon name="alert-triangle" size={12} />
                    Received {sender.emails_received_after} email{sender.emails_received_after !== 1 ? 's' : ''} after unsubscribing
                  </div>
                </div>
              {/if}
            </div>
          {:else}
            <div class="text-center py-16">
              <div class="w-12 h-12 rounded-full mx-auto mb-4 flex items-center justify-center" style="background: var(--bg-tertiary)">
                <Icon name="bell-off" size={24} />
              </div>
              <div class="text-sm font-medium" style="color: var(--text-secondary)">
                {#if statusFilter === 'active'}
                  No active subscriptions
                {:else if statusFilter === 'unsubscribed'}
                  No unsubscribed senders yet
                {:else}
                  No subscriptions detected yet
                {/if}
              </div>
              <div class="text-xs mt-1" style="color: var(--text-tertiary)">
                Subscriptions are detected automatically as emails are analyzed
              </div>
            </div>
          {/each}
        </div>

        {#if totalPages > 1}
          <div class="flex items-center justify-center gap-2 mt-4 mb-2">
            <button
              onclick={() => { page = Math.max(1, page - 1); loadSubscriptions(); }}
              disabled={page <= 1}
              class="px-3 py-1.5 rounded-lg text-xs font-medium border transition-all"
              style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-secondary); opacity: {page <= 1 ? 0.4 : 1}"
            >Previous</button>
            <span class="text-xs tabular-nums" style="color: var(--text-tertiary)">Page {page} of {totalPages}</span>
            <button
              onclick={() => { page = Math.min(totalPages, page + 1); loadSubscriptions(); }}
              disabled={page >= totalPages}
              class="px-3 py-1.5 rounded-lg text-xs font-medium border transition-all"
              style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-secondary); opacity: {page >= totalPages ? 0.4 : 1}"
            >Next</button>
          </div>
        {/if}
      </div>
    </div>

    <!-- Resizable Divider + Email Preview -->
    {#if previewSender}
      <!-- Drag handle -->
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div
        class="h-1.5 shrink-0 cursor-row-resize flex items-center justify-center group"
        style="background: var(--border-color)"
        onmousedown={startDrag}
      >
        <div class="w-8 h-0.5 rounded-full transition-all" style="background: var(--text-tertiary); opacity: 0.4"></div>
      </div>

      <!-- Email Preview Pane -->
      <div class="flex-1 min-h-0 overflow-y-auto border-t" style="border-color: var(--border-color); background: var(--bg-primary)">
        {#if previewLoading}
          <div class="flex items-center justify-center h-full py-12">
            <div class="w-5 h-5 border-2 rounded-full animate-spin" style="border-color: var(--border-color); border-top-color: var(--color-accent-500)"></div>
            <span class="ml-2 text-sm" style="color: var(--text-tertiary)">Loading email...</span>
          </div>
        {:else if previewEmail}
          <div class="relative">
            <button
              onclick={closePreview}
              class="absolute top-3 right-3 z-10 p-1 rounded-lg transition-all hover:opacity-70"
              style="background: var(--bg-secondary); color: var(--text-tertiary)"
              title="Close preview"
            >
              <Icon name="x" size={16} />
            </button>
            <EmailView email={previewEmail} />
          </div>
        {/if}
      </div>
    {/if}
  {/if}
</div>

<!-- Unsubscribe Modal -->
{#if showUnsubModal && unsubTarget}
  <div class="fixed inset-0 z-50 flex items-center justify-center p-4">
    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
    <div class="absolute inset-0" style="background: rgba(0,0,0,0.5); backdrop-filter: blur(4px)" onclick={closeModal}></div>

    <div
      class="relative w-full max-w-lg rounded-2xl border shadow-2xl overflow-hidden"
      style="background: var(--bg-primary); border-color: var(--border-color)"
    >
      <div class="flex items-center justify-between px-5 py-4 border-b" style="border-color: var(--border-color)">
        <div class="flex items-center gap-3">
          <div class="w-8 h-8 rounded-lg flex items-center justify-center" style="background: color-mix(in srgb, var(--status-error) 12%, var(--bg-tertiary))">
            <Icon name="bell-off" size={16} />
          </div>
          <div>
            <h3 class="text-sm font-bold" style="color: var(--text-primary)">
              {#if bulkCurrentUrlIdx >= 0}
                Unsubscribing ({bulkCurrentUrlIdx + 1}/{bulkUrlQueue.length})
              {:else}
                Unsubscribe
              {/if}
            </h3>
            <p class="text-xs" style="color: var(--text-tertiary)">{unsubTarget.from_name || unsubTarget.domain}</p>
          </div>
        </div>
        <button onclick={closeModal} class="p-1.5 rounded-lg transition-all hover:opacity-70" style="color: var(--text-tertiary)">
          <Icon name="x" size={18} />
        </button>
      </div>

      <div class="px-5 py-4 max-h-[70vh] overflow-y-auto">
        {#if !unsubStreamEmailId && !unsubInProgress}
          <div class="space-y-4">
            <div class="rounded-xl p-4" style="background: var(--bg-secondary)">
              <div class="text-xs font-medium mb-2" style="color: var(--text-tertiary)">Unsubscribe method</div>
              {#if unsubTarget.unsubscribe_info}
                {@const info = unsubTarget.unsubscribe_info}
                {#if info.email}
                  <div class="flex items-center gap-2 text-sm" style="color: var(--text-primary)">
                    <Icon name="mail" size={14} />
                    <span>Send email to <strong>{info.email}</strong></span>
                  </div>
                {/if}
                {#if info.url}
                  <div class="flex items-center gap-2 text-sm mt-1.5" style="color: var(--text-primary)">
                    <Icon name="globe" size={14} />
                    <span>Visit unsubscribe page (automated via AI)</span>
                  </div>
                {/if}
              {:else}
                <div class="text-sm" style="color: var(--text-tertiary)">No unsubscribe method available</div>
              {/if}
            </div>

            <label class="flex items-center justify-between p-3 rounded-xl cursor-pointer" style="background: var(--bg-secondary)">
              <div class="flex items-center gap-2">
                <Icon name="alert-triangle" size={14} />
                <span class="text-sm" style="color: var(--text-primary)">Also mark as spam in Gmail</span>
              </div>
              <div class="relative">
                <input type="checkbox" bind:checked={unsubMarkSpam} class="sr-only" />
                <div class="w-9 h-5 rounded-full transition-all" style="background: {unsubMarkSpam ? 'var(--color-accent-500)' : 'var(--bg-tertiary)'}">
                  <div class="w-4 h-4 rounded-full bg-white shadow-sm transition-transform" style="transform: translate({unsubMarkSpam ? '18px' : '2px'}, 2px)"></div>
                </div>
              </div>
            </label>

            {#if unsubTarget.unsubscribe_info && (unsubTarget.unsubscribe_info.email || unsubTarget.unsubscribe_info.url)}
              <button
                onclick={confirmUnsubscribe}
                class="w-full py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:opacity-90"
                style="background: var(--status-error)"
              >
                Unsubscribe from {unsubTarget.from_name || unsubTarget.domain}
              </button>
            {:else}
              <div class="rounded-xl p-4 mb-1" style="background: color-mix(in srgb, var(--status-warning) 8%, var(--bg-secondary))">
                <div class="flex items-center gap-2 text-xs font-medium mb-1.5" style="color: var(--status-warning)">
                  <Icon name="alert-circle" size={13} />
                  No unsubscribe link found
                </div>
                <p class="text-xs" style="color: var(--text-tertiary)">
                  This sender didn't include an unsubscribe link. You can block them instead -- this marks their emails as spam in Gmail so future emails go straight to your spam folder.
                </p>
              </div>
              <button
                onclick={confirmBlock}
                class="w-full py-2.5 rounded-xl text-sm font-semibold text-white transition-all hover:opacity-90"
                style="background: var(--status-error)"
              >
                Block {unsubTarget.from_name || unsubTarget.domain}
              </button>
            {/if}
          </div>
        {:else if unsubInProgress && !unsubStreamEmailId}
          <div class="flex items-center justify-center py-8">
            <div class="w-6 h-6 border-2 rounded-full animate-spin" style="border-color: var(--border-color); border-top-color: var(--color-accent-500)"></div>
            <span class="ml-3 text-sm" style="color: var(--text-secondary)">Sending unsubscribe email...</span>
          </div>
        {:else if unsubStreamEmailId}
          <UnsubscribeViewer
            emailId={unsubStreamEmailId}
            markSpam={unsubMarkSpam}
            onComplete={bulkCurrentUrlIdx >= 0 ? onBulkStreamComplete : onStreamComplete}
          />
        {/if}
      </div>
    </div>
  </div>
{/if}
