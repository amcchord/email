<script>
  import { onMount } from 'svelte';
  import { api } from '../api.js';
  import {
    browserFollowUpTimeZone,
    followUpDelayChoices,
    followUpPolicyIsDirty,
    followUpPolicyPayload,
    followUpPolicySummary,
    normalizeFollowUpPolicy,
    normalizeFollowUpPolicyList,
    validateFollowUpPolicy,
  } from '../followUpReminders.js';
  import {
    captureAuthenticatedSession,
    isAuthenticatedSessionCurrent,
    showToast,
  } from '../stores.js';
  import Button from '../../components/common/Button.svelte';
  import Icon from '../../components/common/Icon.svelte';

  let policies = $state([]);
  let drafts = $state({});
  let loading = $state(true);
  let loadError = $state('');
  let saving = $state({});
  let saveErrors = $state({});
  let saveMessages = $state({});
  let conflicts = $state({});
  let loadGeneration = 0;
  let mounted = true;
  const saveGenerations = new Map();
  const browserTimeZone = browserFollowUpTimeZone();

  function keyFor(accountId) {
    return String(accountId);
  }

  function draftFor(policy) {
    return drafts[keyFor(policy.account_id)] || policy;
  }

  function replacePolicies(nextPolicies) {
    policies = nextPolicies;
    drafts = Object.fromEntries(nextPolicies.map(policy => [keyFor(policy.account_id), { ...policy }]));
    saving = {};
    saveErrors = {};
    saveMessages = {};
    conflicts = {};
  }

  function updateDraft(policy, changes) {
    const key = keyFor(policy.account_id);
    drafts = {
      ...drafts,
      [key]: { ...draftFor(policy), ...changes },
    };
    if (!conflicts[key]) saveErrors = { ...saveErrors, [key]: '' };
    saveMessages = { ...saveMessages, [key]: '' };
  }

  function dirty(policy) {
    return followUpPolicyIsDirty(policy, draftFor(policy));
  }

  async function loadPolicies() {
    const generation = ++loadGeneration;
    const session = captureAuthenticatedSession();
    loading = true;
    loadError = '';
    try {
      const response = await api.listFollowUpPolicies();
      if (!mounted || generation !== loadGeneration || !isAuthenticatedSessionCurrent(session)) return;
      const normalized = normalizeFollowUpPolicyList(response, { browserTimeZone });
      replacePolicies(normalized.accounts);
    } catch (error) {
      if (!mounted || generation !== loadGeneration || !isAuthenticatedSessionCurrent(session)) return;
      loadError = error?.message || 'Automatic follow-up preferences could not be loaded.';
    } finally {
      if (mounted && generation === loadGeneration && isAuthenticatedSessionCurrent(session)) loading = false;
    }
  }

  function revisionConflict(error) {
    const code = String(error?.code || error?.detail?.code || '').toLowerCase();
    return error?.status === 409 || code.includes('conflict') || code.includes('revision');
  }

  async function savePolicy(policy) {
    const key = keyFor(policy.account_id);
    if (saving[key] || !dirty(policy)) return;
    const draft = draftFor(policy);
    const validationError = validateFollowUpPolicy(draft);
    if (validationError) {
      saveErrors = { ...saveErrors, [key]: validationError };
      return;
    }

    const generation = (saveGenerations.get(key) || 0) + 1;
    saveGenerations.set(key, generation);
    const session = captureAuthenticatedSession();
    saving = { ...saving, [key]: true };
    saveErrors = { ...saveErrors, [key]: '' };
    saveMessages = { ...saveMessages, [key]: '' };
    conflicts = { ...conflicts, [key]: false };

    try {
      const payload = followUpPolicyPayload(draft);
      const response = await api.replaceFollowUpPolicy(policy.account_id, payload);
      if (!mounted || saveGenerations.get(key) !== generation || !isAuthenticatedSessionCurrent(session)) return;
      const saved = normalizeFollowUpPolicy(response, { browserTimeZone });
      if (!saved || saved.account_id !== policy.account_id) {
        throw new Error('The saved automatic follow-up preference response is invalid.');
      }
      policies = policies.map(item => item.account_id === saved.account_id ? saved : item);
      drafts = { ...drafts, [key]: { ...saved } };
      saveMessages = { ...saveMessages, [key]: 'Changes saved.' };
      showToast(`Follow-up preferences saved for ${saved.account_email}`, 'success');
    } catch (error) {
      if (!mounted || saveGenerations.get(key) !== generation || !isAuthenticatedSessionCurrent(session)) return;
      if (revisionConflict(error)) {
        conflicts = { ...conflicts, [key]: true };
        saveErrors = {
          ...saveErrors,
          [key]: 'These preferences changed elsewhere. Reload the latest version before saving again.',
        };
      } else {
        saveErrors = {
          ...saveErrors,
          [key]: error?.message || 'These automatic follow-up preferences could not be saved.',
        };
      }
    } finally {
      if (mounted && saveGenerations.get(key) === generation && isAuthenticatedSessionCurrent(session)) {
        saving = { ...saving, [key]: false };
      }
    }
  }

  onMount(() => {
    void loadPolicies();
    return () => {
      mounted = false;
      loadGeneration += 1;
      for (const [key, generation] of saveGenerations) saveGenerations.set(key, generation + 1);
    };
  });
</script>

<section class="space-y-5" aria-labelledby="automatic-follow-up-title">
  <div>
    <h2 id="automatic-follow-up-title" class="text-lg font-semibold" style="color: var(--text-primary)">Automatic follow-up reminders</h2>
    <p class="mt-1 max-w-3xl text-sm leading-relaxed" style="color: var(--text-secondary)">
      After your provider confirms delivery, messages to people other than your connected addresses return only if nobody replies. This uses no tracking pixels or read receipts.
    </p>
  </div>

  {#if loading}
    <div class="flex min-h-36 items-center justify-center gap-2 rounded-xl border text-sm" style="border-color: var(--border-color); color: var(--text-secondary)" role="status">
      <span class="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
      Loading automatic follow-up preferences…
    </div>
  {:else if loadError}
    <div class="flex min-h-36 flex-col items-center justify-center gap-3 rounded-xl border px-5 text-center" style="border-color: var(--border-color)" role="alert">
      <Icon name="alert-circle" size={24} />
      <p class="text-sm" style="color: var(--status-error)">{loadError}</p>
      <Button class="min-h-11" onclick={loadPolicies}>Retry</Button>
    </div>
  {:else if policies.length === 0}
    <div class="flex min-h-36 flex-col items-center justify-center gap-2 rounded-xl border px-5 text-center" style="border-color: var(--border-color); background: var(--bg-secondary)">
      <Icon name="mail" size={24} />
      <p class="text-sm font-semibold" style="color: var(--text-primary)">No connected mail accounts</p>
      <p class="text-xs" style="color: var(--text-tertiary)">Connect an account before setting automatic follow-up reminders.</p>
    </div>
  {:else}
    <div class="grid gap-4">
      {#each policies as policy (policy.account_id)}
        {@const draft = draftFor(policy)}
        {@const key = keyFor(policy.account_id)}
        {@const isSaving = Boolean(saving[key])}
        {@const isDirty = dirty(policy)}
        {@const delayOptions = followUpDelayChoices(draft.delay_days)}
        <article class="rounded-2xl border p-4 sm:p-5" style="border-color: var(--border-color); background: var(--bg-secondary)" aria-labelledby="follow-up-account-{policy.account_id}">
          <div class="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div class="min-w-0">
              <h3 id="follow-up-account-{policy.account_id}" class="truncate text-sm font-semibold" style="color: var(--text-primary)">{policy.account_email}</h3>
              <p class="mt-1 text-xs" style="color: var(--text-tertiary)">{followUpPolicySummary(draft)}</p>
            </div>
            <div class="flex min-h-11 items-center justify-between gap-3 sm:justify-end">
              <span id="follow-up-switch-label-{policy.account_id}" class="text-sm font-medium" style="color: var(--text-primary)">Automatic follow-up reminders</span>
              <button
                type="button"
                class="relative inline-flex min-h-11 min-w-14 shrink-0 items-center rounded-full p-1 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500 disabled:cursor-not-allowed disabled:opacity-50"
                style="background: {draft.enabled ? 'var(--color-accent-600)' : 'var(--bg-tertiary)'}"
                role="switch"
                aria-checked={draft.enabled}
                aria-labelledby="follow-up-switch-label-{policy.account_id} follow-up-account-{policy.account_id}"
                disabled={isSaving}
                onclick={() => updateDraft(policy, { enabled: !draft.enabled })}
              >
                <span class="h-6 w-6 rounded-full bg-white shadow transition-transform {draft.enabled ? 'translate-x-5' : 'translate-x-0'}"></span>
              </button>
            </div>
          </div>

          {#if draft.enabled}
            <div class="mt-5 grid gap-4 border-t pt-5 sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(11rem,0.8fr)]" style="border-color: var(--border-color)">
              <label class="space-y-1.5 text-sm" for="follow-up-delay-{policy.account_id}">
                <span class="block font-semibold" style="color: var(--text-primary)">Wait</span>
                <select
                  id="follow-up-delay-{policy.account_id}"
                  class="min-h-11 w-full rounded-lg border px-3 outline-none focus:ring-2 focus:ring-accent-500/40"
                  style="border-color: var(--border-color); background: var(--bg-primary); color: var(--text-primary)"
                  value={draft.delay_days}
                  disabled={isSaving}
                  onchange={(event) => updateDraft(policy, { delay_days: Number(event.currentTarget.value) })}
                >
                  {#each delayOptions as days}
                    <option value={days}>{days} {days === 1 ? 'day' : 'days'}</option>
                  {/each}
                </select>
              </label>

              <label class="space-y-1.5 text-sm" for="follow-up-time-{policy.account_id}">
                <span class="block font-semibold" style="color: var(--text-primary)">Local time</span>
                <input
                  id="follow-up-time-{policy.account_id}"
                  type="time"
                  class="min-h-11 w-full rounded-lg border px-3 outline-none focus:ring-2 focus:ring-accent-500/40"
                  style="border-color: var(--border-color); background: var(--bg-primary); color: var(--text-primary)"
                  value={draft.wake_local_time}
                  disabled={isSaving}
                  oninput={(event) => updateDraft(policy, { wake_local_time: event.currentTarget.value })}
                />
                <span class="block break-all text-[11px]" style="color: var(--text-tertiary)">Time zone: {draft.time_zone}</span>
                {#if draft.time_zone !== browserTimeZone}
                  <button
                    type="button"
                    class="min-h-11 rounded-lg px-2 text-left text-xs font-semibold hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500 disabled:cursor-not-allowed disabled:opacity-50"
                    style="color: var(--color-accent-600)"
                    disabled={isSaving}
                    onclick={() => updateDraft(policy, { time_zone: browserTimeZone })}
                  >
                    Use current time zone ({browserTimeZone})
                  </button>
                {/if}
              </label>

              <div class="space-y-1.5 text-sm">
                <span class="block font-semibold" style="color: var(--text-primary)">Reminder days</span>
                <div class="flex min-h-11 items-center justify-between gap-3 rounded-lg border px-3" style="border-color: var(--border-color); background: var(--bg-primary)">
                  <span id="follow-up-weekdays-label-{policy.account_id}" class="text-sm" style="color: var(--text-primary)">Weekdays only</span>
                  <button
                    type="button"
                    class="relative inline-flex min-h-11 min-w-14 shrink-0 items-center rounded-full p-1 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500 disabled:cursor-not-allowed disabled:opacity-50"
                    style="background: {draft.weekdays_only ? 'var(--color-accent-600)' : 'var(--bg-tertiary)'}"
                    role="switch"
                    aria-checked={draft.weekdays_only}
                    aria-labelledby="follow-up-weekdays-label-{policy.account_id} follow-up-account-{policy.account_id}"
                    disabled={isSaving}
                    onclick={() => updateDraft(policy, { weekdays_only: !draft.weekdays_only })}
                  >
                    <span class="h-6 w-6 rounded-full bg-white shadow transition-transform {draft.weekdays_only ? 'translate-x-5' : 'translate-x-0'}"></span>
                  </button>
                </div>
              </div>
            </div>
          {/if}

          {#if saveErrors[key]}
            <div class="mt-4 flex flex-col items-start gap-2 rounded-lg border px-3 py-2 sm:flex-row sm:items-center sm:justify-between" style="border-color: var(--status-error)" role="alert">
              <p class="text-sm" style="color: var(--status-error)">{saveErrors[key]}</p>
              {#if conflicts[key]}
                <Button class="min-h-11 shrink-0" disabled={isSaving} onclick={loadPolicies}>Reload latest</Button>
              {/if}
            </div>
          {:else if saveMessages[key]}
            <p class="mt-4 text-sm" style="color: var(--text-secondary)" role="status">{saveMessages[key]}</p>
          {/if}

          <div class="mt-5 flex flex-col gap-2 border-t pt-4 sm:flex-row sm:items-center sm:justify-between" style="border-color: var(--border-color)">
            <p class="text-xs" style="color: var(--text-tertiary)">
              {isDirty
                ? 'Unsaved changes'
                : policy.revision === 0
                  ? 'Default preference · not saved yet'
                  : `Saved preference · revision ${policy.revision}`}
            </p>
            <Button variant="primary" class="min-h-11 w-full sm:w-auto" disabled={!isDirty || isSaving || Boolean(conflicts[key])} onclick={() => savePolicy(policy)}>
              {isSaving ? 'Saving…' : 'Save changes'}
            </Button>
          </div>
        </article>
      {/each}
    </div>
  {/if}
</section>

<style>
  @media (prefers-reduced-motion: reduce) {
    .animate-spin { animation: none; }
  }
</style>
