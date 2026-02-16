<script>
  import { accountColorMap } from '../../lib/stores.js';
  import { mergeEvents, layoutEvents } from '../../lib/calendarLayout.js';
  import { onMount } from 'svelte';

  let { events = [], currentDate = new Date(), onEventClick = null } = $props();

  const HOURS = Array.from({ length: 24 }, (_, i) => i);

  function dateStr(date) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  }

  let allDayEvents = $derived(
    events.filter(e => {
      if (!e.is_all_day) return false;
      const ds = dateStr(currentDate);
      return e.start_date <= ds && e.end_date > ds;
    })
  );

  let timedEvents = $derived(
    events.filter(e => {
      if (e.is_all_day || !e.start_time) return false;
      const eventDate = new Date(e.start_time);
      return eventDate.getFullYear() === currentDate.getFullYear() &&
        eventDate.getMonth() === currentDate.getMonth() &&
        eventDate.getDate() === currentDate.getDate();
    })
  );

  const PX_PER_HOUR = 60;

  let mergedTimedEvents = $derived(mergeEvents(timedEvents));
  let mergedAllDayEvents = $derived(mergeEvents(allDayEvents));
  let layoutItems = $derived(layoutEvents(mergedTimedEvents, PX_PER_HOUR));

  function formatEventTime(event) {
    if (!event.start_time) return '';
    const start = new Date(event.start_time);
    const end = event.end_time ? new Date(event.end_time) : null;
    const fmtTime = (d) => d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
    return end ? `${fmtTime(start)} - ${fmtTime(end)}` : fmtTime(start);
  }

  function formatHour(h) {
    if (h === 0) return '12 AM';
    if (h < 12) return `${h} AM`;
    if (h === 12) return '12 PM';
    return `${h - 12} PM`;
  }

  let currentTimeTop = $state(0);
  let isCurrentDay = $derived.by(() => {
    const now = new Date();
    return currentDate.getDate() === now.getDate() &&
      currentDate.getMonth() === now.getMonth() &&
      currentDate.getFullYear() === now.getFullYear();
  });

  function updateCurrentTime() {
    const now = new Date();
    currentTimeTop = (now.getHours() * 60 + now.getMinutes()) / 60 * 60;
  }

  let scrollContainer = $state(null);

  onMount(() => {
    updateCurrentTime();
    const interval = setInterval(updateCurrentTime, 60000);
    if (scrollContainer) {
      scrollContainer.scrollTop = 8 * 60 - 20;
    }
    return () => clearInterval(interval);
  });
</script>

<div class="flex flex-col h-full overflow-hidden">
  <!-- Date header -->
  <div class="py-3 px-4 border-b shrink-0" style="border-color: var(--border-color)">
    <div class="text-lg font-semibold" style="color: {isCurrentDay ? 'var(--color-accent-500)' : 'var(--text-primary)'}">
      {currentDate.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
    </div>
  </div>

  <!-- All-day events -->
  {#if mergedAllDayEvents.length > 0}
    <div class="px-4 py-2 border-b space-y-1 shrink-0" style="border-color: var(--border-color)">
      <div class="text-[10px] font-semibold uppercase tracking-wider mb-1" style="color: var(--text-tertiary)">All Day</div>
      {#each mergedAllDayEvents as event}
        {@const color = $accountColorMap[event.account_email]}
        <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
        <div
          class="rounded px-2 py-1 text-sm cursor-pointer transition-opacity hover:opacity-80 flex items-center gap-1.5"
          style="background: {color ? color.light : 'var(--bg-tertiary)'}; color: {color ? color.bg : 'var(--text-primary)'}"
          onclick={() => onEventClick?.(event)}
        >
          {#if event._mergedAccounts && event._mergedAccounts.length > 1}
            <div class="flex flex-col gap-0.5 shrink-0">
              {#each event._mergedAccounts as acctEmail}
                {@const acctColor = $accountColorMap[acctEmail]}
                <span class="w-2 h-2 rounded-full" style="background: {acctColor ? acctColor.bg : 'var(--color-accent-500)'}"></span>
              {/each}
            </div>
          {:else}
            <span class="w-1 self-stretch rounded-full shrink-0" style="background: {color ? color.bg : 'var(--color-accent-500)'}"></span>
          {/if}
          {event.summary || '(No title)'}
        </div>
      {/each}
    </div>
  {/if}

  <!-- Time grid -->
  <div class="flex-1 overflow-y-auto" bind:this={scrollContainer}>
    <div class="grid relative" style="grid-template-columns: 64px 1fr">
      <!-- Hour labels -->
      <div>
        {#each HOURS as h}
          <div class="flex items-start justify-end pr-3 -translate-y-2" style="height: 60px">
            <span class="text-xs" style="color: var(--text-tertiary)">{formatHour(h)}</span>
          </div>
        {/each}
      </div>

      <!-- Event column -->
      <div class="relative border-l" style="border-color: var(--border-color); height: {24 * 60}px">
        <!-- Hour lines -->
        {#each HOURS as h}
          <div
            class="absolute w-full border-t"
            style="top: {h * 60}px; border-color: var(--border-color)"
          ></div>
        {/each}

        <!-- Current time indicator -->
        {#if isCurrentDay}
          <div
            class="absolute w-full z-20 pointer-events-none"
            style="top: {currentTimeTop}px"
          >
            <div class="flex items-center">
              <div class="w-2.5 h-2.5 rounded-full bg-red-500 -ml-1"></div>
              <div class="flex-1 h-0.5 bg-red-500"></div>
            </div>
          </div>
        {/if}

        <!-- Events -->
        {#each layoutItems as item}
          {@const color = $accountColorMap[item.event.account_email]}
          <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
          {#if item.isBackground}
            <div
              class="absolute px-3 py-1.5 overflow-hidden cursor-pointer pointer-events-auto"
              style="top: {item.top}px; height: {item.height}px; left: {item.left}; width: {item.width}; background: {color ? color.light : 'var(--bg-tertiary)'}; opacity: 0.3; z-index: {item.zIndex}; border-left: 4px solid {color ? color.bg : 'var(--color-accent-500)'}"
              onclick={() => onEventClick?.(item.event)}
            >
              <div class="text-sm font-medium leading-tight truncate" style="color: {color ? color.bg : 'var(--text-primary)'}">{item.event.summary || '(No title)'}</div>
            </div>
          {:else}
            <div
              class="absolute rounded-lg px-3 py-1.5 overflow-hidden cursor-pointer transition-opacity hover:opacity-80 hover:!z-40"
              style="top: {item.top}px; height: {item.height}px; left: {item.left}; width: {item.width}; z-index: {item.zIndex}; background: {color ? color.light : 'var(--bg-tertiary)'}; color: {color ? color.bg : 'var(--text-primary)'}"
              onclick={() => onEventClick?.(item.event)}
            >
              <div class="flex gap-1.5 h-full">
                {#if item.isMerged}
                  <div class="flex flex-col gap-0.5 py-0.5 shrink-0">
                    {#each item.event._mergedAccounts as acctEmail}
                      {@const acctColor = $accountColorMap[acctEmail]}
                      <span class="w-2 h-2 rounded-full" style="background: {acctColor ? acctColor.bg : 'var(--color-accent-500)'}"></span>
                    {/each}
                  </div>
                {:else}
                  <span class="w-1 self-stretch rounded-full shrink-0" style="background: {color ? color.bg : 'var(--color-accent-500)'}"></span>
                {/if}
                <div class="flex-1 min-w-0">
                  <div class="text-sm font-medium leading-tight truncate">{item.event.summary || '(No title)'}</div>
                  <div class="text-xs leading-tight opacity-75 mt-0.5">{formatEventTime(item.event)}</div>
                  {#if item.height > 50 && item.event.location}
                    <div class="text-xs leading-tight opacity-60 mt-0.5 truncate">{item.event.location}</div>
                  {/if}
                </div>
              </div>
            </div>
          {/if}
        {/each}
      </div>
    </div>
  </div>
</div>
