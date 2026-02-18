<script>
  import { onMount } from 'svelte';
  import { slide } from 'svelte/transition';
  import { accountColorMap, selectedAccountId } from '../../lib/stores.js';
  import Icon from '../common/Icon.svelte';

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

  let showAccountCol = $derived($selectedAccountId === null);

  let selectedIds = $state(new Set());
  let expandedThreads = $state(new Set());
  let selectAll = $state(false);
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
    urgent: 'bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-300',
    can_ignore: 'bg-surface-100 text-surface-500 dark:bg-surface-800 dark:text-surface-500',
    fyi: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300',
    awaiting_reply: 'bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300',
  };

  const emailTypeColors = {
    work: 'bg-purple-100 text-purple-700 dark:bg-purple-500/20 dark:text-purple-300',
    personal: 'bg-teal-100 text-teal-700 dark:bg-teal-500/20 dark:text-teal-300',
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
    for (const tid of Object.keys(map)) {
      map[tid].sort((a, b) => new Date(a.date) - new Date(b.date));
    }
    return map;
  });

  const digestTypeConfig = {
    scheduling: { label: 'Scheduling', classes: 'bg-purple-100 text-purple-700 dark:bg-purple-500/20 dark:text-purple-300' },
    discussion: { label: 'Discussion', classes: 'bg-blue-100 text-blue-700 dark:bg-blue-500/20 dark:text-blue-300' },
    notification: { label: 'Notification', classes: 'bg-gray-100 text-gray-600 dark:bg-gray-700/50 dark:text-gray-300' },
    transactional: { label: 'Transactional', classes: 'bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-300' },
    other: { label: 'Thread', classes: 'bg-stone-100 text-stone-600 dark:bg-stone-700/50 dark:text-stone-300' },
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

<div class="flex flex-col h-full" class:select-none={resizing}>
  <!-- Search indicator -->
  {#if searchActive}
    <div class="px-4 py-2 border-b shrink-0 flex items-center gap-2" style="border-color: var(--border-color); background: var(--bg-tertiary)">
      <span class="shrink-0" style="color: var(--color-accent-500)">
        <Icon name="search" size={16} />
      </span>
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
                  <Icon name="check" size={12} class="text-white" strokeWidth={3} />
                {/if}
              </button>
            </th>
            <!-- Star col (fixed) -->
            <th class="px-1 py-2" style="width: 32px; min-width: 32px; max-width: 32px"></th>
            <!-- Account col (only in unified inbox) -->
            {#if showAccountCol}
              <th class="px-2 py-2 text-center text-xs font-semibold uppercase tracking-wider" style="color: var(--text-tertiary); width: 36px; min-width: 36px; max-width: 36px">
              </th>
            {/if}
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
            {#if hiddenDigestEmails.has(email.id)}
              <!-- Hidden: part of a digested thread (rendered grouped under header) -->
            {:else if email.thread_digest_type && seenThreadIds[email.id]}
              <!-- ========== DIGEST THREAD HEADER (collapsed or expanded) ========== -->
              {@const dConf = getDigestConfig(email.thread_digest_type)}
              {@const isExpanded = expandedThreads.has(email.gmail_thread_id)}
              {@const borderColor = email.thread_digest_type === 'scheduling' ? 'rgb(168, 85, 247)' : email.thread_digest_type === 'discussion' ? 'rgb(59, 130, 246)' : 'var(--border-color)'}
              <!-- svelte-ignore a11y_click_events_have_key_events -->
              <tr
                class="border-b cursor-pointer transition-fast"
                style="border-color: var(--border-subtle); background: {isExpanded ? 'var(--bg-tertiary)' : 'var(--bg-secondary)'}; border-left: 3px solid {borderColor};"
                onclick={(e) => toggleThread(email.gmail_thread_id, e)}
              >
                <td class="px-3 py-2" style="width: 40px">
                  <div class="transition-transform" style="transform: rotate({isExpanded ? '90' : '0'}deg)">
                    <Icon name="chevron-right" size={16} />
                  </div>
                </td>
                <td class="px-1 py-2" style="width: 32px"></td>
                {#if showAccountCol}
                  <td class="px-2 py-2 text-center" style="width: 36px">
                    {#if email.account_email && $accountColorMap[email.account_email]}
                      <span class="inline-block w-2.5 h-2.5 rounded-full" style="background: {$accountColorMap[email.account_email].bg}" title={email.account_email}></span>
                    {/if}
                  </td>
                {/if}
                <td class="px-3 py-2 overflow-hidden" style="{colStyle('from')}">
                  <div class="flex items-center gap-1.5">
                    <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium whitespace-nowrap {dConf.classes}">{dConf.label}</span>
                    {#if email.thread_digest_resolved}
                      <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium whitespace-nowrap bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-300">Resolved</span>
                    {/if}
                  </div>
                </td>
                <td class="px-3 py-2 overflow-hidden">
                  <div class="flex items-center gap-2 min-w-0">
                    <span class="truncate font-medium" style="color: var(--text-primary)">{email.subject || '(no subject)'}</span>
                    {#if email.thread_digest_type === 'scheduling' && email.thread_digest_outcome}
                      <span class="text-xs truncate hidden xl:inline font-medium" style="color: rgb(168, 85, 247)">— {email.thread_digest_outcome}</span>
                    {:else if email.thread_digest_summary}
                      <span class="text-xs truncate hidden xl:inline" style="color: var(--text-secondary)">— {email.thread_digest_summary}</span>
                    {/if}
                  </div>
                </td>
                <td class="px-3 py-2 overflow-hidden" style="{colStyle('category')}">
                  <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium whitespace-nowrap" style="background: var(--bg-tertiary); color: var(--text-secondary)">
                    {email.thread_digest_count || threadCounts[email.gmail_thread_id]} msgs
                  </span>
                </td>
                <td class="px-3 py-2 text-right whitespace-nowrap overflow-hidden" style="{colStyle('date')}">
                  <span class="text-xs" style="color: var(--text-tertiary)">{formatDate(email.date)}</span>
                </td>
              </tr>
              <!-- ========== EXPANDED THREAD CHILDREN (rendered inline) ========== -->
              {#if isExpanded && digestThreadEmails[email.gmail_thread_id]}
                {#each digestThreadEmails[email.gmail_thread_id] as child (child.id)}
                  <!-- svelte-ignore a11y_click_events_have_key_events -->
                  <tr
                    class="border-b cursor-pointer transition-fast"
                    style="border-color: var(--border-subtle); background: {selectedId === child.id ? 'var(--bg-hover)' : 'var(--bg-primary)'}; border-left: 3px solid {borderColor};"
                    transition:slide={{ duration: 150 }}
                    onclick={() => onSelect && onSelect(child.id)}
                  >
                    <td class="py-2" style="width: 40px"></td>
                    <td class="px-1 py-2" style="width: 32px"></td>
                    {#if showAccountCol}
                      <td class="px-2 py-2" style="width: 36px"></td>
                    {/if}
                    <td class="px-3 py-2 overflow-hidden" style="{colStyle('from')}">
                      <div class="flex items-center gap-2 pl-2">
                        {#if !child.is_read}
                          <span class="w-2 h-2 rounded-full bg-accent-500 shrink-0"></span>
                        {/if}
                        <span class="truncate text-xs" style="color: var(--text-primary)">{child.from_name || child.from_address || 'Unknown'}</span>
                      </div>
                    </td>
                    <td class="px-3 py-2 overflow-hidden">
                      <span class="text-xs truncate" style="color: var(--text-tertiary)">{child.snippet || ''}</span>
                    </td>
                    <td class="px-3 py-2 overflow-hidden" style="{colStyle('category')}"></td>
                    <td class="px-3 py-2 text-right whitespace-nowrap overflow-hidden" style="{colStyle('date')}">
                      <span class="text-xs" style="color: var(--text-tertiary)">{formatDate(child.date)}</span>
                    </td>
                  </tr>
                {/each}
              {/if}
            {:else}
              <!-- ========== NORMAL EMAIL ROW ========== -->
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
                      <Icon name="check" size={12} class="text-white" strokeWidth={3} />
                    {/if}
                  </button>
                </td>
                <td class="px-1 py-2" style="width: 32px">
                  <button
                    onclick={(e) => { e.stopPropagation(); onAction && onAction(email.is_starred ? 'unstar' : 'star', [email.id]); }}
                    style="color: {email.is_starred ? 'var(--color-accent-500)' : 'var(--text-tertiary)'}"
                  >
                    <Icon name="star" size={16} />
                  </button>
                </td>
                {#if showAccountCol}
                  <td class="px-2 py-2 text-center" style="width: 36px">
                    {#if email.account_email && $accountColorMap[email.account_email]}
                      <span
                        class="inline-block w-2.5 h-2.5 rounded-full"
                        style="background: {$accountColorMap[email.account_email].bg}"
                        title={email.account_email}
                      ></span>
                    {/if}
                  </td>
                {/if}
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
                      <span class="shrink-0" style="color: var(--text-tertiary)">
                        <Icon name="paperclip" size={14} />
                      </span>
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
                      <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium whitespace-nowrap bg-blue-100 dark:bg-blue-500/20 text-blue-700 dark:text-blue-300">
                        reply
                      </span>
                    {/if}
                    {#if email.is_subscription}
                      <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium whitespace-nowrap bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-300">
                        sub
                      </span>
                    {/if}
                    {#if email.ai_category}
                      <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium whitespace-nowrap {categoryColors[email.ai_category] || ''}">
                        {email.ai_category.replace('_', ' ')}
                      </span>
                    {/if}
                    {#if email.ai_email_type}
                      <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium whitespace-nowrap {emailTypeColors[email.ai_email_type] || ''}">
                        {email.ai_email_type}
                      </span>
                    {/if}
                  </div>
                </td>
                <td class="px-3 py-2 text-right whitespace-nowrap overflow-hidden" style="{colStyle('date')}">
                  <span class="text-xs" style="color: var(--text-tertiary)">{formatDate(email.date)}</span>
                </td>
              </tr>
            {/if}
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
