<script>
  import { slide } from 'svelte/transition';
  import { accountColorMap, accounts, labels as labelsStore, selectedAccountId } from '../../lib/stores.js';
  import Icon from '../common/Icon.svelte';
  import { cleanEmailText, categoryLabel, typeLabel } from '../../lib/emailText.js';
  import { focusEmailRow, shouldFocusAdjacentRow } from '../../lib/emailRowFocus.js';
  import { formatSnoozeWake } from '../../lib/remindLater.js';
  import { safeLabelColor, visibleUserLabels } from '../../lib/labelWorkflows.js';
  import { placementProvenanceLabel } from '../../lib/focusedInbox.js';

  let {
    emails = [],
    loading = false,
    loadingMore = false,
    hasMore = false,
    total = 0,
    selectedId = null,
    mailbox = 'INBOX',
    searchActive = false,
    loadFailed = false,
    actionsDisabled = false,
    sectionTotals = null,
    selectionEpoch = 0,
    selectedIds = new Set(),
    onSelect = null,
    onFocus = null,
    onToggleSelection = null,
    onSelectLoaded = null,
    onClearSelection = null,
    onAction = null,
    onLabel = null,
    allowMove = false,
    onSnooze = null,
    onTeachSplit = null,
    onManageSplitRules = null,
    onLoadMore = null,
  } = $props();

  let showAccountCol = $derived($selectedAccountId === null);

  let expandedThreads = $state(new Set());
  let selectAll = $derived(emails.length > 0 && emails.every(email => selectedIds.has(email.id)));
  let sentinelEl = $state(null);
  let tableEl = $state(null);
  let observer = null;
  let previousSelectedId = null;
  let previousEmailIds = new Set();
  let conversationResults = $derived(emails.some(email => email?.conversation_scope));

  $effect(() => {
    const currentEmailIds = new Set(emails.map(email => email.id));
    const focusAdjacent = shouldFocusAdjacentRow({
      previousSelectedId,
      selectedId,
      previousEmailIds,
      emailIds: currentEmailIds,
    });
    const focusId = selectedId;

    previousSelectedId = selectedId;
    previousEmailIds = currentEmailIds;

    if (focusAdjacent) {
      queueMicrotask(() => {
        if (selectedId === focusId) focusEmailRow(tableEl, focusId);
      });
    }
  });

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
        if (entry && entry.isIntersecting && hasMore && !loadingMore && !loading && !actionsDisabled) {
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
    if (actionsDisabled) return;
    onToggleSelection?.(id, { range: Boolean(event.shiftKey) });
  }

  function toggleSelectAll() {
    if (actionsDisabled) return;
    if (selectAll) onClearSelection?.();
    else onSelectLoaded?.();
  }

  function activateRow(event, callback) {
    if (event.target !== event.currentTarget) return;
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      callback();
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
  function shouldShowRecipient(mailbox, email = null) {
    return mailbox === 'SENT'
      || mailbox === 'DRAFTS'
      || (searchActive && Boolean(email?.is_sent || email?.is_draft));
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
      if (!tid || !e.thread_digest_type || e.conversation_scope) continue;
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
      if (!tid || !e.thread_digest_type || e.conversation_scope) continue;
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
  <!-- Table -->
  <div class="flex-1 overflow-auto" bind:this={tableEl}>
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
    {:else if loadFailed}
      <div class="flex items-center justify-center h-full p-8 text-center">
        <p class="text-xs" style="color: var(--text-tertiary)">Results unavailable. Use Try again above.</p>
      </div>
    {:else if emails.length === 0 && !loading}
      <div class="flex flex-col items-center justify-center h-full text-center p-8">
        <div class="text-4xl mb-3 opacity-40">
          {#if searchActive}🔍{:else}📭{/if}
        </div>
        <p class="text-sm font-medium" style="color: var(--text-primary)">
          {#if searchActive}No mail matches this search
          {:else if mailbox === 'SNOOZED'}No snoozed emails
          {:else if sectionTotals}Split Inbox is clear
          {:else}No emails{/if}
        </p>
        {#if searchActive}
          <p class="text-xs mt-1" style="color: var(--text-secondary)">Edit a filter above or clear the search</p>
        {:else if mailbox === 'SNOOZED'}
          <p class="text-xs mt-1" style="color: var(--text-secondary)">Messages you snooze will wait here until their reminder time</p>
        {:else if sectionTotals}
          <p class="text-xs mt-1" style="color: var(--text-secondary)">There are no Focused or Other conversations in Inbox</p>
        {/if}
      </div>
    {:else}
      <table class="w-full text-sm table-fixed">
        <thead class="sticky top-0 z-10" style="background: var(--bg-tertiary)">
          <tr class="border-b" style="border-color: var(--border-color)">
            <!-- Checkbox col (fixed) -->
            <th class="px-0 py-0 text-center" style="width: 48px; min-width: 48px; max-width: 48px">
              <button
                onclick={toggleSelectAll}
                disabled={actionsDisabled}
                class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md transition-fast disabled:opacity-50"
                aria-label={selectAll ? `Deselect all loaded ${conversationResults ? 'conversations' : 'emails'}` : `Select all loaded ${conversationResults ? 'conversations' : 'emails'}`}
              >
                <span class="flex h-4 w-4 items-center justify-center rounded border" style="border-color: var(--border-color); background: {selectAll ? 'var(--color-accent-500)' : 'transparent'}">
                  {#if selectAll}<Icon name="check" size={12} class="text-white" strokeWidth={3} />{/if}
                </span>
              </button>
            </th>
            <!-- Star col (fixed) -->
            <th class="px-1 py-2" style="width: 32px; min-width: 32px; max-width: 32px"></th>
            <!-- Snooze col (fixed) -->
            <th class="px-1 py-2" style="width: 36px; min-width: 36px; max-width: 36px"><span class="sr-only">Snooze</span></th>
            <!-- Account col (only in unified inbox) -->
            {#if showAccountCol}
              <th class="px-2 py-2 text-center text-xs font-semibold uppercase tracking-wider" style="color: var(--text-tertiary); width: 36px; min-width: 36px; max-width: 36px">
              </th>
            {/if}
            <!-- From / To -->
            <th class="relative px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider" style="color: var(--text-tertiary); {colStyle('from')}">
              {searchActive ? 'People' : (shouldShowRecipient(mailbox) ? 'To' : 'From')}
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
          {#if sectionTotals}
            <tr data-inbox-section="focused">
              <td
                colspan={showAccountCol ? 8 : 7}
                class="sticky z-10 border-b px-4 py-2.5 text-left"
                style="top: 37px; background: color-mix(in srgb, var(--bg-secondary) 94%, var(--color-accent-500) 6%); border-color: var(--border-color)"
              >
                <span role="heading" aria-level="2" class="text-sm font-semibold" style="color: var(--text-primary)">Focused</span>
                <span class="ml-2 text-xs tabular-nums font-normal" style="color: var(--text-tertiary)">{sectionTotals.focused.toLocaleString()}</span>
                <span class="ml-3 text-[11px] font-normal" style="color: var(--text-secondary)">Priority, reply, trusted, and direct conversations</span>
                <button
                  type="button"
                  class="float-right inline-flex min-h-11 items-center justify-center rounded-lg border px-3 text-xs font-semibold"
                  style="border-color: var(--border-color); color: var(--text-secondary); background: var(--bg-primary)"
                  disabled={actionsDisabled || !onManageSplitRules}
                  data-shortcut="inbox.manageSplitRules"
                  onclick={() => onManageSplitRules?.()}
                >Rules</button>
              </td>
            </tr>
            {#if sectionTotals.focused === 0}
              <tr>
                <td colspan={showAccountCol ? 8 : 7} class="border-b px-4 py-4 text-xs" style="border-color: var(--border-subtle); color: var(--text-tertiary)">No conversations need focus right now.</td>
              </tr>
            {/if}
          {/if}
          {#each emails as email, emailIndex (email.id)}
            {#if sectionTotals && email.inbox_placement === 'other' && (emailIndex === 0 || emails[emailIndex - 1]?.inbox_placement !== 'other')}
              <tr data-inbox-section="other">
                <td
                  colspan={showAccountCol ? 8 : 7}
                  class="sticky z-10 border-y px-4 py-2.5 text-left"
                  style="top: 37px; background: var(--bg-tertiary); border-color: var(--border-color)"
                >
                  <span role="heading" aria-level="2" class="text-sm font-semibold" style="color: var(--text-primary)">Other</span>
                  <span class="ml-2 text-xs tabular-nums font-normal" style="color: var(--text-tertiary)">{sectionTotals.other.toLocaleString()}</span>
                  <span class="ml-3 text-[11px] font-normal" style="color: var(--text-secondary)">Lower-priority conversations · still in Inbox</span>
                </td>
              </tr>
            {/if}
            {#if hiddenDigestEmails.has(email.id)}
              <!-- Hidden: part of a digested thread (rendered grouped under header) -->
            {:else if !email.conversation_scope && email.thread_digest_type && seenThreadIds[email.id]}
              <!-- ========== DIGEST THREAD HEADER (collapsed or expanded) ========== -->
              {@const dConf = getDigestConfig(email.thread_digest_type)}
              {@const isExpanded = expandedThreads.has(email.gmail_thread_id)}
              {@const borderColor = email.thread_digest_type === 'scheduling' ? 'rgb(168, 85, 247)' : email.thread_digest_type === 'discussion' ? 'rgb(59, 130, 246)' : 'var(--border-color)'}
              <tr
                class="border-b cursor-pointer transition-fast"
                style="border-color: var(--border-subtle); background: {isExpanded ? 'var(--bg-tertiary)' : 'var(--bg-secondary)'}; border-left: 3px solid {borderColor};"
                onclick={(e) => toggleThread(email.gmail_thread_id, e)}
                onkeydown={(e) => activateRow(e, () => toggleThread(email.gmail_thread_id, e))}
                tabindex="0"
                aria-expanded={isExpanded}
                aria-label="{cleanEmailText(email.subject) || 'No subject'} conversation"
              >
                <td class="px-0 py-2" style="width: 48px">
                  <div class="transition-transform" style="transform: rotate({isExpanded ? '90' : '0'}deg)">
                    <Icon name="chevron-right" size={16} />
                  </div>
                </td>
                <td class="px-1 py-2" style="width: 32px"></td>
                <td class="px-1 py-2" style="width: 36px">
                  {#if onSnooze && !email.is_draft && !email.is_trash && !email.is_spam}
                    <button
                      type="button"
                      onclick={(event) => { event.stopPropagation(); onSnooze(email); }}
                      disabled={actionsDisabled}
                      class="flex min-h-9 min-w-9 items-center justify-center rounded-md disabled:opacity-50"
                      style="color: {email.snooze_id ? 'var(--color-accent-600)' : 'var(--text-tertiary)'}"
                      aria-label={email.snooze_id ? 'Change conversation reminder' : 'Snooze conversation'}
                    ><Icon name="clock" size={15} /></button>
                  {/if}
                </td>
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
                    <span class="truncate font-medium" style="color: var(--text-primary)">{cleanEmailText(email.subject) || '(no subject)'}</span>
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
                  <tr
                    class="border-b cursor-pointer transition-fast"
                    style="border-color: var(--border-subtle); background: {selectedId === child.id ? 'var(--bg-hover)' : 'var(--bg-primary)'}; border-left: 3px solid {borderColor};"
                    transition:slide={{ duration: 150 }}
                    onclick={() => onSelect && onSelect(child.id)}
                    onkeydown={(e) => activateRow(e, () => onSelect && onSelect(child.id))}
                    tabindex="0"
                    aria-label="Open message from {cleanEmailText(child.from_name || child.from_address || 'Unknown')}"
                    data-email-row-id={child.id}
                  >
                    <td class="py-2" style="width: 48px"></td>
                    <td class="px-1 py-2" style="width: 32px"></td>
                    <td class="px-1 py-2" style="width: 36px"></td>
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
                      <span class="text-xs truncate" style="color: var(--text-tertiary)">{cleanEmailText(child.snippet)}</span>
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
              {@const userLabelState = visibleUserLabels(email, $labelsStore, $accounts, 2)}
              <tr
                class="border-b cursor-pointer transition-fast"
                style="border-color: var(--border-subtle); background: {selectedId === email.id ? 'var(--bg-hover)' : 'var(--bg-secondary)'}"
                onclick={() => onSelect && onSelect(email.id)}
                onkeydown={(e) => activateRow(e, () => onSelect && onSelect(email.id))}
                onfocus={() => onFocus && onFocus(email.id)}
                tabindex="0"
                aria-label="Open {email.conversation_scope ? 'conversation' : 'email'}: {cleanEmailText(email.subject) || 'No subject'}"
                aria-selected={selectedIds.has(email.id)}
                data-triage-row-id={email.id}
                data-email-row-id={email.id}
              >
                <td class="px-0 py-0 text-center" style="width: 48px">
                  <button
                    onclick={(e) => toggleSelect(email.id, e)}
                    disabled={actionsDisabled}
                    class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md transition-fast disabled:opacity-50"
                    aria-label="{selectedIds.has(email.id) ? 'Deselect' : 'Select'} {cleanEmailText(email.subject) || (email.conversation_scope ? 'conversation' : 'email')}"
                  >
                    <span class="flex h-4 w-4 items-center justify-center rounded border" style="border-color: var(--border-color); background: {selectedIds.has(email.id) ? 'var(--color-accent-500)' : 'transparent'}">
                      {#if selectedIds.has(email.id)}<Icon name="check" size={12} class="text-white" strokeWidth={3} />{/if}
                    </span>
                  </button>
                </td>
                <td class="px-1 py-2" style="width: 32px">
                  <button
                    onclick={(e) => { e.stopPropagation(); onAction && onAction(email.is_starred ? 'unstar' : 'star', [email.id]); }}
                    disabled={actionsDisabled}
                    class="disabled:opacity-50"
                    style="color: {email.is_starred ? 'var(--color-accent-500)' : 'var(--text-tertiary)'}"
                    aria-label="{email.star_state === 'some' ? 'Some messages starred; unstar conversation' : (email.is_starred ? 'Unstar' : 'Star')} {cleanEmailText(email.subject) || (email.conversation_scope ? 'conversation' : 'email')}"
                  >
                    <Icon name="star" size={16} />
                  </button>
                </td>
                <td class="px-1 py-2" style="width: 36px">
                  {#if onSnooze && !email.is_draft && !email.is_trash && !email.is_spam}
                    <button
                      type="button"
                      onclick={(event) => { event.stopPropagation(); onSnooze(email); }}
                      disabled={actionsDisabled}
                      class="flex min-h-9 min-w-9 items-center justify-center rounded-md disabled:opacity-50"
                      style="color: {email.snooze_id ? 'var(--color-accent-600)' : 'var(--text-tertiary)'}"
                      aria-label={email.snooze_id ? `Change reminder for ${cleanEmailText(email.subject) || 'email'}` : `Snooze ${cleanEmailText(email.subject) || 'email'}`}
                      title={email.snooze_id ? 'Change reminder' : 'Snooze'}
                    ><Icon name="clock" size={15} /></button>
                  {/if}
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
                      {getPrimaryDisplayInfo(email, shouldShowRecipient(mailbox, email))}
                    </span>
                  </div>
                </td>
                <td class="px-3 py-2 overflow-hidden">
                  <div class="flex items-center gap-2 min-w-0">
                    <span class="truncate" class:font-semibold={!email.is_read} style="color: var(--text-primary)">
                      {cleanEmailText(email.subject) || '(no subject)'}
                    </span>
                    {#each userLabelState.labels as label}
                      <span
                        class="max-w-24 shrink-0 truncate rounded-full px-1.5 py-0.5 text-[10px] font-medium"
                        style="background: {label.coverage === 'some' ? 'transparent' : safeLabelColor(label.color_bg, 'var(--bg-tertiary)')}; color: {safeLabelColor(label.color_text, 'var(--text-secondary)')}; border: {label.coverage === 'some' ? `1px dashed ${safeLabelColor(label.color_text, 'var(--border-color)')}` : '1px solid transparent'}"
                        title={label.coverage === 'some' ? `${label.name} on some messages` : label.name}
                      >{label.name}</span>
                    {/each}
                    {#if userLabelState.overflow > 0}
                      <span class="shrink-0 text-[10px]" style="color: var(--text-tertiary)" title={`${userLabelState.overflow} more labels`}>+{userLabelState.overflow}</span>
                    {/if}
                    {#if email.has_attachments}
                      <span class="shrink-0" style="color: var(--text-tertiary)">
                        <Icon name="paperclip" size={14} />
                      </span>
                    {/if}
                    <span class="text-xs truncate hidden xl:inline" style="color: var(--text-tertiary)">
                      — {cleanEmailText(email.snippet)}
                    </span>
                  </div>
                </td>
                <td class="px-3 py-2 overflow-hidden" style="{colStyle('category')}">
                  <div class="flex items-center gap-1 flex-wrap">
                    {#if (email.member_count || (email.gmail_thread_id && seenThreadIds[email.id] ? threadCounts[email.gmail_thread_id] : 0)) > 1}
                      {@const displayCount = email.member_count || threadCounts[email.gmail_thread_id]}
                      <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium whitespace-nowrap" style="background: var(--bg-tertiary); color: var(--text-secondary)" title="Conversation with {displayCount} messages">
                        {displayCount}
                      </span>
                    {/if}
                    {#if email.needs_reply}
                      <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium whitespace-nowrap bg-blue-100 dark:bg-blue-500/20 text-blue-700 dark:text-blue-300">
                        Needs reply
                      </span>
                    {/if}
                    {#if sectionTotals && placementProvenanceLabel(email)}
                      <button
                        type="button"
                        class="min-h-7 rounded-full px-2 text-[10px] font-medium whitespace-nowrap"
                        style="background: var(--bg-tertiary); color: var(--text-secondary)"
                        disabled={actionsDisabled || !onTeachSplit}
                        title="Explain or change this Split Inbox placement"
                        aria-label="Why this conversation is in {email.inbox_placement === 'other' ? 'Other' : 'Focused'}: {placementProvenanceLabel(email)}. Open Teach Split Inbox"
                        onclick={(event) => { event.stopPropagation(); onTeachSplit?.(email); }}
                      >{placementProvenanceLabel(email)}</button>
                    {/if}
                    {#if sectionTotals}
                      <button
                        type="button"
                        class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md disabled:opacity-50"
                        style="color: var(--text-tertiary)"
                        disabled={actionsDisabled}
                        aria-label="Teach Split Inbox for this conversation"
                        title="Teach Split Inbox"
                        onclick={(event) => { event.stopPropagation(); onTeachSplit?.(email); }}
                      ><Icon name="target" size={16} /></button>
                    {/if}
                    {#if email.is_subscription}
                      <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium whitespace-nowrap bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-300">
                        Subscription
                      </span>
                    {/if}
                    {#if email.snooze_wake_at}
                      <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium whitespace-nowrap bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-300" title={formatSnoozeWake(email.snooze_wake_at, email.snooze_time_zone || undefined)}>
                        {formatSnoozeWake(email.snooze_wake_at, email.snooze_time_zone || undefined, { compact: true })}
                      </span>
                    {/if}
                    {#if email.ai_category}
                      <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium whitespace-nowrap {categoryColors[email.ai_category] || ''}">
                        {categoryLabel(email.ai_category)}
                      </span>
                    {/if}
                    {#if email.ai_email_type}
                      <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium whitespace-nowrap {emailTypeColors[email.ai_email_type] || ''}">
                        {typeLabel(email.ai_email_type)}
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
          {#if sectionTotals && sectionTotals.other === 0}
            <tr data-inbox-section="other">
              <td
                colspan={showAccountCol ? 8 : 7}
                class="border-y px-4 py-2.5 text-left"
                style="background: var(--bg-tertiary); border-color: var(--border-color)"
              >
                <span role="heading" aria-level="2" class="text-sm font-semibold" style="color: var(--text-primary)">Other</span>
                <span class="ml-2 text-xs tabular-nums font-normal" style="color: var(--text-tertiary)">0</span>
                <span class="ml-3 text-[11px] font-normal" style="color: var(--text-secondary)">No lower-priority conversations · everything remains in Inbox</span>
              </td>
            </tr>
          {/if}
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
        Showing {emails.length.toLocaleString()} of {total.toLocaleString()} {conversationResults ? (total === 1 ? 'conversation' : 'conversations') : ''}
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
