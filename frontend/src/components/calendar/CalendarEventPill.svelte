<script>
  import { accountColorMap } from '../../lib/stores.js';

  let { event, color = null, showTime = false, compact = false, onclick = null, mergedAccounts = null } = $props();

  let timeStr = $derived.by(() => {
    if (event.is_all_day) return '';
    if (!event.start_time) return '';
    const d = new Date(event.start_time);
    let h = d.getHours();
    const m = d.getMinutes();
    const ampm = h >= 12 ? 'p' : 'a';
    h = h % 12 || 12;
    return m > 0 ? `${h}:${m.toString().padStart(2, '0')}${ampm}` : `${h}${ampm}`;
  });

  let accounts = $derived(mergedAccounts || event._mergedAccounts || null);
  let hasMerged = $derived(accounts && accounts.length > 1);

  let bgColor = $derived(color ? color.bg : 'var(--color-accent-500)');
  let lightColor = $derived(color ? color.light : 'var(--color-accent-100)');
</script>

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<div
  class="rounded px-1.5 truncate cursor-pointer transition-opacity hover:opacity-80 flex items-center gap-1"
  class:py-0.5={!compact}
  class:text-xs={!compact}
  class:text-[10px]={compact}
  class:leading-tight={compact}
  style="background: {lightColor}; color: {bgColor}"
  onclick={onclick}
  title={event.summary || '(No title)'}
>
  {#if hasMerged}
    <div class="flex flex-col gap-px shrink-0">
      {#each accounts as acctEmail}
        {@const acctColor = $accountColorMap[acctEmail]}
        <span class="w-1.5 h-1.5 rounded-full" style="background: {acctColor ? acctColor.bg : 'var(--color-accent-500)'}"></span>
      {/each}
    </div>
  {:else}
    <span class="w-0.5 self-stretch rounded-full shrink-0" style="background: {bgColor}"></span>
  {/if}
  <span class="truncate">
    {#if showTime && timeStr}
      <span class="font-medium">{timeStr}</span>
      {' '}
    {/if}
    {event.summary || '(No title)'}
  </span>
</div>
