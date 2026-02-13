<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { user, showToast, syncStatus, forceSyncPoll } from '../lib/stores.js';
  import Button from '../components/common/Button.svelte';
  import Input from '../components/common/Input.svelte';

  let activeTab = $state('about-me');
  let dashboard = $state(null);
  let settings = $state([]);
  let loading = $state(true);
  let isAdmin = $derived($user?.is_admin || false);

  // Use the live syncStatus store for real-time updates
  let adminAccounts = $derived($syncStatus.length > 0 ? $syncStatus : []);

  // New setting form
  let newKey = $state('');
  let newValue = $state('');
  let newIsSecret = $state(false);
  let newDescription = $state('');

  let allTabs = [
    { id: 'about-me', label: 'About Me', adminOnly: false },
    { id: 'accounts', label: 'My Accounts', adminOnly: false },
    { id: 'ai-models', label: 'AI Models', adminOnly: false },
    { id: 'dashboard', label: 'Dashboard', adminOnly: true },
    { id: 'apikeys', label: 'API Keys', adminOnly: true },
    { id: 'settings', label: 'Settings', adminOnly: true },
  ];

  let tabs = $derived(allTabs.filter(t => !t.adminOnly || isAdmin));

  onMount(async () => {
    await loadData();
    // Check URL params for tab
    const params = new URLSearchParams(window.location.search);
    if (params.get('tab')) {
      activeTab = params.get('tab');
    }
    if (params.get('error') === 'not_allowed') {
      showToast('That Google account is not on the allowed list', 'error', 5000);
      window.history.replaceState({}, '', '/?page=admin');
    }
    if (params.get('error') === 'account_taken') {
      showToast('That Google account is already connected to another user', 'error', 5000);
      window.history.replaceState({}, '', '/?page=admin');
    }
  });

  async function loadData() {
    loading = true;
    try {
      // Trigger a fresh poll so syncStatus store is up to date
      forceSyncPoll();

      // Load admin-only data if admin
      let dash = null;
      let sets = [];
      let allowed = { allowed_accounts: '' };
      if ($user?.is_admin) {
        const results = await Promise.all([
          api.getDashboard(),
          api.getSettings(),
          api.get('/accounts/allowed'),
        ]);
        dash = results[0];
        sets = results[1];
        allowed = results[2];
      }
      dashboard = dash;
      settings = sets;
      allowedAccounts = allowed.allowed_accounts || '';
      allowedLoaded = true;

      // Always load AI preferences and About Me (available to all users)
      await Promise.all([loadAIPreferences(), loadAboutMe()]);
    } catch (err) {
      showToast(err.message, 'error');
    }
    loading = false;
  }

  async function saveAllowedAccounts() {
    try {
      await api.put('/accounts/allowed', { allowed_accounts: allowedAccounts });
      showToast('Allowed accounts saved', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function saveSetting() {
    if (!newKey) return;
    try {
      await api.updateSetting({
        key: newKey,
        value: newValue,
        is_secret: newIsSecret,
        description: newDescription,
      });
      showToast('Setting saved', 'success');
      newKey = '';
      newValue = '';
      newIsSecret = false;
      newDescription = '';
      settings = await api.getSettings();
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function deleteSetting(key) {
    try {
      await api.deleteSetting(key);
      showToast('Setting deleted', 'success');
      settings = await api.getSettings();
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function saveApiKey(key, value, description) {
    try {
      await api.updateSetting({
        key: key,
        value: value,
        is_secret: true,
        description: description,
      });
      showToast(`${key} saved`, 'success');
      settings = await api.getSettings();
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function connectGoogle() {
    try {
      const result = await api.startOAuth();
      window.location.href = result.auth_url;
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function removeAccount(id) {
    try {
      await api.delete(`/accounts/${id}`);
      showToast('Account removed', 'success');
      setTimeout(forceSyncPoll, 500);
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function triggerSync(accountId) {
    try {
      await api.triggerSync(accountId);
      showToast('Sync started', 'success');
      // Force immediate poll to pick up the syncing state, then adaptive polling kicks in
      setTimeout(forceSyncPoll, 500);
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  // API key form values
  let claudeKey = $state('');
  let googleClientId = $state('');
  let googleClientSecret = $state('');

  // Allowed accounts
  let allowedAccounts = $state('');
  let allowedLoaded = $state(false);

  // AI model preferences
  let aiPrefs = $state({
    chat_plan_model: 'claude-opus-4-6',
    chat_execute_model: 'claude-opus-4-6',
    chat_verify_model: 'claude-opus-4-6',
    agentic_model: 'claude-sonnet-4-5-20250929',
  });
  let aiPrefsAllowedModels = $state([]);
  let aiPrefsLoaded = $state(false);
  let aiPrefsSaving = $state(false);
  let reprocessing = $state(false);

  // About Me
  let aboutMeText = $state('');
  let aboutMeLoaded = $state(false);
  let aboutMeSaving = $state(false);

  // Account descriptions (keyed by account id)
  let accountDescriptions = $state({});
  let accountDescSaving = $state({});
  let accountDescInitialized = $state(new Set());

  // Sync account descriptions from server data when accounts load
  $effect(() => {
    for (const acct of adminAccounts) {
      if (!accountDescInitialized.has(acct.id)) {
        accountDescriptions[acct.id] = acct.description || '';
        accountDescInitialized.add(acct.id);
      }
    }
  });

  const modelLabels = {
    'claude-opus-4-6': 'Claude Opus 4.6 — Most capable',
    'claude-sonnet-4-5-20250929': 'Claude Sonnet 4.5 — Balanced',
    'claude-haiku-4-5-20251001': 'Claude Haiku 4.5 — Fastest',
  };

  async function loadAIPreferences() {
    try {
      const data = await api.getAIPreferences();
      aiPrefs = {
        chat_plan_model: data.chat_plan_model,
        chat_execute_model: data.chat_execute_model,
        chat_verify_model: data.chat_verify_model,
        agentic_model: data.agentic_model,
      };
      aiPrefsAllowedModels = data.allowed_models || [];
      aiPrefsLoaded = true;
    } catch (err) {
      showToast('Failed to load AI preferences', 'error');
    }
  }

  async function saveAIPreferences() {
    aiPrefsSaving = true;
    try {
      const data = await api.updateAIPreferences(aiPrefs);
      aiPrefs = {
        chat_plan_model: data.chat_plan_model,
        chat_execute_model: data.chat_execute_model,
        chat_verify_model: data.chat_verify_model,
        agentic_model: data.agentic_model,
      };
      showToast('AI model preferences saved', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
    aiPrefsSaving = false;
  }

  async function reprocessWithModel() {
    reprocessing = true;
    try {
      const result = await api.reprocessEmails(aiPrefs.agentic_model);
      if (result.queued > 0) {
        showToast(result.message, 'success');
      } else {
        showToast(result.message, 'info');
      }
    } catch (err) {
      showToast(err.message, 'error');
    }
    reprocessing = false;
  }

  // About Me
  async function loadAboutMe() {
    try {
      const data = await api.getAboutMe();
      aboutMeText = data.about_me || '';
      aboutMeLoaded = true;
    } catch (err) {
      showToast('Failed to load About Me', 'error');
    }
  }

  async function saveAboutMe() {
    aboutMeSaving = true;
    try {
      const data = await api.updateAboutMe(aboutMeText);
      aboutMeText = data.about_me || '';
      showToast('About Me saved', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
    aboutMeSaving = false;
  }

  // Account descriptions
  async function saveAccountDescription(accountId) {
    accountDescSaving = { ...accountDescSaving, [accountId]: true };
    try {
      const desc = accountDescriptions[accountId] || '';
      await api.updateAccountDescription(accountId, desc);
      showToast('Account description saved', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
    accountDescSaving = { ...accountDescSaving, [accountId]: false };
  }
</script>

<div class="h-full overflow-y-auto" style="background: var(--bg-primary)">
  <div class="max-w-4xl mx-auto p-6">
    <!-- Tabs -->
    <div class="flex gap-1 mb-6 border-b" style="border-color: var(--border-color)">
      {#each tabs as tab}
        <button
          onclick={() => activeTab = tab.id}
          class="px-4 py-2.5 text-sm font-medium transition-fast border-b-2 -mb-px"
          style="color: {activeTab === tab.id ? 'var(--color-accent-600)' : 'var(--text-secondary)'}; border-color: {activeTab === tab.id ? 'var(--color-accent-500)' : 'transparent'}"
        >
          {tab.label}
        </button>
      {/each}
    </div>

    {#if loading}
      <div class="flex justify-center py-12">
        <div class="w-6 h-6 border-2 rounded-full animate-spin" style="border-color: var(--border-color); border-top-color: var(--color-accent-500)"></div>
      </div>
    {:else if activeTab === 'about-me'}
      <!-- About Me -->
      <div class="space-y-6">
        <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <h3 class="text-sm font-semibold mb-1" style="color: var(--text-primary)">About Me</h3>
          <p class="text-xs mb-4" style="color: var(--text-tertiary)">
            Tell the AI about yourself -- your role, how you work, and what matters to you.
            This helps the AI write smarter replies, better summaries, and more relevant categorization.
          </p>
          <textarea
            bind:value={aboutMeText}
            placeholder="e.g., I'm a partner at a VC fund. I evaluate early-stage SaaS deals, focusing on ARR growth, churn rates, and founding team backgrounds. I prioritize emails from portfolio companies and potential deal flow."
            rows="6"
            class="w-full px-3 py-2.5 rounded-lg text-sm outline-none border resize-y"
            style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary); min-height: 120px"
          ></textarea>
          <div class="mt-3 flex items-center gap-3">
            <Button variant="primary" size="sm" onclick={saveAboutMe} disabled={aboutMeSaving}>
              {aboutMeSaving ? 'Saving...' : 'Save'}
            </Button>
            <span class="text-[10px]" style="color: var(--text-tertiary)">
              This context is used when analyzing emails, suggesting replies, and chatting about your inbox.
            </span>
          </div>
        </div>

        <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <h3 class="text-sm font-semibold mb-1" style="color: var(--text-primary)">Tips</h3>
          <ul class="text-xs space-y-2 mt-3" style="color: var(--text-secondary)">
            <li class="flex gap-2">
              <span class="shrink-0 w-1.5 h-1.5 rounded-full mt-1.5" style="background: var(--color-accent-500)"></span>
              <span>Describe your job role and industry so the AI can prioritize relevant emails.</span>
            </li>
            <li class="flex gap-2">
              <span class="shrink-0 w-1.5 h-1.5 rounded-full mt-1.5" style="background: var(--color-accent-500)"></span>
              <span>Mention key topics or projects you care about for better categorization.</span>
            </li>
            <li class="flex gap-2">
              <span class="shrink-0 w-1.5 h-1.5 rounded-full mt-1.5" style="background: var(--color-accent-500)"></span>
              <span>Explain your communication style (e.g., "I prefer concise, direct replies") for smarter reply suggestions.</span>
            </li>
            <li class="flex gap-2">
              <span class="shrink-0 w-1.5 h-1.5 rounded-full mt-1.5" style="background: var(--color-accent-500)"></span>
              <span>You can also describe each connected email account's purpose in the My Accounts tab.</span>
            </li>
          </ul>
        </div>
      </div>

    {:else if activeTab === 'dashboard'}
      <!-- Dashboard -->
      <div class="grid grid-cols-2 md:grid-cols-3 gap-4">
        <div class="rounded-xl border p-4" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <div class="text-2xl font-bold" style="color: var(--text-primary)">{dashboard?.total_accounts || 0}</div>
          <div class="text-xs mt-1" style="color: var(--text-secondary)">Connected Accounts</div>
        </div>
        <div class="rounded-xl border p-4" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <div class="text-2xl font-bold" style="color: var(--text-primary)">{(dashboard?.total_emails || 0).toLocaleString()}</div>
          <div class="text-xs mt-1" style="color: var(--text-secondary)">Total Emails</div>
        </div>
        <div class="rounded-xl border p-4" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <div class="text-2xl font-bold" style="color: var(--text-primary)">{(dashboard?.total_unread || 0).toLocaleString()}</div>
          <div class="text-xs mt-1" style="color: var(--text-secondary)">Unread</div>
        </div>
        <div class="rounded-xl border p-4" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <div class="text-2xl font-bold" style="color: {dashboard?.sync_active ? 'var(--color-accent-500)' : 'var(--text-primary)'}">{dashboard?.sync_active ? 'Active' : 'Idle'}</div>
          <div class="text-xs mt-1" style="color: var(--text-secondary)">Sync Status</div>
        </div>
        <div class="rounded-xl border p-4" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <div class="text-2xl font-bold" style="color: var(--text-primary)">{(dashboard?.ai_analyses_count || 0).toLocaleString()}</div>
          <div class="text-xs mt-1" style="color: var(--text-secondary)">AI Analyses</div>
        </div>
      </div>

    {:else if activeTab === 'apikeys'}
      <!-- API Keys -->
      <div class="space-y-6">
        <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <h3 class="text-sm font-semibold mb-4" style="color: var(--text-primary)">Claude API Key</h3>
          <div class="flex gap-3">
            <div class="flex-1">
              <input
                type="password"
                bind:value={claudeKey}
                placeholder="sk-ant-api03-..."
                class="w-full h-9 px-3 rounded-lg text-sm outline-none border"
                style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
              />
            </div>
            <Button variant="primary" size="sm" onclick={() => saveApiKey('claude_api_key', claudeKey, 'Claude API key for AI features')}>
              Save
            </Button>
          </div>
          <p class="text-xs mt-2" style="color: var(--text-tertiary)">Used for email categorization, summarization, and smart replies.</p>
        </div>

        <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <h3 class="text-sm font-semibold mb-4" style="color: var(--text-primary)">Google OAuth Credentials</h3>
          <div class="space-y-3">
            <div class="flex gap-3">
              <div class="flex-1">
                <input
                  type="text"
                  bind:value={googleClientId}
                  placeholder="Client ID"
                  class="w-full h-9 px-3 rounded-lg text-sm outline-none border"
                  style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
                />
              </div>
            </div>
            <div class="flex gap-3">
              <div class="flex-1">
                <input
                  type="password"
                  bind:value={googleClientSecret}
                  placeholder="Client Secret"
                  class="w-full h-9 px-3 rounded-lg text-sm outline-none border"
                  style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
                />
              </div>
            </div>
            <Button variant="primary" size="sm" onclick={() => {
              saveApiKey('google_client_id', googleClientId, 'Google OAuth Client ID');
              saveApiKey('google_client_secret', googleClientSecret, 'Google OAuth Client Secret');
            }}>
              Save Google Credentials
            </Button>
          </div>
          <p class="text-xs mt-2" style="color: var(--text-tertiary)">
            Create credentials at <a href="https://console.cloud.google.com/apis/credentials" target="_blank" class="underline" style="color: var(--color-accent-600)">Google Cloud Console</a>.
            Enable the Gmail API and add the redirect URI below as an authorized redirect URI.
          </p>
          <div class="mt-3 space-y-2">
            <p class="text-[11px] font-semibold tracking-wider uppercase" style="color: var(--text-tertiary)">Add both redirect URIs to Google Cloud Console:</p>
            {#each [
              { label: 'Login', uri: `${window.location.origin}/api/auth/google/callback` },
              { label: 'Connect', uri: `${window.location.origin}/api/accounts/oauth/callback` },
            ] as item}
              <div class="flex items-center gap-2 px-3 py-2 rounded-lg border" style="background: var(--bg-primary); border-color: var(--border-color)">
                <span class="text-[10px] font-bold tracking-wider uppercase w-16 shrink-0" style="color: var(--text-tertiary)">{item.label}</span>
                <code class="flex-1 text-xs font-mono select-all" style="color: var(--text-primary)">{item.uri}</code>
                <button
                  onclick={() => { navigator.clipboard.writeText(item.uri); showToast('Copied to clipboard', 'success'); }}
                  class="p-1 rounded transition-fast shrink-0"
                  style="color: var(--text-tertiary)"
                  title="Copy to clipboard"
                >
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M15.666 3.888A2.25 2.25 0 0013.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 01-.75.75H9.75a.75.75 0 01-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 01-2.25 2.25H6.75A2.25 2.25 0 014.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 011.927-.184" />
                  </svg>
                </button>
              </div>
            {/each}
          </div>
        </div>
      </div>

    {:else if activeTab === 'accounts'}
      <!-- Google Accounts -->
      <div class="space-y-4">
        <!-- Allowed Accounts -->
        <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <h3 class="text-sm font-semibold mb-1" style="color: var(--text-primary)">Allowed Accounts</h3>
          <p class="text-xs mb-3" style="color: var(--text-tertiary)">
            Only these emails and domains can connect via Google OAuth. Use full emails (<code style="color: var(--text-secondary)">user@example.com</code>) or domains with @ prefix (<code style="color: var(--text-secondary)">@example.com</code>). Comma-separated. Leave empty to allow any account.
          </p>
          <div class="flex gap-3">
            <input
              type="text"
              bind:value={allowedAccounts}
              placeholder="user@company.com, @company.com, other@gmail.com"
              class="flex-1 h-9 px-3 rounded-lg text-sm outline-none border font-mono"
              style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
            />
            <Button variant="primary" size="sm" onclick={saveAllowedAccounts}>
              Save
            </Button>
          </div>
        </div>

        <div class="flex justify-between items-center">
          <h3 class="text-sm font-semibold" style="color: var(--text-primary)">Connected Google Accounts</h3>
          <Button variant="primary" size="sm" onclick={connectGoogle}>
            Connect Account
          </Button>
        </div>

        {#if adminAccounts.length === 0}
          <div class="rounded-xl border p-8 text-center" style="background: var(--bg-secondary); border-color: var(--border-color)">
            <p class="text-sm font-medium" style="color: var(--text-primary)">No accounts connected</p>
            <p class="text-xs mt-1" style="color: var(--text-secondary)">
              First configure Google OAuth credentials in API Keys, then connect an account.
            </p>
          </div>
        {:else}
          {#each adminAccounts as acct}
            <div class="rounded-xl border p-4" style="background: var(--bg-secondary); border-color: var(--border-color)">
              <div class="flex items-center gap-4">
                <div class="w-10 h-10 rounded-full bg-accent-500/20 flex items-center justify-center text-lg font-bold shrink-0" style="color: var(--color-accent-600)">
                  {acct.email[0].toUpperCase()}
                </div>
                <div class="flex-1 min-w-0">
                  <div class="text-sm font-medium truncate" style="color: var(--text-primary)">{acct.email}</div>
                  <div class="text-xs" style="color: var(--text-secondary)">
                    {#if !acct.sync_status}
                      Not synced
                    {:else if acct.sync_status.status === 'syncing'}
                      <span style="color: var(--color-accent-500)">
                        {#if acct.sync_status.current_phase}
                          {acct.sync_status.current_phase}
                        {:else}
                          Syncing...
                        {/if}
                      </span>
                    {:else if acct.sync_status.status === 'rate_limited'}
                      <span style="color: #f59e0b">Rate limited by Gmail</span>
                    {:else if acct.sync_status.status === 'error'}
                      <span style="color: #ef4444">Error: {acct.sync_status.error_message || 'Unknown error'}</span>
                    {:else if acct.sync_status.status === 'completed'}
                      {acct.sync_status.messages_synced ? acct.sync_status.messages_synced.toLocaleString() + ' messages synced' : 'Completed'}
                    {:else}
                      {acct.sync_status.status || 'Idle'}
                      {#if acct.sync_status.messages_synced}
                        -- {acct.sync_status.messages_synced.toLocaleString()} messages
                      {/if}
                    {/if}
                  </div>
                </div>
                <div class="flex gap-2 shrink-0">
                  <Button size="sm" onclick={() => triggerSync(acct.id)}>
                    {#if acct.sync_status && acct.sync_status.status === 'syncing'}
                      Syncing...
                    {:else}
                      Sync
                    {/if}
                  </Button>
                  <Button size="sm" variant="danger" onclick={() => removeAccount(acct.id)}>
                    Remove
                  </Button>
                </div>
              </div>

              <!-- Account description -->
              <div class="mt-3">
                <label class="block text-[10px] font-semibold uppercase tracking-wider mb-1" style="color: var(--text-tertiary)">
                  Account Purpose
                </label>
                <div class="flex gap-2">
                  <input
                    type="text"
                    bind:value={accountDescriptions[acct.id]}
                    placeholder="e.g., Work email, Personal, Side project, Junk..."
                    class="flex-1 h-8 px-3 rounded-lg text-xs outline-none border"
                    style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
                  />
                  <Button size="sm" onclick={() => saveAccountDescription(acct.id)} disabled={accountDescSaving[acct.id]}>
                    {accountDescSaving[acct.id] ? 'Saving...' : 'Save'}
                  </Button>
                </div>
                <p class="text-[10px] mt-1" style="color: var(--text-tertiary)">
                  Helps the AI understand what kind of emails to expect from this account.
                </p>
              </div>

              <!-- Progress bar during sync -->
              {#if acct.sync_status && acct.sync_status.status === 'syncing' && acct.sync_status.total_messages > 0}
                <div class="mt-3">
                  <div class="flex justify-between text-[10px] mb-1" style="color: var(--text-tertiary)">
                    <span>{(acct.sync_status.messages_synced || 0).toLocaleString()} of {acct.sync_status.total_messages.toLocaleString()} messages</span>
                    <span>{Math.round((acct.sync_status.messages_synced || 0) / acct.sync_status.total_messages * 100)}%</span>
                  </div>
                  <div class="h-1.5 rounded-full overflow-hidden" style="background: var(--border-color)">
                    <div
                      class="h-full rounded-full transition-all duration-700 ease-out"
                      style="background: var(--color-accent-500); width: {Math.min(100, Math.round((acct.sync_status.messages_synced || 0) / acct.sync_status.total_messages * 100))}%"
                    ></div>
                  </div>
                </div>
              {/if}

              <!-- Rate limit notice -->
              {#if acct.sync_status && acct.sync_status.status === 'rate_limited' && acct.sync_status.retry_after}
                <div class="mt-2 px-3 py-2 rounded-lg text-xs flex items-center gap-2" style="background: #f59e0b10; color: #f59e0b; border: 1px solid #f59e0b30">
                  <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  Gmail rate limit reached. Will automatically retry at {new Date(acct.sync_status.retry_after).toLocaleTimeString()}.
                </div>
              {/if}

              <!-- Error detail -->
              {#if acct.sync_status && acct.sync_status.status === 'error' && acct.sync_status.error_message}
                <div class="mt-2 px-3 py-2 rounded-lg text-xs" style="background: #ef444410; color: #ef4444; border: 1px solid #ef444430">
                  {acct.sync_status.error_message}
                </div>
              {/if}

              <!-- Last sync info -->
              {#if acct.sync_status && acct.sync_status.status !== 'syncing'}
                <div class="mt-2 flex gap-4 text-[10px]" style="color: var(--text-tertiary)">
                  {#if acct.sync_status.last_full_sync}
                    <span>Full sync: {new Date(acct.sync_status.last_full_sync).toLocaleString()}</span>
                  {/if}
                  {#if acct.sync_status.last_incremental_sync}
                    <span>Last update: {new Date(acct.sync_status.last_incremental_sync).toLocaleString()}</span>
                  {/if}
                </div>
              {/if}
            </div>
          {/each}
        {/if}
      </div>

    {:else if activeTab === 'ai-models'}
      <!-- AI Model Preferences -->
      <div class="space-y-6">
        <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <h3 class="text-sm font-semibold mb-1" style="color: var(--text-primary)">Chat AI Models</h3>
          <p class="text-xs mb-5" style="color: var(--text-tertiary)">
            Choose which Claude model to use for each phase of the "Talk to your Emails" chat feature.
            Opus gives the best quality, Haiku is fastest and cheapest.
          </p>

          <div class="space-y-5">
            <!-- Plan model -->
            <div>
              <label for="ai-plan-model" class="block text-xs font-semibold mb-1.5 uppercase tracking-wider" style="color: var(--text-tertiary)">
                Plan
              </label>
              <p class="text-[11px] mb-2" style="color: var(--text-tertiary)">
                Analyzes your question and builds a research task list.
              </p>
              <select
                id="ai-plan-model"
                bind:value={aiPrefs.chat_plan_model}
                class="w-full h-9 px-3 rounded-lg text-sm outline-none border appearance-none cursor-pointer"
                style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
              >
                {#each aiPrefsAllowedModels as model}
                  <option value={model}>{modelLabels[model] || model}</option>
                {/each}
              </select>
            </div>

            <!-- Execute model -->
            <div>
              <label for="ai-execute-model" class="block text-xs font-semibold mb-1.5 uppercase tracking-wider" style="color: var(--text-tertiary)">
                Research
              </label>
              <p class="text-[11px] mb-2" style="color: var(--text-tertiary)">
                Searches and reads your emails to complete each task in the plan.
              </p>
              <select
                id="ai-execute-model"
                bind:value={aiPrefs.chat_execute_model}
                class="w-full h-9 px-3 rounded-lg text-sm outline-none border appearance-none cursor-pointer"
                style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
              >
                {#each aiPrefsAllowedModels as model}
                  <option value={model}>{modelLabels[model] || model}</option>
                {/each}
              </select>
            </div>

            <!-- Verify model -->
            <div>
              <label for="ai-verify-model" class="block text-xs font-semibold mb-1.5 uppercase tracking-wider" style="color: var(--text-tertiary)">
                Answer
              </label>
              <p class="text-[11px] mb-2" style="color: var(--text-tertiary)">
                Verifies completeness and writes the final formatted answer.
              </p>
              <select
                id="ai-verify-model"
                bind:value={aiPrefs.chat_verify_model}
                class="w-full h-9 px-3 rounded-lg text-sm outline-none border appearance-none cursor-pointer"
                style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
              >
                {#each aiPrefsAllowedModels as model}
                  <option value={model}>{modelLabels[model] || model}</option>
                {/each}
              </select>
            </div>
          </div>

          <div class="mt-5 flex items-center gap-3">
            <Button variant="primary" size="sm" onclick={saveAIPreferences} disabled={aiPrefsSaving}>
              {aiPrefsSaving ? 'Saving...' : 'Save Preferences'}
            </Button>
            <span class="text-[10px]" style="color: var(--text-tertiary)">
              Changes take effect on the next chat conversation.
            </span>
          </div>
        </div>

        <!-- Email Processing Model -->
        <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <h3 class="text-sm font-semibold mb-1" style="color: var(--text-primary)">Email Processing Model</h3>
          <p class="text-xs mb-5" style="color: var(--text-tertiary)">
            Used for email categorization, summarization, action items, and suggested replies.
            Changing this model affects new analyses. Use "Reprocess" to re-analyze emails with the new model.
          </p>

          <div>
            <label for="ai-agentic-model" class="block text-xs font-semibold mb-1.5 uppercase tracking-wider" style="color: var(--text-tertiary)">
              Model
            </label>
            <select
              id="ai-agentic-model"
              bind:value={aiPrefs.agentic_model}
              class="w-full h-9 px-3 rounded-lg text-sm outline-none border appearance-none cursor-pointer"
              style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
            >
              {#each aiPrefsAllowedModels as model}
                <option value={model}>{modelLabels[model] || model}</option>
              {/each}
            </select>
          </div>

          <div class="mt-5 flex items-center gap-3">
            <Button variant="primary" size="sm" onclick={saveAIPreferences} disabled={aiPrefsSaving}>
              {aiPrefsSaving ? 'Saving...' : 'Save'}
            </Button>
            <button
              onclick={reprocessWithModel}
              disabled={reprocessing}
              class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-fast disabled:opacity-50"
              style="background: var(--bg-primary); color: var(--text-primary); border: 1px solid var(--border-color)"
            >
              {#if reprocessing}
                <div class="w-3.5 h-3.5 border-2 rounded-full animate-spin" style="border-color: var(--border-color); border-top-color: var(--color-accent-500)"></div>
                Reprocessing...
              {:else}
                Reprocess with this model
              {/if}
            </button>
            <span class="text-[10px]" style="color: var(--text-tertiary)">
              Re-analyzes emails previously processed with a different model.
            </span>
          </div>
        </div>

        <!-- Model comparison info -->
        <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <h3 class="text-sm font-semibold mb-3" style="color: var(--text-primary)">Model Comparison</h3>
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b" style="border-color: var(--border-color)">
                <th class="text-left py-2 text-xs font-semibold uppercase tracking-wider" style="color: var(--text-secondary)">Model</th>
                <th class="text-left py-2 text-xs font-semibold uppercase tracking-wider" style="color: var(--text-secondary)">Quality</th>
                <th class="text-left py-2 text-xs font-semibold uppercase tracking-wider" style="color: var(--text-secondary)">Speed</th>
                <th class="text-left py-2 text-xs font-semibold uppercase tracking-wider" style="color: var(--text-secondary)">Cost</th>
              </tr>
            </thead>
            <tbody>
              <tr class="border-b" style="border-color: var(--border-color)">
                <td class="py-2 font-medium" style="color: var(--text-primary)">Opus 4.6</td>
                <td class="py-2" style="color: #22c55e">Highest</td>
                <td class="py-2" style="color: var(--text-secondary)">Slower</td>
                <td class="py-2" style="color: var(--text-secondary)">$$$</td>
              </tr>
              <tr class="border-b" style="border-color: var(--border-color)">
                <td class="py-2 font-medium" style="color: var(--text-primary)">Sonnet 4.5</td>
                <td class="py-2" style="color: var(--color-accent-600)">High</td>
                <td class="py-2" style="color: var(--color-accent-600)">Balanced</td>
                <td class="py-2" style="color: var(--text-secondary)">$$</td>
              </tr>
              <tr>
                <td class="py-2 font-medium" style="color: var(--text-primary)">Haiku 4.5</td>
                <td class="py-2" style="color: var(--text-secondary)">Good</td>
                <td class="py-2" style="color: #22c55e">Fastest</td>
                <td class="py-2" style="color: #22c55e">$</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

    {:else if activeTab === 'settings'}
      <!-- General Settings -->
      <div class="space-y-4">
        <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <h3 class="text-sm font-semibold mb-4" style="color: var(--text-primary)">Add Setting</h3>
          <div class="grid grid-cols-2 gap-3 mb-3">
            <Input label="Key" bind:value={newKey} placeholder="setting_key" />
            <Input label="Value" bind:value={newValue} placeholder="setting_value" type={newIsSecret ? 'password' : 'text'} />
          </div>
          <div class="flex items-center gap-4 mb-3">
            <label class="flex items-center gap-2 text-sm cursor-pointer" style="color: var(--text-secondary)">
              <input type="checkbox" bind:checked={newIsSecret} class="accent-accent-500" />
              Secret value
            </label>
            <input
              type="text"
              bind:value={newDescription}
              placeholder="Description (optional)"
              class="flex-1 h-8 px-3 rounded-lg text-sm outline-none border"
              style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
            />
          </div>
          <Button variant="primary" size="sm" onclick={saveSetting}>Save Setting</Button>
        </div>

        {#if settings.length > 0}
          <div class="rounded-xl border overflow-hidden" style="background: var(--bg-secondary); border-color: var(--border-color)">
            <table class="w-full text-sm">
              <thead>
                <tr class="border-b" style="border-color: var(--border-color)">
                  <th class="text-left px-4 py-2.5 text-xs font-semibold uppercase tracking-wider" style="color: var(--text-secondary)">Key</th>
                  <th class="text-left px-4 py-2.5 text-xs font-semibold uppercase tracking-wider" style="color: var(--text-secondary)">Value</th>
                  <th class="text-left px-4 py-2.5 text-xs font-semibold uppercase tracking-wider" style="color: var(--text-secondary)">Description</th>
                  <th class="w-20"></th>
                </tr>
              </thead>
              <tbody>
                {#each settings as s}
                  <tr class="border-b last:border-0" style="border-color: var(--border-color)">
                    <td class="px-4 py-2.5 font-mono text-xs" style="color: var(--text-primary)">{s.key}</td>
                    <td class="px-4 py-2.5 font-mono text-xs" style="color: var(--text-secondary)">{s.is_secret ? '••••••••' : (s.value || '—')}</td>
                    <td class="px-4 py-2.5 text-xs" style="color: var(--text-tertiary)">{s.description || '—'}</td>
                    <td class="px-4 py-2.5">
                      <button onclick={() => deleteSetting(s.key)} class="text-xs text-red-500 hover:text-red-600">Delete</button>
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      </div>
    {/if}
  </div>
</div>
