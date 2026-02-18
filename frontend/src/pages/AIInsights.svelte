<script>
  import { onMount, onDestroy } from 'svelte';
  import { api } from '../lib/api.js';
  import { showToast, selectedEmailId, currentPage, currentMailbox, composeData, pendingReplyDraft } from '../lib/stores.js';
  import Icon from '../components/common/Icon.svelte';

  let activeTab = $state('overview');
  let trends = $state(null);
  let needsReplyData = $state(null);
  let subscriptionsData = $state(null);
  let threadsData = $state(null);
  let digestsData = $state(null);
  let bundlesData = $state(null);
  let aiStats = $state(null);
  let loading = $state(true);
  let tabLoading = $state(false);
  let digestFilter = $state(null); // conversation_type filter for digests
  let categorizing = $state(false);
  let unsubscribingId = $state(null);
  let unsubscribePreview = $state(null); // { emailId, to, subject, body }
  let showBackfillMenu = $state(false);
  let showDropConfirm = $state(false);
  let dropRebuildDays = $state(90);
  let dropping = $state(false);

  // AI processing progress state
  let processingStatus = $state(null);
  let processingPollInterval = null;
  let processingJustFinished = $state(false);

  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'needs-reply', label: 'Needs Reply' },
    { id: 'subscriptions', label: 'Subscriptions' },
    { id: 'conversations', label: 'Conversations' },
    { id: 'topics', label: 'Topics' },
  ];

  const conversationTypeConfig = {
    scheduling: { label: 'Scheduling', bg: 'bg-purple-100 dark:bg-purple-500/20', text: 'text-purple-700 dark:text-purple-300', icon: 'calendar' },
    discussion: { label: 'Discussion', bg: 'bg-blue-100 dark:bg-blue-500/20', text: 'text-blue-700 dark:text-blue-300', icon: 'chat' },
    notification: { label: 'Notification', bg: 'bg-gray-100 dark:bg-gray-700/50', text: 'text-gray-600 dark:text-gray-300', icon: 'bell' },
    transactional: { label: 'Transactional', bg: 'bg-green-100 dark:bg-green-500/20', text: 'text-green-700 dark:text-green-300', icon: 'receipt' },
    other: { label: 'Other', bg: 'bg-stone-100 dark:bg-stone-700/50', text: 'text-stone-600 dark:text-stone-300', icon: 'dot' },
  };

  function getConversationTypeConfig(type) {
    return conversationTypeConfig[type] || conversationTypeConfig.other;
  }

  function getProcessingLabel(status) {
    if (!status) return '';
    if (status.type === 'reprocess') {
      return `Reprocessing emails with ${status.model || 'AI'}`;
    }
    return 'Categorizing emails';
  }

  function getProcessingPercent(status) {
    if (!status || !status.total || status.total === 0) return 0;
    return Math.min(Math.round((status.processed / status.total) * 100), 100);
  }

  async function pollProcessingStatus() {
    try {
      const result = await api.getAIProcessingStatus();
      if (result.active) {
        processingStatus = result;
      } else if (result.just_finished) {
        // Processing just completed -- show briefly then refresh data
        processingStatus = null;
        processingJustFinished = true;
        stopProcessingPoll();
        setTimeout(() => {
          processingJustFinished = false;
        }, 3000);
        // Refresh insights data
        refreshAllData();
      } else {
        processingStatus = null;
        stopProcessingPoll();
      }
    } catch {
      // Ignore polling errors
    }
  }

  function startProcessingPoll() {
    stopProcessingPoll();
    pollProcessingStatus();
    processingPollInterval = setInterval(pollProcessingStatus, 3000);
  }

  function stopProcessingPoll() {
    if (processingPollInterval) {
      clearInterval(processingPollInterval);
      processingPollInterval = null;
    }
  }

  async function refreshAllData() {
    const results = await Promise.allSettled([
      api.getAITrends(),
      api.getNeedsReply(),
      api.getSubscriptions(),
      api.getThreadSummaries(),
      api.getAIStats(),
      api.getThreadDigests(),
      api.getEmailBundles(),
    ]);
    if (results[0].status === 'fulfilled') {
      trends = results[0].value;
    }
    if (results[1].status === 'fulfilled') {
      needsReplyData = results[1].value;
    }
    if (results[2].status === 'fulfilled') {
      subscriptionsData = results[2].value;
    }
    if (results[3].status === 'fulfilled') {
      threadsData = results[3].value;
    }
    if (results[4].status === 'fulfilled') {
      aiStats = results[4].value;
    }
    if (results[5].status === 'fulfilled') {
      digestsData = results[5].value;
    }
    if (results[6].status === 'fulfilled') {
      bundlesData = results[6].value;
    }
  }

  onMount(async () => {
    // Check for active AI processing and start polling if needed
    try {
      const status = await api.getAIProcessingStatus();
      if (status.active) {
        processingStatus = status;
        startProcessingPoll();
      }
    } catch {
      // Ignore
    }

    // Fetch all data in parallel so tab counts show immediately
    const results = await Promise.allSettled([
      api.getAITrends(),
      api.getNeedsReply(),
      api.getSubscriptions(),
      api.getThreadSummaries(),
      api.getAIStats(),
      api.getThreadDigests(),
      api.getEmailBundles(),
    ]);

    if (results[0].status === 'fulfilled') {
      trends = results[0].value;
    }
    if (results[1].status === 'fulfilled') {
      needsReplyData = results[1].value;
    }
    if (results[2].status === 'fulfilled') {
      subscriptionsData = results[2].value;
    }
    if (results[3].status === 'fulfilled') {
      threadsData = results[3].value;
    }
    if (results[4].status === 'fulfilled') {
      aiStats = results[4].value;
    }
    if (results[5].status === 'fulfilled') {
      digestsData = results[5].value;
    }
    if (results[6].status === 'fulfilled') {
      bundlesData = results[6].value;
    }

    loading = false;
  });

  onDestroy(() => {
    stopProcessingPoll();
  });

  async function switchTab(tabId) {
    activeTab = tabId;
    // Data is already loaded from mount, but refresh if missing
    if (tabId === 'needs-reply' && !needsReplyData) {
      tabLoading = true;
      try {
        needsReplyData = await api.getNeedsReply();
      } catch (err) {
        showToast(err.message, 'error');
      }
      tabLoading = false;
    } else if (tabId === 'subscriptions' && !subscriptionsData) {
      tabLoading = true;
      try {
        subscriptionsData = await api.getSubscriptions();
      } catch (err) {
        showToast(err.message, 'error');
      }
      tabLoading = false;
    } else if (tabId === 'conversations' && !digestsData) {
      tabLoading = true;
      try {
        digestsData = await api.getThreadDigests();
      } catch (err) {
        showToast(err.message, 'error');
      }
      tabLoading = false;
    } else if (tabId === 'topics' && !bundlesData) {
      tabLoading = true;
      try {
        bundlesData = await api.getEmailBundles();
      } catch (err) {
        showToast(err.message, 'error');
      }
      tabLoading = false;
    }
  }

  async function filterDigests(type) {
    if (digestFilter === type) {
      digestFilter = null;
    } else {
      digestFilter = type;
    }
    tabLoading = true;
    try {
      const params = {};
      if (digestFilter) {
        params.conversation_type = digestFilter;
      }
      digestsData = await api.getThreadDigests(params);
    } catch (err) {
      showToast(err.message, 'error');
    }
    tabLoading = false;
  }

  async function triggerAutoCategorize(days = null) {
    categorizing = true;
    showBackfillMenu = false;
    try {
      const result = await api.triggerAutoCategorize(days);
      showToast(result.message, 'success');
      // Start polling for progress
      startProcessingPoll();
    } catch (err) {
      showToast(err.message, 'error');
    }
    categorizing = false;
  }

  async function loadAIStats() {
    try {
      aiStats = await api.getAIStats();
    } catch {
      // Ignore stats loading errors
    }
  }

  async function dropAndRebuild(rebuildDays = null) {
    dropping = true;
    showDropConfirm = false;
    try {
      const result = await api.deleteAIAnalyses(rebuildDays);
      showToast(result.message, 'success');
      // Refresh stats and start polling if rebuilding
      await loadAIStats();
      if (rebuildDays !== null) {
        startProcessingPoll();
      }
      refreshAllData();
    } catch (err) {
      showToast(err.message, 'error');
    }
    dropping = false;
  }

  async function dropOnly() {
    dropping = true;
    showDropConfirm = false;
    try {
      const result = await api.deleteAIAnalyses();
      showToast(result.message, 'success');
      await loadAIStats();
      refreshAllData();
    } catch (err) {
      showToast(err.message, 'error');
    }
    dropping = false;
  }

  async function handleUnsubscribe(emailId) {
    // If we already have a preview for this email, this is the second click -- send it
    if (unsubscribePreview && unsubscribePreview.emailId === emailId) {
      unsubscribingId = emailId;
      try {
        const result = await api.unsubscribe(emailId, false);
        if (result.email_sent) {
          showToast(`Unsubscribe email sent to ${result.sent_to}`, 'success');
        } else if (result.url) {
          window.open(result.url, '_blank');
          showToast('Opened unsubscribe page in new tab', 'success');
        } else {
          showToast('No unsubscribe method available', 'error');
        }
        unsubscribePreview = null;
        // Refresh subscriptions data to show updated tracking badges
        try {
          subscriptionsData = await api.getSubscriptions();
        } catch (_) {
          // ignore refresh error
        }
      } catch (err) {
        showToast(err.message, 'error');
      }
      unsubscribingId = null;
      return;
    }

    // First click -- fetch preview
    unsubscribingId = emailId;
    try {
      const result = await api.unsubscribe(emailId, true);
      if (result.preview) {
        unsubscribePreview = {
          emailId,
          to: result.preview.to,
          subject: result.preview.subject,
          body: result.preview.body,
        };
      } else if (result.url) {
        // URL-only method: open directly, no preview needed
        window.open(result.url, '_blank');
        showToast('Opened unsubscribe page in new tab', 'success');
        // Still record the tracking by calling the non-preview endpoint
        try {
          await api.unsubscribe(emailId, false);
          subscriptionsData = await api.getSubscriptions();
        } catch (_) {
          // ignore
        }
      } else {
        showToast('No unsubscribe method available', 'error');
      }
    } catch (err) {
      showToast(err.message, 'error');
    }
    unsubscribingId = null;
  }

  function cancelUnsubscribePreview() {
    unsubscribePreview = null;
  }

  function formatDate(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    const now = new Date();
    const diff = now - d;
    const dayMs = 86400000;
    if (diff < dayMs) {
      return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    }
    if (diff < 7 * dayMs) {
      return d.toLocaleDateString([], { weekday: 'short' });
    }
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  }

  function goToEmail(emailId) {
    // Set mailbox first (this triggers the Inbox effect that resets selectedEmailId),
    // then set the email ID on the next tick so it sticks.
    currentMailbox.set('ALL');
    currentPage.set('inbox');
    setTimeout(() => {
      selectedEmailId.set(emailId);
    }, 0);
  }

  function goToEmailWithReply(email, replyBody) {
    // Navigate to the email and pre-fill an inline reply composer
    const subject = email.subject && email.subject.startsWith('Re:') ? email.subject : `Re: ${email.subject || ''}`;
    // Use explicit replyBody if provided, otherwise fall back to first reply option or suggested_reply
    let body = replyBody || '';
    if (!body && email.reply_options && email.reply_options.length > 0) {
      body = email.reply_options[0].body || '';
    }
    if (!body) {
      body = email.suggested_reply || '';
    }
    pendingReplyDraft.set({
      emailId: email.id,
      to: email.from_address,
      subject: subject,
      body: body,
      threadId: email.gmail_thread_id || null,
    });
    currentMailbox.set('ALL');
    currentPage.set('inbox');
    setTimeout(() => {
      selectedEmailId.set(email.id);
    }, 0);
  }

  function handleReply(email) {
    // Same as goToEmailWithReply -- open email and prefill reply
    goToEmailWithReply(email);
  }

  const categoryColors = {
    urgent: { bg: 'bg-red-100 dark:bg-red-500/20', text: 'text-red-700 dark:text-red-300' },
    can_ignore: { bg: 'bg-gray-100 dark:bg-gray-700/50', text: 'text-gray-600 dark:text-gray-300' },
    fyi: { bg: 'bg-emerald-100 dark:bg-emerald-500/20', text: 'text-emerald-700 dark:text-emerald-300' },
    awaiting_reply: { bg: 'bg-amber-100 dark:bg-amber-500/20', text: 'text-amber-700 dark:text-amber-300' },
    expired: { bg: 'bg-stone-100 dark:bg-stone-700/50/40', text: 'text-stone-500 dark:text-stone-300' },
  };

  function categoryLabel(cat) {
    if (!cat) return 'Unknown';
    return cat.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  function maxCount(data, key) {
    if (!data || data.length === 0) return 1;
    return Math.max(...data.map(d => d[key]), 1);
  }

  function getUnsubMethod(info) {
    if (!info) return null;
    if (info.method === 'both') return 'email & link';
    if (info.method === 'email') return 'email';
    if (info.method === 'url') return 'link';
    return null;
  }
</script>

<div class="h-full overflow-y-auto" style="background: var(--bg-primary)">
  {#if loading}
    <div class="flex items-center justify-center h-full">
      <div class="w-6 h-6 border-2 rounded-full animate-spin" style="border-color: var(--border-color); border-top-color: var(--color-accent-500)"></div>
    </div>
  {:else}
    <div class="max-w-6xl mx-auto p-6 space-y-6">
      <!-- Header with Analyze & Manage buttons -->
      <div class="flex items-center justify-between">
        <h2 class="text-xl font-bold" style="color: var(--text-primary)">AI Insights</h2>
        <div class="flex items-center gap-2">
          <!-- Drop & Rebuild button -->
          <div class="relative">
            <button
              onclick={() => { showDropConfirm = !showDropConfirm; showBackfillMenu = false; }}
              disabled={dropping || (processingStatus && processingStatus.active)}
              class="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-fast disabled:opacity-50 border"
              style="border-color: var(--border-color); color: var(--text-secondary); background: var(--bg-secondary)"
              title="Drop & Rebuild AI Data"
            >
              {#if dropping}
                <div class="w-4 h-4 border-2 rounded-full animate-spin" style="border-color: var(--border-color); border-top-color: var(--text-secondary)"></div>
              {:else}
                <Icon name="refresh-cw" size={16} />
              {/if}
              Rebuild
            </button>
            {#if showDropConfirm}
              <!-- svelte-ignore a11y_click_events_have_key_events -->
              <!-- svelte-ignore a11y_no_static_element_interactions -->
              <div class="absolute right-0 top-full mt-1 w-72 rounded-lg border shadow-lg z-50 p-4 space-y-3" style="background: var(--bg-secondary); border-color: var(--border-color)" onclick={(e) => e.stopPropagation()}>
                <div class="text-sm font-medium" style="color: var(--text-primary)">Drop & Rebuild AI Data</div>
                {#if aiStats}
                  <div class="text-xs space-y-1" style="color: var(--text-tertiary)">
                    <div>{aiStats.total_analyzed} analyses will be deleted</div>
                    {#if aiStats.models && Object.keys(aiStats.models).length > 0}
                      <div class="flex flex-wrap gap-1">
                        {#each Object.entries(aiStats.models) as [model, count]}
                          <span class="px-1.5 py-0.5 rounded text-[10px]" style="background: var(--bg-tertiary)">{model}: {count}</span>
                        {/each}
                      </div>
                    {/if}
                  </div>
                {/if}
                <div class="text-xs" style="color: var(--text-secondary)">Rebuild range:</div>
                <div class="flex flex-wrap gap-1">
                  {#each [{ label: '30 days', days: 30 }, { label: '90 days', days: 90 }, { label: '1 year', days: 365 }, { label: 'All', days: 0 }] as opt}
                    <button
                      onclick={() => { dropRebuildDays = opt.days; }}
                      class="px-2 py-1 rounded text-xs font-medium transition-fast"
                      style="background: {dropRebuildDays === opt.days ? 'var(--color-accent-500)' : 'var(--bg-tertiary)'}; color: {dropRebuildDays === opt.days ? 'white' : 'var(--text-secondary)'}"
                    >
                      {opt.label}
                      {#if aiStats && aiStats.unanalyzed}
                        {#if opt.days === 0}
                          ({aiStats.total_emails})
                        {:else if opt.days === 30}
                          ({aiStats.unanalyzed['30d'] + (aiStats.total_analyzed || 0) > 0 ? '~' : ''}{aiStats.unanalyzed['30d']})
                        {:else if opt.days === 90}
                          ({aiStats.unanalyzed['90d'] + (aiStats.total_analyzed || 0) > 0 ? '~' : ''}{aiStats.unanalyzed['90d']})
                        {:else if opt.days === 365}
                          ({aiStats.unanalyzed['1y'] + (aiStats.total_analyzed || 0) > 0 ? '~' : ''}{aiStats.unanalyzed['1y']})
                        {/if}
                      {/if}
                    </button>
                  {/each}
                </div>
                <div class="flex gap-2">
                  <button
                    onclick={() => dropAndRebuild(dropRebuildDays === 0 ? 0 : dropRebuildDays)}
                    class="flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-fast"
                    style="background: var(--color-accent-500); color: white"
                  >
                    Drop & Rebuild
                  </button>
                  <button
                    onclick={dropOnly}
                    class="px-3 py-1.5 rounded-md text-xs font-medium transition-fast"
                    style="background: var(--status-error); color: white"
                  >
                    Drop Only
                  </button>
                  <button
                    onclick={() => { showDropConfirm = false; }}
                    class="px-3 py-1.5 rounded-md text-xs font-medium transition-fast"
                    style="background: var(--bg-tertiary); color: var(--text-secondary)"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            {/if}
          </div>

          <!-- Analyze backfill dropdown -->
          <div class="relative">
            <button
              onclick={() => { showBackfillMenu = !showBackfillMenu; showDropConfirm = false; }}
              disabled={categorizing || (processingStatus && processingStatus.active)}
              class="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-fast disabled:opacity-50"
              style="background: var(--color-accent-500); color: white"
            >
              {#if categorizing}
                <div class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
                Analyzing...
              {:else}
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
                </svg>
                Analyze
                <span class="-mr-1"><Icon name="chevron-down" size={12} /></span>
              {/if}
            </button>
            {#if showBackfillMenu}
              <div class="absolute right-0 top-full mt-1 w-56 rounded-lg border shadow-lg z-50 py-1" style="background: var(--bg-secondary); border-color: var(--border-color)">
                {#each [{ label: 'Last 30 days', days: 30, key: '30d' }, { label: 'Last 90 days', days: 90, key: '90d' }, { label: 'Last year', days: 365, key: '1y' }, { label: 'All unanalyzed', days: null, key: 'all' }] as opt}
                  <button
                    onclick={() => triggerAutoCategorize(opt.days)}
                    class="w-full text-left px-4 py-2 text-sm transition-fast flex items-center justify-between"
                    style="color: var(--text-primary)"
                    onmouseenter={(e) => e.target.style.background = 'var(--bg-tertiary)'}
                    onmouseleave={(e) => e.target.style.background = 'transparent'}
                  >
                    <span>{opt.label}</span>
                    {#if aiStats && aiStats.unanalyzed}
                      <span class="text-xs px-1.5 py-0.5 rounded-full" style="background: var(--bg-tertiary); color: var(--text-tertiary)">{aiStats.unanalyzed[opt.key]}</span>
                    {/if}
                  </button>
                {/each}
              </div>
            {/if}
          </div>
        </div>
      </div>

      <!-- Click outside to close menus -->
      {#if showBackfillMenu || showDropConfirm}
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div class="fixed inset-0 z-40" onclick={() => { showBackfillMenu = false; showDropConfirm = false; }}></div>
      {/if}

      <!-- AI Processing Progress Bar -->
      {#if processingStatus && processingStatus.active}
        {@const pct = getProcessingPercent(processingStatus)}
        <div class="rounded-xl border overflow-hidden" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <div class="px-4 py-3 flex items-center gap-3">
            <div class="w-5 h-5 shrink-0">
              <div class="w-5 h-5 rounded-full border-2 border-t-transparent animate-spin" style="border-color: var(--color-accent-500); border-top-color: transparent"></div>
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex items-center justify-between mb-1.5">
                <span class="text-sm font-medium" style="color: var(--text-primary)">{getProcessingLabel(processingStatus)}</span>
                <span class="text-xs font-medium shrink-0 ml-2" style="color: var(--text-tertiary)">{processingStatus.processed} / {processingStatus.total} emails</span>
              </div>
              <div class="h-2 rounded-full overflow-hidden" style="background: var(--bg-tertiary)">
                <div
                  class="h-full rounded-full transition-all duration-500 ease-out"
                  style="width: {pct}%; background: var(--color-accent-500)"
                ></div>
              </div>
              <div class="flex items-center justify-between mt-1">
                <span class="text-[10px]" style="color: var(--text-tertiary)">{pct}% complete</span>
              </div>
            </div>
          </div>
        </div>
      {/if}

      {#if processingJustFinished}
        <div class="rounded-xl border overflow-hidden" style="background: var(--bg-secondary); border-color: var(--status-success)">
          <div class="px-4 py-3 flex items-center gap-3">
            <div class="w-5 h-5 rounded-full flex items-center justify-center shrink-0" style="background: var(--status-success)">
              <span class="text-white"><Icon name="check" size={12} /></span>
            </div>
            <span class="text-sm font-medium" style="color: var(--text-primary)">Processing complete -- insights updated</span>
          </div>
        </div>
      {/if}

      <!-- Tab Navigation -->
      <div class="flex gap-1 border-b" style="border-color: var(--border-color)">
        {#each tabs as tab}
          <button
            onclick={() => switchTab(tab.id)}
            class="px-4 py-2 text-sm font-medium transition-fast border-b-2 -mb-px"
            style="color: {activeTab === tab.id ? 'var(--color-accent-500)' : 'var(--text-secondary)'}; border-color: {activeTab === tab.id ? 'var(--color-accent-500)' : 'transparent'}"
          >
            {tab.label}
            {#if tab.id === 'needs-reply' && needsReplyData}
              <span class="ml-1 text-[10px] px-1.5 py-0.5 rounded-full bg-red-500/20 text-red-500">{needsReplyData.total}</span>
            {/if}
            {#if tab.id === 'subscriptions' && subscriptionsData}
              <span class="ml-1 text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500/20 text-amber-500">{subscriptionsData.total}</span>
            {/if}
            {#if tab.id === 'conversations' && digestsData}
              <span class="ml-1 text-[10px] px-1.5 py-0.5 rounded-full" style="background: var(--bg-tertiary); color: var(--text-tertiary)">{digestsData.total}</span>
            {/if}
            {#if tab.id === 'topics' && bundlesData}
              <span class="ml-1 text-[10px] px-1.5 py-0.5 rounded-full" style="background: var(--bg-tertiary); color: var(--text-tertiary)">{bundlesData.total}</span>
            {/if}
          </button>
        {/each}
      </div>

      {#if tabLoading}
        <div class="flex items-center justify-center py-12">
          <div class="w-6 h-6 border-2 rounded-full animate-spin" style="border-color: var(--border-color); border-top-color: var(--color-accent-500)"></div>
        </div>

      <!-- ==================== OVERVIEW TAB ==================== -->
      {:else if activeTab === 'overview'}
        <!-- Smart Summary Banner -->
        {#if trends}
          {#if trends.summary}
            <div class="rounded-xl border p-4 flex items-start gap-3" style="background: var(--bg-secondary); border-color: var(--border-color)">
              <div class="w-10 h-10 rounded-full flex items-center justify-center shrink-0" style="background: var(--color-accent-500); color: white">
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
                </svg>
              </div>
              <div>
                <p class="text-sm font-medium" style="color: var(--text-primary)">{trends.summary}</p>
                <div class="flex items-center gap-4 mt-1">
                  <span class="text-xs" style="color: var(--text-tertiary)">{trends.total_analyzed} emails analyzed</span>
                  {#if trends.total_unanalyzed > 0}
                    <span class="text-xs" style="color: var(--text-tertiary)">{trends.total_unanalyzed} pending analysis</span>
                  {/if}
                </div>
              </div>
            </div>
          {:else}
            <div class="rounded-xl border p-4" style="background: var(--bg-secondary); border-color: var(--border-color)">
              <p class="text-sm" style="color: var(--text-secondary)">{trends.total_analyzed} emails analyzed. No urgent items right now.</p>
            </div>
          {/if}

          <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <!-- Needs Attention Queue -->
            <div class="rounded-xl border p-5 lg:col-span-2" style="background: var(--bg-secondary); border-color: var(--border-color)">
              <h3 class="text-sm font-semibold mb-4" style="color: var(--text-primary)">Needs Attention</h3>
              {#if trends.needs_attention && trends.needs_attention.length > 0}
                <div class="space-y-2 max-h-[350px] overflow-y-auto">
                  {#each trends.needs_attention as email}
                    <!-- svelte-ignore a11y_click_events_have_key_events -->
                    <!-- svelte-ignore a11y_no_static_element_interactions -->
                    <div
                      class="flex items-start gap-3 p-3 rounded-lg cursor-pointer transition-fast"
                      style="background: var(--bg-primary)"
                      onclick={() => goToEmail(email.id)}
                    >
                      <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 mt-0.5 {categoryColors[email.category]?.bg || ''} {categoryColors[email.category]?.text || ''}">
                        {categoryLabel(email.category)}
                      </span>
                      <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2">
                          <span class="text-sm font-medium truncate" style="color: var(--text-primary)">{email.subject || '(no subject)'}</span>
                          <span class="text-xs shrink-0 ml-auto" style="color: var(--text-tertiary)">{formatDate(email.date)}</span>
                        </div>
                        <div class="text-xs mt-0.5" style="color: var(--text-secondary)">
                          From: {email.from_name || email.from_address}
                        </div>
                        {#if email.summary}
                          <div class="text-xs mt-1 truncate" style="color: var(--text-tertiary)">{email.summary}</div>
                        {/if}
                      </div>
                    </div>
                  {/each}
                </div>
              {:else}
                <div class="flex flex-col items-center justify-center py-8">
                  <div class="text-3xl mb-2 opacity-40">&#10003;</div>
                  <p class="text-sm" style="color: var(--text-tertiary)">All caught up! No urgent items.</p>
                </div>
              {/if}
            </div>

            <!-- Top Topics -->
            <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
              <h3 class="text-sm font-semibold mb-4" style="color: var(--text-primary)">Trending Topics (14d)</h3>
              {#if trends.top_topics && trends.top_topics.length > 0}
                <div class="flex flex-wrap gap-2">
                  {#each trends.top_topics as topic}
                    {@const max = maxCount(trends.top_topics, 'count')}
                    {@const opacity = 0.4 + (topic.count / max) * 0.6}
                    <span
                      class="text-xs px-2.5 py-1 rounded-full font-medium"
                      style="background: var(--color-accent-500); color: white; opacity: {opacity}"
                    >
                      {topic.topic}
                      <span class="text-[10px] opacity-70 ml-1">{topic.count}</span>
                    </span>
                  {/each}
                </div>
              {:else}
                <p class="text-sm" style="color: var(--text-tertiary)">No topics data yet</p>
              {/if}
            </div>

            <!-- Urgent Senders -->
            <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
              <h3 class="text-sm font-semibold mb-4" style="color: var(--text-primary)">Top Action Senders</h3>
              {#if trends.urgent_senders && trends.urgent_senders.length > 0}
                <div class="space-y-2">
                  {#each trends.urgent_senders as sender, i}
                    {@const max = trends.urgent_senders[0].count}
                    {@const width = Math.max((sender.count / max) * 100, 8)}
                    <div class="flex items-center gap-3">
                      <span class="text-xs w-5 text-right font-medium" style="color: var(--text-tertiary)">{i + 1}</span>
                      <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2 mb-0.5">
                          <span class="text-xs truncate font-medium" style="color: var(--text-primary)">{sender.name}</span>
                          <span class="text-[10px] ml-auto shrink-0" style="color: var(--text-tertiary)">{sender.count} action emails</span>
                        </div>
                        <div class="h-1.5 rounded-full overflow-hidden" style="background: var(--bg-tertiary)">
                          <div class="h-full rounded-full" style="width: {width}%; background: var(--status-error); opacity: {1 - i * 0.08}"></div>
                        </div>
                      </div>
                    </div>
                  {/each}
                </div>
              {:else}
                <p class="text-sm" style="color: var(--text-tertiary)">No data yet</p>
              {/if}
            </div>
          </div>
        {/if}

      <!-- ==================== NEEDS REPLY TAB ==================== -->
      {:else if activeTab === 'needs-reply'}
        {#if needsReplyData}
          <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
            <div class="flex items-center justify-between mb-4">
              <h3 class="text-sm font-semibold" style="color: var(--text-primary)">Emails You Should Reply To</h3>
              <span class="text-xs px-2 py-0.5 rounded-full" style="background: var(--bg-tertiary); color: var(--text-tertiary)">{needsReplyData.total} total</span>
            </div>
            {#if needsReplyData.emails && needsReplyData.emails.length > 0}
              <div class="space-y-2">
                {#each needsReplyData.emails as email}
                  <div class="flex items-start gap-3 p-3 rounded-lg transition-fast" style="background: var(--bg-primary)">
                    <div class="flex-1 min-w-0">
                      <!-- svelte-ignore a11y_click_events_have_key_events -->
                      <!-- svelte-ignore a11y_no_static_element_interactions -->
                      <div class="cursor-pointer" onclick={() => goToEmailWithReply(email)}>
                        <div class="flex items-center gap-2">
                          <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 {categoryColors[email.category]?.bg || ''} {categoryColors[email.category]?.text || ''}">
                            {categoryLabel(email.category)}
                          </span>
                          {#if !email.is_read}
                            <span class="w-2 h-2 rounded-full shrink-0" style="background: var(--color-accent-500)"></span>
                          {/if}
                          <span class="text-sm font-medium truncate" style="color: var(--text-primary)">{email.subject || '(no subject)'}</span>
                          <span class="text-xs shrink-0 ml-auto" style="color: var(--text-tertiary)">{formatDate(email.date)}</span>
                        </div>
                        <div class="text-xs mt-0.5" style="color: var(--text-secondary)">
                          From: {email.from_name || email.from_address}
                        </div>
                        {#if email.summary}
                          <div class="text-xs mt-1" style="color: var(--text-tertiary)">{email.summary}</div>
                        {/if}
                      </div>
                      {#if email.reply_options?.length > 0}
                        <div class="mt-2 flex flex-wrap gap-1.5">
                          {#each email.reply_options as option}
                            <button
                              onclick={() => goToEmailWithReply(email, option.body)}
                              class="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium border transition-fast cursor-pointer
                                {option.intent === 'accept' ? 'bg-emerald-50 dark:bg-emerald-500/15 border-emerald-200 dark:border-emerald-500/30 text-emerald-700 dark:text-emerald-300' :
                                 option.intent === 'decline' ? 'bg-red-50 dark:bg-red-500/15 border-red-200 dark:border-red-500/30 text-red-700 dark:text-red-300' :
                                 option.intent === 'defer' ? 'bg-amber-50 dark:bg-amber-500/15 border-amber-200 dark:border-amber-500/30 text-amber-700 dark:text-amber-300' :
                                 option.intent === 'not_relevant' ? 'bg-gray-50 dark:bg-gray-700/50 border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-300' :
                                 'bg-blue-50 dark:bg-blue-500/15 border-blue-200 dark:border-blue-500/30 text-blue-700 dark:text-blue-300'}"
                              title={option.body}
                            >
                              {option.label}
                            </button>
                          {/each}
                        </div>
                      {:else if email.suggested_reply}
                        <div class="mt-2 p-2 rounded-md text-xs" style="background: var(--bg-tertiary); color: var(--text-secondary)">
                          <span class="font-semibold" style="color: var(--color-accent-600)">Suggested:</span> {email.suggested_reply}
                        </div>
                      {/if}
                    </div>
                    <div class="flex flex-col gap-1 shrink-0">
                      <button
                        onclick={() => handleReply(email)}
                        class="flex items-center gap-1 px-3 py-1.5 rounded-md text-xs font-medium transition-fast"
                        style="background: var(--color-accent-500); color: white"
                      >
                        <Icon name="corner-up-left" size={14} />
                        Reply
                      </button>
                    </div>
                  </div>
                {/each}
              </div>
            {:else}
              <div class="flex flex-col items-center justify-center py-8">
                <div class="text-3xl mb-2 opacity-40">&#10003;</div>
                <p class="text-sm" style="color: var(--text-tertiary)">No emails need a reply right now.</p>
              </div>
            {/if}
          </div>
        {/if}

      <!-- ==================== SUBSCRIPTIONS TAB ==================== -->
      {:else if activeTab === 'subscriptions'}
        {#if subscriptionsData}
          <!-- Sender summary cards -->
          {#if subscriptionsData.senders && subscriptionsData.senders.length > 0}
            <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
              <div class="flex items-center justify-between mb-4">
                <h3 class="text-sm font-semibold" style="color: var(--text-primary)">Subscription Senders</h3>
                <span class="text-xs px-2 py-0.5 rounded-full" style="background: var(--bg-tertiary); color: var(--text-tertiary)">{subscriptionsData.senders.length} sources</span>
              </div>
              <div class="space-y-2">
                {#each subscriptionsData.senders as sender}
                  <div class="rounded-lg" style="background: var(--bg-primary)">
                    <div class="flex items-center gap-3 p-3">
                      <div class="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0" style="background: var(--bg-tertiary); color: var(--color-accent-600)">
                        {sender.domain[0].toUpperCase()}
                      </div>
                      <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2">
                          <span class="text-sm font-medium truncate" style="color: var(--text-primary)">{sender.from_name}</span>
                          <span class="text-[10px] px-1.5 py-0.5 rounded-full shrink-0" style="background: var(--bg-tertiary); color: var(--text-tertiary)">{sender.count} emails</span>
                          {#if sender.unsubscribed_at}
                            <span class="text-[10px] px-1.5 py-0.5 rounded-full shrink-0" style="background: color-mix(in srgb, var(--status-success) 12%, transparent); color: var(--status-success)">Unsubscribed</span>
                          {/if}
                        </div>
                        <div class="text-xs mt-0.5" style="color: var(--text-tertiary)">{sender.domain}</div>
                        {#if sender.unsubscribed_at && !sender.honors_unsubscribe}
                          <div class="flex items-center gap-1 mt-1">
                            <span class="shrink-0" style="color: var(--status-warning)"><Icon name="alert-triangle" size={12} /></span>
                            <span class="text-[10px]" style="color: var(--status-warning)">Still sending emails after unsubscribe ({sender.emails_received_after} received)</span>
                          </div>
                        {/if}
                      </div>
                      {#if sender.unsubscribe_info}
                        <button
                          onclick={() => handleUnsubscribe(sender.sample_email_id)}
                          disabled={unsubscribingId === sender.sample_email_id}
                          class="flex items-center gap-1 px-3 py-1.5 rounded-md text-xs font-medium transition-fast shrink-0 disabled:opacity-50"
                          style="background: var(--status-error); color: white"
                        >
                          {#if unsubscribingId === sender.sample_email_id}
                            <div class="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
                          {:else}
                            {#if unsubscribePreview && unsubscribePreview.emailId === sender.sample_email_id}
                              <Icon name="send" size={14} />
                            {:else}
                              <Icon name="slash" size={14} />
                            {/if}
                          {/if}
                          {#if unsubscribePreview && unsubscribePreview.emailId === sender.sample_email_id}
                            Send
                          {:else}
                            Unsubscribe
                          {/if}
                        </button>
                      {/if}
                    </div>
                    {#if unsubscribePreview && unsubscribePreview.emailId === sender.sample_email_id}
                      <div class="mx-3 mb-3 p-2.5 rounded-md border text-xs space-y-1" style="background: var(--bg-secondary); border-color: var(--border-color)">
                        <div class="flex items-center justify-between">
                          <span class="font-semibold text-[10px] uppercase tracking-wide" style="color: var(--text-tertiary)">Unsubscribe Email Preview</span>
                          <button onclick={cancelUnsubscribePreview} class="text-[10px] px-1.5 py-0.5 rounded" style="color: var(--text-tertiary)">Cancel</button>
                        </div>
                        <div style="color: var(--text-secondary)"><span class="font-medium" style="color: var(--text-primary)">To:</span> {unsubscribePreview.to}</div>
                        <div style="color: var(--text-secondary)"><span class="font-medium" style="color: var(--text-primary)">Subject:</span> {unsubscribePreview.subject}</div>
                        <div style="color: var(--text-secondary)"><span class="font-medium" style="color: var(--text-primary)">Body:</span> {unsubscribePreview.body}</div>
                      </div>
                    {/if}
                  </div>
                {/each}
              </div>
            </div>
          {/if}

          <!-- Individual subscription emails -->
          <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
            <div class="flex items-center justify-between mb-4">
              <h3 class="text-sm font-semibold" style="color: var(--text-primary)">Recent Subscription Emails</h3>
              <span class="text-xs px-2 py-0.5 rounded-full" style="background: var(--bg-tertiary); color: var(--text-tertiary)">{subscriptionsData.total} total</span>
            </div>
            {#if subscriptionsData.emails && subscriptionsData.emails.length > 0}
              <div class="space-y-2 max-h-[500px] overflow-y-auto">
                {#each subscriptionsData.emails as email}
                  <div class="rounded-lg" style="background: var(--bg-primary)">
                    <div class="flex items-start gap-3 p-3">
                      <!-- svelte-ignore a11y_click_events_have_key_events -->
                      <!-- svelte-ignore a11y_no_static_element_interactions -->
                      <div class="flex-1 min-w-0 cursor-pointer" onclick={() => goToEmail(email.id)}>
                        <div class="flex items-center gap-2">
                          <span class="text-sm font-medium truncate" style="color: var(--text-primary)">{email.subject || '(no subject)'}</span>
                          {#if email.unsubscribed_at}
                            <span class="text-[10px] px-1.5 py-0.5 rounded-full shrink-0" style="background: color-mix(in srgb, var(--status-success) 12%, transparent); color: var(--status-success)">Unsubscribed</span>
                          {/if}
                          <span class="text-xs shrink-0 ml-auto" style="color: var(--text-tertiary)">{formatDate(email.date)}</span>
                        </div>
                        <div class="text-xs mt-0.5" style="color: var(--text-secondary)">
                          From: {email.from_name || email.from_address}
                        </div>
                        {#if email.summary}
                          <div class="text-xs mt-1 truncate" style="color: var(--text-tertiary)">{email.summary}</div>
                        {/if}
                        {#if email.unsubscribe_info}
                          <div class="text-[10px] mt-1 px-1.5 py-0.5 rounded inline-block" style="background: var(--bg-tertiary); color: var(--text-tertiary)">
                            Unsubscribe via {getUnsubMethod(email.unsubscribe_info)}
                          </div>
                        {/if}
                      </div>
                      {#if email.unsubscribe_info}
                        <button
                          onclick={() => handleUnsubscribe(email.id)}
                          disabled={unsubscribingId === email.id}
                          class="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-medium transition-fast shrink-0 disabled:opacity-50"
                          style="background: var(--status-error); color: white"
                          title="{unsubscribePreview && unsubscribePreview.emailId === email.id ? 'Send unsubscribe email' : 'Unsubscribe'}"
                        >
                          {#if unsubscribingId === email.id}
                            <div class="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
                          {:else}
                            {#if unsubscribePreview && unsubscribePreview.emailId === email.id}
                              <Icon name="send" size={12} />
                            {:else}
                              <Icon name="slash" size={12} />
                            {/if}
                          {/if}
                          {#if unsubscribePreview && unsubscribePreview.emailId === email.id}
                            <span>Send</span>
                          {/if}
                        </button>
                      {/if}
                    </div>
                    {#if unsubscribePreview && unsubscribePreview.emailId === email.id}
                      <div class="mx-3 mb-3 p-2.5 rounded-md border text-xs space-y-1" style="background: var(--bg-secondary); border-color: var(--border-color)">
                        <div class="flex items-center justify-between">
                          <span class="font-semibold text-[10px] uppercase tracking-wide" style="color: var(--text-tertiary)">Unsubscribe Email Preview</span>
                          <button onclick={cancelUnsubscribePreview} class="text-[10px] px-1.5 py-0.5 rounded" style="color: var(--text-tertiary)">Cancel</button>
                        </div>
                        <div style="color: var(--text-secondary)"><span class="font-medium" style="color: var(--text-primary)">To:</span> {unsubscribePreview.to}</div>
                        <div style="color: var(--text-secondary)"><span class="font-medium" style="color: var(--text-primary)">Subject:</span> {unsubscribePreview.subject}</div>
                        <div style="color: var(--text-secondary)"><span class="font-medium" style="color: var(--text-primary)">Body:</span> {unsubscribePreview.body}</div>
                      </div>
                    {/if}
                  </div>
                {/each}
              </div>
            {:else}
              <div class="flex flex-col items-center justify-center py-8">
                <p class="text-sm" style="color: var(--text-tertiary)">No subscription emails detected yet. Run auto-categorize to scan your inbox.</p>
              </div>
            {/if}
          </div>
        {/if}

      <!-- ==================== CONVERSATIONS TAB ==================== -->
      {:else if activeTab === 'conversations'}
        {#if digestsData}
          <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
            <div class="flex items-center justify-between mb-4">
              <h3 class="text-sm font-semibold" style="color: var(--text-primary)">Conversations</h3>
              <span class="text-xs px-2 py-0.5 rounded-full" style="background: var(--bg-tertiary); color: var(--text-tertiary)">{digestsData.total} threads</span>
            </div>

            <!-- Conversation type filter chips -->
            <div class="flex flex-wrap gap-1.5 mb-4">
              {#each Object.entries(conversationTypeConfig) as [type, config]}
                <button
                  onclick={() => filterDigests(type)}
                  class="text-[11px] px-2.5 py-1 rounded-full font-medium transition-fast {config.bg} {config.text}"
                  style="opacity: {digestFilter === null || digestFilter === type ? '1' : '0.4'}"
                >
                  {config.label}
                </button>
              {/each}
              {#if digestFilter}
                <button
                  onclick={() => filterDigests(digestFilter)}
                  class="text-[11px] px-2.5 py-1 rounded-full font-medium transition-fast"
                  style="background: var(--bg-tertiary); color: var(--text-tertiary)"
                >
                  Clear filter
                </button>
              {/if}
            </div>

            {#if digestsData.digests && digestsData.digests.length > 0}
              <div class="space-y-2">
                {#each digestsData.digests as digest}
                  {@const typeConfig = getConversationTypeConfig(digest.conversation_type)}
                  <!-- svelte-ignore a11y_click_events_have_key_events -->
                  <!-- svelte-ignore a11y_no_static_element_interactions -->
                  <div
                    class="p-3 rounded-lg cursor-pointer transition-fast"
                    style="background: var(--bg-primary)"
                    onclick={() => { selectedEmailId.set(null); currentMailbox.set('ALL'); currentPage.set('inbox'); }}
                  >
                    <div class="flex items-start gap-3">
                      <!-- Conversation type icon -->
                      <div class="flex items-center justify-center w-8 h-8 rounded-full shrink-0 {typeConfig.bg}">
                        {#if digest.conversation_type === 'scheduling'}
                          <Icon name="calendar" size={16} class={typeConfig.text} />
                        {:else if digest.conversation_type === 'discussion'}
                          <Icon name="message-circle" size={16} class={typeConfig.text} />
                        {:else if digest.conversation_type === 'notification'}
                          <Icon name="bell" size={16} class={typeConfig.text} />
                        {:else}
                          <Icon name="mail" size={16} class={typeConfig.text} />
                        {/if}
                      </div>

                      <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2">
                          <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 {typeConfig.bg} {typeConfig.text}">
                            {typeConfig.label}
                          </span>
                          {#if digest.is_resolved}
                            <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-300">Resolved</span>
                          {/if}
                          <span class="text-xs shrink-0 ml-auto" style="color: var(--text-tertiary)">{formatDate(digest.latest_date)}</span>
                        </div>

                        <!-- Subject line -->
                        <div class="text-sm font-medium mt-1 truncate" style="color: var(--text-primary)">
                          {digest.subject || '(no subject)'}
                        </div>

                        <!-- For scheduling: show resolved outcome prominently -->
                        {#if digest.conversation_type === 'scheduling' && digest.resolved_outcome}
                          <div class="mt-1.5 p-2 rounded-md text-xs font-medium" style="background: var(--color-accent-500); background: rgba(168, 85, 247, 0.1); color: var(--text-primary)">
                            <span style="color: rgb(168, 85, 247)">Outcome:</span> {digest.resolved_outcome}
                          </div>
                        {:else if digest.summary}
                          <div class="text-xs mt-1" style="color: var(--text-tertiary)">{digest.summary}</div>
                        {/if}

                        <!-- Participants and metadata -->
                        <div class="flex items-center gap-2 mt-1.5 flex-wrap">
                          <span class="text-[10px]" style="color: var(--text-tertiary)">{digest.message_count} messages</span>
                          <span class="text-[10px]" style="color: var(--text-tertiary)">&#183;</span>
                          {#each (digest.participants || []) as p, i}
                            {#if i < 3}
                              <span class="text-[10px]" style="color: var(--text-secondary)">{p.name || p.address}</span>
                              {#if i < (digest.participants || []).length - 1 && i < 2}
                                <span class="text-[10px]" style="color: var(--text-tertiary)">&#183;</span>
                              {/if}
                            {/if}
                          {/each}
                          {#if (digest.participants || []).length > 3}
                            <span class="text-[10px]" style="color: var(--text-tertiary)">+{(digest.participants || []).length - 3} more</span>
                          {/if}
                        </div>

                        <!-- Topic tags -->
                        {#if digest.key_topics && digest.key_topics.length > 0}
                          <div class="flex flex-wrap gap-1 mt-1.5">
                            {#each digest.key_topics.slice(0, 4) as topic}
                              <span class="text-[10px] px-1.5 py-0.5 rounded" style="background: var(--bg-tertiary); color: var(--text-tertiary)">{topic}</span>
                            {/each}
                            {#if digest.key_topics.length > 4}
                              <span class="text-[10px] px-1.5 py-0.5 rounded" style="background: var(--bg-tertiary); color: var(--text-tertiary)">+{digest.key_topics.length - 4}</span>
                            {/if}
                          </div>
                        {/if}
                      </div>
                    </div>
                  </div>
                {/each}
              </div>
            {:else}
              <div class="flex flex-col items-center justify-center py-8">
                <p class="text-sm" style="color: var(--text-tertiary)">
                  {#if digestFilter}
                    No {conversationTypeConfig[digestFilter]?.label || digestFilter} conversations found.
                  {:else}
                    No conversation digests yet. Run analysis to generate thread summaries.
                  {/if}
                </p>
              </div>
            {/if}
          </div>
        {/if}

      <!-- ==================== TOPICS TAB ==================== -->
      {:else if activeTab === 'topics'}
        {#if bundlesData}
          <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
            <div class="flex items-center justify-between mb-4">
              <div>
                <h3 class="text-sm font-semibold" style="color: var(--text-primary)">Topic Bundles</h3>
                <p class="text-xs mt-0.5" style="color: var(--text-tertiary)">Emails grouped by shared topics across threads and accounts</p>
              </div>
              <span class="text-xs px-2 py-0.5 rounded-full" style="background: var(--bg-tertiary); color: var(--text-tertiary)">{bundlesData.total} bundles</span>
            </div>
            {#if bundlesData.bundles && bundlesData.bundles.length > 0}
              <div class="space-y-3">
                {#each bundlesData.bundles as bundle}
                  <div class="p-4 rounded-lg" style="background: var(--bg-primary)">
                    <div class="flex items-start gap-3">
                      <!-- Bundle icon -->
                      <div class="flex items-center justify-center w-10 h-10 rounded-lg shrink-0" style="background: var(--color-accent-500); opacity: 0.15">
                        <span style="color: var(--color-accent-500); opacity: 1"><Icon name="folder" size={20} /></span>
                      </div>

                      <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2">
                          <span class="text-sm font-semibold" style="color: var(--text-primary)">{bundle.title}</span>
                          <span class="text-xs shrink-0 ml-auto" style="color: var(--text-tertiary)">{formatDate(bundle.latest_date)}</span>
                        </div>

                        {#if bundle.summary}
                          <div class="text-xs mt-1" style="color: var(--text-secondary)">{bundle.summary}</div>
                        {/if}

                        <!-- Stats row -->
                        <div class="flex items-center gap-3 mt-2">
                          <span class="text-[10px] flex items-center gap-1" style="color: var(--text-tertiary)">
                            <Icon name="mail" size={12} />
                            {bundle.email_count} emails
                          </span>
                          <span class="text-[10px] flex items-center gap-1" style="color: var(--text-tertiary)">
                            <Icon name="message-circle" size={12} />
                            {bundle.thread_count} threads
                          </span>
                          {#if bundle.account_ids && bundle.account_ids.length > 1}
                            <span class="text-[10px] flex items-center gap-1" style="color: var(--text-tertiary)">
                              <Icon name="users" size={12} />
                              {bundle.account_ids.length} accounts
                            </span>
                          {/if}
                        </div>

                        <!-- Topic tags -->
                        {#if bundle.key_topics && bundle.key_topics.length > 0}
                          <div class="flex flex-wrap gap-1 mt-2">
                            {#each bundle.key_topics.slice(0, 6) as topic}
                              <span class="text-[10px] px-2 py-0.5 rounded-full font-medium" style="background: var(--color-accent-500); color: white; opacity: 0.8">{topic}</span>
                            {/each}
                            {#if bundle.key_topics.length > 6}
                              <span class="text-[10px] px-2 py-0.5 rounded-full" style="background: var(--bg-tertiary); color: var(--text-tertiary)">+{bundle.key_topics.length - 6} more</span>
                            {/if}
                          </div>
                        {/if}
                      </div>
                    </div>
                  </div>
                {/each}
              </div>
            {:else}
              <div class="flex flex-col items-center justify-center py-8">
                <p class="text-sm" style="color: var(--text-tertiary)">No topic bundles yet. Bundles are generated automatically after email analysis.</p>
              </div>
            {/if}
          </div>
        {/if}
      {/if}
    </div>
  {/if}
</div>
