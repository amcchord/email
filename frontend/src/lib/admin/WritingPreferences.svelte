<script>
  import { onMount, tick } from 'svelte';
  import { api } from '../api.js';
  import {
    normalizeSnippet,
    normalizeSnippetList,
    rankPersonalSnippets,
    snippetEditorPayload,
    snippetHtmlToPlainText,
    validSnippetShortcut,
  } from '../personalSnippets.js';
  import {
    captureAuthenticatedSession,
    isAuthenticatedSessionCurrent,
    showToast,
  } from '../stores.js';
  import Button from '../../components/common/Button.svelte';
  import Icon from '../../components/common/Icon.svelte';
  import DeferredRichEditor from '../../components/email/DeferredRichEditor.svelte';

  let snippets = $state([]);
  let loading = $state(true);
  let loadError = $state('');
  let query = $state('');
  let editorOpen = $state(false);
  let editing = $state(null);
  let name = $state('');
  let shortcut = $state('');
  let bodyHtml = $state('');
  let bodyText = $state('');
  let initialBodyHtml = $state('');
  let editorRevision = $state(0);
  let saving = $state(false);
  let formError = $state('');
  let discardConfirm = $state(false);
  let deleteConfirm = $state(false);
  let dialog = $state(null);
  let nameInput = $state(null);
  let returnFocus = null;
  let createSnippetId = null;
  let requestGeneration = 0;

  let filtered = $derived(rankPersonalSnippets(snippets, query));
  let dirty = $derived.by(() => {
    if (!editorOpen) return false;
    const original = editing || { name: '', shortcut: '', body_html: '' };
    return name.trim() !== original.name
      || shortcut.trim().replace(/^;/, '').toLowerCase() !== original.shortcut
      || bodyHtml.trim() !== original.body_html;
  });

  function formatUpdated(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'Recently updated';
    return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(date);
  }

  async function loadSnippets() {
    const generation = ++requestGeneration;
    const session = captureAuthenticatedSession();
    loading = true;
    loadError = '';
    try {
      const response = await api.listPersonalSnippets();
      if (generation !== requestGeneration || !isAuthenticatedSessionCurrent(session)) return;
      snippets = normalizeSnippetList(response);
    } catch (error) {
      if (generation !== requestGeneration || !isAuthenticatedSessionCurrent(session)) return;
      loadError = error?.message || 'Personal snippets could not be loaded';
    } finally {
      if (generation === requestGeneration) loading = false;
    }
  }

  async function openEditor(snippet = null, event = null) {
    returnFocus = event?.currentTarget || document.activeElement;
    editing = snippet ? normalizeSnippet(snippet) : null;
    createSnippetId = editing ? null : crypto.randomUUID();
    name = editing?.name || '';
    shortcut = editing?.shortcut || '';
    bodyHtml = editing?.body_html || '';
    bodyText = editing?.body_text || '';
    initialBodyHtml = bodyHtml;
    formError = '';
    discardConfirm = false;
    deleteConfirm = false;
    editorRevision += 1;
    editorOpen = true;
    await tick();
    nameInput?.focus({ preventScroll: true });
  }

  async function closeEditor({ force = false } = {}) {
    if (!force && dirty) {
      discardConfirm = true;
      deleteConfirm = false;
      return;
    }
    editorOpen = false;
    createSnippetId = null;
    discardConfirm = false;
    deleteConfirm = false;
    await tick();
    if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true });
    returnFocus = null;
  }

  function updateBody(html) {
    bodyHtml = html;
    bodyText = snippetHtmlToPlainText(html);
  }

  function validateForm() {
    if (!name.trim()) return 'Add a descriptive snippet name.';
    if (!validSnippetShortcut(shortcut)) {
      return 'Use a shortcut of up to 32 letters, numbers, hyphens, or underscores.';
    }
    if (!bodyText.trim() || !bodyHtml.trim()) return 'Write the reusable message content.';
    return '';
  }

  async function saveSnippet() {
    if (saving) return;
    formError = validateForm();
    if (formError) return;
    const session = captureAuthenticatedSession();
    saving = true;
    try {
      const payload = snippetEditorPayload({
        snippetId: editing?.snippet_id || createSnippetId,
        name,
        shortcut,
        bodyHtml,
        bodyText,
        revision: editing?.revision,
      });
      const response = editing
        ? await api.replacePersonalSnippet(editing.snippet_id, payload)
        : await api.createPersonalSnippet(payload);
      if (!isAuthenticatedSessionCurrent(session)) return;
      const saved = normalizeSnippet(response);
      if (!saved) throw new Error('The saved snippet response is invalid');
      snippets = [...snippets.filter(item => item.snippet_id !== saved.snippet_id), saved];
      showToast(editing ? 'Snippet updated' : 'Snippet created', 'success');
      await closeEditor({ force: true });
    } catch (error) {
      if (!isAuthenticatedSessionCurrent(session)) return;
      formError = error?.message || 'The snippet could not be saved';
    } finally {
      if (isAuthenticatedSessionCurrent(session)) saving = false;
    }
  }

  async function deleteSnippet() {
    if (!editing || saving) return;
    const session = captureAuthenticatedSession();
    saving = true;
    formError = '';
    try {
      await api.deletePersonalSnippet(editing.snippet_id, editing.revision);
      if (!isAuthenticatedSessionCurrent(session)) return;
      snippets = snippets.filter(item => item.snippet_id !== editing.snippet_id);
      showToast('Snippet deleted', 'success');
      await closeEditor({ force: true });
    } catch (error) {
      if (!isAuthenticatedSessionCurrent(session)) return;
      formError = error?.message || 'The snippet could not be deleted';
      deleteConfirm = false;
    } finally {
      if (isAuthenticatedSessionCurrent(session)) saving = false;
    }
  }

  function focusableElements() {
    if (!dialog) return [];
    return [...dialog.querySelectorAll('button:not([disabled]), input:not([disabled]), [contenteditable="true"], a[href]')]
      .filter(element => !element.hidden && element.offsetParent !== null);
  }

  function handleDialogKeydown(event) {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      void closeEditor();
      return;
    }
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
      event.preventDefault();
      void saveSnippet();
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = focusableElements();
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  onMount(() => {
    void loadSnippets();
    return () => { requestGeneration += 1; };
  });
</script>

<section class="space-y-5" aria-labelledby="writing-snippets-title">
  <div class="flex flex-wrap items-start justify-between gap-3">
    <div>
      <h2 id="writing-snippets-title" class="text-lg font-semibold" style="color: var(--text-primary)">Personal snippets</h2>
      <p class="mt-1 max-w-2xl text-sm" style="color: var(--text-secondary)">
        Save polished replies and insert them from any message with <kbd class="rounded border px-1.5 py-0.5 text-xs" style="border-color: var(--border-color)">⌘;</kbd> or <kbd class="rounded border px-1.5 py-0.5 text-xs" style="border-color: var(--border-color)">Ctrl+;</kbd>.
      </p>
    </div>
    <Button variant="primary" class="min-h-11" onclick={(event) => openEditor(null, event)}>
      <Icon name="plus" size={16} /> New snippet
    </Button>
  </div>

  <div class="flex min-h-11 items-center gap-2 rounded-xl border px-3" style="border-color: var(--border-color); background: var(--bg-secondary)">
    <Icon name="search" size={16} />
    <label class="sr-only" for="writing-snippet-search">Search snippets</label>
    <input id="writing-snippet-search" bind:value={query} class="min-w-0 flex-1 bg-transparent text-sm outline-none" style="color: var(--text-primary)" placeholder="Search name, shortcut, or content" />
  </div>

  {#if loading}
    <div class="flex min-h-48 items-center justify-center gap-2 rounded-xl border text-sm" style="border-color: var(--border-color); color: var(--text-secondary)" role="status">
      <span class="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
      Loading personal snippets…
    </div>
  {:else if loadError}
    <div class="flex min-h-48 flex-col items-center justify-center gap-3 rounded-xl border px-5 text-center" style="border-color: var(--border-color)" role="alert">
      <Icon name="alert-circle" size={24} />
      <p class="text-sm" style="color: var(--status-error)">{loadError}</p>
      <Button class="min-h-11" onclick={loadSnippets}>Retry</Button>
    </div>
  {:else if filtered.length === 0}
    <div class="flex min-h-52 flex-col items-center justify-center gap-3 rounded-xl border px-6 text-center" style="border-color: var(--border-color); background: var(--bg-secondary)">
      <span class="flex h-12 w-12 items-center justify-center rounded-2xl" style="background: var(--bg-tertiary); color: var(--color-accent-600)"><Icon name="file-text" size={24} /></span>
      <div>
        <p class="text-sm font-semibold" style="color: var(--text-primary)">{snippets.length ? 'No snippets match' : 'Write it once, reuse it anywhere'}</p>
        <p class="mt-1 text-xs" style="color: var(--text-tertiary)">{snippets.length ? 'Try another search.' : 'Create a reusable reply, introduction, follow-up, or handoff.'}</p>
      </div>
      {#if !snippets.length}<Button variant="primary" class="min-h-11" onclick={(event) => openEditor(null, event)}>Create your first snippet</Button>{/if}
    </div>
  {:else}
    <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {#each filtered as snippet (snippet.snippet_id)}
        <button
          type="button"
          class="snippet-card min-h-32 rounded-xl border p-4 text-left transition-fast"
          style="border-color: var(--border-color); background: var(--bg-secondary)"
          onclick={(event) => openEditor(snippet, event)}
          aria-label="Edit snippet {snippet.name}"
        >
          <span class="flex items-start justify-between gap-3">
            <span class="min-w-0">
              <span class="block truncate text-sm font-semibold" style="color: var(--text-primary)">{snippet.name}</span>
              <span class="mt-1 inline-flex rounded-md px-2 py-1 font-mono text-[11px]" style="background: var(--bg-tertiary); color: var(--color-accent-700)">;{snippet.shortcut}</span>
            </span>
            <span class="shrink-0 text-[11px]" style="color: var(--text-tertiary)">{formatUpdated(snippet.updated_at)}</span>
          </span>
          <span class="mt-3 line-clamp-2 block text-xs leading-relaxed" style="color: var(--text-secondary)">{snippet.body_text}</span>
        </button>
      {/each}
    </div>
  {/if}
</section>

{#if editorOpen}
  <div class="writing-layer fixed inset-0 z-[75] flex items-center justify-center p-4" role="presentation">
    <button type="button" class="absolute inset-0 bg-black/45" aria-label="Close snippet editor" onclick={() => closeEditor()}></button>
    <div
      bind:this={dialog}
      class="writing-dialog relative flex max-h-[92dvh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border shadow-2xl"
      style="background: var(--bg-primary); border-color: var(--border-color)"
      role="dialog"
      tabindex="-1"
      aria-modal="true"
      aria-labelledby="writing-editor-title"
      onkeydown={handleDialogKeydown}
    >
      <header class="flex items-center justify-between gap-3 border-b px-5 py-4" style="border-color: var(--border-color)">
        <div>
          <h2 id="writing-editor-title" class="text-base font-semibold" style="color: var(--text-primary)">{editing ? 'Edit snippet' : 'New snippet'}</h2>
          <p class="text-xs" style="color: var(--text-tertiary)">Private to your account · ⌘/Ctrl+Enter saves</p>
        </div>
        <button type="button" class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg" aria-label="Close snippet editor" onclick={() => closeEditor()}><Icon name="x" size={19} /></button>
      </header>

      <div class="min-h-0 flex-1 overflow-y-auto p-5">
        <div class="grid gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(12rem,0.6fr)]">
          <label class="space-y-1.5 text-sm">
            <span class="font-semibold" style="color: var(--text-primary)">Name</span>
            <input bind:this={nameInput} bind:value={name} maxlength="120" class="min-h-11 w-full rounded-lg border px-3 outline-none focus:ring-2 focus:ring-accent-500/40" style="border-color: var(--border-color); background: var(--bg-secondary); color: var(--text-primary)" placeholder="Friendly follow-up" />
          </label>
          <label class="space-y-1.5 text-sm">
            <span class="font-semibold" style="color: var(--text-primary)">Shortcut</span>
            <span class="flex min-h-11 items-center rounded-lg border px-3" style="border-color: var(--border-color); background: var(--bg-secondary)">
              <span class="font-mono" style="color: var(--text-tertiary)">;</span>
              <input bind:value={shortcut} maxlength="32" class="min-h-11 min-w-0 flex-1 bg-transparent font-mono outline-none" style="color: var(--text-primary)" placeholder="followup" aria-describedby="snippet-shortcut-help" />
            </span>
            <span id="snippet-shortcut-help" class="block text-[11px]" style="color: var(--text-tertiary)">Letters, numbers, hyphens, and underscores</span>
          </label>
        </div>

        <div class="mt-5 space-y-1.5">
          <span class="text-sm font-semibold" style="color: var(--text-primary)">Reusable message</span>
          <div class="overflow-hidden rounded-xl border" style="border-color: var(--border-color)">
            {#key editorRevision}
              <DeferredRichEditor
                content={initialBodyHtml}
                onUpdate={updateBody}
                placeholder="Write the message you want to reuse…"
                ariaLabel="Snippet message"
                surface="snippet-editor"
              />
            {/key}
          </div>
        </div>

        {#if formError}
          <p class="mt-4 rounded-lg border px-3 py-2 text-sm" style="border-color: var(--status-error); color: var(--status-error)" role="alert">{formError}</p>
        {/if}
      </div>

      <footer class="border-t px-5 py-3" style="border-color: var(--border-color); background: var(--bg-secondary)">
        {#if discardConfirm}
          <div class="flex flex-wrap items-center justify-between gap-3" role="alert">
            <p class="text-sm font-medium" style="color: var(--text-primary)">Discard your unsaved changes?</p>
            <div class="flex gap-2">
              <Button class="min-h-11" onclick={() => { discardConfirm = false; }}>Keep editing</Button>
              <Button variant="danger" class="min-h-11" onclick={() => closeEditor({ force: true })}>Discard changes</Button>
            </div>
          </div>
        {:else if deleteConfirm}
          <div class="flex flex-wrap items-center justify-between gap-3" role="alert">
            <p class="text-sm font-medium" style="color: var(--text-primary)">Delete “{editing?.name}”? Existing drafts will keep their inserted text.</p>
            <div class="flex gap-2">
              <Button class="min-h-11" onclick={() => { deleteConfirm = false; }}>Cancel</Button>
              <Button variant="danger" class="min-h-11" disabled={saving} onclick={deleteSnippet}>{saving ? 'Deleting…' : 'Delete snippet'}</Button>
            </div>
          </div>
        {:else}
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div>{#if editing}<Button variant="danger" class="min-h-11" disabled={saving} onclick={() => { deleteConfirm = true; }}>Delete</Button>{/if}</div>
            <div class="flex gap-2">
              <Button class="min-h-11" disabled={saving} onclick={() => closeEditor()}>Cancel</Button>
              <Button variant="primary" class="min-h-11" disabled={saving} onclick={saveSnippet}>{saving ? 'Saving…' : 'Save snippet'}</Button>
            </div>
          </div>
        {/if}
      </footer>
    </div>
  </div>
{/if}

<style>
  .snippet-card:hover,
  .snippet-card:focus-visible {
    border-color: var(--color-accent-400) !important;
    box-shadow: 0 10px 26px color-mix(in srgb, var(--text-primary) 8%, transparent);
  }

  @media (max-width: 767px) {
    .writing-layer {
      align-items: flex-end;
      padding: 0;
    }

    .writing-dialog {
      max-height: 94dvh;
      border-radius: 1.25rem 1.25rem 0 0;
      border-bottom: 0;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .animate-spin { animation: none; }
  }
</style>
