<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { showToast, selectedEmailId, currentPage, currentMailbox, composeData, pendingReplyDraft } from '../lib/stores.js';

  let activeTab = $state('overview');
  let trends = $state(null);
  let needsReplyData = $state(null);
  let subscriptionsData = $state(null);
  let threadsData = $state(null);
  let loading = $state(true);
  let tabLoading = $state(false);
  let categorizing = $state(false);
  let unsubscribingId = $state(null);

  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'needs-reply', label: 'Needs Reply' },
    { id: 'subscriptions', label: 'Subscriptions' },
    { id: 'threads', label: 'Threads' },
  ];

  onMount(async () => {
    // Fetch all data in parallel so tab counts show immediately
    const results = await Promise.allSettled([
      api.getAITrends(),
      api.getNeedsReply(),
      api.getSubscriptions(),
      api.getThreadSummaries(),
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

    loading = false;
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
    } else if (tabId === 'threads' && !threadsData) {
      tabLoading = true;
      try {
        threadsData = await api.getThreadSummaries();
      } catch (err) {
        showToast(err.message, 'error');
      }
      tabLoading = false;
    }
  }

  async function triggerAutoCategorize() {
    categorizing = true;
    try {
      const result = await api.triggerAutoCategorize();
      showToast(result.message, 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
    categorizing = false;
  }

  async function handleUnsubscribe(emailId) {
    unsubscribingId = emailId;
    try {
      const result = await api.unsubscribe(emailId);
      if (result.email_sent) {
        showToast(`Unsubscribe email sent to ${result.sent_to}`, 'success');
      } else if (result.url) {
        window.open(result.url, '_blank');
        showToast('Opened unsubscribe page in new tab', 'success');
      } else {
        showToast('No unsubscribe method available', 'error');
      }
    } catch (err) {
      showToast(err.message, 'error');
    }
    unsubscribingId = null;
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

  function goToEmailWithReply(email) {
    // Navigate to the email and pre-fill an inline reply composer
    const subject = email.subject && email.subject.startsWith('Re:') ? email.subject : `Re: ${email.subject || ''}`;
    pendingReplyDraft.set({
      emailId: email.id,
      to: email.from_address,
      subject: subject,
      body: email.suggested_reply || '',
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
    needs_response: { bg: 'bg-blue-100 dark:bg-blue-900/40', text: 'text-blue-700 dark:text-blue-400' },
    urgent: { bg: 'bg-red-100 dark:bg-red-900/40', text: 'text-red-700 dark:text-red-400' },
    can_ignore: { bg: 'bg-gray-100 dark:bg-gray-800', text: 'text-gray-600 dark:text-gray-400' },
    fyi: { bg: 'bg-emerald-100 dark:bg-emerald-900/40', text: 'text-emerald-700 dark:text-emerald-400' },
    awaiting_reply: { bg: 'bg-amber-100 dark:bg-amber-900/40', text: 'text-amber-700 dark:text-amber-400' },
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
      <!-- Header with Auto-Categorize button -->
      <div class="flex items-center justify-between">
        <h2 class="text-xl font-bold" style="color: var(--text-primary)">AI Insights</h2>
        <button
          onclick={triggerAutoCategorize}
          disabled={categorizing}
          class="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-fast disabled:opacity-50"
          style="background: var(--color-accent-500); color: white"
        >
          {#if categorizing}
            <div class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
            Categorizing...
          {:else}
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
            </svg>
            Auto-Categorize (1000)
          {/if}
        </button>
      </div>

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
            {#if tab.id === 'threads' && threadsData}
              <span class="ml-1 text-[10px] px-1.5 py-0.5 rounded-full" style="background: var(--bg-tertiary); color: var(--text-tertiary)">{threadsData.total}</span>
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
                          <div class="h-full rounded-full" style="width: {width}%; background: #ef4444; opacity: {1 - i * 0.08}"></div>
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
                      {#if email.suggested_reply}
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
                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 15L3 9m0 0l6-6M3 9h12a6 6 0 010 12h-3" />
                        </svg>
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
                  <div class="flex items-center gap-3 p-3 rounded-lg" style="background: var(--bg-primary)">
                    <div class="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0" style="background: var(--bg-tertiary); color: var(--color-accent-600)">
                      {sender.domain[0].toUpperCase()}
                    </div>
                    <div class="flex-1 min-w-0">
                      <div class="flex items-center gap-2">
                        <span class="text-sm font-medium truncate" style="color: var(--text-primary)">{sender.from_name}</span>
                        <span class="text-[10px] px-1.5 py-0.5 rounded-full shrink-0" style="background: var(--bg-tertiary); color: var(--text-tertiary)">{sender.count} emails</span>
                      </div>
                      <div class="text-xs mt-0.5" style="color: var(--text-tertiary)">{sender.domain}</div>
                    </div>
                    {#if sender.unsubscribe_info}
                      <button
                        onclick={() => handleUnsubscribe(sender.sample_email_id)}
                        disabled={unsubscribingId === sender.sample_email_id}
                        class="flex items-center gap-1 px-3 py-1.5 rounded-md text-xs font-medium transition-fast shrink-0 disabled:opacity-50"
                        style="background: #ef4444; color: white"
                      >
                        {#if unsubscribingId === sender.sample_email_id}
                          <div class="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
                        {:else}
                          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
                          </svg>
                        {/if}
                        Unsubscribe
                      </button>
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
                  <div class="flex items-start gap-3 p-3 rounded-lg" style="background: var(--bg-primary)">
                    <!-- svelte-ignore a11y_click_events_have_key_events -->
                    <!-- svelte-ignore a11y_no_static_element_interactions -->
                    <div class="flex-1 min-w-0 cursor-pointer" onclick={() => goToEmail(email.id)}>
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
                        style="background: #ef4444; color: white"
                        title="Unsubscribe"
                      >
                        {#if unsubscribingId === email.id}
                          <div class="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
                        {:else}
                          <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        {/if}
                      </button>
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

      <!-- ==================== THREADS TAB ==================== -->
      {:else if activeTab === 'threads'}
        {#if threadsData}
          <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
            <div class="flex items-center justify-between mb-4">
              <h3 class="text-sm font-semibold" style="color: var(--text-primary)">Active Threads</h3>
              <span class="text-xs px-2 py-0.5 rounded-full" style="background: var(--bg-tertiary); color: var(--text-tertiary)">{threadsData.total} threads</span>
            </div>
            {#if threadsData.threads && threadsData.threads.length > 0}
              <div class="space-y-2">
                {#each threadsData.threads as thread}
                  <!-- svelte-ignore a11y_click_events_have_key_events -->
                  <!-- svelte-ignore a11y_no_static_element_interactions -->
                  <div
                    class="flex items-start gap-3 p-3 rounded-lg cursor-pointer transition-fast"
                    style="background: var(--bg-primary)"
                    onclick={() => { selectedEmailId.set(null); currentMailbox.set('ALL'); currentPage.set('inbox'); }}
                  >
                    <div class="flex items-center justify-center w-8 h-8 rounded-full shrink-0 text-xs font-bold" style="background: var(--bg-tertiary); color: var(--color-accent-600)">
                      {thread.message_count}
                    </div>
                    <div class="flex-1 min-w-0">
                      <div class="flex items-center gap-2">
                        <span class="text-sm font-medium truncate" style="color: var(--text-primary)">{thread.subject || '(no subject)'}</span>
                        {#if thread.has_unread}
                          <span class="w-2 h-2 rounded-full shrink-0" style="background: var(--color-accent-500)"></span>
                        {/if}
                        {#if thread.needs_reply}
                          <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-400">Needs Reply</span>
                        {/if}
                        <span class="text-xs shrink-0 ml-auto" style="color: var(--text-tertiary)">{formatDate(thread.latest_date)}</span>
                      </div>
                      <div class="flex items-center gap-2 mt-1 flex-wrap">
                        {#each thread.participants as p, i}
                          {#if i < 4}
                            <span class="text-xs" style="color: var(--text-secondary)">{p.name || p.address}</span>
                            {#if i < thread.participants.length - 1 && i < 3}
                              <span class="text-[10px]" style="color: var(--text-tertiary)">&#183;</span>
                            {/if}
                          {/if}
                        {/each}
                        {#if thread.participants.length > 4}
                          <span class="text-[10px]" style="color: var(--text-tertiary)">+{thread.participants.length - 4} more</span>
                        {/if}
                      </div>
                      <div class="text-[10px] mt-1" style="color: var(--text-tertiary)">
                        {thread.message_count} messages
                      </div>
                    </div>
                  </div>
                {/each}
              </div>
            {:else}
              <div class="flex flex-col items-center justify-center py-8">
                <p class="text-sm" style="color: var(--text-tertiary)">No multi-message threads found.</p>
              </div>
            {/if}
          </div>
        {/if}
      {/if}
    </div>
  {/if}
</div>
