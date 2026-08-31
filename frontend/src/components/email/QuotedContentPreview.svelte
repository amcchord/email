<script>
  import { sanitizeComposeHtml } from '../../lib/sanitize.js';

  let { html = '', text = '', label = 'Forwarded message' } = $props();
  let safeHtml = $derived(sanitizeComposeHtml(String(html || '')));
</script>

{#if safeHtml || text}
  <details class="quoted-content-preview rounded-lg border px-4 py-3" style="border-color: var(--border-subtle); background: var(--bg-secondary)" data-quoted-content="">
    <summary class="min-h-11 cursor-pointer select-none py-3 text-xs font-semibold" style="color: var(--text-secondary)">{label}</summary>
    <div class="border-t pt-3 text-sm" style="border-color: var(--border-subtle); color: var(--text-secondary)">
      {#if safeHtml}
        {@html safeHtml}
      {:else}
        <p class="whitespace-pre-wrap">{text}</p>
      {/if}
    </div>
</details>
{/if}
