<script>
  import { onMount } from 'svelte';

  let {
    emails = [],
    loading = false,
    loadingMore = false,
    hasMore = false,
    total = 0,
    selectedId = null,
    mailbox = 'INBOX',
    searchActive = false,
    searchTerm = '',
    onSelect = null,
    onAction = null,
    onLoadMore = null,
  } = $props();

  let selectedIds = $state(new Set());
  let selectAll = $state(false);
  let sentinelEl = $state(null);
  let observer = null;

  // Column widths (px). Checkbox and star are fixed.
  const savedWidths = (() => {
    try {
      const stored = localStorage.getItem('tableColWidths');
      if (stored) return JSON.parse(stored);
    } catch {}
    return null;
  })();
  let colWidths = $state({
    from: savedWidths?.from || 180,
    subject: savedWidths?.subject || 0, // 0 = flex fill
    category: savedWidths?.category || 100,
    date: savedWidths?.date || 120,
  });

  let resizing = $state(null); // { col, startX, startWidth }

  function startResize(col, e) {
    e.preventDefault();
    e.stopPropagation();
    const startX = e.clientX;
    const startWidth = colWidths[col];
    resizing = { col, startX, startWidth };

    function onMove(ev) {
      const delta = ev.clientX - startX;
      const newWidth = Math.max(60, startWidth + delta);
      colWidths = { ...colWidths, [col]: newWidth };
    }

    function onUp() {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      resizing = null;
      // Save to localStorage
      try {
        localStorage.setItem('tableColWidths', JSON.stringify(colWidths));
      } catch {}
    }

    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }

  // IntersectionObserver for infinite scroll
  $effect(() => {
    if (observer) observer.disconnect();
    if (sentinelEl) {
      observer = new IntersectionObserver((entries) => {
        const entry = entries[0];
        if (entry && entry.isIntersecting && hasMore && !loadingMore && !loading) {
          if (onLoadMore) onLoadMore();
        }
      }, { rootMargin: '200px' });
      observer.observe(sentinelEl);
    }
    return () => { if (observer) observer.disconnect(); };
  });

  function formatDate(dateStr) {
    if (!dateStr) return '';
    const date = new Date(dateStr);
    const now = new Date();
    const diff = now - date;
    const dayMs = 86400000;
    if (diff < dayMs) return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    if (diff < 7 * dayMs) return date.toLocaleDateString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' });
    if (date.getFullYear() === now.getFullYear()) return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
    return date.toLocaleDateString([], { month: 'short', day: 'numeric', year: '2-digit' });
  }

  function toggleSelect(id, event) {
    event.stopPropagation();
    const next = new Set(selectedIds);
    if (next.has(id)) { next.delete(id); } else { next.add(id); }
    selectedIds = next;
    selectAll = next.size === emails.length && emails.length > 0;
  }

  function toggleSelectAll() {
    if (selectAll) { selectedIds = new Set(); selectAll = false; }
    else { selectedIds = new Set(emails.map(e => e.id)); selectAll = true; }
  }

  function handleBulkAction(action) {
    if (selectedIds.size > 0 && onAction) {
      onAction(action, Array.from(selectedIds));
      selectedIds = new Set();
      selectAll = false;
    }
  }

  const categoryColors = {
    needs_response: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400',
    urgent: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400',
    can_ignore: 'bg-surface-100 text-surface-500 dark:bg-surface-800 dark:text-surface-500',
    fyi: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400',
    awaiting_reply: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400',
  };

  function colStyle(col) {
    const w = colWidths[col];
    if (!w) return 'width: auto';
    return `width: ${w}px; min-width: ${w}px; max-width: ${w}px`;
  }

  // Helper to determine if we should show recipient instead of sender
  function shouldShowRecipient(mailbox) {
    return mailbox === 'SENT' || mailbox === 'DRAFTS';
  }

  // Build a map of thread_id -> count of emails in that thread
  let threadCounts = $derived.by(() => {
    const counts = {};
    for (const e of emails) {
      if (e.gmail_thread_id) {
        if (!counts[e.gmail_thread_id]) {
          counts[e.gmail_thread_id] = 0;
        }
        counts[e.gmail_thread_id] += 1;
      }
    }
    return counts;
  });

  // Track which thread IDs we've already shown a count badge for
  let seenThreadIds = $derived.by(() => {
    const seen = {};
    const result = {};
    for (const e of emails) {
      const tid = e.gmail_thread_id;
      if (tid && !seen[tid]) {
        seen[tid] = true;
        result[e.id] = true;
      }
    }
    return result;
  });

  // Get primary display name/address for email list
  function getPrimaryDisplayInfo(email, showRecipient) {
    if (!showRecipient) {
      return email.from_name || email.from_address || 'Unknown';
    }

    // For sent/drafts, show primary recipient
    if (!email.to_addresses || email.to_addresses.length === 0) {
      return '(No recipients)';
    }

    const first = email.to_addresses[0];
    const firstDisplay = typeof first === 'string' ? first : (first.name || first.address);

    if (email.to_addresses.length > 1) {
      return `${firstDisplay} +${email.to_addresses.length - 1}`;
    }
    return firstDisplay;
  }
</script>

<div class="flex flex-col h-full" class:select-none={resizing}>
  <!-- Search indicator -->
  {#if searchActive}
    <div class="px-4 py-2 border-b shrink-0 flex items-center gap-2" style="border-color: var(--border-color); background: var(--bg-tertiary)">
      <svg class="w-4 h-4 shrink-0" style="color: var(--color-accent-500)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
      </svg>
      <span class="text-xs" style="color: var(--text-secondary)">Results for "<strong style="color: var(--text-primary)">{searchTerm}</strong>"</span>
      <span class="text-xs ml-auto" style="color: var(--text-tertiary)">{total.toLocaleString()} found</span>
    </div>
  {/if}

  <!-- Bulk actions toolbar -->
  {#if selectedIds.size > 0}
    <div class="h-10 flex items-center gap-2 px-3 border-b shrink-0" style="border-color: var(--border-color); background: var(--bg-tertiary)">
      <span class="text-xs font-medium" style="color: var(--text-secondary)">{selectedIds.size} selected</span>
      <div class="flex gap-1 ml-auto">
        <button onclick={() => handleBulkAction('mark_read')} class="px-2 py-1 text-xs rounded" style="color: var(--text-secondary)">Read</button>
        <button onclick={() => handleBulkAction('mark_unread')} class="px-2 py-1 text-xs rounded" style="color: var(--text-secondary)">Unread</button>
        <button onclick={() => handleBulkAction('archive')} class="px-2 py-1 text-xs rounded" style="color: var(--text-secondary)">Archive</button>
        <button onclick={() => handleBulkAction('star')} class="px-2 py-1 text-xs rounded" style="color: var(--text-secondary)">Star</button>
        {#if mailbox === 'SPAM'}
          <button onclick={() => handleBulkAction('unspam')} class="px-2 py-1 text-xs rounded font-medium" style="color: var(--color-accent-600)">Not Spam</button>
        {:else}
          <button onclick={() => handleBulkAction('spam')} class="px-2 py-1 text-xs rounded text-red-500">Spam</button>
        {/if}
        {#if mailbox === 'TRASH'}
          <button onclick={() => handleBulkAction('untrash')} class="px-2 py-1 text-xs rounded font-medium" style="color: var(--color-accent-600)">Restore</button>
        {:else}
          <button onclick={() => handleBulkAction('trash')} class="px-2 py-1 text-xs rounded text-red-500">Trash</button>
        {/if}
      </div>
    </div>
  {/if}

  <!-- Table -->
  <div class="flex-1 overflow-auto">
    {#if loading && emails.length === 0}
      <div class="p-4 space-y-2">
        {#each Array(10) as _}
          <div class="animate-pulse flex gap-4 py-2 px-4">
            <div class="w-4 h-4 rounded bg-surface-200 dark:bg-surface-700"></div>
            <div class="w-4 h-4 rounded bg-surface-200 dark:bg-surface-700"></div>
            <div class="flex-1 h-4 rounded bg-surface-200 dark:bg-surface-700"></div>
            <div class="flex-[2] h-4 rounded bg-surface-200 dark:bg-surface-700"></div>
            <div class="w-24 h-4 rounded bg-surface-200 dark:bg-surface-700"></div>
          </div>
        {/each}
      </div>
    {:else if emails.length === 0 && !loading}
      <div class="flex flex-col items-center justify-center h-full text-center p-8">
        <div class="text-4xl mb-3 opacity-40">
          {#if searchActive}🔍{:else}📭{/if}
        </div>
        <p class="text-sm font-medium" style="color: var(--text-primary)">
          {#if searchActive}No results found{:else}No emails{/if}
        </p>
      </div>
    {:else}
      <table class="w-full text-sm table-fixed">
        <thead class="sticky top-0 z-10" style="background: var(--bg-tertiary)">
          <tr class="border-b" style="border-color: var(--border-color)">
            <!-- Checkbox col (fixed) -->
            <th class="px-3 py-2 text-left" style="width: 40px; min-width: 40px; max-width: 40px">
              <button
                onclick={toggleSelectAll}
                class="w-4 h-4 rounded border flex items-center justify-center transition-fast"
                style="border-color: var(--border-color); background: {selectAll ? 'var(--color-accent-500)' : 'transparent'}"
              >
                {#if selectAll}
                  <svg class="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7" />
                  </svg>
                {/if}
              </button>
            </th>
            <!-- Star col (fixed) -->
            <th class="px-1 py-2" style="width: 32px; min-width: 32px; max-width: 32px"></th>
            <!-- From / To -->
            <th class="relative px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider" style="color: var(--text-tertiary); {colStyle('from')}">
              {shouldShowRecipient(mailbox) ? 'To' : 'From'}
              <!-- svelte-ignore a11y_no_static_element_interactions -->
              <div class="col-resize-handle" onmousedown={(e) => startResize('from', e)}></div>
            </th>
            <!-- Subject (flex fill) -->
            <th class="relative px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider" style="color: var(--text-tertiary)">
              Subject
              <!-- svelte-ignore a11y_no_static_element_interactions -->
              <div class="col-resize-handle" onmousedown={(e) => startResize('subject', e)}></div>
            </th>
            <!-- Category -->
            <th class="relative px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider" style="color: var(--text-tertiary); {colStyle('category')}">
              Category
              <!-- svelte-ignore a11y_no_static_element_interactions -->
              <div class="col-resize-handle" onmousedown={(e) => startResize('category', e)}></div>
            </th>
            <!-- Date -->
            <th class="px-3 py-2 text-right text-xs font-semibold uppercase tracking-wider" style="color: var(--text-tertiary); {colStyle('date')}">
              Date
            </th>
          </tr>
        </thead>
        <tbody>
          {#each emails as email (email.id)}
            <!-- svelte-ignore a11y_click_events_have_key_events -->
            <tr
              class="border-b cursor-pointer transition-fast"
              style="border-color: var(--border-subtle); background: {selectedId === email.id ? 'var(--bg-hover)' : 'var(--bg-secondary)'}"
              onclick={() => onSelect && onSelect(email.id)}
            >
              <td class="px-3 py-2" style="width: 40px">
                <button
                  onclick={(e) => toggleSelect(email.id, e)}
                  class="w-4 h-4 rounded border flex items-center justify-center transition-fast"
                  style="border-color: var(--border-color); background: {selectedIds.has(email.id) ? 'var(--color-accent-500)' : 'transparent'}"
                >
                  {#if selectedIds.has(email.id)}
                    <svg class="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7" />
                    </svg>
                  {/if}
                </button>
              </td>
              <td class="px-1 py-2" style="width: 32px">
                <button
                  onclick={(e) => { e.stopPropagation(); onAction && onAction(email.is_starred ? 'unstar' : 'star', [email.id]); }}
                  style="color: {email.is_starred ? 'var(--color-accent-500)' : 'var(--text-tertiary)'}"
                >
                  <svg class="w-4 h-4" fill={email.is_starred ? 'currentColor' : 'none'} stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.563 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z"/>
                  </svg>
                </button>
              </td>
              <td class="px-3 py-2 overflow-hidden" style="{colStyle('from')}">
                <div class="flex items-center gap-2">
                  {#if !email.is_read}
                    <span class="w-2 h-2 rounded-full bg-accent-500 shrink-0"></span>
                  {/if}
                  <span class="truncate" class:font-semibold={!email.is_read} style="color: var(--text-primary)">
                    {getPrimaryDisplayInfo(email, shouldShowRecipient(mailbox))}
                  </span>
                </div>
              </td>
              <td class="px-3 py-2 overflow-hidden">
                <div class="flex items-center gap-2 min-w-0">
                  <span class="truncate" class:font-semibold={!email.is_read} style="color: var(--text-primary)">
                    {email.subject || '(no subject)'}
                  </span>
                  {#if email.has_attachments}
                    <svg class="w-3.5 h-3.5 shrink-0" style="color: var(--text-tertiary)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M18.375 12.739l-7.693 7.693a4.5 4.5 0 01-6.364-6.364l10.94-10.94A3 3 0 1119.5 7.372L8.552 18.32m.009-.01l-.01.01m5.699-9.941l-7.81 7.81a1.5 1.5 0 002.112 2.13" />
                    </svg>
                  {/if}
                  <span class="text-xs truncate hidden xl:inline" style="color: var(--text-tertiary)">
                    — {email.snippet || ''}
                  </span>
                </div>
              </td>
              <td class="px-3 py-2 overflow-hidden" style="{colStyle('category')}">
                <div class="flex items-center gap-1 flex-wrap">
                  {#if email.gmail_thread_id && seenThreadIds[email.id] && threadCounts[email.gmail_thread_id] > 1}
                    <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium whitespace-nowrap" style="background: var(--bg-tertiary); color: var(--text-secondary)" title="Thread with {threadCounts[email.gmail_thread_id]} messages">
                      {threadCounts[email.gmail_thread_id]}
                    </span>
                  {/if}
                  {#if email.needs_reply}
                    <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium whitespace-nowrap bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-400">
                      reply
                    </span>
                  {/if}
                  {#if email.is_subscription}
                    <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium whitespace-nowrap bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400">
                      sub
                    </span>
                  {/if}
                  {#if email.ai_category}
                    <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium whitespace-nowrap {categoryColors[email.ai_category] || ''}">
                      {email.ai_category.replace('_', ' ')}
                    </span>
                  {/if}
                </div>
              </td>
              <td class="px-3 py-2 text-right whitespace-nowrap overflow-hidden" style="{colStyle('date')}">
                <span class="text-xs" style="color: var(--text-tertiary)">{formatDate(email.date)}</span>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>

      <div bind:this={sentinelEl} class="h-1"></div>

      {#if loadingMore}
        <div class="flex items-center justify-center py-4">
          <div class="w-5 h-5 border-2 rounded-full animate-spin" style="border-color: var(--border-color); border-top-color: var(--color-accent-500)"></div>
          <span class="text-xs ml-2" style="color: var(--text-tertiary)">Loading more...</span>
        </div>
      {/if}
    {/if}
  </div>

  {#if emails.length > 0}
    <div class="h-8 flex items-center justify-center px-4 border-t shrink-0" style="border-color: var(--border-color); background: var(--bg-secondary)">
      <span class="text-xs" style="color: var(--text-tertiary)">
        Showing {emails.length.toLocaleString()} of {total.toLocaleString()}
        {#if !hasMore && total > 0} — all loaded{/if}
      </span>
    </div>
  {/if}
</div>

<style>
  .col-resize-handle {
    position: absolute;
    right: 0;
    top: 0;
    bottom: 0;
    width: 6px;
    cursor: col-resize;
    z-index: 1;
  }
  .col-resize-handle:hover,
  .col-resize-handle:active {
    background: var(--color-accent-500);
    opacity: 0.4;
  }
</style>
