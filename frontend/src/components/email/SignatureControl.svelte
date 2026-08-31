<script>
  import Icon from '../common/Icon.svelte';
  import {
    effectiveSignatureSnapshot,
    signatureDefaultIncluded,
  } from '../../lib/accountSignatures.js';
  import { sanitizeComposeHtml } from '../../lib/sanitize.js';

  let {
    initialized = false,
    mode = 'default',
    compositionKind = 'new',
    policy = null,
    snapshot = null,
    disabled = false,
    compact = false,
    onchange = null,
  } = $props();

  let effective = $derived(effectiveSignatureSnapshot({
    initialized,
    mode,
    compositionKind,
    policy,
    snapshot,
  }));
  let canRestore = $derived(
    initialized
    && mode === 'disabled'
    && Boolean(policy?.body_html || policy?.body_text),
  );
  let defaultIncluded = $derived(signatureDefaultIncluded(policy, compositionKind));
  let previewHtml = $derived(sanitizeComposeHtml(effective?.body_html || ''));
</script>

{#if initialized && policy}
  <section
    class="signature-control rounded-lg border {compact ? 'px-3 py-2' : 'px-4 py-3'}"
    style="border-color: var(--border-subtle); background: var(--bg-secondary)"
    data-signature-control=""
    aria-label="Message signature"
  >
    {#if effective}
      <div class="flex items-start justify-between gap-3">
        <div class="min-w-0 flex-1">
          <p class="mb-1 text-[10px] font-semibold uppercase tracking-wide" style="color: var(--text-tertiary)">
            Signature{mode === 'default' ? ' · Account default' : ''}
          </p>
          {#if previewHtml}
            <div class="signature-preview break-words text-sm" style="color: var(--text-secondary)">
              {@html previewHtml}
            </div>
          {:else}
            <p class="whitespace-pre-wrap text-sm" style="color: var(--text-secondary)">{effective.body_text}</p>
          {/if}
        </div>
        <button
          type="button"
          class="inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-md px-2 text-xs font-semibold hover:opacity-75 disabled:opacity-50"
          style="color: var(--text-secondary)"
          {disabled}
          onclick={() => onchange?.('disabled')}
          aria-label="Remove signature from this message"
        >
          <Icon name="x" size={13} />
          Remove
        </button>
      </div>
    {:else if canRestore}
      <div class="flex min-h-11 items-center justify-between gap-3">
        <p class="text-xs" style="color: var(--text-tertiary)">Signature removed from this message</p>
        <button
          type="button"
          class="inline-flex min-h-11 items-center gap-1.5 rounded-md px-2 text-xs font-semibold hover:opacity-75 disabled:opacity-50"
          style="color: var(--color-accent-700)"
          {disabled}
          onclick={() => onchange?.('enabled')}
          aria-label="Restore the account signature"
        >
          <Icon name="rotate-ccw" size={13} />
          Restore
        </button>
      </div>
    {:else if mode === 'default' && !defaultIncluded}
      <p class="text-[11px]" style="color: var(--text-tertiary)">Account signature is off for this message type.</p>
    {/if}
  </section>
{/if}
