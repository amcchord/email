<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { calendarView, calendarDate, calendarEvents, selectedAccountId, accounts, accountsLoaded, accountsLoadError, accountColorMap, currentPage, forceSyncPoll, showToast } from '../lib/stores.js';
  import { registerActions } from '../lib/shortcutStore.js';
  import { mergeEvents } from '../lib/calendarLayout.js';
  import {
    calendarCoverage,
    calendarSyncHasActiveTarget,
    calendarRequestDescriptor,
    calendarSyncTargetsFinished,
    createCalendarSyncMonitor,
    createLatestRequestGate,
    isCalendarAbort,
    shiftCalendarDate,
  } from '../lib/calendarState.js';
  import CalendarMonth from '../components/calendar/CalendarMonth.svelte';
  import CalendarWeek from '../components/calendar/CalendarWeek.svelte';
  import CalendarDay from '../components/calendar/CalendarDay.svelte';
  import CalendarEventDetail from '../components/calendar/CalendarEventDetail.svelte';
  import Icon from '../components/common/Icon.svelte';

  let selectedEvent = $state(null);
  let selectedEventOpener = $state(null);
  let syncing = $state(false);
  let syncStatuses = $state([]);
  let statusState = $state('loading');
  let statusError = $state('');
  let eventStatus = $state('idle');
  let eventError = $state('');
  let currentRequestKey = $state('');
  let visibleEvents = $state([]);
  let observedDescriptorKey = null;
  let destroyed = false;
  let syncPollTimer = null;

  const eventCache = new Map();
  const eventGate = createLatestRequestGate();
  const statusGate = createLatestRequestGate();

  function resolveDisplayTimeZone() {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    } catch {
      // UTC is an explicit fallback for both fetching and display messaging.
      return 'UTC';
    }
  }

  const displayTimeZone = resolveDisplayTimeZone();
  const timeZoneLabel = displayTimeZone.replaceAll('_', ' ');

  let coverage = $derived(calendarCoverage({
    accounts: $accountsLoaded ? $accounts : [],
    selectedAccountId: $selectedAccountId,
    statuses: syncStatuses,
    statusState: $accountsLoaded ? statusState : ($accountsLoadError ? 'accounts-error' : 'loading'),
    range: currentDescriptor().range,
  }));

  let reauthStatuses = $derived(
    syncStatuses.filter(s =>
      s
      && s.needs_reauth
      && ($selectedAccountId === null || s.account_id === $selectedAccountId)
    )
  );

  let transientErrorStatuses = $derived(
    syncStatuses.filter(s =>
      s
      && s.status === 'error'
      && !s.needs_reauth
      && ($selectedAccountId === null || s.account_id === $selectedAccountId)
    )
  );

  let visibleAccountsWithoutScope = $derived(
    $accounts.filter(account =>
      account?.is_active !== false
      && account?.has_calendar_scope === false
      && ($selectedAccountId === null || account.id === $selectedAccountId)
      && !syncStatuses.some(status => status.account_id === account.id && status.needs_reauth)
    )
  );

  let firstReconnectAccountId = $derived(
    coverage.accounts?.[0]?.id
      || visibleAccountsWithoutScope[0]?.id
      || reauthStatuses[0]?.account_id
      || null
  );

  let eventCount = $derived(mergeEvents(visibleEvents).length);
  let hasCurrentResult = $derived(
    eventStatus === 'ready'
      || eventStatus === 'refreshing'
      || (eventStatus === 'error' && visibleEvents.length > 0)
  );
  let hasVisibleEvents = $derived(visibleEvents.length > 0);
  let canSync = $derived(
    $accountsLoaded
      && coverage.accounts?.length > 0
      && coverage.state !== 'reauth'
      && coverage.state !== 'unavailable'
      && coverage.state !== 'partial'
      && coverage.state !== 'syncing'
      && !syncing
  );
  let emptyStateTitle = $derived(
    coverage.state === 'verified' ? 'No events in this range' : 'No saved events to show'
  );

  async function loadSyncStatus() {
    const request = statusGate.begin('calendar-sync-status');
    if (syncStatuses.length === 0) statusState = 'loading';
    statusError = '';
    try {
      const result = await api.getCalendarSyncStatus({ signal: request.signal });
      if (!request.isCurrent()) return null;
      syncStatuses = Array.isArray(result) ? result : [];
      statusState = 'ready';
      return syncStatuses;
    } catch (err) {
      if (isCalendarAbort(err) || !request.isCurrent()) return null;
      console.error('Failed to load calendar sync status:', err);
      statusState = 'error';
      statusError = err.message || 'Calendar freshness could not be loaded.';
      return null;
    }
  }

  async function reauthorize(accountId) {
    try {
      const result = await api.reauthorizeAccount(accountId, { returnPage: 'calendar' });
      window.location.href = result.auth_url;
    } catch (err) {
      showToast(err.message || 'Failed to start reauthorization', 'error');
    }
  }

  onMount(() => {
    const narrowQuery = window.matchMedia('(max-width: 767px)');
    const enforceNarrowView = () => {
      if (narrowQuery.matches && $calendarView === 'week') calendarView.set('day');
    };
    enforceNarrowView();
    narrowQuery.addEventListener('change', enforceNarrowView);
    const cleanupShortcuts = registerActions({
      'cal.today': () => goToday(),
      'cal.prev': () => navigatePrev(),
      'cal.next': () => navigateNext(),
      'cal.month': () => calendarView.set('month'),
      'cal.week': () => calendarView.set(narrowQuery.matches ? 'day' : 'week'),
      'cal.day': () => calendarView.set('day'),
    });
    loadSyncStatus();
    const statusInterval = setInterval(loadSyncStatus, 60000);
    return () => {
      destroyed = true;
      narrowQuery.removeEventListener('change', enforceNarrowView);
      cleanupShortcuts();
      clearInterval(statusInterval);
      clearTimeout(syncPollTimer);
      eventGate.cancel();
      statusGate.cancel();
    };
  });

  function currentDescriptor() {
    return calendarRequestDescriptor({
      view: $calendarView,
      date: new Date($calendarDate),
      accountId: $selectedAccountId,
      timeZone: displayTimeZone,
    });
  }

  async function loadEvents(descriptor = currentDescriptor(), { force = false } = {}) {
    const cached = eventCache.get(descriptor.key);
    currentRequestKey = descriptor.key;
    eventError = '';
    if (cached && !force) {
      visibleEvents = cached;
      calendarEvents.set(cached);
      eventStatus = 'refreshing';
    } else if (cached) {
      visibleEvents = cached;
      calendarEvents.set(cached);
      eventStatus = 'refreshing';
    } else {
      visibleEvents = [];
      calendarEvents.set([]);
      eventStatus = 'loading';
    }

    const request = eventGate.begin(descriptor.key);
    try {
      const result = await api.getCalendarEvents(descriptor.params, { signal: request.signal });
      if (!request.isCurrent() || currentRequestKey !== descriptor.key) return;
      const events = Array.isArray(result?.events) ? result.events : [];
      eventCache.set(descriptor.key, events);
      visibleEvents = events;
      calendarEvents.set(events);
      eventStatus = 'ready';
    } catch (err) {
      if (isCalendarAbort(err) || !request.isCurrent() || currentRequestKey !== descriptor.key) return;
      console.error('Failed to load calendar events:', err);
      eventError = err.message || 'Calendar events could not be loaded.';
      eventStatus = 'error';
    }
  }

  // Invalid account selections can survive an account removal because this store
  // is shared with mail. Reset only after an authoritative account load.
  $effect(() => {
    if (
      $accountsLoaded
      && $selectedAccountId !== null
      && !$accounts.some(account => account.id === $selectedAccountId && account.is_active !== false)
    ) {
      selectedAccountId.set(null);
    }
  });

  // Every dataset gets an immutable request identity. loadEvents aborts the
  // previous fetch and stale completions are unable to commit state.
  $effect(() => {
    const descriptor = calendarRequestDescriptor({
      view: $calendarView,
      date: new Date($calendarDate),
      accountId: $selectedAccountId,
      timeZone: displayTimeZone,
    });
    if (observedDescriptorKey && observedDescriptorKey !== descriptor.key) selectedEvent = null;
    observedDescriptorKey = descriptor.key;
    loadEvents(descriptor);
  });

  function navigatePrev() {
    calendarDate.update(date => shiftCalendarDate($calendarView, date, -1));
  }

  function navigateNext() {
    calendarDate.update(date => shiftCalendarDate($calendarView, date, 1));
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
    selectedEventOpener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    selectedEvent = event;
  }

  function closeEventDetail() {
    selectedEvent = null;
  }

  async function pollTriggeredSync(context, attempt = 0) {
    if (destroyed) return;
    const statuses = await loadSyncStatus();
    if (destroyed) return;

    const everyTargetFinished = calendarSyncTargetsFinished(context, statuses || []);

    if (everyTargetFinished || attempt >= 22) {
      syncing = false;
      await loadEvents(currentDescriptor(), { force: true });
      if (destroyed) return;
      if (attempt >= 22 && !everyTargetFinished) {
        const activeNow = calendarSyncHasActiveTarget(context, statuses || []);
        showToast(
          activeNow
            ? 'Calendar sync is still running. Displayed saved events were reloaded.'
            : 'Couldn’t confirm sync completion. Displayed saved events were reloaded.',
          'info',
        );
      }
      return;
    }

    syncPollTimer = setTimeout(() => pollTriggeredSync(context, attempt + 1), 2000);
  }

  async function triggerSync() {
    const selectedAccountSnapshot = $selectedAccountId;
    const context = createCalendarSyncMonitor({
      accounts: $accounts,
      statuses: syncStatuses,
      selectedAccountId: selectedAccountSnapshot,
    });
    if (context.targetIds.length === 0) {
      showToast('Connect Calendar access before syncing.', 'error');
      return;
    }
    syncing = true;
    clearTimeout(syncPollTimer);
    try {
      await api.triggerCalendarSync(selectedAccountSnapshot || undefined);
      showToast('Calendar sync triggered', 'success');
      syncPollTimer = setTimeout(() => pollTriggeredSync(context), 1000);
    } catch (err) {
      showToast(err.message || 'Sync failed', 'error');
      syncing = false;
    }
  }

  function formatFreshness(value) {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return `Oldest visible calendar sync: ${date.toLocaleString([], {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
    })}`;
  }
</script>

<div class="flex flex-col h-full overflow-hidden" style="background: var(--bg-primary)">
  <!-- Navigation bar -->
  <div class="calendar-toolbar flex items-center justify-between px-4 py-2 border-b shrink-0" style="border-color: var(--border-color)">
    <div class="calendar-date-nav flex items-center gap-2 min-w-0">
      <button
        onclick={navigatePrev}
        class="calendar-nav-button p-1.5 rounded-md transition-fast hover:bg-black/5"
        style="color: var(--text-secondary)"
        aria-label={`Previous ${$calendarView}`}
        data-shortcut="cal.prev"
      >
        <Icon name="chevron-left" size={20} />
      </button>
      <button
        onclick={navigateNext}
        class="calendar-nav-button p-1.5 rounded-md transition-fast hover:bg-black/5"
        style="color: var(--text-secondary)"
        aria-label={`Next ${$calendarView}`}
        data-shortcut="cal.next"
      >
        <Icon name="chevron-right" size={20} />
      </button>
      <button
        onclick={goToday}
        class="calendar-nav-button px-3 py-1 rounded-md text-sm font-medium border transition-fast hover:bg-black/5"
        style="color: var(--text-secondary); border-color: var(--border-color)"
        data-shortcut="cal.today"
      >
        Today
      </button>

      <div class="calendar-title min-w-0 ml-2">
        <h2 class="calendar-heading text-lg font-semibold truncate" style="color: var(--text-primary)">
          {getHeaderLabel()}
        </h2>
        <div class="timezone-label text-[10px] truncate" style="color: var(--text-tertiary)" title={`Times shown in ${displayTimeZone}`}>
          Times in {timeZoneLabel}
        </div>
      </div>

      {#if hasCurrentResult && eventCount > 0}
        <span class="event-count text-xs ml-2 shrink-0" style="color: var(--text-tertiary)">
          {eventCount} {coverage.state === 'verified' ? 'event' : 'saved event'}{eventCount !== 1 ? 's' : ''}
        </span>
      {/if}
    </div>

    <div class="calendar-controls flex items-center gap-2 min-w-0">
      <!-- Account filter chips -->
      {#if $accounts.length > 1}
        <div class="account-filter flex items-center gap-1 mr-1 overflow-x-auto" role="group" aria-label="Visible calendar account">
          <button
            onclick={() => selectedAccountId.set(null)}
            class="calendar-control-button px-2 py-1 rounded-md text-xs font-medium transition-fast"
            style="background: {$selectedAccountId === null ? 'var(--color-accent-500)' : 'var(--bg-tertiary)'}; color: {$selectedAccountId === null ? 'white' : 'var(--text-secondary)'}"
            aria-pressed={$selectedAccountId === null}
          >
            All
          </button>
          {#each $accounts as acct}
            {@const color = $accountColorMap[acct.email]}
            <button
              onclick={() => selectedAccountId.set($selectedAccountId === acct.id ? null : acct.id)}
              class="calendar-control-button flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium transition-fast"
              style="background: {$selectedAccountId === acct.id ? (color ? color.bg : 'var(--color-accent-500)') : 'var(--bg-tertiary)'}; color: {$selectedAccountId === acct.id ? 'white' : 'var(--text-secondary)'}"
              title={acct.email}
              aria-pressed={$selectedAccountId === acct.id}
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

      <div class="calendar-actions flex items-center gap-1.5">
        <!-- Reload reads the current cached dataset only; Sync starts Google ingestion. -->
        <button
          onclick={() => loadEvents(currentDescriptor(), { force: true })}
          disabled={eventStatus === 'loading' || eventStatus === 'refreshing'}
          class="calendar-control-button flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-fast border disabled:opacity-50"
          style="color: var(--text-secondary); border-color: var(--border-color)"
          title="Reload visible events"
          aria-label="Reload visible events"
        >
          <span class:animate-spin={eventStatus === 'refreshing'}>
            <Icon name="refresh-cw" size={14} />
          </span>
          <span class="action-label">Reload</span>
        </button>

        <button
          onclick={triggerSync}
          disabled={!canSync}
          class="calendar-control-button flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-fast border disabled:opacity-50"
          style="color: var(--text-secondary); border-color: var(--border-color)"
          title="Sync calendar from Google"
        >
          <span class:animate-pulse={syncing || coverage.state === 'syncing'}>
            <Icon name="cloud" size={14} />
          </span>
          {syncing || coverage.state === 'syncing' ? 'Syncing…' : 'Sync'}
        </button>
      </div>

      <!-- View toggle -->
      <div class="view-toggle flex rounded-lg overflow-hidden border" style="border-color: var(--border-color)" role="group" aria-label="Calendar view">
        {#each ['month', 'week', 'day'] as view}
          <button
            onclick={() => calendarView.set(view)}
            class:mobile-week-option={view === 'week'}
            class="calendar-control-button px-3 py-1 text-sm font-medium capitalize transition-fast"
            style="background: {$calendarView === view ? 'var(--color-accent-500)' : 'transparent'}; color: {$calendarView === view ? 'white' : 'var(--text-secondary)'}"
            data-shortcut={view === 'month' ? 'cal.month' : view === 'week' ? 'cal.week' : 'cal.day'}
            aria-pressed={$calendarView === view}
          >
            {view}
          </button>
        {/each}
      </div>
    </div>
  </div>

  {#if visibleAccountsWithoutScope.length > 0}
    <div class="calendar-notice px-4 py-2 border-b shrink-0" style="background: var(--color-warning-bg, #fef3c7); border-color: var(--border-color)">
      {#each visibleAccountsWithoutScope as account (account.id)}
        <div class="flex items-center justify-between gap-3 py-1 text-sm">
          <div class="flex items-center gap-2 min-w-0">
            <Icon name="calendar" size={16} />
            <span class="font-medium truncate" style="color: var(--text-primary)">{account.email}</span>
            <span class="truncate" style="color: var(--text-secondary)">Calendar access is not connected.</span>
          </div>
          <button
            onclick={() => reauthorize(account.id)}
            class="notice-action px-3 py-1 rounded-md text-xs font-medium border shrink-0 transition-fast hover:bg-black/5"
            style="color: var(--text-primary); border-color: var(--border-color); background: var(--bg-primary)"
          >
            Connect Calendar
          </button>
        </div>
      {/each}
    </div>
  {/if}

  {#if reauthStatuses.length > 0}
    <div class="calendar-notice px-4 py-2 border-b shrink-0" style="background: var(--color-warning-bg, #fef3c7); border-color: var(--border-color)">
      {#each reauthStatuses as s (s.account_id)}
        <div class="flex items-center justify-between gap-3 py-1 text-sm">
          <div class="flex items-center gap-2 min-w-0">
            <Icon name="alert-triangle" size={16} />
            <span class="font-medium truncate" style="color: var(--text-primary)">
              {s.account_email || `Account ${s.account_id}`}
            </span>
            <span class="truncate" style="color: var(--text-secondary)">
              {s.error_message || 'Calendar sync failed'}
            </span>
          </div>
          <button
            onclick={() => reauthorize(s.account_id)}
            class="notice-action px-3 py-1 rounded-md text-xs font-medium border shrink-0 transition-fast hover:bg-black/5"
            style="color: var(--text-primary); border-color: var(--border-color); background: var(--bg-primary)"
          >
            Reconnect
          </button>
        </div>
      {/each}
    </div>
  {/if}

  {#if transientErrorStatuses.length > 0}
    <div class="px-4 py-1.5 border-b shrink-0 text-xs" style="background: var(--bg-tertiary); border-color: var(--border-color); color: var(--text-tertiary)">
      {#each transientErrorStatuses as s (s.account_id)}
        <div class="flex items-center gap-2 py-0.5">
          <Icon name="refresh-cw" size={12} />
          <span class="truncate">
            {s.account_email || `Account ${s.account_id}`}: sync issue, retrying...
          </span>
        </div>
      {/each}
    </div>
  {/if}

  {#if statusState === 'error'}
    <div class="calendar-notice flex items-center justify-between gap-3 px-4 py-2 border-b shrink-0 text-xs" style="background: var(--bg-tertiary); border-color: var(--border-color); color: var(--text-secondary)" role="status">
      <span class="truncate">Calendar freshness is unavailable. {statusError}</span>
      <button class="notice-action px-3 py-1 rounded-md border shrink-0" style="border-color: var(--border-color); color: var(--text-primary); background: var(--bg-primary)" onclick={loadSyncStatus}>
        Retry status
      </button>
    </div>
  {/if}

  <!-- Calendar content -->
  <div class="calendar-content relative flex-1 overflow-hidden" aria-busy={eventStatus === 'loading' || eventStatus === 'refreshing'}>
    {#if eventStatus === 'loading'}
      <!-- Initial loading spinner -->
      <div class="flex items-center justify-center h-full" role="status" aria-live="polite">
        <div class="flex flex-col items-center gap-3">
          <div class="w-8 h-8 border-2 rounded-full animate-spin" style="border-color: var(--border-color); border-top-color: var(--color-accent-500)"></div>
          <span class="text-sm" style="color: var(--text-secondary)">Loading calendar...</span>
        </div>
      </div>
    {:else if eventStatus === 'error' && !hasVisibleEvents}
      <div class="flex items-center justify-center h-full px-6" role="alert">
        <div class="state-card max-w-md rounded-xl border p-6 text-center shadow-sm" style="background: var(--bg-primary); border-color: var(--border-color)">
          <div class="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full" style="background: var(--color-error-bg, #fee2e2); color: var(--status-error, #b91c1c)">
            <Icon name="alert-circle" size={20} />
          </div>
          <h3 class="text-base font-semibold" style="color: var(--text-primary)">Couldn’t load this calendar</h3>
          <p class="mt-1 text-sm" style="color: var(--text-secondary)">{eventError}</p>
          <button
            class="mt-4 min-h-10 rounded-md px-4 text-sm font-medium"
            style="background: var(--color-accent-500); color: white"
            onclick={() => loadEvents(currentDescriptor(), { force: true })}
          >
            Try again
          </button>
        </div>
      </div>
    {:else}
      <!-- A grid is rendered only for the current request identity. -->
      {#if $calendarView === 'month'}
        <CalendarMonth
          events={visibleEvents}
          currentDate={$calendarDate}
          onEventClick={handleEventClick}
        />
      {:else if $calendarView === 'week'}
        <CalendarWeek
          events={visibleEvents}
          currentDate={$calendarDate}
          onEventClick={handleEventClick}
        />
      {:else}
        <CalendarDay
          events={visibleEvents}
          currentDate={$calendarDate}
          onEventClick={handleEventClick}
        />
      {/if}

      {#if eventStatus === 'refreshing'}
        <div class="absolute left-1/2 top-3 z-20 -translate-x-1/2 rounded-full border px-3 py-1.5 text-xs shadow-sm" style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-secondary)" role="status">
          Refreshing visible events…
        </div>
      {:else if eventStatus === 'error' && hasVisibleEvents}
        <div class="absolute left-1/2 top-3 z-20 flex -translate-x-1/2 items-center gap-3 rounded-lg border px-3 py-2 text-xs shadow-md" style="background: var(--bg-primary); border-color: var(--status-error, #b91c1c); color: var(--text-secondary)" role="alert">
          <span>Showing saved events. Reload failed.</span>
          <button class="font-semibold underline" style="color: var(--text-primary)" onclick={() => loadEvents(currentDescriptor(), { force: true })}>Retry</button>
        </div>
      {:else if hasCurrentResult && !hasVisibleEvents}
        <div class="empty-state-overlay absolute inset-x-0 top-5 z-10 flex justify-center px-4" role="status" aria-live="polite">
          <div class="state-card max-w-md rounded-xl border px-5 py-4 text-center shadow-sm" style="background: color-mix(in srgb, var(--bg-primary) 94%, transparent); border-color: var(--border-color)">
            <h3 class="text-sm font-semibold" style="color: var(--text-primary)">{emptyStateTitle}</h3>
            <p class="mt-1 text-xs" style="color: var(--text-secondary)">{coverage.message}</p>
            {#if coverage.state === 'verified' && coverage.oldestTimestamp}
              <p class="mt-1 text-[11px]" style="color: var(--text-tertiary)">{formatFreshness(coverage.oldestTimestamp)}</p>
            {:else if coverage.state === 'unknown'}
              <button
                class="mt-3 min-h-9 rounded-md border px-3 text-xs font-medium"
                style="border-color: var(--border-color); color: var(--text-primary)"
                onclick={() => coverage.retry === 'accounts' ? forceSyncPoll() : loadSyncStatus()}
              >{coverage.retry === 'accounts' ? 'Retry accounts' : 'Retry status'}</button>
            {:else if coverage.state === 'unavailable' && $accountsLoaded && $accounts.length === 0}
              <button class="mt-3 min-h-9 rounded-md px-3 text-xs font-medium" style="background: var(--color-accent-500); color: white" onclick={() => currentPage.set('admin')}>Connect an account</button>
            {:else if (coverage.state === 'reauth' || coverage.state === 'unavailable' || coverage.state === 'partial') && firstReconnectAccountId && visibleAccountsWithoutScope.length === 0 && reauthStatuses.length === 0}
              <button class="mt-3 min-h-9 rounded-md px-3 text-xs font-medium" style="background: var(--color-accent-500); color: white" onclick={() => reauthorize(firstReconnectAccountId)}>Reconnect Calendar</button>
            {/if}
          </div>
        </div>
      {/if}
    {/if}
  </div>
</div>

<!-- Event detail modal -->
{#if selectedEvent}
  <CalendarEventDetail
    event={selectedEvent}
    returnFocus={selectedEventOpener}
    onclose={closeEventDetail}
  />
{/if}

<style>
  @media (max-width: 767px) {
    .calendar-toolbar {
      align-items: stretch;
      flex-direction: column;
      gap: 0.5rem;
      padding: 0.5rem;
    }
    .calendar-date-nav {
      width: 100%;
    }
    .calendar-heading {
      font-size: 0.95rem;
    }
    .event-count {
      display: none;
    }
    .calendar-controls {
      width: 100%;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 0.5rem;
      overflow: visible;
    }
    .account-filter {
      grid-column: 1 / -1;
      min-width: 0;
      max-width: 100%;
      width: 100%;
      margin-right: 0;
    }
    .account-filter > button {
      flex: none;
    }
    .calendar-controls > .w-px {
      display: none;
    }
    .calendar-actions {
      min-width: 0;
    }
    .calendar-control-button,
    .calendar-nav-button,
    .notice-action {
      min-height: 44px;
    }
    .view-toggle {
      justify-self: end;
    }
    .view-toggle button {
      min-width: 54px;
      padding-left: 0.65rem;
      padding-right: 0.65rem;
    }
    .calendar-controls button,
    .calendar-notice button {
      white-space: nowrap;
    }
    .calendar-notice > div,
    .calendar-notice {
      align-items: flex-start;
    }
    .timezone-label {
      display: block;
      font-size: 9px;
    }
    .state-card {
      max-width: calc(100vw - 2rem);
    }
    .state-card button {
      min-height: 44px;
    }
    .mobile-week-option {
      display: none;
    }
  }

  @media (max-width: 390px) {
    .action-label {
      display: none;
    }
    .calendar-actions > :first-child {
      width: 44px;
      justify-content: center;
      padding-left: 0;
      padding-right: 0;
    }
  }
</style>
