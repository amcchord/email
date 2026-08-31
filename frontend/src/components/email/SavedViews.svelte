<script>
  import { onMount, tick } from 'svelte';
  import { api } from '../../lib/api.js';
  import {
    accounts,
    activeSavedViewId,
    createAuthenticatedSessionGuard,
    currentMailbox,
    savedViewEditorRequest,
    savedViewFocusRequest,
    savedViews,
    savedViewsError,
    savedViewsLoaded,
    savedViewsLoading,
    savedViewsMax,
    searchQuery,
    selectedAccountId,
    smartFilter,
  } from '../../lib/stores.js';
  import {
    createSavedViewPayload,
    isSavableStructuredSearch,
    normalizeSavedView,
    normalizeSavedViewsResponse,
    reorderSavedViewsPayload,
    replaceSavedViewPayload,
    savedViewMatches,
  } from '../../lib/savedViews.js';
  import { openSavedView, refreshSavedViews, requestSavedViewEditor } from '../../lib/savedViewState.js';
  import Icon from '../common/Icon.svelte';

  let { showSection = true } = $props();

  let expanded = $state(true);
  let dialogOpen = $state(false);
  let mode = $state('create');
  let editingId = $state(null);
  let draftName = $state('');
  let draftAccount = $state('');
  let draftQuery = $state('');
  let createId = $state('');
  let saving = $state(false);
  let deleting = $state(false);
  let confirmingDelete = $state(false);
  let dialogError = $state('');
  let dialogStatus = $state('');
  let nameInput = $state(null);
  let dialogEl = $state(null);
  let sectionButton = $state(null);
  let returnFocus = null;
  let lastRequestId = null;
  let lastFocusRequest = 0;

  let editingView = $derived($savedViews.find(view => view.id === editingId) || null);
  let canCreate = $derived(isSavableStructuredSearch($searchQuery) && $savedViews.length < $savedViewsMax);

  function isActive(view) {
    return $activeSavedViewId === view.id
      && $currentMailbox === 'ALL'
      && !$smartFilter
      && savedViewMatches(view, $selectedAccountId, $searchQuery);
  }

  function accountLabel(accountId) {
    if (accountId === null) return 'All accounts';
    return $accounts.find(account => account.id === accountId)?.email || 'Unavailable account';
  }

  function accountAvailable(accountId) {
    return accountId === null || $accounts.some(account => account.id === accountId);
  }

  function captureFocus() {
    returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  }

  async function openEditor(request = {}) {
    const view = request.view_id ? $savedViews.find(item => item.id === request.view_id) : null;
    captureFocus();
    mode = view ? 'edit' : 'create';
    editingId = view?.id || null;
    draftName = view?.name || '';
    const requestedAccount = Object.hasOwn(request, 'account_id') ? request.account_id : view?.account_id;
    const requestedQuery = Object.hasOwn(request, 'query') ? request.query : view?.query;
    draftAccount = requestedAccount === null || requestedAccount === undefined ? '' : String(requestedAccount);
    draftQuery = String(requestedQuery ?? $searchQuery);
    createId = view ? '' : crypto.randomUUID();
    saving = false;
    deleting = false;
    confirmingDelete = false;
    dialogError = '';
    dialogStatus = '';
    dialogOpen = true;
    await tick();
    nameInput?.focus();
  }

  function closeEditor() {
    if (saving || deleting) return;
    dialogOpen = false;
    savedViewEditorRequest.set(null);
    const target = returnFocus;
    returnFocus = null;
    void tick().then(() => target?.isConnected ? target.focus() : sectionButton?.focus());
  }

  function replaceLocalView(view) {
    savedViews.update(items => {
      const next = items.filter(item => item.id !== view.id);
      next.push(view);
      return next.sort((a, b) => a.position - b.position);
    });
  }

  function assertKnownAccount(view) {
    if (view.account_id !== null && !$accounts.some(account => account.id === view.account_id)) {
      throw new Error('The server returned a Saved View for an unavailable account.');
    }
    return view;
  }

  async function saveView() {
    if (saving) return;
    saving = true;
    dialogError = '';
    dialogStatus = '';
    const session = createAuthenticatedSessionGuard();
    try {
      const accountId = draftAccount === '' ? null : Number(draftAccount);
      let normalized;
      if (editingView) {
        const payload = replaceSavedViewPayload({
          revision: editingView.revision,
          name: draftName,
          accountId,
          query: draftQuery,
        });
        normalized = assertKnownAccount(normalizeSavedView(await api.replaceSavedView(editingView.id, payload)));
        if (normalized.id !== editingView.id) throw new Error('The server returned the wrong Saved View.');
      } else {
        const payload = createSavedViewPayload({ createId, name: draftName, accountId, query: draftQuery });
        normalized = assertKnownAccount(normalizeSavedView(await api.createSavedView(payload)));
        if (normalized.create_id !== createId.toLowerCase()) throw new Error('The server returned the wrong Saved View.');
      }
      if (!session.isCurrent()) return;
      replaceLocalView(normalized);
      openSavedView(normalized);
      dialogStatus = editingView ? 'Saved View updated.' : 'Saved View created.';
      saving = false;
      closeEditor();
    } catch (error) {
      if (!session.isCurrent()) return;
      if (error?.status === 409 || error?.status === 412) {
        dialogError = 'This Saved View changed elsewhere. Reload before trying again.';
      } else {
        dialogError = error?.message || 'The Saved View could not be saved.';
      }
    } finally {
      if (session.isCurrent()) saving = false;
      session.dispose();
    }
  }

  async function removeView() {
    if (!editingView || deleting) return;
    if (!confirmingDelete) {
      confirmingDelete = true;
      dialogStatus = 'Press Delete again to permanently remove this Saved View.';
      return;
    }
    deleting = true;
    dialogError = '';
    const session = createAuthenticatedSessionGuard();
    try {
      await api.deleteSavedView(editingView.id, editingView.revision);
      if (!session.isCurrent()) return;
      savedViews.update(items => items.filter(item => item.id !== editingView.id));
      if ($activeSavedViewId === editingView.id) activeSavedViewId.set(null);
      deleting = false;
      closeEditor();
    } catch (error) {
      if (session.isCurrent()) {
        dialogError = error?.status === 409 || error?.status === 412
          ? 'This Saved View changed elsewhere. Reload before deleting it.'
          : (error?.message || 'The Saved View could not be deleted.');
      }
    } finally {
      if (session.isCurrent()) deleting = false;
      session.dispose();
    }
  }

  async function moveView(view, delta) {
    const index = $savedViews.findIndex(item => item.id === view.id);
    const nextIndex = index + delta;
    if (index < 0 || nextIndex < 0 || nextIndex >= $savedViews.length || saving) return;
    const desired = $savedViews.map(item => item.id);
    [desired[index], desired[nextIndex]] = [desired[nextIndex], desired[index]];
    saving = true;
    dialogError = '';
    const session = createAuthenticatedSessionGuard();
    try {
      const response = normalizeSavedViewsResponse(await api.reorderSavedViews(
        reorderSavedViewsPayload($savedViews, desired),
      ));
      if (!session.isCurrent()) return;
      savedViews.set([...response.items]);
    } catch (error) {
      if (session.isCurrent()) {
        dialogError = error?.status === 409 || error?.status === 412
          ? 'Saved View order changed elsewhere. Reload before reordering.'
          : (error?.message || 'Saved Views could not be reordered.');
      }
    } finally {
      if (session.isCurrent()) saving = false;
      session.dispose();
    }
  }

  function focusableElements() {
    return dialogEl
      ? [...dialogEl.querySelectorAll('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])')]
      : [];
  }

  function handleDialogKeydown(event) {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeEditor();
      return;
    }
    if (event.key !== 'Tab') return;
    const elements = focusableElements();
    if (!elements.length) return;
    const index = elements.indexOf(document.activeElement);
    const next = event.shiftKey
      ? (index <= 0 ? elements.length - 1 : index - 1)
      : (index === elements.length - 1 ? 0 : index + 1);
    event.preventDefault();
    elements[next].focus();
  }

  $effect(() => {
    const request = $savedViewEditorRequest;
    if (!request?.request_id || request.request_id === lastRequestId) return;
    lastRequestId = request.request_id;
    void openEditor(request);
  });

  $effect(() => {
    const request = $savedViewFocusRequest;
    if (!request || request === lastFocusRequest) return;
    lastFocusRequest = request;
    expanded = true;
    void tick().then(() => sectionButton?.focus());
  });

  onMount(() => {
    if (!$savedViewsLoaded && !$savedViewsLoading) void refreshSavedViews();
  });
</script>

{#if showSection}
<section class="saved-views-section mt-4" aria-labelledby="saved-views-heading">
  <div class="flex min-h-11 items-center gap-1">
    <button
      bind:this={sectionButton}
      data-saved-views-focus
      class="flex min-h-11 min-w-0 flex-1 items-center gap-2 rounded-md px-3 text-left"
      onclick={() => expanded = !expanded}
      aria-expanded={expanded}
      aria-controls="saved-views-list"
    >
      <Icon name="chevron-right" size={12} class="transition-transform duration-200 {expanded ? 'rotate-90' : ''}" />
      <span id="saved-views-heading" class="truncate text-[11px] font-semibold uppercase tracking-wider" style="color: var(--text-tertiary)">Saved Views</span>
      <span class="ml-auto text-[10px]" style="color: var(--text-tertiary)">{$savedViews.length}/{$savedViewsMax}</span>
    </button>
    <button
      class="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md"
      style="color: var(--text-secondary)"
      onclick={() => requestSavedViewEditor({ mode: 'create' })}
      disabled={!canCreate}
      aria-label={canCreate ? 'Save current search as a view' : 'Open a valid search to save a view'}
      title={canCreate ? 'Save current search' : 'Open a valid search first'}
    ><Icon name="plus" size={16} /></button>
  </div>

  {#if expanded}
    <div id="saved-views-list" class="space-y-0.5" aria-live="polite">
      {#if $savedViewsLoading}
        <p class="min-h-11 px-3 py-3 text-xs" style="color: var(--text-tertiary)">Loading Saved Views…</p>
      {:else if $savedViewsError}
        <div class="rounded-md px-3 py-2 text-xs" role="alert" style="color: var(--status-error)">
          <p>Saved Views unavailable.</p>
          <button class="mt-1 min-h-11 font-semibold underline" onclick={() => refreshSavedViews()}>Retry</button>
        </div>
      {:else if $savedViews.length === 0}
        <p class="px-3 py-2 text-xs leading-5" style="color: var(--text-tertiary)">Run a structured search, then save it here.</p>
      {:else}
        {#each $savedViews as view, index (view.id)}
          <div class="group flex min-h-11 items-center rounded-md" style="background: {isActive(view) ? 'var(--bg-hover)' : 'transparent'}">
            <button
              class="flex min-h-11 min-w-0 flex-1 items-center gap-2 px-3 text-left text-sm"
              class:font-semibold={isActive(view)}
              aria-current={isActive(view) ? 'page' : undefined}
              title={`${view.name} · ${accountLabel(view.account_id)}`}
              disabled={!accountAvailable(view.account_id)}
              onclick={() => openSavedView(view)}
            >
              <Icon name="bookmark" size={15} class="shrink-0" />
              <span class="min-w-0 flex-1 truncate">{view.name}</span>
            </button>
            <button class="h-11 w-11 shrink-0 rounded-md opacity-70 hover:opacity-100 focus:opacity-100" aria-label={`Manage ${view.name}`} onclick={() => requestSavedViewEditor({ mode: 'edit', viewId: view.id })}>
              <Icon name="more-horizontal" size={16} />
            </button>
          </div>
        {/each}
      {/if}
    </div>
  {/if}
</section>
{/if}

{#if dialogOpen}
  <div class="saved-view-layer">
    <button class="saved-view-backdrop" onclick={closeEditor} aria-label="Close Saved View editor"></button>
    <div class="saved-view-dialog" role="dialog" aria-modal="true" aria-labelledby="saved-view-dialog-title" tabindex="-1" bind:this={dialogEl} onkeydown={handleDialogKeydown}>
      <header class="flex items-start gap-3 border-b p-4" style="border-color: var(--border-color)">
        <div class="min-w-0 flex-1">
          <h2 id="saved-view-dialog-title" class="text-base font-semibold" style="color: var(--text-primary)">{editingView ? 'Manage Saved View' : 'Save current search'}</h2>
          <p class="mt-1 text-xs" style="color: var(--text-tertiary)">Changes are saved only when you press {editingView ? 'Save changes' : 'Create view'}.</p>
        </div>
        <button class="flex h-11 w-11 items-center justify-center rounded-lg" onclick={closeEditor} aria-label="Close"><Icon name="x" size={18} /></button>
      </header>

      <form class="space-y-4 overflow-y-auto p-4" onsubmit={(event) => { event.preventDefault(); void saveView(); }}>
        {#if dialogError}
          <div class="rounded-lg p-3 text-sm" role="alert" style="color: var(--status-error); background: color-mix(in srgb, var(--status-error) 9%, transparent)">
            <p>{dialogError}</p>
            {#if dialogError.includes('Reload')}
              <button type="button" class="mt-2 min-h-11 font-semibold underline" onclick={() => refreshSavedViews()}>Reload Saved Views</button>
            {/if}
          </div>
        {/if}
        {#if dialogStatus}<p class="text-sm" role="status" style="color: var(--text-secondary)">{dialogStatus}</p>{/if}

        <label class="block text-sm font-medium" style="color: var(--text-primary)">
          Name
          <input bind:this={nameInput} bind:value={draftName} maxlength="80" autocomplete="off" required class="mt-1 min-h-11 w-full rounded-lg border px-3" style="border-color: var(--border-color); background: var(--bg-primary)" />
        </label>
        <label class="block text-sm font-medium" style="color: var(--text-primary)">
          Account
          <select bind:value={draftAccount} class="mt-1 min-h-11 w-full rounded-lg border px-3" style="border-color: var(--border-color); background: var(--bg-primary)">
            <option value="">All accounts</option>
            {#each $accounts as account (account.id)}
              <option value={String(account.id)}>{account.email}</option>
            {/each}
          </select>
        </label>
        <label class="block text-sm font-medium" style="color: var(--text-primary)">
          Structured search
          <textarea bind:value={draftQuery} maxlength="512" rows="3" required spellcheck="false" class="mt-1 min-h-24 w-full resize-y rounded-lg border p-3 font-mono text-sm" style="border-color: var(--border-color); background: var(--bg-primary)"></textarea>
        </label>

        {#if editingView}
          <div class="border-t pt-3" style="border-color: var(--border-color)">
            <p class="mb-2 text-xs font-semibold uppercase tracking-wide" style="color: var(--text-tertiary)">Order</p>
            <div class="flex gap-2">
              <button type="button" class="min-h-11 flex-1 rounded-lg border px-3 text-sm" disabled={$savedViews[0]?.id === editingView.id || saving} onclick={() => moveView(editingView, -1)}><Icon name="arrow-up" size={15} /> Move up</button>
              <button type="button" class="min-h-11 flex-1 rounded-lg border px-3 text-sm" disabled={$savedViews[$savedViews.length - 1]?.id === editingView.id || saving} onclick={() => moveView(editingView, 1)}><Icon name="arrow-down" size={15} /> Move down</button>
            </div>
          </div>
        {/if}

        <footer class="flex flex-wrap items-center gap-2 border-t pt-4" style="border-color: var(--border-color)">
          {#if editingView}
            <button type="button" class="min-h-11 rounded-lg px-3 text-sm font-semibold" style="color: var(--status-error)" disabled={saving || deleting} onclick={() => void removeView()}>
              {deleting ? 'Deleting…' : confirmingDelete ? 'Delete permanently' : 'Delete'}
            </button>
          {/if}
          <div class="ml-auto flex gap-2">
            <button type="button" class="min-h-11 rounded-lg px-4 text-sm font-semibold" onclick={closeEditor}>Cancel</button>
            <button type="submit" class="min-h-11 rounded-lg bg-accent-600 px-4 text-sm font-semibold text-white" disabled={saving || deleting}>
              {saving ? 'Saving…' : editingView ? 'Save changes' : 'Create view'}
            </button>
          </div>
        </footer>
      </form>
    </div>
  </div>
{/if}

<style>
  button:disabled { cursor: not-allowed; opacity: 0.45; }
  .saved-view-layer { position: fixed; inset: 0; z-index: 10030; display: flex; align-items: center; justify-content: center; padding: 1rem; }
  .saved-view-backdrop { position: absolute; inset: 0; border: 0; background: rgb(15 23 42 / 0.5); backdrop-filter: blur(3px); }
  .saved-view-dialog { position: relative; z-index: 1; display: flex; width: min(34rem, 100%); max-height: calc(100vh - 2rem); flex-direction: column; overflow: hidden; border: 1px solid var(--border-color); border-radius: 1rem; background: var(--bg-elevated); box-shadow: 0 24px 70px rgb(15 23 42 / 0.32); }
  .saved-view-dialog button { display: inline-flex; align-items: center; justify-content: center; gap: 0.4rem; }
  @media (max-width: 767px) {
    .saved-view-layer { align-items: flex-end; padding: 0; }
    .saved-view-dialog { width: 100%; max-height: calc(100dvh - 1rem); border-radius: 1rem 1rem 0 0; }
  }
</style>
