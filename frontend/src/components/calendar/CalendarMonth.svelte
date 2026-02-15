<script>
  import CalendarEventPill from './CalendarEventPill.svelte';
  import { mergeEvents } from '../../lib/calendarLayout.js';
  import { accountColorMap, calendarView, calendarDate } from '../../lib/stores.js';

  let { events = [], currentDate = new Date(), onEventClick = null } = $props();

  const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const MAX_VISIBLE = 3;

  let year = $derived(currentDate.getFullYear());
  let month = $derived(currentDate.getMonth());

  let calendarGrid = $derived.by(() => {
    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);
    const startOffset = firstDay.getDay();
    const totalDays = lastDay.getDate();

    const grid = [];
    const prevMonthLast = new Date(year, month, 0).getDate();
    for (let i = startOffset - 1; i >= 0; i--) {
      grid.push({ day: prevMonthLast - i, inMonth: false, date: new Date(year, month - 1, prevMonthLast - i) });
    }
    for (let d = 1; d <= totalDays; d++) {
      grid.push({ day: d, inMonth: true, date: new Date(year, month, d) });
    }
    const remaining = 42 - grid.length;
    for (let d = 1; d <= remaining; d++) {
      grid.push({ day: d, inMonth: false, date: new Date(year, month + 1, d) });
    }
    return grid;
  });

  function isToday(date) {
    const now = new Date();
    return date.getDate() === now.getDate() &&
      date.getMonth() === now.getMonth() &&
      date.getFullYear() === now.getFullYear();
  }

  function fmtDateStr(date) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  }

  function getEventsForDay(date) {
    const dateStr = fmtDateStr(date);

    return events.filter(e => {
      if (e.is_all_day) {
        return e.start_date <= dateStr && e.end_date > dateStr;
      }
      if (!e.start_time) return false;
      const eventDate = new Date(e.start_time);
      return eventDate.getFullYear() === date.getFullYear() &&
        eventDate.getMonth() === date.getMonth() &&
        eventDate.getDate() === date.getDate();
    });
  }

  function switchToDay(date) {
    calendarDate.set(date);
    calendarView.set('day');
  }
</script>

<div class="flex flex-col h-full">
  <!-- Day headers -->
  <div class="grid grid-cols-7 border-b" style="border-color: var(--border-color)">
    {#each DAYS as day}
      <div class="py-2 text-center text-xs font-semibold uppercase tracking-wider" style="color: var(--text-tertiary)">
        {day}
      </div>
    {/each}
  </div>

  <!-- Calendar grid -->
  <div class="grid grid-cols-7 flex-1" style="grid-template-rows: repeat(6, 1fr)">
    {#each calendarGrid as cell, i}
      {@const dayEvents = mergeEvents(getEventsForDay(cell.date))}
      {@const visibleEvents = dayEvents.slice(0, MAX_VISIBLE)}
      {@const overflowCount = dayEvents.length - MAX_VISIBLE}
      <div
        class="border-b border-r p-1 min-h-0 overflow-hidden"
        style="border-color: var(--border-color); background: {isToday(cell.date) ? 'var(--bg-hover)' : 'transparent'}"
      >
        <!-- Day number -->
        <button
          class="w-6 h-6 flex items-center justify-center rounded-full text-xs font-medium mb-0.5"
          class:opacity-40={!cell.inMonth}
          style="color: {isToday(cell.date) ? 'white' : 'var(--text-primary)'}; background: {isToday(cell.date) ? 'var(--color-accent-500)' : 'transparent'}"
          onclick={() => switchToDay(cell.date)}
        >
          {cell.day}
        </button>

        <!-- Events -->
        <div class="space-y-0.5">
          {#each visibleEvents as event}
            <CalendarEventPill
              {event}
              color={$accountColorMap[event.account_email]}
              showTime={!event.is_all_day}
              compact={true}
              onclick={() => onEventClick?.(event)}
            />
          {/each}
          {#if overflowCount > 0}
            <button
              class="text-[10px] font-medium px-1.5 w-full text-left rounded hover:bg-black/5 transition-fast"
              style="color: var(--text-tertiary)"
              onclick={() => switchToDay(cell.date)}
            >
              +{overflowCount} more
            </button>
          {/if}
        </div>
      </div>
    {/each}
  </div>
</div>
