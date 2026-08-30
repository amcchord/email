<script>
  import { onMount } from 'svelte';
  import { slide } from 'svelte/transition';
  import { accountColorMap, selectedAccountId } from '../../lib/stores.js';
  import Icon from '../common/Icon.svelte';
  import { cleanEmailText, categoryLabel, typeLabel } from '../../lib/emailText.js';
  import { focusEmailRow, shouldFocusAdjacentRow } from '../../lib/emailRowFocus.js';
  import { selectedBooleanState } from '../../lib/inboxDataset.js';
  import { formatSnoozeWake } from '../../lib/remindLater.js';

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
    selectionEpoch = 0,
    onSelect = null,
    onAction = null,
    onSnooze = null,
    onLoadMore = null,
  } = $props();

  let showAccountDot = $derived($selectedAccountId === null);

  let selectedIds = $state(new Set());
  let bulkActionPending = $state(false);
  let expandedThreads = $state(new Set());
  let sentinelEl = $state(null);
  let listEl = $state(null);
  let observer = null;
  let previousSelectedId = null;
  let previousEmailIds = new Set();
  let selectedSpamState = $derived(selectedBooleanState(emails, selectedIds, 'is_spam'));
  let selectedTrashState = $derived(selectedBooleanState(emails, selectedIds, 'is_trash'));
  let selectedInProtectedMailbox = $derived(
    emails.some(email => selectedIds.has(email.id) && (email.is_spam || email.is_trash))
  );

  $effect(() => {
    void selectionEpoch;
    void actionsDisabled;
    selectedIds = new Set();
  });

  $effect(() => {
    const currentEmailIds = new Set(emails.map(email => email.id));
    for (const threadEmails of Object.values(digestThreadEmails)) {
      for (const child of threadEmails) currentEmailIds.add(child.id);
    }
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
        if (selectedId === focusId) focusEmailRow(listEl, focusId);
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

  // Set up IntersectionObserver to trigger loading more when sentinel is visible
  $effect(() => {
    if (observer) {
      observer.disconnect();
    }
    if (sentinelEl) {
      observer = new IntersectionObserver((entries) => {
        const entry = entries[0];
        if (entry && entry.isIntersecting && hasMore && !loadingMore && !loading && !actionsDisabled) {
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
    if (actionsDisabled) return;
    const next = new Set(selectedIds);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    selectedIds = next;
  }

  function activateRow(event, callback) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      callback();
    }
  }

  async function handleBulkAction(action) {
    if (actionsDisabled || bulkActionPending || selectedIds.size === 0 || !onAction) return;
    bulkActionPending = true;
    try {
      const accepted = await onAction(action, Array.from(selectedIds));
      if (accepted) selectedIds = new Set();
    } finally {
      bulkActionPending = false;
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

  // Helper to determine if we should show recipient instead of sender
  function shouldShowRecipient(mailbox, email = null) {
    return mailbox === 'SENT'
      || mailbox === 'DRAFTS'
      || (searchActive && Boolean(email?.is_sent || email?.is_draft));
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

<div class="flex flex-col h-full">
  <!-- Toolbar -->
  {#if selectedIds.size > 0}
    <div class="flex flex-col items-stretch gap-1 px-3 py-2 border-b shrink-0 sm:flex-row sm:items-center sm:gap-2" style="border-color: var(--border-color); background: var(--bg-tertiary)" aria-busy={bulkActionPending}>
      <span class="text-xs font-medium shrink-0" style="color: var(--text-secondary)">{selectedIds.size} selected</span>
      <div class="grid grid-cols-3 gap-1 sm:ml-auto sm:flex sm:min-w-0 sm:flex-1 sm:flex-wrap sm:justify-end">
        <button onclick={() => handleBulkAction('mark_read')} disabled={actionsDisabled || bulkActionPending} class="min-h-11 px-3 text-xs rounded disabled:opacity-50" style="color: var(--text-secondary)">Read</button>
        <button onclick={() => handleBulkAction('mark_unread')} disabled={actionsDisabled || bulkActionPending} class="min-h-11 px-3 text-xs rounded disabled:opacity-50" style="color: var(--text-secondary)">Unread</button>
        <button onclick={() => handleBulkAction('archive')} disabled={actionsDisabled || bulkActionPending || selectedInProtectedMailbox} title={selectedInProtectedMailbox ? 'Restore spam or trash results before archiving' : 'Archive selected email'} class="min-h-11 px-3 text-xs rounded disabled:opacity-50" style="color: var(--text-secondary)">Archive</button>
        <button onclick={() => handleBulkAction('star')} disabled={actionsDisabled || bulkActionPending} class="min-h-11 px-3 text-xs rounded disabled:opacity-50" style="color: var(--text-secondary)">Star</button>
        {#if selectedSpamState === true}
          <button onclick={() => handleBulkAction('unspam')} disabled={actionsDisabled || bulkActionPending} class="min-h-11 px-3 text-xs rounded font-medium disabled:opacity-50" style="color: var(--color-accent-600)">Not Spam</button>
        {:else if selectedSpamState === false}
          <button onclick={() => handleBulkAction('spam')} disabled={actionsDisabled || bulkActionPending} class="min-h-11 px-3 text-xs rounded text-red-500 disabled:opacity-50">Spam</button>
        {:else}
          <button disabled title="Selected results have mixed spam states" class="min-h-11 px-3 text-xs rounded disabled:opacity-50" style="color: var(--text-secondary)">Spam varies</button>
        {/if}
        {#if selectedTrashState === true}
          <button onclick={() => handleBulkAction('untrash')} disabled={actionsDisabled || bulkActionPending} class="min-h-11 px-3 text-xs rounded font-medium disabled:opacity-50" style="color: var(--color-accent-600)">Restore</button>
        {:else if selectedTrashState === false}
          <button onclick={() => handleBulkAction('trash')} disabled={actionsDisabled || bulkActionPending} class="min-h-11 px-3 text-xs rounded text-red-500 disabled:opacity-50">Trash</button>
        {:else}
          <button disabled title="Selected results have mixed trash states" class="min-h-11 px-3 text-xs rounded disabled:opacity-50" style="color: var(--text-secondary)">Trash varies</button>
        {/if}
      </div>
    </div>
  {/if}

  <!-- Email list -->
  <div class="flex-1 overflow-y-auto" bind:this={listEl}>
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
    {:else if loadFailed}
      <div class="flex items-center justify-center h-full p-8 text-center">
        <p class="text-xs" style="color: var(--text-tertiary)">Results unavailable. Use Try again above.</p>
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
          {#if searchActive}No mail matches this search
          {:else if mailbox === 'SPAM'}No spam
          {:else if mailbox === 'SNOOZED'}No snoozed emails
          {:else}No emails
          {/if}
        </p>
        <p class="text-xs mt-1" style="color: var(--text-secondary)">
          {#if searchActive}Edit a filter above or clear the search
          {:else if mailbox === 'SPAM'}Your spam folder is clean
          {:else if mailbox === 'SNOOZED'}Snoozed messages will appear here
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
            onkeydown={(e) => activateRow(e, () => toggleThread(email.gmail_thread_id, e))}
            role="button"
            tabindex="0"
            aria-expanded={isExpanded}
            aria-label="{cleanEmailText(email.subject) || 'No subject'} conversation"
          >
            <!-- Chevron -->
            <div class="mt-1 shrink-0 transition-transform" style="color: var(--text-tertiary); transform: rotate({isExpanded ? '90' : '0'}deg)">
              <Icon name="chevron-right" size={16} />
            </div>

            <!-- Conversation type icon -->
            <div class="mt-0.5 w-7 h-7 rounded-full flex items-center justify-center shrink-0 {dConf.classes}" style="opacity: 0.9">
              {#if email.thread_digest_type === 'scheduling'}
                <Icon name="calendar" size={14} />
              {:else if email.thread_digest_type === 'discussion'}
                <Icon name="message-circle" size={14} />
              {:else if email.thread_digest_type === 'notification'}
                <Icon name="bell" size={14} />
              {:else}
                <Icon name="mail" size={14} />
              {/if}
            </div>

            <!-- Content -->
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-1.5 mb-0.5">
                <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 {dConf.classes}">{dConf.label}</span>
                {#if email.thread_digest_resolved}
                  <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-300">Resolved</span>
                {/if}
                <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0" style="background: var(--bg-tertiary); color: var(--text-secondary)">
                  {email.thread_digest_count || threadCounts[email.gmail_thread_id]} msgs
                </span>
                {#if showAccountDot && email.account_email && $accountColorMap[email.account_email]}
                  <span class="w-2 h-2 rounded-full shrink-0" style="background: {$accountColorMap[email.account_email].bg}" title={email.account_email}></span>
                {/if}
                <span class="text-xs ml-auto shrink-0" style="color: var(--text-tertiary)">{formatDate(email.date)}</span>
              </div>
              <div class="text-sm truncate mb-0.5" style="color: var(--text-primary)">{cleanEmailText(email.subject) || '(no subject)'}</div>
              {#if email.thread_digest_type === 'scheduling' && email.thread_digest_outcome}
                <div class="text-xs truncate font-medium" style="color: rgb(168, 85, 247)">{email.thread_digest_outcome}</div>
              {:else if email.thread_digest_summary}
                <div class="text-xs truncate" style="color: var(--text-secondary)">{email.thread_digest_summary}</div>
              {:else}
                <div class="text-xs truncate" style="color: var(--text-tertiary)">{cleanEmailText(email.snippet)}</div>
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
                  onkeydown={(e) => activateRow(e, () => onSelect && onSelect(child.id))}
                  role="button"
                  tabindex="0"
                  aria-label="Open message from {cleanEmailText(child.from_name || child.from_address || 'Unknown')}"
                  data-email-row-id={child.id}
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
                    <div class="text-xs truncate" style="color: var(--text-tertiary)">{cleanEmailText(child.snippet)}</div>
                  </div>
                </div>
              {/each}
            </div>
          {/if}
        {:else}
          <!-- ========== NORMAL EMAIL ROW ========== -->
          <div
            class="flex items-start gap-1 px-2 py-2 border-b transition-fast"
            class:font-medium={!email.is_read}
            style="border-color: var(--border-subtle); background: {selectedId === email.id ? 'var(--bg-hover)' : 'var(--bg-secondary)'};"
          >
            <!-- Checkbox -->
            <button
              onclick={(e) => toggleSelect(email.id, e)}
              disabled={actionsDisabled}
              class="min-w-11 min-h-11 rounded-md flex items-center justify-center shrink-0 transition-fast disabled:opacity-50"
              aria-label="{selectedIds.has(email.id) ? 'Deselect' : 'Select'} {cleanEmailText(email.subject) || 'email'}"
            >
              <span
                class="w-4 h-4 rounded border flex items-center justify-center"
                style="border-color: var(--border-color); background: {selectedIds.has(email.id) ? 'var(--color-accent-500)' : 'transparent'}"
                aria-hidden="true"
              >
                {#if selectedIds.has(email.id)}
                  <Icon name="check" size={12} class="text-white" strokeWidth={3} />
                {/if}
              </span>
            </button>

            <!-- Star -->
            <button
              onclick={(e) => { e.stopPropagation(); onAction && onAction(email.is_starred ? 'unstar' : 'star', [email.id]); }}
              disabled={actionsDisabled}
              class="min-w-11 min-h-11 rounded-md inline-flex items-center justify-center shrink-0 transition-fast disabled:opacity-50"
              style="color: {email.is_starred ? 'var(--color-accent-500)' : 'var(--text-tertiary)'}"
              aria-label="{email.is_starred ? 'Unstar' : 'Star'} {cleanEmailText(email.subject) || 'email'}"
            >
              <Icon name="star" size={16} />
            </button>

            {#if onSnooze && !email.is_draft && !email.is_trash && !email.is_spam}
              <button
                type="button"
                onclick={(event) => { event.stopPropagation(); onSnooze(email); }}
                disabled={actionsDisabled}
                class="min-w-11 min-h-11 rounded-md inline-flex items-center justify-center shrink-0 transition-fast disabled:opacity-50"
                style="color: {email.snooze_id ? 'var(--color-accent-600)' : 'var(--text-tertiary)'}"
                aria-label={email.snooze_id ? `Change reminder for ${cleanEmailText(email.subject) || 'email'}` : `Snooze ${cleanEmailText(email.subject) || 'email'}`}
                title={email.snooze_id ? 'Change reminder' : 'Snooze'}
              >
                <Icon name="clock" size={16} />
              </button>
            {/if}

            <!-- Content -->
            <button
              type="button"
              class="flex-1 min-w-0 min-h-11 text-left py-1"
              onclick={() => onSelect && onSelect(email.id)}
              aria-label="Open email: {cleanEmailText(email.subject) || 'No subject'}"
              data-email-row-id={email.id}
            >
              <span class="flex items-center gap-2 mb-0.5">
                {#if showAccountDot && email.account_email && $accountColorMap[email.account_email]}
                  <span class="w-2 h-2 rounded-full shrink-0" style="background: {$accountColorMap[email.account_email].bg}" title={email.account_email}></span>
                {/if}
                <span class="text-sm truncate" style="color: var(--text-primary)">
                  {getPrimaryDisplayInfo(email, shouldShowRecipient(mailbox, email))}
                </span>
                {#if !email.is_read}
                  <span class="w-2 h-2 rounded-full bg-accent-500 shrink-0"></span>
                {/if}
                {#if email.has_attachments}
                  <span class="shrink-0" style="color: var(--text-tertiary)">
                    <Icon name="paperclip" size={14} />
                  </span>
                {/if}
                <span class="text-xs ml-auto shrink-0" style="color: var(--text-tertiary)">{formatDate(email.date)}</span>
              </span>
              <span class="block text-sm truncate mb-0.5" style="color: var(--text-primary); opacity: {email.is_read ? 0.8 : 1}">
                {cleanEmailText(email.subject) || '(no subject)'}
              </span>
              <span class="flex items-center gap-2">
                <span class="text-xs truncate" style="color: var(--text-tertiary)">{cleanEmailText(email.snippet)}</span>
                {#if email.gmail_thread_id && seenThreadIds[email.id] && threadCounts[email.gmail_thread_id] > 1}
                  <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0" style="background: var(--bg-tertiary); color: var(--text-secondary)" title="Thread with {threadCounts[email.gmail_thread_id]} messages">
                    {threadCounts[email.gmail_thread_id]}
                  </span>
                {/if}
                {#if email.needs_reply}
                  <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 bg-blue-100 dark:bg-blue-500/20 text-blue-700 dark:text-blue-300">Needs reply</span>
                {/if}
                {#if email.is_subscription}
                  <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-300">Subscription</span>
                {/if}
                {#if email.snooze_wake_at}
                  <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-300" title={formatSnoozeWake(email.snooze_wake_at, email.snooze_time_zone || undefined)}>
                    {formatSnoozeWake(email.snooze_wake_at, email.snooze_time_zone || undefined, { compact: true })}
                  </span>
                {/if}
                {#if email.ai_category}
                  <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 {categoryColors[email.ai_category] || ''}">{categoryLabel(email.ai_category)}</span>
                {/if}
                {#if email.ai_email_type}
                  <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 {emailTypeColors[email.ai_email_type] || ''}">{typeLabel(email.ai_email_type)}</span>
                {/if}
              </span>
            </button>
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
