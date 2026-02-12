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
  let sentinelEl = $state(null);
  let observer = null;

  // Set up IntersectionObserver to trigger loading more when sentinel is visible
  $effect(() => {
    if (observer) {
      observer.disconnect();
    }
    if (sentinelEl) {
      observer = new IntersectionObserver((entries) => {
        const entry = entries[0];
        if (entry && entry.isIntersecting && hasMore && !loadingMore && !loading) {
          if (onLoadMore) onLoadMore();
        }
      }, { rootMargin: '200px' });
      observer.observe(sentinelEl);
    }
    return () => {
      if (observer) observer.disconnect();
    };
  });

  function formatDate(dateStr) {
    if (!dateStr) return '';
    const date = new Date(dateStr);
    const now = new Date();
    const diff = now - date;
    const dayMs = 86400000;

    if (diff < dayMs) {
      return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    }
    if (diff < 7 * dayMs) {
      return date.toLocaleDateString([], { weekday: 'short' });
    }
    if (date.getFullYear() === now.getFullYear()) {
      return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
    }
    return date.toLocaleDateString([], { month: 'short', day: 'numeric', year: '2-digit' });
  }

  function toggleSelect(id, event) {
    event.stopPropagation();
    const next = new Set(selectedIds);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    selectedIds = next;
  }

  function handleBulkAction(action) {
    if (selectedIds.size > 0 && onAction) {
      onAction(action, Array.from(selectedIds));
      selectedIds = new Set();
    }
  }

  const categoryColors = {
    needs_response: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400',
    urgent: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400',
    can_ignore: 'bg-surface-100 text-surface-500 dark:bg-surface-800 dark:text-surface-500',
    fyi: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400',
    awaiting_reply: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400',
  };

  // Helper to determine if we should show recipient instead of sender
  function shouldShowRecipient(mailbox) {
    return mailbox === 'SENT' || mailbox === 'DRAFTS';
  }

  // Build a map of thread_id -> count of emails in that thread for the current list
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
        result[e.id] = true; // This email is the first one in its thread
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

<div class="flex flex-col h-full">
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

  <!-- Toolbar -->
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

  <!-- Email list -->
  <div class="flex-1 overflow-y-auto">
    {#if loading && emails.length === 0}
      <div class="p-4 space-y-3">
        {#each Array(8) as _}
          <div class="animate-pulse flex gap-3 p-3">
            <div class="w-5 h-5 rounded bg-surface-200 dark:bg-surface-700"></div>
            <div class="flex-1 space-y-2">
              <div class="h-3 rounded w-1/4 bg-surface-200 dark:bg-surface-700"></div>
              <div class="h-3 rounded w-3/4 bg-surface-200 dark:bg-surface-700"></div>
              <div class="h-3 rounded w-1/2 bg-surface-200 dark:bg-surface-700"></div>
            </div>
          </div>
        {/each}
      </div>
    {:else if emails.length === 0 && !loading}
      <div class="flex flex-col items-center justify-center h-full text-center p-8">
        <div class="text-4xl mb-3 opacity-40">
          {#if searchActive}
            🔍
          {:else if mailbox === 'SPAM'}
            🛡️
          {:else}
            📭
          {/if}
        </div>
        <p class="text-sm font-medium" style="color: var(--text-primary)">
          {#if searchActive}No results found
          {:else if mailbox === 'SPAM'}No spam
          {:else}No emails
          {/if}
        </p>
        <p class="text-xs mt-1" style="color: var(--text-secondary)">
          {#if searchActive}Try different search terms
          {:else if mailbox === 'SPAM'}Your spam folder is clean
          {:else}This mailbox is empty
          {/if}
        </p>
      </div>
    {:else}
      {#each emails as email (email.id)}
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div
          class="flex items-start gap-3 px-4 py-3 border-b cursor-pointer transition-fast"
          class:font-medium={!email.is_read}
          style="border-color: var(--border-subtle); background: {selectedId === email.id ? 'var(--bg-hover)' : 'var(--bg-secondary)'};"
          onclick={() => onSelect && onSelect(email.id)}
        >
          <!-- Checkbox -->
          <button
            onclick={(e) => toggleSelect(email.id, e)}
            class="mt-0.5 w-4 h-4 rounded border flex items-center justify-center shrink-0 transition-fast"
            style="border-color: var(--border-color); background: {selectedIds.has(email.id) ? 'var(--color-accent-500)' : 'transparent'}"
          >
            {#if selectedIds.has(email.id)}
              <svg class="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7" />
              </svg>
            {/if}
          </button>

          <!-- Star -->
          <button
            onclick={(e) => { e.stopPropagation(); onAction && onAction(email.is_starred ? 'unstar' : 'star', [email.id]); }}
            class="mt-0.5 shrink-0"
            style="color: {email.is_starred ? 'var(--color-accent-500)' : 'var(--text-tertiary)'}"
          >
            <svg class="w-4 h-4" fill={email.is_starred ? 'currentColor' : 'none'} stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.563 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z"/>
            </svg>
          </button>

          <!-- Content -->
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 mb-0.5">
              <span class="text-sm truncate" style="color: var(--text-primary)">
                {getPrimaryDisplayInfo(email, shouldShowRecipient(mailbox))}
              </span>
              {#if !email.is_read}
                <span class="w-2 h-2 rounded-full bg-accent-500 shrink-0"></span>
              {/if}
              {#if email.has_attachments}
                <svg class="w-3.5 h-3.5 shrink-0" style="color: var(--text-tertiary)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M18.375 12.739l-7.693 7.693a4.5 4.5 0 01-6.364-6.364l10.94-10.94A3 3 0 1119.5 7.372L8.552 18.32m.009-.01l-.01.01m5.699-9.941l-7.81 7.81a1.5 1.5 0 002.112 2.13" />
                </svg>
              {/if}
              <span class="text-xs ml-auto shrink-0" style="color: var(--text-tertiary)">
                {formatDate(email.date)}
              </span>
            </div>
            <div class="text-sm truncate mb-0.5" style="color: var(--text-primary); opacity: {email.is_read ? 0.8 : 1}">
              {email.subject || '(no subject)'}
            </div>
            <div class="flex items-center gap-2">
              <span class="text-xs truncate" style="color: var(--text-tertiary)">
                {email.snippet || ''}
              </span>
              {#if email.gmail_thread_id && seenThreadIds[email.id] && threadCounts[email.gmail_thread_id] > 1}
                <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0" style="background: var(--bg-tertiary); color: var(--text-secondary)" title="Thread with {threadCounts[email.gmail_thread_id]} messages">
                  {threadCounts[email.gmail_thread_id]}
                </span>
              {/if}
              {#if email.needs_reply}
                <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-400">
                  reply
                </span>
              {/if}
              {#if email.is_subscription}
                <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400">
                  sub
                </span>
              {/if}
              {#if email.ai_category}
                <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 {categoryColors[email.ai_category] || ''}">
                  {email.ai_category.replace('_', ' ')}
                </span>
              {/if}
            </div>
          </div>
        </div>
      {/each}

      <!-- Infinite scroll sentinel -->
      <div bind:this={sentinelEl} class="h-1"></div>

      <!-- Loading more indicator -->
      {#if loadingMore}
        <div class="flex items-center justify-center py-4">
          <div class="w-5 h-5 border-2 rounded-full animate-spin" style="border-color: var(--border-color); border-top-color: var(--color-accent-500)"></div>
          <span class="text-xs ml-2" style="color: var(--text-tertiary)">Loading more...</span>
        </div>
      {/if}
    {/if}
  </div>

  <!-- Status bar -->
  {#if emails.length > 0}
    <div class="h-8 flex items-center justify-center px-4 border-t shrink-0" style="border-color: var(--border-color); background: var(--bg-secondary)">
      <span class="text-xs" style="color: var(--text-tertiary)">
        Showing {emails.length.toLocaleString()} of {total.toLocaleString()}
        {#if !hasMore && total > 0}
          — all loaded
        {/if}
      </span>
    </div>
  {/if}
</div>
