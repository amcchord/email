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
  import AIModelsPanel from '../lib/admin/AIModelsPanel.svelte';
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
    { id: 'terminals', label: 'E-Ink Terminals', adminOnly: false },
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

      // Always load AI preferences, About Me, UI preferences, feature flags, API tokens, and terminal settings (available to all users)
      await Promise.all([
        loadAIPreferences(),
        loadAboutMe(),
        loadUIPreferences(),
        loadFeatureFlags(),
        loadApiTokens(),
        loadTerminalSettings(),
        loadTerminals(),
      ]);
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

  // ── Read-only API tokens ────────────────────────────────────────
  let apiTokens = $state([]);
  let apiTokensLoaded = $state(false);
  let newTokenName = $state('');
  let newTokenCreating = $state(false);
  // The plaintext value of a freshly-created token, shown exactly once.
  let freshToken = $state(null);

  async function loadApiTokens() {
    try {
      apiTokens = await api.listApiTokens();
      apiTokensLoaded = true;
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function createApiToken() {
    const name = newTokenName.trim();
    if (!name) return;
    newTokenCreating = true;
    try {
      const created = await api.createApiToken(name);
      freshToken = created;
      newTokenName = '';
      await loadApiTokens();
    } catch (err) {
      showToast(err.message, 'error');
    }
    newTokenCreating = false;
  }

  async function revokeApiToken(id) {
    if (!confirm('Revoke this token? Any clients using it will stop working immediately.')) return;
    try {
      await api.revokeApiToken(id);
      showToast('Token revoked', 'success');
      await loadApiTokens();
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function copyTokenToClipboard(token) {
    try {
      await navigator.clipboard.writeText(token);
      showToast('Token copied to clipboard', 'success');
    } catch (err) {
      showToast('Copy failed -- select and copy manually', 'error');
    }
  }

  function dismissFreshToken() {
    freshToken = null;
  }

  // API key form values
  let claudeKey = $state('');
  let googleClientId = $state('');
  let googleClientSecret = $state('');

  // Allowed accounts
  let allowedAccounts = $state('');
  let allowedLoaded = $state(false);

  // AI model preferences (defaults overwritten by /ai-preferences response)
  let aiPrefs = $state({
    chat_plan_model: '',
    chat_execute_model: '',
    chat_verify_model: '',
    agentic_model: '',
    custom_prompt_model: '',
    unsubscribe_model: '',
  });
  let aiPrefsAllowedModels = $state([]);
  let aiPrefsLabels = $state({});
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

  function modelLabel(modelId) {
    return aiPrefsLabels[modelId] || modelId;
  }

  async function loadAIPreferences() {
    try {
      const data = await api.getAIPreferences();
      aiPrefs = {
        chat_plan_model: data.chat_plan_model,
        chat_execute_model: data.chat_execute_model,
        chat_verify_model: data.chat_verify_model,
        agentic_model: data.agentic_model,
        custom_prompt_model: data.custom_prompt_model,
        unsubscribe_model: data.unsubscribe_model,
      };
      aiPrefsAllowedModels = data.allowed_models || [];
      aiPrefsLabels = data.labels || {};
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
        unsubscribe_model: data.unsubscribe_model,
      };
      aiPrefsLabels = data.labels || aiPrefsLabels;
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

  // ── E-Ink Terminals ─────────────────────────────────────────────
  let terminalSettings = $state(null);
  let terminalSettingsLoaded = $state(false);
  let terminals = $state([]);
  let terminalsLoaded = $state(false);
  let terminalsRefreshing = $state(false);
  let terminalRowSaving = $state({});
  let haUrlInput = $state('');
  let haTokenInput = $state('');
  let haSaving = $state(false);
  let regenLoading = $state(false);
  let copyHint = $state('');
  let tzInput = $state('');
  let tzSaving = $state(false);

  // Common IANA zones surfaced as quick picks. Users can type any other valid
  // zone (server validates against the system zoneinfo db) into the input.
  const TIMEZONE_PRESETS = [
    'America/New_York',
    'America/Chicago',
    'America/Denver',
    'America/Los_Angeles',
    'America/Anchorage',
    'America/Phoenix',
    'America/Toronto',
    'Europe/London',
    'Europe/Paris',
    'Europe/Berlin',
    'Europe/Madrid',
    'Asia/Tokyo',
    'Asia/Shanghai',
    'Asia/Kolkata',
    'Australia/Sydney',
    'UTC',
  ];

  function terminalBaseUrl() {
    if (!terminalSettings?.code) return '';
    return `${window.location.origin}/terminal/${terminalSettings.code}`;
  }

  function terminalScheduleUrl(variantQuery) {
    const base = terminalBaseUrl();
    if (!base) return '';
    if (!variantQuery) return `${base}/schedule.json`;
    return `${base}/schedule.json?variant=${encodeURIComponent(variantQuery)}`;
  }

  async function loadTerminalSettings() {
    try {
      const s = await api.getTerminalSettings();
      terminalSettings = s;
      haUrlInput = s.home_assistant_url || '';
      tzInput = s.timezone || '';
      terminalSettingsLoaded = true;
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function loadTerminals() {
    try {
      terminals = await api.listTerminals();
      terminalsLoaded = true;
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function refreshTerminals() {
    terminalsRefreshing = true;
    await loadTerminals();
    terminalsRefreshing = false;
  }

  async function regenerateTerminalCode() {
    if (!confirm('Regenerate the terminal short code? All existing devices will need their firmware URL updated to the new code before they can check in again.')) return;
    regenLoading = true;
    try {
      const s = await api.regenerateTerminalCode();
      terminalSettings = s;
      showToast('Terminal code regenerated', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
    regenLoading = false;
  }

  async function copyToClipboard(text, hint = 'Copied') {
    try {
      await navigator.clipboard.writeText(text);
      copyHint = hint;
      setTimeout(() => { if (copyHint === hint) copyHint = ''; }, 1200);
    } catch {
      showToast('Copy failed -- select and copy manually', 'error');
    }
  }

  async function saveTerminalTimezone() {
    const tz = (tzInput || '').trim();
    if (!tz) {
      showToast('Enter an IANA timezone (e.g. America/New_York)', 'error');
      return;
    }
    if (terminalSettings && tz === (terminalSettings.timezone || '')) return;
    tzSaving = true;
    try {
      const s = await api.setTerminalTimezone(tz);
      terminalSettings = s;
      tzInput = s.timezone || '';
      showToast('Timezone saved', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
    tzSaving = false;
  }

  async function saveHomeAssistant() {
    haSaving = true;
    try {
      const payload = {
        home_assistant_url: haUrlInput.trim(),
        home_assistant_token: haTokenInput.trim() || null,
      };
      const s = await api.setHomeAssistant(payload);
      terminalSettings = s;
      haTokenInput = '';
      showToast('Home Assistant settings saved', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
    haSaving = false;
  }

  async function clearHomeAssistant() {
    if (!confirm('Clear Home Assistant URL and access token?')) return;
    haSaving = true;
    try {
      const s = await api.setHomeAssistant({ clear: true });
      terminalSettings = s;
      haUrlInput = '';
      haTokenInput = '';
      showToast('Home Assistant settings cleared', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
    haSaving = false;
  }

  async function renameTerminal(device, newName) {
    const name = (newName || '').trim();
    if (name === (device.name || '').trim()) return;
    terminalRowSaving = { ...terminalRowSaving, [device.id]: true };
    try {
      const updated = await api.updateTerminal(device.id, { name });
      terminals = terminals.map(d => d.id === updated.id ? updated : d);
      showToast('Terminal renamed', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
    terminalRowSaving = { ...terminalRowSaving, [device.id]: false };
  }

  async function setTerminalContentType(device, contentType) {
    if (contentType === device.content_type) return;
    terminalRowSaving = { ...terminalRowSaving, [device.id]: true };
    try {
      const updated = await api.updateTerminal(device.id, { content_type: contentType });
      terminals = terminals.map(d => d.id === updated.id ? updated : d);
      showToast('Content updated', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
    terminalRowSaving = { ...terminalRowSaving, [device.id]: false };
  }

  async function setTerminalRefreshInterval(device, value) {
    // value is the literal <option> value: a string of digits, or '' for "default"
    const parsed = value === '' || value === null || value === undefined ? null : parseInt(value, 10);
    if (parsed === device.refresh_interval_sec) return;
    terminalRowSaving = { ...terminalRowSaving, [device.id]: true };
    try {
      let payload;
      if (parsed === null) {
        payload = { refresh_interval_clear: true };
      } else {
        payload = { refresh_interval_sec: parsed };
      }
      const updated = await api.updateTerminal(device.id, payload);
      terminals = terminals.map(d => d.id === updated.id ? updated : d);
      showToast('Refresh rate updated', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
    terminalRowSaving = { ...terminalRowSaving, [device.id]: false };
  }

  function formatIntervalSec(sec) {
    if (!sec || sec <= 0) return '—';
    if (sec < 60) return `${sec}s`;
    if (sec < 3600) return `${Math.round(sec / 60)}m`;
    if (sec < 86400) return `${Math.round(sec / 360) / 10}h`.replace('.0h', 'h');
    return `${Math.round(sec / 8640) / 10}d`;
  }

  async function deleteTerminal(device) {
    if (!confirm(`Forget terminal "${device.name || device.mac}"? It will reappear on its next check-in.`)) return;
    try {
      await api.deleteTerminal(device.id);
      terminals = terminals.filter(d => d.id !== device.id);
      showToast('Terminal forgotten', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function setTerminalDesign(device, design) {
    const cur = (device.content_config && device.content_config.design) || 'editorial';
    if (design === cur) return;
    terminalRowSaving = { ...terminalRowSaving, [device.id]: true };
    try {
      const updated = await api.updateTerminal(device.id, {
        content_config: { ...(device.content_config || {}), design },
      });
      terminals = terminals.map(d => d.id === updated.id ? updated : d);
      showToast('Design updated', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
    terminalRowSaving = { ...terminalRowSaving, [device.id]: false };
  }

  // ── Home Assistant connection test ─────────────────────────────
  let haTesting = $state(false);
  let haTestResult = $state(null); // { ok: bool, entity_count: int, error?: string }
  async function testHomeAssistantConnection() {
    haTesting = true;
    haTestResult = null;
    try {
      haTestResult = await api.testHomeAssistant();
    } catch (err) {
      haTestResult = { ok: false, error: err.message || 'Unknown error' };
    }
    haTesting = false;
  }

  // ── E-Ink preview modal ────────────────────────────────────────
  let previewDevice = $state(null);
  let previewPaletteOverride = $state(null); // null|'six'|'bw' (null = device default)
  let previewPngBuster = $state(0);
  let previewAutoRefreshTimer = null;

  function openPreview(device) {
    previewDevice = device;
    previewPaletteOverride = null;
    previewPngBuster = Date.now();
    if (previewAutoRefreshTimer) clearInterval(previewAutoRefreshTimer);
    previewAutoRefreshTimer = setInterval(() => {
      previewPngBuster = Date.now();
    }, 30000);
  }
  function closePreview() {
    previewDevice = null;
    if (previewAutoRefreshTimer) {
      clearInterval(previewAutoRefreshTimer);
      previewAutoRefreshTimer = null;
    }
  }
  function refreshPreviewPng() {
    previewPngBuster = Date.now();
  }

  function previewPngUrl() {
    if (!previewDevice) return '';
    return api.terminalPreviewPngUrl(previewDevice.id, previewPaletteOverride, previewPngBuster);
  }

  function einkFieldsGridCols(isEink) {
    if (isEink) return 'sm:grid-cols-3';
    return 'sm:grid-cols-2';
  }
  function paletteTabBg(active) {
    if (active) return 'var(--color-accent-500)';
    return 'var(--bg-secondary)';
  }
  function paletteTabFg(active) {
    if (active) return 'white';
    return 'var(--text-secondary)';
  }

  function formatRelative(ts) {
    if (!ts) return 'never';
    const diff = (Date.now() - new Date(ts).getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
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

        <!-- API Tokens for read-only public API -->
        <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <h3 class="text-sm font-semibold mb-1" style="color: var(--text-primary)">API Tokens</h3>
          <p class="text-xs mb-4" style="color: var(--text-tertiary)">
            Create a shared-secret token to access your emails and calendar from external apps
            (e.g. an e-ink display) over the read-only <code style="color: var(--text-secondary)">/api/v1</code> JSON API.
            Use it as <code style="color: var(--text-secondary)">Authorization: Bearer &lt;token&gt;</code>.
            See <code style="color: var(--text-secondary)">docs/api.md</code> for endpoint reference.
          </p>

          {#if freshToken}
            <div class="mb-4 rounded-lg p-3" style="background: var(--status-warning-bg); border: 1px solid var(--status-warning-border); color: var(--status-warning-text)">
              <div class="flex items-start gap-2 mb-2">
                <span class="shrink-0 mt-0.5" style="color: var(--status-warning)">
                  <Icon name="alert-triangle" size={16} />
                </span>
                <div class="flex-1">
                  <div class="text-xs font-semibold mb-1">Copy your token now -- you won't be able to see it again.</div>
                  <div class="text-[11px]" style="color: var(--status-warning-text)">Token "{freshToken.name}"</div>
                </div>
              </div>
              <div class="flex gap-2 items-center">
                <input
                  type="text"
                  readonly
                  value={freshToken.token}
                  onclick={(e) => e.target.select()}
                  class="flex-1 h-8 px-3 rounded-md text-xs outline-none border font-mono"
                  style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
                />
                <Button size="sm" variant="primary" onclick={() => copyTokenToClipboard(freshToken.token)}>
                  Copy
                </Button>
                <Button size="sm" onclick={dismissFreshToken}>
                  Done
                </Button>
              </div>
            </div>
          {/if}

          <!-- Create token form -->
          <div class="flex gap-2 mb-4">
            <input
              type="text"
              bind:value={newTokenName}
              placeholder="Token name (e.g. e-ink display)"
              class="flex-1 h-9 px-3 rounded-lg text-sm outline-none border"
              style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
              onkeydown={(e) => { if (e.key === 'Enter') createApiToken(); }}
            />
            <Button variant="primary" size="sm" onclick={createApiToken} disabled={newTokenCreating || !newTokenName.trim()}>
              {newTokenCreating ? 'Creating...' : 'Create token'}
            </Button>
          </div>

          {#if !apiTokensLoaded}
            <div class="text-xs" style="color: var(--text-tertiary)">Loading...</div>
          {:else if apiTokens.length === 0}
            <div class="text-xs" style="color: var(--text-tertiary)">No tokens yet.</div>
          {:else}
            <div class="rounded-lg border overflow-hidden" style="border-color: var(--border-color)">
              <table class="w-full text-xs">
                <thead>
                  <tr style="background: var(--bg-primary); color: var(--text-tertiary)">
                    <th class="text-left font-medium px-3 py-2">Name</th>
                    <th class="text-left font-medium px-3 py-2">Prefix</th>
                    <th class="text-left font-medium px-3 py-2">Created</th>
                    <th class="text-left font-medium px-3 py-2">Last used</th>
                    <th class="text-left font-medium px-3 py-2">Status</th>
                    <th class="text-right font-medium px-3 py-2">&nbsp;</th>
                  </tr>
                </thead>
                <tbody>
                  {#each apiTokens as t (t.id)}
                    <tr style="border-top: 1px solid var(--border-color); color: var(--text-primary)">
                      <td class="px-3 py-2">{t.name || '(unnamed)'}</td>
                      <td class="px-3 py-2 font-mono" style="color: var(--text-secondary)">{t.prefix}…</td>
                      <td class="px-3 py-2" style="color: var(--text-secondary)">{new Date(t.created_at).toLocaleString()}</td>
                      <td class="px-3 py-2" style="color: var(--text-secondary)">
                        {#if t.last_used_at}
                          {new Date(t.last_used_at).toLocaleString()}
                        {:else}
                          Never
                        {/if}
                      </td>
                      <td class="px-3 py-2">
                        {#if t.revoked_at}
                          <span style="color: var(--status-error)">Revoked</span>
                        {:else}
                          <span style="color: var(--status-success, #10b981)">Active</span>
                        {/if}
                      </td>
                      <td class="px-3 py-2 text-right">
                        {#if !t.revoked_at}
                          <Button size="sm" variant="danger" onclick={() => revokeApiToken(t.id)}>
                            Revoke
                          </Button>
                        {/if}
                      </td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {/if}
        </div>

      </div>

    {:else if activeTab === 'terminals'}
      <!-- E-Ink Terminals (per-user short URL + Home Assistant settings + device cards) -->
      <div class="space-y-6">
        <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <h3 class="text-sm font-semibold mb-1" style="color: var(--text-primary)">E-Ink Terminals</h3>
          <p class="text-xs" style="color: var(--text-tertiary)">
            Point a SeeedStudio reTerminal (E1001 / E1002 / E1004) at your personal short URL below.
            All of your devices share one URL; the server identifies each panel by its MAC address.
            See <code style="color: var(--text-secondary)">docs/terminal/</code> for the firmware-side protocol.
          </p>
        </div>

        {#if !terminalSettingsLoaded}
          <div class="rounded-xl border p-5 text-xs" style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-tertiary)">Loading...</div>
        {:else if terminalSettings}
          <!-- Schedule URLs (one card per panel variant) -->
          <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
            <div class="flex items-center justify-between mb-3">
              <div>
                <h4 class="text-sm font-semibold" style="color: var(--text-primary)">Firmware schedule URLs</h4>
                <p class="text-[11px] mt-0.5" style="color: var(--text-tertiary)">Paste one of these into your reTerminal's <code>data/config.json</code> as <code>schedule_url</code>.</p>
              </div>
              <Button size="sm" onclick={regenerateTerminalCode} disabled={regenLoading}>
                {regenLoading ? 'Regenerating…' : 'Regenerate code'}
              </Button>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-2 gap-3">
              {#each terminalSettings.variants as v (v.key)}
                {@const url = terminalScheduleUrl(v.query)}
                <div class="rounded-lg border p-3" style="background: var(--bg-primary); border-color: var(--border-color)">
                  <div class="flex items-baseline justify-between gap-3 mb-1">
                    <div class="text-xs font-semibold" style="color: var(--text-primary)">{v.image_format}</div>
                    <div class="text-[11px] whitespace-nowrap" style="color: var(--text-tertiary)">{v.width}×{v.height} · wake {v.next_checkin_sec}s</div>
                  </div>
                  <div class="flex gap-2 items-stretch">
                    <code class="flex-1 px-2 py-1.5 rounded-md text-[11px] break-all border" style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-primary)">{url}</code>
                    <Button size="sm" onclick={() => copyToClipboard(url, `Copied ${v.key}`)}>
                      {copyHint === `Copied ${v.key}` ? 'Copied' : 'Copy'}
                    </Button>
                  </div>
                </div>
              {/each}
            </div>
          </div>

          <!-- Timezone -->
          <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
            <h4 class="text-sm font-semibold mb-1" style="color: var(--text-primary)">Clock timezone</h4>
            <p class="text-xs mb-3" style="color: var(--text-tertiary)">
              IANA timezone used to render the clock on every panel. Pick a preset or type any zone the server's tzdata knows
              (e.g. <code style="color: var(--text-secondary)">America/New_York</code>, <code style="color: var(--text-secondary)">Europe/Berlin</code>).
            </p>
            <div class="flex flex-wrap items-stretch gap-2">
              <input
                type="text"
                bind:value={tzInput}
                list="terminal-timezone-presets"
                placeholder="America/New_York"
                spellcheck="false"
                autocomplete="off"
                class="h-9 px-3 rounded-lg text-sm outline-none border min-w-[16rem] flex-1"
                style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
              />
              <datalist id="terminal-timezone-presets">
                {#each TIMEZONE_PRESETS as tz}
                  <option value={tz}></option>
                {/each}
              </datalist>
              <Button variant="primary" size="sm" onclick={saveTerminalTimezone} disabled={tzSaving}>
                {tzSaving ? 'Saving…' : 'Save'}
              </Button>
            </div>
            {#if terminalSettings.timezone}
              <p class="text-[11px] mt-2" style="color: var(--text-tertiary)">
                Currently rendering as <code style="color: var(--text-secondary)">{terminalSettings.timezone}</code>.
              </p>
            {/if}
          </div>

          <!-- Home Assistant -->
          <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
            <h4 class="text-sm font-semibold mb-1" style="color: var(--text-primary)">Home Assistant</h4>
            <p class="text-xs mb-4" style="color: var(--text-tertiary)">
              Optional. Future content types (calendar, sensors, dashboards) will pull from this Home Assistant instance.
              The token is stored encrypted and never returned through the API.
            </p>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
              <div>
                <label class="block text-[11px] mb-1" style="color: var(--text-tertiary)">Base URL</label>
                <input
                  type="url"
                  bind:value={haUrlInput}
                  placeholder="https://homeassistant.local:8123"
                  class="w-full h-9 px-3 rounded-lg text-sm outline-none border"
                  style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
                />
              </div>
              <div>
                <label class="block text-[11px] mb-1" style="color: var(--text-tertiary)">
                  Long-lived access token
                  {#if terminalSettings.home_assistant_token_set}
                    <span style="color: var(--status-success, #10b981)">· saved</span>
                  {/if}
                </label>
                <input
                  type="password"
                  bind:value={haTokenInput}
                  placeholder={terminalSettings.home_assistant_token_set ? '(token saved · enter new to replace)' : 'eyJ…'}
                  class="w-full h-9 px-3 rounded-lg text-sm outline-none border"
                  style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
                />
              </div>
            </div>
            <div class="flex gap-2 items-center flex-wrap">
              <Button variant="primary" size="sm" onclick={saveHomeAssistant} disabled={haSaving}>
                {haSaving ? 'Saving…' : 'Save'}
              </Button>
              <Button size="sm" onclick={testHomeAssistantConnection} disabled={haTesting || !terminalSettings.home_assistant_url || !terminalSettings.home_assistant_token_set}>
                {haTesting ? 'Testing…' : 'Test connection'}
              </Button>
              {#if terminalSettings.home_assistant_url || terminalSettings.home_assistant_token_set}
                <Button size="sm" variant="danger" onclick={clearHomeAssistant} disabled={haSaving}>Clear</Button>
              {/if}
              {#if haTestResult}
                {#if haTestResult.ok}
                  <span class="text-[11px]" style="color: var(--status-success, #10b981)">
                    Connected · {haTestResult.entity_count} entities
                  </span>
                {:else}
                  <span class="text-[11px]" style="color: var(--status-error, #ef4444)">
                    Failed: {haTestResult.error}
                  </span>
                {/if}
              {/if}
            </div>
          </div>
        {/if}

        <!-- Devices (one card per device) -->
        <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <div class="flex items-center justify-between mb-3">
            <div>
              <h4 class="text-sm font-semibold" style="color: var(--text-primary)">Checked-in devices</h4>
              <p class="text-[11px] mt-0.5" style="color: var(--text-tertiary)">Devices auto-register on their first wake. "Forget" deletes the row; the device will reappear with default settings on its next check-in.</p>
            </div>
            <Button size="sm" onclick={refreshTerminals} disabled={terminalsRefreshing}>
              {terminalsRefreshing ? 'Refreshing…' : 'Refresh'}
            </Button>
          </div>

          {#if !terminalsLoaded}
            <div class="text-xs" style="color: var(--text-tertiary)">Loading...</div>
          {:else if terminals.length === 0}
            <div class="rounded-lg border p-4 text-xs" style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-tertiary)">
              No devices have checked in yet. Configure your reTerminal firmware to point at one of the URLs above; it will register automatically on its first wake.
            </div>
          {:else}
            <div class="space-y-3">
              {#each terminals as d (d.id)}
                {@const saving = !!terminalRowSaving[d.id]}
                {@const isEink = d.content_type === 'eink_dashboard'}
                {@const designKey = (d.content_config && d.content_config.design) || 'editorial'}
                {@const fieldsGridCols = einkFieldsGridCols(isEink)}
                <div class="rounded-lg border p-4" style="background: var(--bg-primary); border-color: var(--border-color)">
                  <!-- Header: name + variant + Forget -->
                  <div class="flex items-start justify-between gap-3 mb-3">
                    <div class="flex-1 min-w-0">
                      <input
                        type="text"
                        value={d.name}
                        onblur={(e) => renameTerminal(d, e.target.value)}
                        onkeydown={(e) => { if (e.key === 'Enter') e.target.blur(); }}
                        disabled={saving}
                        placeholder="Terminal name"
                        class="w-full h-9 px-3 rounded-lg text-sm font-semibold outline-none border"
                        style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-primary)"
                      />
                      <div class="flex flex-wrap gap-x-3 gap-y-1 mt-1.5 text-[11px]" style="color: var(--text-tertiary)">
                        <span class="font-mono">{d.mac}</span>
                        <span>{d.variant || 'unknown variant'}</span>
                        <span>last seen {formatRelative(d.last_seen_at)}</span>
                        {#if d.last_wake_reason}<span>wake: {d.last_wake_reason}</span>{/if}
                      </div>
                    </div>
                    <div class="flex flex-col gap-2 shrink-0">
                      <Button size="sm" onclick={() => openPreview(d)}>
                        Preview
                      </Button>
                      <Button size="sm" variant="danger" onclick={() => deleteTerminal(d)}>
                        Forget
                      </Button>
                    </div>
                  </div>

                  <!-- Editable fields -->
                  <div class="grid grid-cols-1 {fieldsGridCols} gap-3">
                    <div>
                      <label class="block text-[11px] mb-1" style="color: var(--text-tertiary)">Content</label>
                      <select
                        value={d.content_type}
                        onchange={(e) => setTerminalContentType(d, e.target.value)}
                        disabled={saving || !terminalSettings}
                        class="w-full h-9 px-2 rounded-lg text-sm outline-none border"
                        style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-primary)"
                      >
                        {#each (terminalSettings?.content_types || []) as ct (ct.key)}
                          <option value={ct.key} disabled={!ct.available && ct.key !== d.content_type}>
                            {ct.label}
                          </option>
                        {/each}
                      </select>
                    </div>
                    {#if isEink}
                      <div>
                        <label class="block text-[11px] mb-1" style="color: var(--text-tertiary)">Design</label>
                        <select
                          value={designKey}
                          onchange={(e) => setTerminalDesign(d, e.target.value)}
                          disabled={saving || !terminalSettings}
                          class="w-full h-9 px-2 rounded-lg text-sm outline-none border"
                          style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-primary)"
                        >
                          {#each (terminalSettings?.designs || [{key:'editorial',label:'Editorial'},{key:'swiss',label:'Swiss'}]) as opt (opt.key)}
                            <option value={opt.key}>{opt.label}</option>
                          {/each}
                        </select>
                      </div>
                    {/if}
                    <div>
                      <label class="block text-[11px] mb-1" style="color: var(--text-tertiary)">
                        Refresh rate
                        <span style="color: var(--text-tertiary)">· now {formatIntervalSec(d.effective_refresh_interval_sec)}</span>
                      </label>
                      <select
                        value={d.refresh_interval_sec == null ? '' : String(d.refresh_interval_sec)}
                        onchange={(e) => setTerminalRefreshInterval(d, e.target.value)}
                        disabled={saving || !terminalSettings}
                        class="w-full h-9 px-2 rounded-lg text-sm outline-none border"
                        style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-primary)"
                      >
                        {#each (terminalSettings?.refresh_interval_presets || []) as p}
                          <option value={p.value == null ? '' : String(p.value)}>{p.label}</option>
                        {/each}
                      </select>
                    </div>
                  </div>

                  <!-- Telemetry footer -->
                  <div class="flex flex-wrap gap-x-4 gap-y-1 mt-3 pt-3 text-[11px] border-t" style="border-color: var(--border-color); color: var(--text-tertiary)">
                    <span>
                      Battery:
                      <span style="color: var(--text-secondary)">
                        {d.last_battery_pct != null ? `${d.last_battery_pct}% (${d.last_battery_mv} mV)` : '—'}
                      </span>
                    </span>
                    <span>
                      RSSI:
                      <span style="color: var(--text-secondary)">{d.last_rssi_dbm != null ? `${d.last_rssi_dbm} dBm` : '—'}</span>
                    </span>
                    <span>
                      Boots:
                      <span style="color: var(--text-secondary)">{d.last_boot_count ?? '—'}</span>
                    </span>
                    {#if d.last_fw_version}
                      <span>
                        FW:
                        <span style="color: var(--text-secondary)">{d.last_fw_version}</span>
                      </span>
                    {/if}
                  </div>
                </div>
              {/each}
            </div>
          {/if}
        </div>
      </div>

      <!-- E-Ink Preview modal -->
      {#if previewDevice}
        <div
          class="fixed inset-0 z-50 flex items-center justify-center p-4"
          style="background: rgba(0,0,0,0.55)"
          onclick={(e) => { if (e.target === e.currentTarget) closePreview(); }}
          onkeydown={(e) => { if (e.key === 'Escape') closePreview(); }}
          role="dialog"
          tabindex="-1"
        >
          <div
            class="rounded-xl border p-5 w-full max-w-[1100px] max-h-[92vh] overflow-y-auto"
            style="background: var(--bg-primary); border-color: var(--border-color)"
          >
            <div class="flex items-start justify-between gap-3 mb-4">
              <div>
                <h3 class="text-sm font-semibold" style="color: var(--text-primary)">
                  Preview · {previewDevice.name || previewDevice.mac}
                </h3>
                <p class="text-[11px] mt-0.5" style="color: var(--text-tertiary)">
                  Live HTML refreshes every 30s. The "Device view" PNG is the post-quantization image
                  the panel actually renders -- click Refresh to re-render with current HA state.
                </p>
              </div>
              <div class="flex items-center gap-2">
                <div class="flex rounded-lg border overflow-hidden text-[11px]" style="border-color: var(--border-color)">
                  {#each [
                    { id: null,  label: 'Device default' },
                    { id: 'six', label: '6-color' },
                    { id: 'bw',  label: 'B&W' },
                  ] as opt}
                    {@const active = previewPaletteOverride === opt.id}
                    <button
                      onclick={() => { previewPaletteOverride = opt.id; refreshPreviewPng(); }}
                      class="px-2.5 py-1.5"
                      style="background: {paletteTabBg(active)}; color: {paletteTabFg(active)}"
                    >
                      {opt.label}
                    </button>
                  {/each}
                </div>
                <Button size="sm" onclick={closePreview}>Close</Button>
              </div>
            </div>

            <div>
              <div class="flex items-center justify-between mb-2">
                <h4 class="text-xs font-semibold tracking-wider uppercase" style="color: var(--text-secondary)">Device view (post-quantize)</h4>
                <button
                  onclick={refreshPreviewPng}
                  class="text-[11px] underline"
                  style="color: var(--text-tertiary)"
                >Re-render</button>
              </div>
              <div
                class="rounded-lg border overflow-hidden mx-auto flex items-center justify-center"
                style="border-color: var(--border-color); width: 800px; height: 480px; background: white; max-width: 100%;"
              >
                <img
                  src={previewPngUrl()}
                  alt="Quantized panel preview"
                  style="width: 800px; height: 480px; image-rendering: pixelated; max-width: 100%;"
                />
              </div>
              <p class="text-[10px] mt-1.5 text-center" style="color: var(--text-tertiary)">Native 800 × 480 BMP — exactly what the panel will show</p>
            </div>
          </div>
        </div>
      {/if}

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
      <AIModelsPanel
        bind:aiPrefs
        allowedModels={aiPrefsAllowedModels}
        labels={aiPrefsLabels}
        saving={aiPrefsSaving}
        {reprocessing}
        onSave={saveAIPreferences}
        onReprocess={reprocessWithModel}
        {Button}
      />
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
