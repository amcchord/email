<script>
  import { api } from '../lib/api.js';
  import { calendarView, calendarDate, calendarEvents, calendarLoading, selectedAccountId, accounts, accountColorMap, showToast } from '../lib/stores.js';
  import CalendarMonth from '../components/calendar/CalendarMonth.svelte';
  import CalendarWeek from '../components/calendar/CalendarWeek.svelte';
  import CalendarDay from '../components/calendar/CalendarDay.svelte';
  import CalendarEventDetail from '../components/calendar/CalendarEventDetail.svelte';
  import Icon from '../components/common/Icon.svelte';

  let selectedEvent = $state(null);
  let hasLoaded = $state(false);
  let syncing = $state(false);

  let selectedAccount = $derived(
    $selectedAccountId ? $accounts.find(a => a.id === $selectedAccountId) : null
  );

  function getVisibleRange(view, date) {
    const y = date.getFullYear();
    const m = date.getMonth();
    const d = date.getDate();

    if (view === 'month') {
      const first = new Date(y, m, 1);
      const startOffset = first.getDay();
      const rangeStart = new Date(y, m, 1 - startOffset);
      const rangeEnd = new Date(y, m + 1, 7);
      return { start: fmtDate(rangeStart), end: fmtDate(rangeEnd) };
    }
    if (view === 'week') {
      const dayOfWeek = date.getDay();
      const weekStart = new Date(y, m, d - dayOfWeek);
      const weekEnd = new Date(y, m, d - dayOfWeek + 6);
      return { start: fmtDate(weekStart), end: fmtDate(weekEnd) };
    }
    return { start: fmtDate(date), end: fmtDate(date) };
  }

  function fmtDate(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  async function loadEvents() {
    calendarLoading.set(true);
    try {
      const { start, end } = getVisibleRange($calendarView, $calendarDate);
      const params = { start, end };
      if ($selectedAccountId) {
        params.account_id = $selectedAccountId;
      }
      const result = await api.getCalendarEvents(params);
      calendarEvents.set(result.events || []);
    } catch (err) {
      console.error('Failed to load calendar events:', err);
      calendarEvents.set([]);
    } finally {
      calendarLoading.set(false);
      hasLoaded = true;
    }
  }

  // Reload events when view, date, or account changes
  $effect(() => {
    void $calendarView;
    void $calendarDate;
    void $selectedAccountId;
    loadEvents();
  });

  function navigatePrev() {
    calendarDate.update(d => {
      const n = new Date(d);
      if ($calendarView === 'month') n.setMonth(n.getMonth() - 1);
      else if ($calendarView === 'week') n.setDate(n.getDate() - 7);
      else n.setDate(n.getDate() - 1);
      return n;
    });
  }

  function navigateNext() {
    calendarDate.update(d => {
      const n = new Date(d);
      if ($calendarView === 'month') n.setMonth(n.getMonth() + 1);
      else if ($calendarView === 'week') n.setDate(n.getDate() + 7);
      else n.setDate(n.getDate() + 1);
      return n;
    });
  }

  function goToday() {
    calendarDate.set(new Date());
  }

  function getHeaderLabel() {
    const d = $calendarDate;
    if ($calendarView === 'month') {
      return d.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
    }
    if ($calendarView === 'week') {
      const weekStart = new Date(d);
      weekStart.setDate(weekStart.getDate() - weekStart.getDay());
      const weekEnd = new Date(weekStart);
      weekEnd.setDate(weekEnd.getDate() + 6);
      const startStr = weekStart.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
      const endStr = weekEnd.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
      return `${startStr} - ${endStr}`;
    }
    return d.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
  }

  function handleEventClick(event) {
    selectedEvent = event;
  }

  async function triggerSync() {
    syncing = true;
    try {
      await api.triggerCalendarSync($selectedAccountId || undefined);
      showToast('Calendar sync triggered', 'success');
      // Poll for new events a few times after sync
      setTimeout(loadEvents, 3000);
      setTimeout(loadEvents, 8000);
      setTimeout(loadEvents, 15000);
    } catch (err) {
      showToast(err.message || 'Sync failed', 'error');
    } finally {
      syncing = false;
    }
  }

  let eventCount = $derived($calendarEvents.length);
</script>

<div class="flex flex-col h-full overflow-hidden" style="background: var(--bg-primary)">
  <!-- Navigation bar -->
  <div class="flex items-center justify-between px-4 py-2 border-b shrink-0" style="border-color: var(--border-color)">
    <div class="flex items-center gap-2">
      <button
        onclick={navigatePrev}
        class="p-1.5 rounded-md transition-fast hover:bg-black/5"
        style="color: var(--text-secondary)"
        aria-label="Previous"
      >
        <Icon name="chevron-left" size={20} />
      </button>
      <button
        onclick={navigateNext}
        class="p-1.5 rounded-md transition-fast hover:bg-black/5"
        style="color: var(--text-secondary)"
        aria-label="Next"
      >
        <Icon name="chevron-right" size={20} />
      </button>
      <button
        onclick={goToday}
        class="px-3 py-1 rounded-md text-sm font-medium border transition-fast hover:bg-black/5"
        style="color: var(--text-secondary); border-color: var(--border-color)"
      >
        Today
      </button>

      <h2 class="text-lg font-semibold ml-2" style="color: var(--text-primary)">
        {getHeaderLabel()}
      </h2>

      {#if hasLoaded}
        <span class="text-xs ml-2" style="color: var(--text-tertiary)">
          {eventCount} event{eventCount !== 1 ? 's' : ''}
        </span>
      {/if}
    </div>

    <div class="flex items-center gap-2">
      <!-- Account filter chips -->
      {#if $accounts.length > 1}
        <div class="flex items-center gap-1 mr-1">
          <button
            onclick={() => selectedAccountId.set(null)}
            class="px-2 py-1 rounded-md text-xs font-medium transition-fast"
            style="background: {$selectedAccountId === null ? 'var(--color-accent-500)' : 'var(--bg-tertiary)'}; color: {$selectedAccountId === null ? 'white' : 'var(--text-secondary)'}"
          >
            All
          </button>
          {#each $accounts as acct}
            {@const color = $accountColorMap[acct.email]}
            <button
              onclick={() => selectedAccountId.set($selectedAccountId === acct.id ? null : acct.id)}
              class="flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium transition-fast"
              style="background: {$selectedAccountId === acct.id ? (color ? color.bg : 'var(--color-accent-500)') : 'var(--bg-tertiary)'}; color: {$selectedAccountId === acct.id ? 'white' : 'var(--text-secondary)'}"
              title={acct.email}
            >
              <span
                class="w-2 h-2 rounded-full shrink-0"
                style="background: {$selectedAccountId === acct.id ? 'white' : (color ? color.bg : 'var(--text-tertiary)')}"
              ></span>
              <span class="truncate max-w-[100px]">{acct.short_label || acct.description || acct.email.split('@')[0]}</span>
            </button>
          {/each}
        </div>
        <div class="w-px h-5" style="background: var(--border-color)"></div>
      {/if}

      <!-- Sync button -->
      <button
        onclick={triggerSync}
        disabled={syncing}
        class="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-fast border"
        style="color: var(--text-secondary); border-color: var(--border-color)"
        title="Sync calendar from Google"
      >
        <span class:animate-spin={syncing || $calendarLoading}>
          <Icon name="refresh-cw" size={14} />
        </span>
        Sync
      </button>

      <!-- View toggle -->
      <div class="flex rounded-lg overflow-hidden border" style="border-color: var(--border-color)">
        {#each ['month', 'week', 'day'] as view}
          <button
            onclick={() => calendarView.set(view)}
            class="px-3 py-1 text-sm font-medium capitalize transition-fast"
            style="background: {$calendarView === view ? 'var(--color-accent-500)' : 'transparent'}; color: {$calendarView === view ? 'white' : 'var(--text-secondary)'}"
          >
            {view}
          </button>
        {/each}
      </div>
    </div>
  </div>

  <!-- Calendar content -->
  <div class="flex-1 overflow-hidden">
    {#if !hasLoaded && $calendarLoading}
      <!-- Initial loading spinner -->
      <div class="flex items-center justify-center h-full">
        <div class="flex flex-col items-center gap-3">
          <div class="w-8 h-8 border-2 rounded-full animate-spin" style="border-color: var(--border-color); border-top-color: var(--color-accent-500)"></div>
          <span class="text-sm" style="color: var(--text-secondary)">Loading calendar...</span>
        </div>
      </div>
    {:else}
      <!-- Always show the calendar grid once loaded -->
      {#if $calendarView === 'month'}
        <CalendarMonth
          events={$calendarEvents}
          currentDate={$calendarDate}
          onEventClick={handleEventClick}
        />
      {:else if $calendarView === 'week'}
        <CalendarWeek
          events={$calendarEvents}
          currentDate={$calendarDate}
          onEventClick={handleEventClick}
        />
      {:else}
        <CalendarDay
          events={$calendarEvents}
          currentDate={$calendarDate}
          onEventClick={handleEventClick}
        />
      {/if}
    {/if}
  </div>
</div>

<!-- Event detail modal -->
{#if selectedEvent}
  <CalendarEventDetail
    event={selectedEvent}
    onclose={() => selectedEvent = null}
  />
{/if}
