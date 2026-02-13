<script>
  import { onMount } from 'svelte';
  import { slide } from 'svelte/transition';
  import { accountColorMap, selectedAccountId } from '../../lib/stores.js';

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

  let showAccountDot = $derived($selectedAccountId === null);

  let selectedIds = $state(new Set());
  let expandedThreads = $state(new Set());
  let sentinelEl = $state(null);
  let observer = null;

  function toggleThread(threadId, event) {
    event.stopPropagation();
    const next = new Set(expandedThreads);
    if (next.has(threadId)) {
      next.delete(threadId);
    } else {
      next.add(threadId);
    }
    expandedThreads = next;
  }

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
    urgent: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400',
    can_ignore: 'bg-surface-100 text-surface-500 dark:bg-surface-800 dark:text-surface-500',
    fyi: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400',
    awaiting_reply: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400',
  };

  const emailTypeColors = {
    work: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-400',
    personal: 'bg-teal-100 text-teal-700 dark:bg-teal-900/40 dark:text-teal-400',
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

  // For digested threads, ALWAYS hide non-first emails from their natural position.
  // When expanded, we render them grouped under the header instead.
  let hiddenDigestEmails = $derived.by(() => {
    const hidden = new Set();
    const seenDigestThreads = {};
    for (const e of emails) {
      const tid = e.gmail_thread_id;
      if (!tid || !e.thread_digest_type) continue;
      if (seenDigestThreads[tid]) {
        hidden.add(e.id);
      } else {
        seenDigestThreads[tid] = true;
      }
    }
    return hidden;
  });

  // Map of threadId -> all emails in that thread, sorted by date (for expanded rendering)
  let digestThreadEmails = $derived.by(() => {
    const map = {};
    for (const e of emails) {
      const tid = e.gmail_thread_id;
      if (!tid || !e.thread_digest_type) continue;
      if (!map[tid]) {
        map[tid] = [];
      }
      map[tid].push(e);
    }
    // Sort each thread's emails by date ascending (oldest first)
    for (const tid of Object.keys(map)) {
      map[tid].sort((a, b) => new Date(a.date) - new Date(b.date));
    }
    return map;
  });

  const digestTypeConfig = {
    scheduling: { label: 'Scheduling', classes: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-400' },
    discussion: { label: 'Discussion', classes: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400' },
    notification: { label: 'Notification', classes: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' },
    transactional: { label: 'Transactional', classes: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400' },
    other: { label: 'Thread', classes: 'bg-stone-100 text-stone-600 dark:bg-stone-800 dark:text-stone-400' },
  };

  function getDigestConfig(type) {
    return digestTypeConfig[type] || digestTypeConfig.other;
  }

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
        {#if hiddenDigestEmails.has(email.id)}
          <!-- Hidden: part of a digested thread (rendered grouped under header) -->
        {:else if email.thread_digest_type && seenThreadIds[email.id]}
          <!-- ========== DIGEST THREAD (collapsed or expanded) ========== -->
          {@const dConf = getDigestConfig(email.thread_digest_type)}
          {@const isExpanded = expandedThreads.has(email.gmail_thread_id)}
          {@const borderColor = email.thread_digest_type === 'scheduling' ? 'rgb(168, 85, 247)' : email.thread_digest_type === 'discussion' ? 'rgb(59, 130, 246)' : 'var(--border-color)'}
          <!-- svelte-ignore a11y_click_events_have_key_events -->
          <!-- svelte-ignore a11y_no_static_element_interactions -->
          <div
            class="flex items-start gap-3 px-4 py-3 border-b cursor-pointer transition-fast"
            style="border-color: var(--border-subtle); background: {isExpanded ? 'var(--bg-tertiary)' : 'var(--bg-secondary)'}; border-left: 3px solid {borderColor};"
            onclick={(e) => toggleThread(email.gmail_thread_id, e)}
          >
            <!-- Chevron -->
            <div class="mt-1 shrink-0 transition-transform" style="color: var(--text-tertiary); transform: rotate({isExpanded ? '90' : '0'}deg)">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
              </svg>
            </div>

            <!-- Conversation type icon -->
            <div class="mt-0.5 w-7 h-7 rounded-full flex items-center justify-center shrink-0 {dConf.classes}" style="opacity: 0.9">
              {#if email.thread_digest_type === 'scheduling'}
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
                </svg>
              {:else if email.thread_digest_type === 'discussion'}
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 01-.825-.242m9.345-8.334a2.126 2.126 0 00-.476-.095 48.64 48.64 0 00-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0011.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155" />
                </svg>
              {:else if email.thread_digest_type === 'notification'}
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
                </svg>
              {:else}
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M21.75 6.75v10.5a2.25 2.25 0 01-2.25 2.25h-15a2.25 2.25 0 01-2.25-2.25V6.75m19.5 0A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25m19.5 0v.243a2.25 2.25 0 01-1.07 1.916l-7.5 4.615a2.25 2.25 0 01-2.36 0L3.32 8.91a2.25 2.25 0 01-1.07-1.916V6.75" />
                </svg>
              {/if}
            </div>

            <!-- Content -->
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-1.5 mb-0.5">
                <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 {dConf.classes}">{dConf.label}</span>
                {#if email.thread_digest_resolved}
                  <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-400">Resolved</span>
                {/if}
                <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0" style="background: var(--bg-tertiary); color: var(--text-secondary)">
                  {email.thread_digest_count || threadCounts[email.gmail_thread_id]} msgs
                </span>
                {#if showAccountDot && email.account_email && $accountColorMap[email.account_email]}
                  <span class="w-2 h-2 rounded-full shrink-0" style="background: {$accountColorMap[email.account_email].bg}" title={email.account_email}></span>
                {/if}
                <span class="text-xs ml-auto shrink-0" style="color: var(--text-tertiary)">{formatDate(email.date)}</span>
              </div>
              <div class="text-sm truncate mb-0.5" style="color: var(--text-primary)">{email.subject || '(no subject)'}</div>
              {#if email.thread_digest_type === 'scheduling' && email.thread_digest_outcome}
                <div class="text-xs truncate font-medium" style="color: rgb(168, 85, 247)">{email.thread_digest_outcome}</div>
              {:else if email.thread_digest_summary}
                <div class="text-xs truncate" style="color: var(--text-secondary)">{email.thread_digest_summary}</div>
              {:else}
                <div class="text-xs truncate" style="color: var(--text-tertiary)">{email.snippet || ''}</div>
              {/if}
            </div>
          </div>

          <!-- ========== EXPANDED THREAD CHILDREN (rendered inline) ========== -->
          {#if isExpanded && digestThreadEmails[email.gmail_thread_id]}
            <div transition:slide={{ duration: 200 }}>
              {#each digestThreadEmails[email.gmail_thread_id] as child (child.id)}
                <!-- svelte-ignore a11y_click_events_have_key_events -->
                <!-- svelte-ignore a11y_no_static_element_interactions -->
                <div
                  class="flex items-start gap-3 py-2.5 border-b cursor-pointer transition-fast"
                  class:font-medium={!child.is_read}
                  style="border-color: var(--border-subtle); background: {selectedId === child.id ? 'var(--bg-hover)' : 'var(--bg-primary)'}; padding-left: 2.5rem; padding-right: 1rem; border-left: 3px solid {borderColor};"
                  onclick={() => onSelect && onSelect(child.id)}
                >
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 mb-0.5">
                      <span class="text-sm truncate" style="color: var(--text-primary)">
                        {child.from_name || child.from_address || 'Unknown'}
                      </span>
                      {#if !child.is_read}
                        <span class="w-2 h-2 rounded-full bg-accent-500 shrink-0"></span>
                      {/if}
                      <span class="text-xs ml-auto shrink-0" style="color: var(--text-tertiary)">{formatDate(child.date)}</span>
                    </div>
                    <div class="text-xs truncate" style="color: var(--text-tertiary)">{child.snippet || ''}</div>
                  </div>
                </div>
              {/each}
            </div>
          {/if}
        {:else}
          <!-- ========== NORMAL EMAIL ROW ========== -->
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
                {#if showAccountDot && email.account_email && $accountColorMap[email.account_email]}
                  <span class="w-2 h-2 rounded-full shrink-0" style="background: {$accountColorMap[email.account_email].bg}" title={email.account_email}></span>
                {/if}
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
                <span class="text-xs ml-auto shrink-0" style="color: var(--text-tertiary)">{formatDate(email.date)}</span>
              </div>
              <div class="text-sm truncate mb-0.5" style="color: var(--text-primary); opacity: {email.is_read ? 0.8 : 1}">
                {email.subject || '(no subject)'}
              </div>
              <div class="flex items-center gap-2">
                <span class="text-xs truncate" style="color: var(--text-tertiary)">{email.snippet || ''}</span>
                {#if email.gmail_thread_id && seenThreadIds[email.id] && threadCounts[email.gmail_thread_id] > 1}
                  <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0" style="background: var(--bg-tertiary); color: var(--text-secondary)" title="Thread with {threadCounts[email.gmail_thread_id]} messages">
                    {threadCounts[email.gmail_thread_id]}
                  </span>
                {/if}
                {#if email.needs_reply}
                  <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-400">reply</span>
                {/if}
                {#if email.is_subscription}
                  <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400">sub</span>
                {/if}
                {#if email.ai_category}
                  <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 {categoryColors[email.ai_category] || ''}">{email.ai_category.replace('_', ' ')}</span>
                {/if}
                {#if email.ai_email_type}
                  <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 {emailTypeColors[email.ai_email_type] || ''}">{email.ai_email_type}</span>
                {/if}
              </div>
            </div>
          </div>
        {/if}
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
