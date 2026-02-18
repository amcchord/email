<script>
  import { onMount, onDestroy } from 'svelte';
  import { api } from '../lib/api.js';
  import { user, showToast, syncStatus, forceSyncPoll, threadOrder } from '../lib/stores.js';
  import { theme, activeTheme, getEffectiveMode } from '../lib/theme.js';
  import { getThemeList } from '../lib/themes.js';
  import {
    activeShortcuts,
    shortcutsByCategory,
    updateShortcut,
    resetShortcut,
    resetAllShortcuts,
    checkConflict,
    eventToCombo,
    formatComboForDisplay,
    normalizeCombo,
  } from '../lib/shortcutStore.js';
  import { getCategories } from '../lib/shortcutDefaults.js';
  import Button from '../components/common/Button.svelte';
  import Input from '../components/common/Input.svelte';
  import Icon from '../components/common/Icon.svelte';

  // Theme state
  let themeList = getThemeList();
  let selectedThemeId = $state($activeTheme);
  let selectedColorScheme = $state($theme);

  function selectTheme(id) {
    selectedThemeId = id;
    activeTheme.set(id);
  }

  function selectColorScheme(scheme) {
    selectedColorScheme = scheme;
    theme.set(scheme);
  }

  async function saveAppearancePreferences() {
    appearanceSaving = true;
    try {
      await api.updateUIPreferences({
        theme: selectedThemeId,
        color_scheme: selectedColorScheme,
      });
      showToast('Appearance saved', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
    appearanceSaving = false;
  }

  let appearanceSaving = $state(false);

  let activeTab = $state('profile');
  let dashboard = $state(null);
  let settings = $state([]);
  let loading = $state(true);
  let isAdmin = $derived($user?.is_admin || false);

  // Use the live syncStatus store for real-time updates
  let adminAccounts = $derived($syncStatus.length > 0 ? $syncStatus : []);

  // Feature flags
  let featureFlags = $state({ desktop_app_enabled: false });
  let featureFlagsLoaded = $state(false);

  // New setting form
  let newKey = $state('');
  let newValue = $state('');
  let newIsSecret = $state(false);
  let newDescription = $state('');

  let allTabs = [
    { id: 'profile', label: 'Profile & Accounts', adminOnly: false },
    { id: 'ai-models', label: 'AI Models', adminOnly: false },
    { id: 'preferences', label: 'Preferences', adminOnly: false },
    { id: 'data', label: 'Data Management', adminOnly: false },
    { id: 'dashboard', label: 'Dashboard', adminOnly: true },
    { id: 'apikeys', label: 'API Keys', adminOnly: true },
    { id: 'settings', label: 'Settings', adminOnly: true },
    { id: 'desktop-app', label: 'Desktop App', adminOnly: false, featureFlag: 'desktop_app_enabled' },
  ];

  let tabs = $derived(allTabs.filter(t => {
    if (t.adminOnly && !isAdmin) return false;
    if (t.featureFlag && !featureFlags[t.featureFlag] && !isAdmin) return false;
    return true;
  }));

  onMount(async () => {
    await loadData();
    // Check URL params for tab
    const params = new URLSearchParams(window.location.search);
    if (params.get('tab')) {
      activeTab = params.get('tab');
    }
    // Listen for navigation from the shortcuts help modal
    window.addEventListener('shortcut-settings-navigate', handleShortcutSettingsNavigate);
    if (params.get('error') === 'not_allowed') {
      showToast('That Google account is not on the allowed list', 'error', 5000);
      window.history.replaceState({}, '', '/?page=admin');
    }
    if (params.get('error') === 'account_taken') {
      showToast('That Google account is already connected to another user', 'error', 5000);
      window.history.replaceState({}, '', '/?page=admin');
    }

    // Load AI stats and check for active processing
    loadAIStats();
    try {
      const status = await api.getAIProcessingStatus();
      if (status.active) {
        processingStatus = status;
        startProcessingPoll();
      }
    } catch {
      // Ignore
    }
  });

  onDestroy(() => {
    stopProcessingPoll();
    window.removeEventListener('shortcut-settings-navigate', handleShortcutSettingsNavigate);
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

      // Always load AI preferences, About Me, UI preferences, and feature flags (available to all users)
      await Promise.all([loadAIPreferences(), loadAboutMe(), loadUIPreferences(), loadFeatureFlags()]);
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

  async function reauthorizeAccount(id) {
    try {
      const result = await api.reauthorizeAccount(id);
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

  // UI Preferences
  let uiPrefsLoaded = $state(false);
  let uiPrefsSaving = $state(false);

  // Account descriptions (keyed by account id)
  let accountDescriptions = $state({});
  let accountDescSaving = $state({});
  let accountDescInitialized = $state(new Set());

  // Error details expand/collapse (keyed by account id)
  let expandedErrors = $state({});

  function toggleErrorDetails(accountId) {
    expandedErrors = { ...expandedErrors, [accountId]: !expandedErrors[accountId] };
  }

  function getFriendlyError(errorMessage) {
    if (!errorMessage) return 'An unknown error occurred';
    const lower = errorMessage.toLowerCase();
    if (lower.includes('insufficient authentication scopes') || lower.includes('insufficientpermissions')) {
      return 'Insufficient permissions — please reauthorize this account';
    }
    if (lower.includes('invalid_grant') || lower.includes('token has been expired') || lower.includes('token expired')) {
      return 'Authorization expired — please reauthorize this account';
    }
    if (lower.includes('invalid credentials') || lower.includes('unauthorized') || lower.includes('401')) {
      return 'Invalid credentials — please reauthorize this account';
    }
    if (lower.includes('403') || lower.includes('forbidden')) {
      return 'Access denied — please reauthorize this account';
    }
    if (lower.includes('rate limit') || lower.includes('429')) {
      return 'Rate limited by Gmail — will retry automatically';
    }
    if (lower.includes('network') || lower.includes('timeout') || lower.includes('connection')) {
      return 'Connection error — will retry on next sync';
    }
    // If it's a short message, show it directly
    if (errorMessage.length <= 80) {
      return errorMessage;
    }
    // Otherwise, give a generic message
    return 'Sync failed — expand details below for more info';
  }

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
    'claude-opus-4-6-fast': 'Claude Opus 4.6 (Fast) — 2.5x speed, 6x cost',
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
        custom_prompt_model: data.custom_prompt_model,
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
        custom_prompt_model: data.custom_prompt_model,
      };
      showToast('AI model preferences saved', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
    aiPrefsSaving = false;
  }

  async function loadUIPreferences() {
    try {
      const data = await api.getUIPreferences();
      threadOrder.set(data.thread_order || 'newest_first');
      if (data.theme) {
        selectedThemeId = data.theme;
        activeTheme.set(data.theme);
      }
      if (data.color_scheme) {
        selectedColorScheme = data.color_scheme;
        theme.set(data.color_scheme);
      }
      uiPrefsLoaded = true;
    } catch (err) {
      showToast('Failed to load UI preferences', 'error');
    }
  }

  async function loadFeatureFlags() {
    try {
      featureFlags = await api.getFeatureFlags();
      featureFlagsLoaded = true;
    } catch (err) {
      // Use defaults on failure
      featureFlagsLoaded = true;
    }
  }

  async function toggleFeatureFlag(key) {
    const newValue = !featureFlags[key];
    try {
      await api.updateSetting({
        key,
        value: String(newValue),
        is_secret: false,
        description: 'Enable the desktop app downloads',
      });
      featureFlags = { ...featureFlags, [key]: newValue };
      // Refresh the settings table if admin is viewing it
      if (isAdmin) {
        settings = await api.getSettings();
      }
      showToast(`${key} ${newValue ? 'enabled' : 'disabled'}`, 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function saveUIPreferences() {
    uiPrefsSaving = true;
    try {
      const data = await api.updateUIPreferences({ thread_order: $threadOrder });
      threadOrder.set(data.thread_order);
      showToast('Preferences saved', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
    uiPrefsSaving = false;
  }

  async function reprocessWithModel() {
    reprocessing = true;
    try {
      const result = await api.reprocessEmails(aiPrefs.agentic_model);
      if (result.queued > 0) {
        showToast(result.message, 'success');
        startProcessingPoll();
      } else {
        showToast(result.message, 'info');
      }
    } catch (err) {
      showToast(err.message, 'error');
    }
    reprocessing = false;
  }

  // Data Management state
  let categorizing = $state(false);
  let showBackfillMenu = $state(false);
  let showDropConfirm = $state(false);
  let showDropOnlyConfirm = $state(false);
  let dropRebuildDays = $state(90);
  let dropping = $state(false);
  let aiStats = $state(null);
  let rebuildingSearch = $state(false);
  let processingStatus = $state(null);
  let processingPollInterval = null;
  let processingJustFinished = $state(false);

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
        processingStatus = null;
        processingJustFinished = true;
        stopProcessingPoll();
        setTimeout(() => {
          processingJustFinished = false;
        }, 3000);
        loadAIStats();
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

  async function loadAIStats() {
    try {
      aiStats = await api.getAIStats();
    } catch {
      // Ignore stats loading errors
    }
  }

  async function triggerAutoCategorize(days = null) {
    categorizing = true;
    showBackfillMenu = false;
    try {
      const result = await api.triggerAutoCategorize(days);
      showToast(result.message, 'success');
      startProcessingPoll();
    } catch (err) {
      showToast(err.message, 'error');
    }
    categorizing = false;
  }

  async function dropAndRebuild(rebuildDays = null) {
    dropping = true;
    showDropConfirm = false;
    try {
      const result = await api.deleteAIAnalyses(rebuildDays);
      showToast(result.message, 'success');
      await loadAIStats();
      if (rebuildDays !== null) {
        startProcessingPoll();
      }
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
    } catch (err) {
      showToast(err.message, 'error');
    }
    dropping = false;
  }

  async function rebuildSearchIndex() {
    rebuildingSearch = true;
    try {
      const result = await api.rebuildSearchIndex();
      showToast(result.message, 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
    rebuildingSearch = false;
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

  // ── Keyboard Shortcuts ────────────────────────────────────────────
  let shortcutSearchFilter = $state('');
  let recordingActionId = $state(null);
  let recordedCombo = $state('');
  let shortcutConflict = $state(null);
  let shortcutCategories = getCategories();

  let filteredShortcutCategories = $derived.by(() => {
    const byCategory = $shortcutsByCategory;
    const query = shortcutSearchFilter.toLowerCase().trim();
    const result = [];
    for (const cat of shortcutCategories) {
      const shortcuts = byCategory[cat] || [];
      let filtered = shortcuts;
      if (query) {
        filtered = shortcuts.filter(s =>
          s.label.toLowerCase().includes(query) ||
          s.key.toLowerCase().includes(query) ||
          s.id.toLowerCase().includes(query)
        );
      }
      if (filtered.length > 0) {
        result.push({ name: cat, shortcuts: filtered });
      }
    }
    return result;
  });

  function startRecording(actionId) {
    recordingActionId = actionId;
    recordedCombo = '';
    shortcutConflict = null;
  }

  function cancelRecording() {
    recordingActionId = null;
    recordedCombo = '';
    shortcutConflict = null;
  }

  function handleShortcutKeydown(e) {
    if (!recordingActionId) return;

    e.preventDefault();
    e.stopPropagation();

    if (e.key === 'Escape') {
      cancelRecording();
      return;
    }

    const combo = eventToCombo(e);
    if (!combo) return;

    recordedCombo = combo;
    const conflict = checkConflict(recordingActionId, combo);
    shortcutConflict = conflict;
  }

  async function saveRecordedShortcut() {
    if (!recordingActionId || !recordedCombo) return;
    await updateShortcut(recordingActionId, recordedCombo);
    showToast('Shortcut updated', 'success');
    cancelRecording();
  }

  async function handleResetShortcut(actionId) {
    await resetShortcut(actionId);
    showToast('Shortcut reset to default', 'success');
  }

  async function handleResetAll() {
    await resetAllShortcuts();
    showToast('All shortcuts reset to defaults', 'success');
  }

  function handleShortcutSettingsNavigate() {
    activeTab = 'preferences';
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
    {:else if activeTab === 'profile'}
      <!-- Profile & Accounts -->
      <div class="space-y-6">
        <!-- About Me section -->
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

        <!-- Connected Accounts section -->
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
              {@const hasError = acct.sync_status && acct.sync_status.status === 'error'}
              {@const isRateLimited = acct.sync_status && acct.sync_status.status === 'rate_limited'}
              {@const isSyncing = acct.sync_status && acct.sync_status.status === 'syncing'}
              <div
                class="rounded-xl border p-4"
                style="background: var(--bg-secondary); border-color: {hasError ? 'var(--status-error-border)' : isRateLimited ? 'var(--status-warning-border)' : 'var(--border-color)'}"
              >
                <!-- Header row: avatar + email + status + actions -->
                <div class="flex items-center gap-4">
                  <div
                    class="w-10 h-10 rounded-full flex items-center justify-center text-lg font-bold shrink-0"
                    style="background: {hasError ? 'var(--status-error-bg)' : 'var(--color-accent-500-alpha, rgba(99,102,241,0.12))'}; color: {hasError ? 'var(--status-error)' : 'var(--color-accent-600)'}"
                  >
                    {#if hasError}
                      <Icon name="alert-triangle" size={20} />
                    {:else}
                      {acct.email[0].toUpperCase()}
                    {/if}
                  </div>
                  <div class="flex-1 min-w-0">
                    <div class="text-sm font-medium truncate" style="color: var(--text-primary)">{acct.email}</div>
                    <div class="text-xs mt-0.5" style="color: var(--text-secondary)">
                      {#if !acct.sync_status}
                        Not synced yet
                      {:else if isSyncing}
                        <span class="flex items-center gap-1.5" style="color: var(--color-accent-500)">
                          <span class="inline-block w-2 h-2 rounded-full animate-pulse" style="background: var(--color-accent-500)"></span>
                          {#if acct.sync_status.current_phase}
                            {acct.sync_status.current_phase}
                          {:else}
                            Syncing...
                          {/if}
                        </span>
                      {:else if isRateLimited}
                        <span style="color: var(--status-warning)">Rate limited by Gmail</span>
                      {:else if hasError}
                        <span style="color: var(--status-error)">{getFriendlyError(acct.sync_status.error_message)}</span>
                      {:else if acct.sync_status.status === 'completed'}
                        {#if acct.sync_status.messages_synced}
                          {acct.sync_status.messages_synced.toLocaleString()} messages synced
                        {:else}
                          Sync complete
                        {/if}
                      {:else}
                        {acct.sync_status.status || 'Idle'}
                        {#if acct.sync_status.messages_synced}
                          &middot; {acct.sync_status.messages_synced.toLocaleString()} messages
                        {/if}
                      {/if}
                    </div>
                  </div>
                  <div class="flex gap-2 shrink-0">
                    <Button size="sm" onclick={() => triggerSync(acct.id)} disabled={isSyncing}>
                      {#if isSyncing}
                        Syncing...
                      {:else}
                        Sync
                      {/if}
                    </Button>
                    <Button size="sm" onclick={() => reauthorizeAccount(acct.id)}>
                      Reauthorize
                    </Button>
                    <Button size="sm" variant="danger" onclick={() => removeAccount(acct.id)}>
                      Remove
                    </Button>
                  </div>
                </div>

                <!-- Error banner with expandable details -->
                {#if hasError && acct.sync_status.error_message}
                  <div class="mt-3 rounded-lg overflow-hidden" style="border: 1px solid var(--status-error-border); background: var(--status-error-bg)">
                    <button
                      onclick={() => toggleErrorDetails(acct.id)}
                      class="w-full flex items-center gap-2 px-3 py-2 text-xs text-left transition-colors"
                      style="color: var(--status-error-text)"
                    >
                      <span class="shrink-0" style="color: var(--status-error)">
                        <Icon name="alert-triangle" size={16} />
                      </span>
                      <span class="flex-1 font-medium">{getFriendlyError(acct.sync_status.error_message)}</span>
                      <span
                        class="shrink-0 transition-transform duration-200"
                        style="transform: rotate({expandedErrors[acct.id] ? '180' : '0'}deg); color: var(--status-error-text)"
                      >
                        <Icon name="chevron-down" size={16} />
                      </span>
                    </button>
                    {#if expandedErrors[acct.id]}
                      <div class="px-3 pb-3">
                        <div class="px-3 py-2 rounded text-[11px] font-mono break-all leading-relaxed" style="background: var(--status-error-border); color: var(--status-error-text); max-height: 120px; overflow-y: auto">
                          {acct.sync_status.error_message}
                        </div>
                      </div>
                    {/if}
                  </div>
                {/if}

                <!-- Rate limit notice -->
                {#if isRateLimited && acct.sync_status.retry_after}
                  <div class="mt-3 px-3 py-2.5 rounded-lg text-xs flex items-center gap-2.5" style="background: var(--status-warning-bg); color: var(--status-warning-text); border: 1px solid var(--status-warning-border)">
                    <span class="shrink-0" style="color: var(--status-warning)">
                      <Icon name="clock" size={16} />
                    </span>
                    <span>Gmail rate limit reached. Will automatically retry at <strong>{new Date(acct.sync_status.retry_after).toLocaleTimeString()}</strong>.</span>
                  </div>
                {/if}

                <!-- Progress bar during sync -->
                {#if isSyncing && acct.sync_status.total_messages > 0}
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

                <!-- Account description -->
                <div class="mt-3 pt-3" style="border-top: 1px solid var(--border-color)">
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

                <!-- Calendar scope notice -->
                {#if acct.has_calendar_scope === false}
                  <div class="mt-3 px-3 py-2.5 rounded-lg text-xs flex items-center gap-2.5" style="background: var(--status-info-bg); color: var(--status-info-text); border: 1px solid var(--status-info-border)">
                    <span class="shrink-0" style="color: var(--status-info)">
                      <Icon name="calendar" size={16} />
                    </span>
                    <span class="flex-1">Calendar access not granted. Reauthorize to enable calendar sync.</span>
                    <button
                      onclick={() => reauthorizeAccount(acct.id)}
                      class="shrink-0 px-2.5 py-1 rounded-md text-[11px] font-medium transition-fast"
                      style="background: var(--status-info-bg); color: var(--status-info)"
                    >
                      Reauthorize
                    </button>
                  </div>
                {/if}

                <!-- Last sync info -->
                {#if acct.sync_status && !isSyncing}
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
                  <Icon name="copy" size={16} />
                </button>
              </div>
            {/each}
          </div>
        </div>
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

        <!-- Custom Prompt Model -->
        <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <h3 class="text-sm font-semibold mb-1" style="color: var(--text-primary)">Custom Prompt Model</h3>
          <p class="text-xs mb-5" style="color: var(--text-tertiary)">
            Used when generating replies from custom prompts in the Flow view.
            Opus gives the best quality, Haiku is fastest and cheapest.
          </p>

          <div>
            <label for="ai-custom-prompt-model" class="block text-xs font-semibold mb-1.5 uppercase tracking-wider" style="color: var(--text-tertiary)">
              Model
            </label>
            <select
              id="ai-custom-prompt-model"
              bind:value={aiPrefs.custom_prompt_model}
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
            <span class="text-[10px]" style="color: var(--text-tertiary)">
              Changes take effect on the next custom prompt generation.
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
                <td class="py-2" style="color: var(--status-success)">Highest</td>
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
                <td class="py-2" style="color: var(--status-success)">Fastest</td>
                <td class="py-2" style="color: var(--status-success)">$</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

    {:else if activeTab === 'preferences'}
      <!-- Preferences & Keyboard Shortcuts -->
      <div class="space-y-6">
        <!-- Appearance -->
        <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <h3 class="text-sm font-semibold mb-1" style="color: var(--text-primary)">Appearance</h3>
          <p class="text-xs mb-5" style="color: var(--text-tertiary)">Choose a color theme and light/dark mode. Changes preview instantly.</p>

          <!-- Color Theme -->
          <div class="mb-5">
            <span class="text-xs font-medium mb-2.5 block" style="color: var(--text-secondary)">Color Theme</span>
            <div class="grid grid-cols-3 sm:grid-cols-6 gap-3">
              {#each themeList as t}
                <button
                  onclick={() => selectTheme(t.id)}
                  class="group relative flex flex-col items-center gap-2 p-3 rounded-xl border-2 transition-fast"
                  style="border-color: {selectedThemeId === t.id ? t.accent['500'] : 'var(--border-color)'}; background: {selectedThemeId === t.id ? 'var(--bg-tertiary)' : 'var(--bg-primary)'}"
                  title={t.description}
                >
                  <!-- Swatch -->
                  <div class="flex gap-1">
                    <div class="w-5 h-5 rounded-full" style="background: {t.accent['500']}"></div>
                    <div class="w-5 h-5 rounded-full" style="background: {t.surface['700']}"></div>
                  </div>
                  <!-- Label -->
                  <span class="text-[11px] font-medium" style="color: {selectedThemeId === t.id ? 'var(--text-primary)' : 'var(--text-secondary)'}">{t.name}</span>
                  <!-- Check indicator -->
                  {#if selectedThemeId === t.id}
                    <div class="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full flex items-center justify-center" style="background: {t.accent['500']}">
                      <svg class="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7" /></svg>
                    </div>
                  {/if}
                </button>
              {/each}
            </div>
          </div>

          <!-- Color Scheme (Light / Dark / System) -->
          <div class="mb-5">
            <span class="text-xs font-medium mb-2 block" style="color: var(--text-secondary)">Mode</span>
            <div class="flex gap-2">
              {#each [
                { id: 'light', label: 'Light', icon: 'sun' },
                { id: 'dark', label: 'Dark', icon: 'moon' },
                { id: 'system', label: 'System', icon: 'monitor' },
              ] as mode}
                <button
                  onclick={() => selectColorScheme(mode.id)}
                  class="flex items-center gap-2 px-4 py-2 rounded-lg border text-xs font-medium transition-fast"
                  style="{selectedColorScheme === mode.id
                    ? 'background: var(--color-accent-500); color: white; border-color: var(--color-accent-500)'
                    : 'background: var(--bg-primary); color: var(--text-secondary); border-color: var(--border-color)'}"
                >
                  <Icon name={mode.icon} size={14} />
                  {mode.label}
                </button>
              {/each}
            </div>
            {#if selectedColorScheme === 'system'}
              <p class="text-[10px] mt-2" style="color: var(--text-tertiary)">Follows your operating system preference.</p>
            {/if}
          </div>

          <div class="flex items-center gap-3">
            <Button variant="primary" size="sm" onclick={saveAppearancePreferences} disabled={appearanceSaving}>
              {appearanceSaving ? 'Saving...' : 'Save Appearance'}
            </Button>
            <span class="text-[10px]" style="color: var(--text-tertiary)">
              Synced across all your devices.
            </span>
          </div>
        </div>

        <!-- Thread Display -->
        <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <h3 class="text-sm font-semibold mb-1" style="color: var(--text-primary)">Thread Display</h3>
          <p class="text-xs mb-4" style="color: var(--text-tertiary)">Configure how email threads are displayed throughout the app.</p>

          <div class="space-y-4">
            <div>
              <label class="text-xs font-medium mb-1.5 block" style="color: var(--text-secondary)">Message Order</label>
              <p class="text-[11px] mb-2" style="color: var(--text-tertiary)">Choose whether to show the newest or oldest message first when viewing a thread.</p>
              <div class="flex gap-2">
                <button
                  onclick={() => threadOrder.set('newest_first')}
                  class="px-4 py-2 rounded-lg border text-xs font-medium transition-fast"
                  style="{$threadOrder === 'newest_first'
                    ? 'background: var(--color-accent-500); color: white; border-color: var(--color-accent-500)'
                    : 'background: var(--bg-primary); color: var(--text-secondary); border-color: var(--border-color)'}"
                >
                  Newest first
                </button>
                <button
                  onclick={() => threadOrder.set('oldest_first')}
                  class="px-4 py-2 rounded-lg border text-xs font-medium transition-fast"
                  style="{$threadOrder === 'oldest_first'
                    ? 'background: var(--color-accent-500); color: white; border-color: var(--color-accent-500)'
                    : 'background: var(--bg-primary); color: var(--text-secondary); border-color: var(--border-color)'}"
                >
                  Oldest first
                </button>
              </div>
            </div>
          </div>

          <div class="mt-5 flex items-center gap-3">
            <Button variant="primary" size="sm" onclick={saveUIPreferences} disabled={uiPrefsSaving}>
              {uiPrefsSaving ? 'Saving...' : 'Save Preferences'}
            </Button>
          </div>
        </div>

        <!-- Keyboard Shortcuts -->
        <!-- svelte-ignore a11y_no_noninteractive_element_interactions a11y_no_static_element_interactions -->
        <div class="space-y-4" onkeydown={handleShortcutKeydown}>
          <div class="flex items-center justify-between gap-4">
            <h3 class="text-sm font-semibold" style="color: var(--text-primary)">Keyboard Shortcuts</h3>
            <button
              onclick={handleResetAll}
              class="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-fast border"
              style="border-color: var(--border-color); color: var(--text-secondary); background: var(--bg-secondary)"
            >
              <Icon name="refresh-cw" size={14} />
              Reset All
            </button>
          </div>

          <div class="flex items-center gap-3">
            <div class="flex-1">
              <input
                type="text"
                placeholder="Search shortcuts..."
                bind:value={shortcutSearchFilter}
                class="w-full h-9 px-3 rounded-lg text-sm outline-none border"
                style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-primary)"
              />
            </div>
          </div>

          <p class="text-xs" style="color: var(--text-tertiary)">
            Click a shortcut key to re-record it. Press <kbd class="px-1.5 py-0.5 rounded text-[10px] font-semibold" style="background: var(--bg-secondary); border: 1px solid var(--border-color)">Esc</kbd> to cancel recording. Hold <kbd class="px-1.5 py-0.5 rounded text-[10px] font-semibold" style="background: var(--bg-secondary); border: 1px solid var(--border-color)">Option/Alt</kbd> on any page to see shortcut badges on screen.
          </p>

          {#each filteredShortcutCategories as category (category.name)}
            <div class="rounded-xl border overflow-hidden" style="background: var(--bg-secondary); border-color: var(--border-color)">
              <div class="px-4 py-2.5 border-b" style="border-color: var(--border-color)">
                <h3 class="text-xs font-bold uppercase tracking-wider" style="color: var(--text-secondary)">{category.name}</h3>
              </div>
              <div>
                {#each category.shortcuts as shortcut, i (shortcut.id)}
                  <div
                    class="flex items-center gap-3 px-4 py-2.5 {i < category.shortcuts.length - 1 ? 'border-b' : ''}"
                    style="border-color: var(--border-color)"
                  >
                    <!-- Label -->
                    <div class="flex-1 min-w-0">
                      <span class="text-sm" style="color: var(--text-primary)">{shortcut.label}</span>
                      <span class="text-[10px] ml-2 font-mono" style="color: var(--text-tertiary)">{shortcut.id}</span>
                    </div>

                    <!-- Current binding -->
                    {#if recordingActionId === shortcut.id}
                      <!-- Recording mode -->
                      <div class="flex items-center gap-2">
                        <div
                          class="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm min-w-[80px] justify-center border-2 animate-pulse"
                          style="border-color: var(--color-accent-500); background: var(--bg-primary); color: var(--text-primary)"
                        >
                          {#if recordedCombo}
                            <span class="font-semibold">{formatComboForDisplay(recordedCombo)}</span>
                          {:else}
                            <span class="text-xs" style="color: var(--text-tertiary)">Press a key...</span>
                          {/if}
                        </div>
                        {#if shortcutConflict}
                          <span class="text-[10px]" style="color: var(--status-error)">Conflicts with: {shortcutConflict.label}</span>
                        {/if}
                        {#if recordedCombo}
                          <button
                            onclick={saveRecordedShortcut}
                            class="px-2 py-1 rounded text-xs font-medium"
                            style="background: var(--color-accent-500); color: white"
                          >Save</button>
                        {/if}
                        <button
                          onclick={cancelRecording}
                          class="px-2 py-1 rounded text-xs font-medium"
                          style="background: var(--bg-tertiary, var(--bg-primary)); color: var(--text-secondary)"
                        >Cancel</button>
                      </div>
                    {:else}
                      <!-- Display mode -->
                      <div class="flex items-center gap-2">
                        <button
                          onclick={() => startRecording(shortcut.id)}
                          class="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm min-w-[60px] justify-center cursor-pointer transition-fast border"
                          style="border-color: var(--border-color); background: var(--bg-primary); color: var(--text-primary)"
                          title="Click to change this shortcut"
                        >
                          {#each shortcut.key.split('+') as part, pi}
                            {#if pi > 0}
                              <span class="text-[10px] mx-0.5" style="color: var(--text-tertiary)">+</span>
                            {/if}
                            <kbd class="px-1.5 py-0.5 rounded text-xs font-semibold" style="background: var(--bg-secondary); border: 1px solid var(--border-color)">{formatComboForDisplay(part)}</kbd>
                          {/each}
                          {#if shortcut.isCustom}
                            <span class="text-[10px] font-bold ml-1" style="color: var(--color-accent-500)">*</span>
                          {/if}
                        </button>
                        {#if shortcut.isCustom}
                          <button
                            onclick={() => handleResetShortcut(shortcut.id)}
                            class="p-1 rounded transition-fast"
                            style="color: var(--text-tertiary)"
                            title="Reset to default ({shortcut.defaultKey})"
                          >
                            <Icon name="refresh-cw" size={12} />
                          </button>
                        {/if}
                      </div>
                    {/if}
                  </div>
                {/each}
              </div>
            </div>
          {/each}

          {#if filteredShortcutCategories.length === 0}
            <div class="rounded-xl border p-8 text-center" style="background: var(--bg-secondary); border-color: var(--border-color)">
              <p class="text-sm" style="color: var(--text-secondary)">No shortcuts match "{shortcutSearchFilter}"</p>
            </div>
          {/if}
        </div>
      </div>

    {:else if activeTab === 'data'}
      <!-- Data Management -->
      <div class="space-y-6">

        <!-- AI Processing Progress Bar -->
        {#if processingStatus && processingStatus.active}
          {@const pct = getProcessingPercent(processingStatus)}
          <div class="rounded-xl border overflow-hidden" style="background: var(--bg-secondary); border-color: var(--border-color)">
            <div class="px-5 py-4 flex items-center gap-3">
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
                    style="background: var(--color-accent-500); width: {pct}%"
                  ></div>
                </div>
              </div>
              <span class="text-xs font-bold shrink-0" style="color: var(--color-accent-500)">{pct}%</span>
            </div>
          </div>
        {/if}

        <!-- Just finished banner -->
        {#if processingJustFinished}
          <div class="rounded-xl border px-5 py-3 flex items-center gap-2" style="background: var(--status-success-bg); border-color: var(--status-success-border); color: var(--status-success-text)">
            <Icon name="check-circle" size={16} />
            <span class="text-sm font-medium">Processing complete! Data has been refreshed.</span>
          </div>
        {/if}

        <!-- AI Analysis Management -->
        <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <h3 class="text-sm font-semibold mb-1" style="color: var(--text-primary)">AI Email Analysis</h3>
          <p class="text-xs mb-4" style="color: var(--text-tertiary)">
            Analyze emails with AI for categorization, summaries, action items, and reply suggestions.
            You can also drop all analyses and rebuild from scratch.
          </p>

          <!-- Stats -->
          {#if aiStats}
            <div class="flex flex-wrap gap-3 mb-4">
              <div class="px-3 py-2 rounded-lg text-center" style="background: var(--bg-tertiary)">
                <div class="text-lg font-bold" style="color: var(--text-primary)">{aiStats.total_analyzed || 0}</div>
                <div class="text-[10px] uppercase tracking-wider font-semibold" style="color: var(--text-tertiary)">Analyzed</div>
              </div>
              <div class="px-3 py-2 rounded-lg text-center" style="background: var(--bg-tertiary)">
                <div class="text-lg font-bold" style="color: var(--text-primary)">{aiStats.total_emails || 0}</div>
                <div class="text-[10px] uppercase tracking-wider font-semibold" style="color: var(--text-tertiary)">Total Emails</div>
              </div>
              {#if aiStats.unanalyzed}
                <div class="px-3 py-2 rounded-lg text-center" style="background: var(--bg-tertiary)">
                  <div class="text-lg font-bold" style="color: var(--color-accent-500)">{aiStats.unanalyzed.all || 0}</div>
                  <div class="text-[10px] uppercase tracking-wider font-semibold" style="color: var(--text-tertiary)">Unanalyzed</div>
                </div>
              {/if}
              {#if aiStats.models && Object.keys(aiStats.models).length > 0}
                <div class="flex items-center gap-1.5 px-3 py-2 rounded-lg" style="background: var(--bg-tertiary)">
                  <span class="text-[10px] uppercase tracking-wider font-semibold" style="color: var(--text-tertiary)">Models:</span>
                  {#each Object.entries(aiStats.models) as [model, count]}
                    <span class="px-1.5 py-0.5 rounded text-[10px] font-medium" style="background: var(--bg-secondary); color: var(--text-secondary)">{model}: {count}</span>
                  {/each}
                </div>
              {/if}
            </div>
          {/if}

          <!-- Action buttons -->
          <div class="flex flex-wrap items-center gap-2">
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
                  <Icon name="zap" size={16} />
                  Analyze Emails
                  <Icon name="chevron-down" size={12} />
                {/if}
              </button>
              {#if showBackfillMenu}
                <div class="absolute left-0 top-full mt-1 w-56 rounded-lg border shadow-lg z-50 py-1" style="background: var(--bg-secondary); border-color: var(--border-color)">
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

            <!-- Drop & Rebuild button -->
            <div class="relative">
              <button
                onclick={() => { showDropConfirm = !showDropConfirm; showBackfillMenu = false; showDropOnlyConfirm = false; }}
                disabled={dropping || (processingStatus && processingStatus.active)}
                class="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-fast disabled:opacity-50 border"
                style="border-color: var(--border-color); color: var(--text-secondary); background: var(--bg-primary)"
                title="Drop & Rebuild AI Data"
              >
                {#if dropping}
                  <div class="w-4 h-4 border-2 rounded-full animate-spin" style="border-color: var(--border-color); border-top-color: var(--text-secondary)"></div>
                {:else}
                  <Icon name="refresh-cw" size={16} />
                {/if}
                Drop & Rebuild
              </button>
              {#if showDropConfirm}
                <!-- svelte-ignore a11y_click_events_have_key_events -->
                <!-- svelte-ignore a11y_no_static_element_interactions -->
                <div class="absolute left-0 top-full mt-1 w-72 rounded-lg border shadow-lg z-50 p-4 space-y-3" style="background: var(--bg-secondary); border-color: var(--border-color)" onclick={(e) => e.stopPropagation()}>
                  <div class="text-sm font-medium" style="color: var(--text-primary)">Drop & Rebuild AI Data</div>
                  {#if aiStats}
                    <div class="text-xs space-y-1" style="color: var(--text-tertiary)">
                      <div>{aiStats.total_analyzed} analyses will be deleted, then re-analyzed</div>
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

            <!-- Drop Only button -->
            <div class="relative">
              <button
                onclick={() => { showDropOnlyConfirm = !showDropOnlyConfirm; showBackfillMenu = false; showDropConfirm = false; }}
                disabled={dropping || (processingStatus && processingStatus.active)}
                class="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-fast disabled:opacity-50 border"
                style="border-color: var(--status-error-border); color: var(--status-error); background: var(--bg-primary)"
                title="Drop all AI data without rebuilding"
              >
                {#if dropping}
                  <div class="w-4 h-4 border-2 rounded-full animate-spin" style="border-color: var(--status-error-border); border-top-color: var(--status-error)"></div>
                {:else}
                  <Icon name="trash-2" size={16} />
                {/if}
                Drop All
              </button>
              {#if showDropOnlyConfirm}
                <!-- svelte-ignore a11y_click_events_have_key_events -->
                <!-- svelte-ignore a11y_no_static_element_interactions -->
                <div class="absolute left-0 top-full mt-1 w-72 rounded-lg border shadow-lg z-50 p-4 space-y-3" style="background: var(--bg-secondary); border-color: var(--border-color)" onclick={(e) => e.stopPropagation()}>
                  <div class="text-sm font-medium" style="color: var(--text-primary)">Drop All AI Data</div>
                  <p class="text-xs" style="color: var(--text-tertiary)">
                    This will permanently delete all AI analyses (categories, summaries, action items, reply suggestions) without rebuilding.
                  </p>
                  {#if aiStats}
                    <div class="text-xs font-medium" style="color: var(--text-secondary)">
                      {aiStats.total_analyzed} analyses will be deleted
                    </div>
                  {/if}
                  <div class="flex gap-2">
                    <button
                      onclick={dropOnly}
                      class="flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-fast"
                      style="background: var(--status-error); color: white"
                    >
                      Yes, Drop All
                    </button>
                    <button
                      onclick={() => { showDropOnlyConfirm = false; }}
                      class="px-3 py-1.5 rounded-md text-xs font-medium transition-fast"
                      style="background: var(--bg-tertiary); color: var(--text-secondary)"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              {/if}
            </div>
          </div>

          <!-- Click outside to close menus -->
          {#if showBackfillMenu || showDropConfirm || showDropOnlyConfirm}
            <!-- svelte-ignore a11y_click_events_have_key_events -->
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <div class="fixed inset-0 z-40" onclick={() => { showBackfillMenu = false; showDropConfirm = false; showDropOnlyConfirm = false; }}></div>
          {/if}
        </div>

        <!-- Search Index -->
        <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <h3 class="text-sm font-semibold mb-1" style="color: var(--text-primary)">Search Index</h3>
          <p class="text-xs mb-4" style="color: var(--text-tertiary)">
            Rebuild the full-text search index for all your emails. This updates the search vectors used
            for email search. Use this if search results seem incomplete or after a large sync.
          </p>
          <Button size="sm" onclick={rebuildSearchIndex} disabled={rebuildingSearch}>
            {#if rebuildingSearch}
              <div class="w-3.5 h-3.5 border-2 rounded-full animate-spin inline-block mr-1.5" style="border-color: var(--border-color); border-top-color: var(--color-accent-500)"></div>
              Rebuilding...
            {:else}
              Rebuild Search Index
            {/if}
          </Button>
        </div>
      </div>

    {:else if activeTab === 'settings'}
      <!-- General Settings -->
      <div class="space-y-4">
        <!-- Feature Flags -->
        <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <h3 class="text-sm font-semibold mb-1" style="color: var(--text-primary)">Feature Flags</h3>
          <p class="text-xs mb-4" style="color: var(--text-tertiary)">Enable or disable optional features for all users.</p>
          <div class="space-y-3">
            <label class="flex items-center justify-between gap-3 cursor-pointer">
              <div>
                <div class="text-sm font-medium" style="color: var(--text-primary)">Desktop App (Electron)</div>
                <div class="text-xs" style="color: var(--text-tertiary)">Show download links for macOS and Windows desktop clients</div>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={featureFlags.desktop_app_enabled}
                aria-label="Toggle Desktop App"
                onclick={() => toggleFeatureFlag('desktop_app_enabled')}
                class="relative inline-flex h-6 w-11 shrink-0 rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none"
                style="background: {featureFlags.desktop_app_enabled ? 'var(--color-accent-500)' : 'var(--bg-tertiary)'}"
              >
                <span
                  class="pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow transform transition duration-200 ease-in-out"
                  style="transform: translateX({featureFlags.desktop_app_enabled ? '20px' : '0px'})"
                ></span>
              </button>
            </label>
          </div>
        </div>

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

    {:else if activeTab === 'desktop-app'}
      <!-- Desktop App -->
      <div class="space-y-6">
        <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <h3 class="text-sm font-semibold mb-1" style="color: var(--text-primary)">Desktop App</h3>
          <p class="text-xs mb-5" style="color: var(--text-tertiary)">
            A native desktop app that wraps the web UI with OS integration: persistent login, pop-out windows, native menus, and secure credential storage.
          </p>

          <div class="flex flex-wrap gap-3 mb-5">
            <a
              href="/downloads/Mail-1.0.0-mac.zip"
              class="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium transition-fast no-underline"
              style="background: var(--color-accent-500); color: white"
            >
              <Icon name="download" size={18} />
              Download for macOS (.zip)
            </a>
            <a
              href="/downloads/Mail-1.0.0-win-setup.exe"
              class="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium transition-fast no-underline"
              style="background: var(--color-accent-500); color: white"
            >
              <Icon name="download" size={18} />
              Download for Windows (.exe)
            </a>
          </div>

          <div class="text-xs space-y-3" style="color: var(--text-tertiary)">
            <div>
              <p class="font-semibold mb-1" style="color: var(--text-secondary)">macOS</p>
              <p><strong style="color: var(--text-secondary)">System requirements:</strong> macOS 12 (Monterey) or later, Intel or Apple Silicon.</p>
              <p><strong style="color: var(--text-secondary)">First launch:</strong> The app is unsigned. Right-click the app and choose "Open" to bypass Gatekeeper on first launch.</p>
            </div>
            <div>
              <p class="font-semibold mb-1" style="color: var(--text-secondary)">Windows</p>
              <p><strong style="color: var(--text-secondary)">System requirements:</strong> Windows 10 or later, 64-bit.</p>
              <p><strong style="color: var(--text-secondary)">First launch:</strong> The installer is unsigned. You may need to click "More info" then "Run anyway" in Windows SmartScreen.</p>
            </div>
          </div>
        </div>
      </div>
    {/if}
  </div>
</div>
