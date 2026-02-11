<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { showToast } from '../lib/stores.js';
  import Button from '../components/common/Button.svelte';
  import Input from '../components/common/Input.svelte';

  let activeTab = $state('dashboard');
  let dashboard = $state(null);
  let settings = $state([]);
  let adminAccounts = $state([]);
  let loading = $state(true);

  // New setting form
  let newKey = $state('');
  let newValue = $state('');
  let newIsSecret = $state(false);
  let newDescription = $state('');

  const tabs = [
    { id: 'dashboard', label: 'Dashboard' },
    { id: 'apikeys', label: 'API Keys' },
    { id: 'accounts', label: 'Google Accounts' },
    { id: 'settings', label: 'Settings' },
  ];

  onMount(async () => {
    await loadData();
    // Check URL params for tab
    const params = new URLSearchParams(window.location.search);
    if (params.get('tab')) {
      activeTab = params.get('tab');
    }
  });

  async function loadData() {
    loading = true;
    try {
      const [dash, sets, accts] = await Promise.all([
        api.getDashboard(),
        api.getSettings(),
        api.getAdminAccounts(),
      ]);
      dashboard = dash;
      settings = sets;
      adminAccounts = accts;
    } catch (err) {
      showToast(err.message, 'error');
    }
    loading = false;
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
      await api.removeAccount(id);
      showToast('Account removed', 'success');
      adminAccounts = await api.getAdminAccounts();
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function triggerSync(accountId) {
    try {
      await api.triggerSync(accountId);
      showToast('Sync started', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  // API key form values
  let claudeKey = $state('');
  let googleClientId = $state('');
  let googleClientSecret = $state('');
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
            Enable Gmail API and set redirect URI.
          </p>
        </div>
      </div>

    {:else if activeTab === 'accounts'}
      <!-- Google Accounts -->
      <div class="space-y-4">
        <div class="flex justify-between items-center">
          <h3 class="text-sm font-semibold" style="color: var(--text-primary)">Connected Google Accounts</h3>
          <Button variant="primary" size="sm" onclick={connectGoogle}>
            Connect Account
          </Button>
        </div>

        {#if adminAccounts.length === 0}
          <div class="rounded-xl border p-8 text-center" style="background: var(--bg-secondary); border-color: var(--border-color)">
            <div class="text-4xl mb-3">📧</div>
            <p class="text-sm font-medium" style="color: var(--text-primary)">No accounts connected</p>
            <p class="text-xs mt-1" style="color: var(--text-secondary)">
              First configure Google OAuth credentials in API Keys, then connect an account.
            </p>
          </div>
        {:else}
          {#each adminAccounts as acct}
            <div class="rounded-xl border p-4 flex items-center gap-4" style="background: var(--bg-secondary); border-color: var(--border-color)">
              <div class="w-10 h-10 rounded-full bg-accent-500/20 flex items-center justify-center text-lg font-bold" style="color: var(--color-accent-600)">
                {acct.email[0].toUpperCase()}
              </div>
              <div class="flex-1 min-w-0">
                <div class="text-sm font-medium truncate" style="color: var(--text-primary)">{acct.email}</div>
                <div class="text-xs" style="color: var(--text-secondary)">
                  {#if acct.sync_status}
                    {acct.sync_status.status}
                    {#if acct.sync_status.status === 'syncing'}
                      — {acct.sync_status.messages_synced?.toLocaleString() || 0} / {acct.sync_status.total_messages?.toLocaleString() || '?'} messages
                    {:else if acct.sync_status.messages_synced}
                      — {acct.sync_status.messages_synced.toLocaleString()} messages synced
                    {/if}
                  {:else}
                    Not synced
                  {/if}
                </div>
              </div>
              <div class="flex gap-2">
                <Button size="sm" onclick={() => triggerSync(acct.id)}>
                  Sync
                </Button>
                <Button size="sm" variant="danger" onclick={() => removeAccount(acct.id)}>
                  Remove
                </Button>
              </div>
            </div>
          {/each}
        {/if}
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
