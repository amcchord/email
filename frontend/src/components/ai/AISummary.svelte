<script>
  let { summary = '', actionItems = [], suggestedReply = '' } = $props();
</script>

{#if summary}
  <div class="rounded-lg border p-4 space-y-3" style="background: var(--bg-tertiary); border-color: var(--border-color)">
    <div class="flex items-center gap-2">
      <span class="text-xs font-semibold tracking-wider uppercase" style="color: var(--color-accent-600)">AI Analysis</span>
    </div>

    <p class="text-sm" style="color: var(--text-primary)">{summary}</p>

    {#if actionItems.length > 0}
      <div>
        <span class="text-xs font-semibold" style="color: var(--text-secondary)">Action Items</span>
        <ul class="mt-1 space-y-1">
          {#each actionItems as item}
            <li class="text-sm flex items-start gap-2" style="color: var(--text-primary)">
              <span class="mt-1.5 w-1.5 h-1.5 rounded-full bg-accent-500 shrink-0"></span>
              {item}
            </li>
          {/each}
        </ul>
      </div>
    {/if}

    {#if suggestedReply}
      <div>
        <span class="text-xs font-semibold" style="color: var(--text-secondary)">Suggested Reply</span>
        <p class="mt-1 text-sm italic" style="color: var(--text-secondary)">"{suggestedReply}"</p>
      </div>
    {/if}
  </div>
{/if}
