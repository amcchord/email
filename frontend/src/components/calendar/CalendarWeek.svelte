<script>
  import { accountColorMap } from '../../lib/stores.js';
  import { mergeEvents, layoutEvents } from '../../lib/calendarLayout.js';
  import { onMount } from 'svelte';

  let { events = [], currentDate = new Date(), onEventClick = null } = $props();

  const HOURS = Array.from({ length: 24 }, (_, i) => i);

  let weekStart = $derived.by(() => {
    const d = new Date(currentDate);
    d.setDate(d.getDate() - d.getDay());
    d.setHours(0, 0, 0, 0);
    return d;
  });

  let weekDays = $derived.by(() => {
    return Array.from({ length: 7 }, (_, i) => {
      const d = new Date(weekStart);
      d.setDate(d.getDate() + i);
      return d;
    });
  });

  function isToday(date) {
    const now = new Date();
    return date.getDate() === now.getDate() &&
      date.getMonth() === now.getMonth() &&
      date.getFullYear() === now.getFullYear();
  }

  function formatDayHeader(date) {
    const day = date.toLocaleDateString('en-US', { weekday: 'short' });
    return `${day} ${date.getDate()}`;
  }

  function dateStr(date) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  }

  function getAllDayEvents(date) {
    const ds = dateStr(date);
    return events.filter(e => {
      if (!e.is_all_day) return false;
      return e.start_date <= ds && e.end_date > ds;
    });
  }

  function getTimedEvents(date) {
    return events.filter(e => {
      if (e.is_all_day || !e.start_time) return false;
      const eventDate = new Date(e.start_time);
      return eventDate.getFullYear() === date.getFullYear() &&
        eventDate.getMonth() === date.getMonth() &&
        eventDate.getDate() === date.getDate();
    });
  }

  const PX_PER_HOUR = 48;

  function getMergedAllDay(date) {
    return mergeEvents(getAllDayEvents(date));
  }

  function getDayLayout(date) {
    const timed = getTimedEvents(date);
    const merged = mergeEvents(timed);
    return layoutEvents(merged, PX_PER_HOUR);
  }

  function formatEventTime(event) {
    if (!event.start_time) return '';
    const d = new Date(event.start_time);
    let h = d.getHours();
    const m = d.getMinutes();
    const ampm = h >= 12 ? 'p' : 'a';
    h = h % 12 || 12;
    return m > 0 ? `${h}:${m.toString().padStart(2, '0')}${ampm}` : `${h}${ampm}`;
  }

  function formatHour(h) {
    if (h === 0) return '12 AM';
    if (h < 12) return `${h} AM`;
    if (h === 12) return '12 PM';
    return `${h - 12} PM`;
  }

  // Current time indicator
  let currentTimeTop = $state(0);
  let nowDay = $state(-1);

  function updateCurrentTime() {
    const now = new Date();
    currentTimeTop = (now.getHours() * 60 + now.getMinutes()) / 60 * 48;
    nowDay = now.getDay();
  }

  let hasAllDay = $derived(weekDays.some(d => getAllDayEvents(d).length > 0));

  let scrollContainer = $state(null);

  onMount(() => {
    updateCurrentTime();
    const interval = setInterval(updateCurrentTime, 60000);
    if (scrollContainer) {
      scrollContainer.scrollTop = 8 * 48 - 20;
    }
    return () => clearInterval(interval);
  });
</script>

<div class="flex flex-col h-full overflow-hidden">
  <!-- All-day header -->
  {#if hasAllDay}
    <div class="grid border-b shrink-0" style="grid-template-columns: 56px repeat(7, 1fr); border-color: var(--border-color)">
      <div class="py-1 px-1 text-[10px]" style="color: var(--text-tertiary)">all-day</div>
      {#each weekDays as day}
        {@const mergedAllDay = getMergedAllDay(day)}
        <div class="py-1 px-0.5 border-l space-y-0.5" style="border-color: var(--border-color)">
          {#each mergedAllDay as event}
            {@const color = $accountColorMap[event.account_email]}
            <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
            <div
              class="rounded px-1 py-0.5 text-[10px] leading-tight truncate cursor-pointer flex items-center gap-0.5"
              style="background: {color ? color.light : 'var(--bg-tertiary)'}; color: {color ? color.bg : 'var(--text-secondary)'}"
              onclick={() => onEventClick?.(event)}
            >
              {#if event._mergedAccounts && event._mergedAccounts.length > 1}
                <div class="flex flex-col gap-px shrink-0">
                  {#each event._mergedAccounts as acctEmail}
                    {@const acctColor = $accountColorMap[acctEmail]}
                    <span class="w-1.5 h-1.5 rounded-full" style="background: {acctColor ? acctColor.bg : 'var(--color-accent-500)'}"></span>
                  {/each}
                </div>
              {:else}
                <span class="w-0.5 self-stretch rounded-full shrink-0" style="background: {color ? color.bg : 'var(--color-accent-500)'}"></span>
              {/if}
              <span class="truncate">{event.summary || '(No title)'}</span>
            </div>
          {/each}
        </div>
      {/each}
    </div>
  {/if}

  <!-- Day headers -->
  <div class="grid border-b shrink-0" style="grid-template-columns: 56px repeat(7, 1fr); border-color: var(--border-color)">
    <div></div>
    {#each weekDays as day}
      <div
        class="py-2 text-center border-l"
        style="border-color: var(--border-color)"
      >
        <span
          class="text-xs font-medium"
          class:font-bold={isToday(day)}
          style="color: {isToday(day) ? 'var(--color-accent-500)' : 'var(--text-secondary)'}"
        >
          {formatDayHeader(day)}
        </span>
      </div>
    {/each}
  </div>

  <!-- Time grid -->
  <div class="flex-1 overflow-y-auto" bind:this={scrollContainer}>
    <div class="grid relative" style="grid-template-columns: 56px repeat(7, 1fr)">
      <!-- Hour labels -->
      <div>
        {#each HOURS as h}
          <div class="h-12 flex items-start justify-end pr-2 -mt-2">
            <span class="text-[10px]" style="color: var(--text-tertiary)">{formatHour(h)}</span>
          </div>
        {/each}
      </div>

      <!-- Day columns -->
      {#each weekDays as day, dayIdx}
        {@const dayLayoutItems = getDayLayout(day)}
        <div class="relative border-l" style="border-color: var(--border-color); height: {24 * 48}px">
          <!-- Hour lines -->
          {#each HOURS as h}
            <div
              class="absolute w-full border-t"
              style="top: {h * 48}px; border-color: var(--border-color)"
            ></div>
          {/each}

          <!-- Current time indicator -->
          {#if dayIdx === nowDay}
            <div
              class="absolute w-full z-20 pointer-events-none"
              style="top: {currentTimeTop}px"
            >
              <div class="flex items-center">
                <div class="w-2 h-2 rounded-full bg-red-500 -ml-1"></div>
                <div class="flex-1 h-0.5 bg-red-500"></div>
              </div>
            </div>
          {/if}

          <!-- Events -->
          {#each dayLayoutItems as item}
            {@const color = $accountColorMap[item.event.account_email]}
            <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
            {#if item.isBackground}
              <div
                class="absolute px-1 py-0.5 overflow-hidden cursor-pointer"
                style="top: {item.top}px; height: {item.height}px; left: {item.left}; width: {item.width}; background: {color ? color.light : 'var(--bg-tertiary)'}; opacity: 0.3; z-index: {item.zIndex}; border-left: 3px solid {color ? color.bg : 'var(--color-accent-500)'}"
                onclick={() => onEventClick?.(item.event)}
              >
                <div class="text-[10px] font-medium leading-tight truncate" style="color: {color ? color.bg : 'var(--text-primary)'}">{item.event.summary || '(No title)'}</div>
              </div>
            {:else}
              <div
                class="absolute rounded px-1 py-0.5 overflow-hidden cursor-pointer transition-opacity hover:opacity-80 hover:!z-40"
                style="top: {item.top}px; height: {item.height}px; left: {item.left}; width: {item.width}; z-index: {item.zIndex}; background: {color ? color.light : 'var(--bg-tertiary)'}; color: {color ? color.bg : 'var(--text-primary)'}"
                onclick={() => onEventClick?.(item.event)}
              >
                <div class="flex gap-0.5 h-full">
                  {#if item.isMerged}
                    <div class="flex flex-col gap-px py-0.5 shrink-0">
                      {#each item.event._mergedAccounts as acctEmail}
                        {@const acctColor = $accountColorMap[acctEmail]}
                        <span class="w-1.5 h-1.5 rounded-full" style="background: {acctColor ? acctColor.bg : 'var(--color-accent-500)'}"></span>
                      {/each}
                    </div>
                  {:else}
                    <span class="w-0.5 self-stretch rounded-full shrink-0" style="background: {color ? color.bg : 'var(--color-accent-500)'}"></span>
                  {/if}
                  <div class="flex-1 min-w-0">
                    <div class="text-[10px] font-medium leading-tight truncate">{item.event.summary || '(No title)'}</div>
                    {#if item.height > 24}
                      <div class="text-[9px] leading-tight truncate opacity-75">{formatEventTime(item.event)}</div>
                    {/if}
                    {#if item.height > 40 && item.event.location}
                      <div class="text-[9px] leading-tight truncate opacity-60">{item.event.location}</div>
                    {/if}
                  </div>
                </div>
              </div>
            {/if}
          {/each}
        </div>
      {/each}
    </div>
  </div>
</div>
