<script>
  import { onMount, tick } from 'svelte';
  import { api } from '../api.js';
  import {
    accountSignatureIsDirty,
    accountSignaturePayload,
    accountSignatureSummary,
    normalizeAccountSignature,
    normalizeAccountSignatureList,
    signatureHtmlToPlainText,
    validateAccountSignature,
  } from '../accountSignatures.js';
  import { sanitizeComposeHtml } from '../sanitize.js';
  import {
    captureAuthenticatedSession,
    isAuthenticatedSessionCurrent,
    showToast,
  } from '../stores.js';
  import Button from '../../components/common/Button.svelte';
  import Icon from '../../components/common/Icon.svelte';
  import DeferredRichEditor from '../../components/email/DeferredRichEditor.svelte';

  const normalizeOptions = { sanitizeHtml: sanitizeComposeHtml };

  let signatures = $state([]);
  let loading = $state(true);
  let loadError = $state('');
  let editorOpen = $state(false);
  let editing = $state(null);
  let enabled = $state(false);
  let includeOnNew = $state(true);
  let includeOnReplies = $state(true);
  let includeOnForwards = $state(true);
  let bodyHtml = $state('');
  let bodyText = $state('');
  let initialBodyHtml = $state('');
  let editorRevision = $state(0);
  let saving = $state(false);
  let reloading = $state(false);
  let formError = $state('');
  let formMessage = $state('');
  let conflict = $state(false);
  let discardConfirm = $state(false);
  let dialog = $state(null);
  let firstControl = $state(null);
  let returnFocus = null;
  let loadGeneration = 0;
  let editorGeneration = 0;
  let mounted = true;

  function signatureDraft() {
    return {
      ...editing,
      enabled,
      include_on_new: includeOnNew,
      include_on_replies: includeOnReplies,
      include_on_forwards: includeOnForwards,
      body_html: bodyHtml,
      body_text: bodyText,
    };
  }

  let dirty = $derived.by(() => (
    editing ? accountSignatureIsDirty(editing, signatureDraft(), normalizeOptions) : false
  ));

  function setForm(policy) {
    editing = policy;
    enabled = policy.enabled;
    includeOnNew = policy.include_on_new;
    includeOnReplies = policy.include_on_replies;
    includeOnForwards = policy.include_on_forwards;
    bodyHtml = policy.body_html;
    bodyText = policy.body_text;
    initialBodyHtml = policy.body_html;
    editorRevision += 1;
  }

  function updateBody(html) {
    bodyHtml = sanitizeComposeHtml(String(html || '')).trim();
    bodyText = signatureHtmlToPlainText(bodyHtml);
    formError = conflict ? formError : '';
    formMessage = '';
  }

  function updateSetting(callback) {
    callback();
    if (!conflict) formError = '';
    formMessage = '';
  }

  async function loadSignatures() {
    const generation = ++loadGeneration;
    const session = captureAuthenticatedSession();
    loading = true;
    loadError = '';
    try {
      const response = await api.listAccountSignatures();
      if (!mounted || generation !== loadGeneration || !isAuthenticatedSessionCurrent(session)) return;
      signatures = normalizeAccountSignatureList(response, normalizeOptions).accounts;
    } catch (error) {
      if (!mounted || generation !== loadGeneration || !isAuthenticatedSessionCurrent(session)) return;
      loadError = error?.message || 'Account signatures could not be loaded.';
    } finally {
      if (mounted && generation === loadGeneration && isAuthenticatedSessionCurrent(session)) loading = false;
    }
  }

  async function openEditor(policy, event) {
    const normalized = normalizeAccountSignature(policy, normalizeOptions);
    if (!normalized) return;
    editorGeneration += 1;
    returnFocus = event?.currentTarget || document.activeElement;
    setForm(normalized);
    saving = false;
    reloading = false;
    formError = '';
    formMessage = '';
    conflict = false;
    discardConfirm = false;
    editorOpen = true;
    await tick();
    firstControl?.focus({ preventScroll: true });
  }

  async function closeEditor({ force = false } = {}) {
    if (saving || reloading) return;
    if (!force && dirty) {
      discardConfirm = true;
      return;
    }
    editorGeneration += 1;
    editorOpen = false;
    editing = null;
    conflict = false;
    discardConfirm = false;
    formError = '';
    formMessage = '';
    await tick();
    if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true });
    returnFocus = null;
  }

  function isRevisionConflict(error) {
    const code = String(error?.code || error?.detail?.code || '').toLowerCase();
    return error?.status === 409 || code.includes('conflict') || code.includes('revision');
  }

  async function saveSignature() {
    if (!editing || saving || reloading || conflict || !dirty) return;
    const submitted = signatureDraft();
    formError = validateAccountSignature(submitted, normalizeOptions);
    formMessage = '';
    if (formError) return;

    const generation = editorGeneration;
    const session = captureAuthenticatedSession();
    saving = true;
    try {
      const payload = accountSignaturePayload(submitted, normalizeOptions);
      const response = await api.replaceAccountSignature(editing.account_id, payload);
      if (
        !mounted
        || !editorOpen
        || generation !== editorGeneration
        || !isAuthenticatedSessionCurrent(session)
      ) return;
      const saved = normalizeAccountSignature(response, normalizeOptions);
      if (!saved || saved.account_id !== submitted.account_id) {
        throw new Error('The saved account signature response is invalid.');
      }
      signatures = signatures.map(item => item.account_id === saved.account_id ? saved : item);
      const changedWhileSaving = accountSignatureIsDirty(submitted, signatureDraft(), normalizeOptions);
      if (changedWhileSaving) {
        editing = saved;
        formMessage = 'Earlier changes were saved. Review and save your newer edits.';
        saving = false;
      } else {
        setForm(saved);
        showToast(`Signature saved for ${saved.account_email}`, 'success');
        saving = false;
        await closeEditor({ force: true });
      }
    } catch (error) {
      if (
        !mounted
        || generation !== editorGeneration
        || !isAuthenticatedSessionCurrent(session)
      ) return;
      if (isRevisionConflict(error)) {
        conflict = true;
        formError = 'This signature changed elsewhere. Reload the latest version before saving again.';
      } else {
        formError = error?.message || 'This account signature could not be saved.';
      }
    } finally {
      if (mounted && generation === editorGeneration && isAuthenticatedSessionCurrent(session)) {
        saving = false;
      }
    }
  }

  async function reloadLatest() {
    if (!editing || reloading) return;
    const accountId = editing.account_id;
    const generation = editorGeneration;
    const session = captureAuthenticatedSession();
    reloading = true;
    formMessage = '';
    try {
      const response = await api.listAccountSignatures();
      if (
        !mounted
        || !editorOpen
        || generation !== editorGeneration
        || !isAuthenticatedSessionCurrent(session)
      ) return;
      const normalized = normalizeAccountSignatureList(response, normalizeOptions).accounts;
      const latest = normalized.find(item => item.account_id === accountId);
      if (!latest) throw new Error('This connected account is no longer available.');
      signatures = normalized;
      setForm(latest);
      conflict = false;
      formError = '';
      formMessage = 'Latest version loaded. Review it before making more changes.';
      await tick();
      firstControl?.focus({ preventScroll: true });
    } catch (error) {
      if (
        mounted
        && generation === editorGeneration
        && isAuthenticatedSessionCurrent(session)
      ) formError = error?.message || 'The latest signature could not be loaded.';
    } finally {
      if (mounted && generation === editorGeneration && isAuthenticatedSessionCurrent(session)) {
        reloading = false;
      }
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
      event.stopPropagation();
      void saveSignature();
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
    void loadSignatures();
    return () => {
      mounted = false;
      loadGeneration += 1;
      editorGeneration += 1;
    };
  });
</script>

<section class="space-y-5" aria-labelledby="account-signatures-title">
  <div>
    <h2 id="account-signatures-title" class="text-lg font-semibold" style="color: var(--text-primary)">Account signatures</h2>
    <p class="mt-1 max-w-3xl text-sm leading-relaxed" style="color: var(--text-secondary)">
      Keep a separate signature for each connected address and choose where it is added. New signatures are off until you explicitly save and enable them.
    </p>
  </div>

  {#if loading}
    <div class="flex min-h-36 items-center justify-center gap-2 rounded-xl border text-sm" style="border-color: var(--border-color); color: var(--text-secondary)" role="status">
      <span class="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
      Loading account signatures…
    </div>
  {:else if loadError}
    <div class="flex min-h-36 flex-col items-center justify-center gap-3 rounded-xl border px-5 text-center" style="border-color: var(--border-color)" role="alert">
      <Icon name="alert-circle" size={24} />
      <p class="text-sm" style="color: var(--status-error)">{loadError}</p>
      <Button class="min-h-11" onclick={loadSignatures}>Retry</Button>
    </div>
  {:else if signatures.length === 0}
    <div class="flex min-h-36 flex-col items-center justify-center gap-2 rounded-xl border px-5 text-center" style="border-color: var(--border-color); background: var(--bg-secondary)">
      <Icon name="edit-3" size={24} />
      <p class="text-sm font-semibold" style="color: var(--text-primary)">No connected mail accounts</p>
      <p class="text-xs" style="color: var(--text-tertiary)">Connect an account before creating an email signature.</p>
    </div>
  {:else}
    <div class="grid gap-4 md:grid-cols-2">
      {#each signatures as signature (signature.account_id)}
        <article class="flex min-h-48 flex-col rounded-2xl border p-4 sm:p-5" style="border-color: var(--border-color); background: var(--bg-secondary)" aria-labelledby="signature-account-{signature.account_id}">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <h3 id="signature-account-{signature.account_id}" class="truncate text-sm font-semibold" style="color: var(--text-primary)">{signature.account_email}</h3>
              <p class="mt-1 text-xs" style="color: var(--text-tertiary)">{accountSignatureSummary(signature)}</p>
            </div>
            <span class="shrink-0 rounded-full px-2 py-1 text-[11px] font-semibold" style="background: var(--bg-tertiary); color: {signature.enabled ? 'var(--color-accent-700)' : 'var(--text-tertiary)'}">
              {signature.enabled ? 'Enabled' : 'Off'}
            </span>
          </div>
          <p class="mt-4 line-clamp-3 flex-1 whitespace-pre-line text-xs leading-relaxed" style="color: var(--text-secondary)">
            {signature.body_text || 'No signature content yet.'}
          </p>
          <div class="mt-4 flex flex-col gap-2 border-t pt-4 sm:flex-row sm:items-center sm:justify-between" style="border-color: var(--border-color)">
            <span class="text-[11px]" style="color: var(--text-tertiary)">
              {signature.revision === 0 ? 'Default · not saved yet' : `Revision ${signature.revision}`}
            </span>
            <Button class="min-h-11 w-full sm:w-auto" onclick={(event) => openEditor(signature, event)}>Edit signature</Button>
          </div>
        </article>
      {/each}
    </div>
  {/if}
</section>

{#if editorOpen && editing}
  <div class="signature-layer fixed inset-0 z-[75] flex items-center justify-center p-4" role="presentation">
    <button type="button" class="absolute inset-0 bg-black/45" aria-label="Close signature editor" onclick={() => closeEditor()}></button>
    <div
      bind:this={dialog}
      class="signature-dialog relative flex max-h-[92dvh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border shadow-2xl"
      style="background: var(--bg-primary); border-color: var(--border-color)"
      role="dialog"
      tabindex="-1"
      aria-modal="true"
      aria-labelledby="signature-editor-title"
      onkeydown={handleDialogKeydown}
    >
      <header class="flex items-center justify-between gap-3 border-b px-5 py-4" style="border-color: var(--border-color)">
        <div class="min-w-0">
          <h2 id="signature-editor-title" class="text-base font-semibold" style="color: var(--text-primary)">Edit account signature</h2>
          <p class="truncate text-xs" style="color: var(--text-tertiary)">{editing.account_email} · ⌘/Ctrl+Enter saves</p>
        </div>
        <button type="button" class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg" aria-label="Close signature editor" onclick={() => closeEditor()}><Icon name="x" size={19} /></button>
      </header>

      <div class="min-h-0 flex-1 overflow-y-auto p-5">
        <div class="flex min-h-14 items-center justify-between gap-4 rounded-xl border px-4" style="border-color: var(--border-color); background: var(--bg-secondary)">
          <div>
            <span id="signature-enabled-label" class="block text-sm font-semibold" style="color: var(--text-primary)">Enable this signature</span>
            <span class="block text-xs" style="color: var(--text-tertiary)">Content stays saved while the signature is off.</span>
          </div>
          <button
            bind:this={firstControl}
            type="button"
            class="relative inline-flex min-h-11 min-w-14 shrink-0 items-center rounded-full p-1 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500 disabled:cursor-not-allowed disabled:opacity-50"
            style="background: {enabled ? 'var(--color-accent-600)' : 'var(--bg-tertiary)'}"
            role="switch"
            aria-checked={enabled}
            aria-labelledby="signature-enabled-label signature-editor-title"
            disabled={saving || reloading || conflict}
            onclick={() => updateSetting(() => { enabled = !enabled; })}
          >
            <span class="h-6 w-6 rounded-full bg-white shadow transition-transform {enabled ? 'translate-x-5' : 'translate-x-0'}"></span>
          </button>
        </div>

        <fieldset class="mt-5">
          <legend class="text-sm font-semibold" style="color: var(--text-primary)">Automatically include on</legend>
          <div class="mt-2 grid gap-2 sm:grid-cols-3">
            {#each [
              { id: 'new', label: 'New messages', value: includeOnNew, update: () => { includeOnNew = !includeOnNew; } },
              { id: 'replies', label: 'Replies', value: includeOnReplies, update: () => { includeOnReplies = !includeOnReplies; } },
              { id: 'forwards', label: 'Forwards', value: includeOnForwards, update: () => { includeOnForwards = !includeOnForwards; } },
            ] as option (option.id)}
              <div class="flex min-h-14 items-center justify-between gap-3 rounded-xl border px-3" style="border-color: var(--border-color); background: var(--bg-secondary)">
                <span id="signature-context-{option.id}" class="text-sm" style="color: var(--text-primary)">{option.label}</span>
                <button
                  type="button"
                  class="relative inline-flex min-h-11 min-w-14 shrink-0 items-center rounded-full p-1 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500 disabled:cursor-not-allowed disabled:opacity-50"
                  style="background: {option.value ? 'var(--color-accent-600)' : 'var(--bg-tertiary)'}"
                  role="switch"
                  aria-checked={option.value}
                  aria-labelledby="signature-context-{option.id} signature-editor-title"
                  disabled={saving || reloading || conflict}
                  onclick={() => updateSetting(option.update)}
                >
                  <span class="h-6 w-6 rounded-full bg-white shadow transition-transform {option.value ? 'translate-x-5' : 'translate-x-0'}"></span>
                </button>
              </div>
            {/each}
          </div>
        </fieldset>

        <div class="mt-5 space-y-1.5">
          <span class="text-sm font-semibold" style="color: var(--text-primary)">Signature content</span>
          <p class="text-xs" style="color: var(--text-tertiary)">Remote images and active content are removed. A plain-text fallback is saved with the rich signature.</p>
          <div
            class:pointer-events-none={saving || reloading || conflict}
            class:opacity-60={saving || reloading || conflict}
            class="overflow-hidden rounded-xl border"
            style="border-color: var(--border-color)"
            inert={saving || reloading || conflict}
            aria-disabled={saving || reloading || conflict}
          >
            {#key editorRevision}
              <DeferredRichEditor
                content={initialBodyHtml}
                onUpdate={updateBody}
                placeholder="Name, role, phone number, or a short sign-off…"
                ariaLabel="Account signature content"
                surface="signature-editor"
              />
            {/key}
          </div>
        </div>

        {#if formError}
          <div class="mt-4 flex flex-col items-start gap-2 rounded-lg border px-3 py-2 sm:flex-row sm:items-center sm:justify-between" style="border-color: var(--status-error)" role="alert">
            <p class="text-sm" style="color: var(--status-error)">{formError}</p>
            {#if conflict}
              <Button class="min-h-11 shrink-0" disabled={reloading} onclick={reloadLatest}>{reloading ? 'Reloading…' : 'Reload latest'}</Button>
            {/if}
          </div>
        {:else if formMessage}
          <p class="mt-4 rounded-lg border px-3 py-2 text-sm" style="border-color: var(--border-color); color: var(--text-secondary)" role="status">{formMessage}</p>
        {/if}
      </div>

      <footer class="border-t px-5 py-3" style="border-color: var(--border-color); background: var(--bg-secondary)">
        {#if discardConfirm}
          <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between" role="alert">
            <p class="text-sm font-medium" style="color: var(--text-primary)">Discard your unsaved signature changes?</p>
            <div class="flex flex-col-reverse gap-2 sm:flex-row">
              <Button class="min-h-11" onclick={() => { discardConfirm = false; }}>Keep editing</Button>
              <Button variant="danger" class="min-h-11" onclick={() => closeEditor({ force: true })}>Discard changes</Button>
            </div>
          </div>
        {:else}
          <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p class="text-xs" style="color: var(--text-tertiary)">
              {dirty
                ? 'Unsaved changes'
                : editing.revision === 0
                  ? 'Default signature · not saved yet'
                  : `Saved signature · revision ${editing.revision}`}
            </p>
            <div class="flex flex-col-reverse gap-2 sm:flex-row">
              <Button class="min-h-11" disabled={saving || reloading} onclick={() => closeEditor()}>Cancel</Button>
              <Button variant="primary" class="min-h-11" disabled={!dirty || saving || reloading || conflict} onclick={saveSignature}>{saving ? 'Saving…' : 'Save changes'}</Button>
            </div>
          </div>
        {/if}
      </footer>
    </div>
  </div>
{/if}

<style>
  @media (max-width: 767px) {
    .signature-layer {
      align-items: flex-end;
      padding: 0;
    }

    .signature-dialog {
      max-height: 94dvh;
      border-radius: 1.25rem 1.25rem 0 0;
      border-bottom: 0;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .animate-spin { animation: none; }
  }
</style>
