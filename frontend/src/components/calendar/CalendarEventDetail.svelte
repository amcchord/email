<script>
  import { onMount } from 'svelte';
  import { accountColorMap } from '../../lib/stores.js';
  import Icon from '../common/Icon.svelte';
  import { inclusiveAllDayEnd, isWebLocation, videoCallUrl } from '../../lib/calendarDisplay.js';

  let { event, onclose = null, returnFocus = null } = $props();
  let dialog = $state(null);
  let closeButton = $state(null);
  const titleId = 'calendar-event-detail-title';

  function displayTimeZone() {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    } catch {
      return 'UTC';
    }
  }

  function close() {
    onclose?.();
  }

  function handleDialogKeydown(keyEvent) {
    if (keyEvent.key === 'Escape') {
      keyEvent.preventDefault();
      close();
      return;
    }
    if (keyEvent.key !== 'Tab' || !dialog) return;
    const focusable = [...dialog.querySelectorAll(
      'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'
    )].filter(element => !element.hasAttribute('hidden'));
    if (focusable.length === 0) {
      keyEvent.preventDefault();
      dialog.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable.at(-1);
    if (keyEvent.shiftKey && document.activeElement === first) {
      keyEvent.preventDefault();
      last.focus();
    } else if (!keyEvent.shiftKey && document.activeElement === last) {
      keyEvent.preventDefault();
      first.focus();
    }
  }

  onMount(() => {
    const fallbackFocus = document.activeElement;
    closeButton?.focus();
    return () => {
      const target = returnFocus?.isConnected ? returnFocus : fallbackFocus;
      target?.focus?.();
    };
  });

  function formatDateTime(dt) {
    if (!dt) return '';
    const d = new Date(dt);
    return d.toLocaleDateString('en-US', {
      weekday: 'long',
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    }) + ' at ' + d.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
    });
  }

  function formatDateOnly(dateStr) {
    if (!dateStr) return '';
    const [y, m, d] = dateStr.split('-').map(Number);
    const dt = new Date(y, m - 1, d);
    return dt.toLocaleDateString('en-US', {
      weekday: 'long',
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    });
  }

  function formatTimeRange() {
    if (event.is_all_day) {
      const start = formatDateOnly(event.start_date);
      const end = formatDateOnly(inclusiveAllDayEnd(event.start_date, event.end_date));
      if (start === end || !event.end_date) return `${start} (All day)`;
      return `${start} - ${end} (All day)`;
    }
    const start = formatDateTime(event.start_time);
    const startDate = event.start_time ? new Date(event.start_time) : null;
    const endDate = event.end_time ? new Date(event.end_time) : null;
    const sameLocalDay = startDate && endDate
      && startDate.getFullYear() === endDate.getFullYear()
      && startDate.getMonth() === endDate.getMonth()
      && startDate.getDate() === endDate.getDate();
    const end = endDate
      ? (sameLocalDay
        ? endDate.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
        : formatDateTime(event.end_time))
      : '';
    return end ? `${start} - ${end}` : start;
  }

  function responseStatusIcon(status) {
    if (status === 'accepted') return { icon: '\u2713', color: 'var(--status-success)' };
    if (status === 'declined') return { icon: '\u2717', color: 'var(--status-error)' };
    if (status === 'tentative') return { icon: '?', color: 'var(--status-warning)' };
    return { icon: '\u2022', color: 'var(--text-tertiary)' };
  }

  let acctColor = $derived($accountColorMap[event.account_email] || null);
</script>

<div class="fixed inset-0 z-50 flex items-center justify-center">
  <button class="absolute inset-0 bg-black/40" onclick={close} aria-label="Close event details" tabindex="-1"></button>
  <div
    bind:this={dialog}
    class="event-detail-dialog relative z-10 w-full max-w-lg max-h-[80vh] overflow-y-auto rounded-xl border shadow-2xl"
    style="background: var(--bg-primary); border-color: var(--border-color)"
    role="dialog"
    aria-modal="true"
    aria-labelledby={titleId}
    tabindex="-1"
    onkeydown={handleDialogKeydown}
  >
    <!-- Header -->
    <div class="flex items-start justify-between p-5 border-b" style="border-color: var(--border-color)">
      <div class="flex-1 min-w-0 pr-4">
        <h2 id={titleId} class="text-lg font-semibold leading-tight" style="color: var(--text-primary)">
          {event.summary || '(No title)'}
        </h2>
        {#if event._mergedAccounts && event._mergedAccounts.length > 1}
          <div class="flex flex-col gap-1 mt-1.5">
            {#each event._mergedAccounts as acctEmail}
              {@const mc = $accountColorMap[acctEmail]}
              <div class="flex items-center gap-1.5">
                <span
                  class="w-2 h-2 rounded-full shrink-0"
                  style="background: {mc ? mc.bg : 'var(--color-accent-500)'}"
                ></span>
                <span class="text-xs" style="color: var(--text-tertiary)">{acctEmail}</span>
              </div>
            {/each}
          </div>
        {:else if event.account_email}
          <div class="flex items-center gap-1.5 mt-1.5">
            <span
              class="w-2 h-2 rounded-full shrink-0"
              style="background: {acctColor ? acctColor.bg : 'var(--color-accent-500)'}"
            ></span>
            <span class="text-xs" style="color: var(--text-tertiary)">{event.account_email}</span>
          </div>
        {/if}
      </div>
      <button
        bind:this={closeButton}
        onclick={close}
        class="event-detail-close p-1 rounded-md transition-fast"
        style="color: var(--text-tertiary)"
        aria-label="Close"
      >
        <Icon name="x" size={20} />
      </button>
    </div>

    <!-- Content -->
    <div class="p-5 space-y-4">
      <!-- Time -->
      <div class="flex items-start gap-3">
        <span class="shrink-0 mt-0.5" style="color: var(--text-tertiary)">
          <Icon name="clock" size={20} />
        </span>
        <div>
          <div class="text-sm" style="color: var(--text-primary)">{formatTimeRange()}</div>
          <div class="text-xs mt-0.5" style="color: var(--text-tertiary)">
            Times shown in {displayTimeZone().replaceAll('_', ' ')}{event.timezone && event.timezone !== displayTimeZone() ? ` · Original timezone: ${event.timezone.replaceAll('_', ' ')}` : ''}
          </div>
        </div>
      </div>

      <!-- Location -->
      {#if event.location && !isWebLocation(event.location)}
        <div class="flex items-start gap-3">
          <span class="shrink-0 mt-0.5" style="color: var(--text-tertiary)">
            <Icon name="map-pin" size={20} />
          </span>
          <span class="text-sm" style="color: var(--text-primary)">{event.location}</span>
        </div>
      {/if}

      <!-- Video call link -->
      {#if videoCallUrl(event)}
        <div class="flex items-center gap-3">
          <span class="shrink-0" style="color: var(--text-tertiary)">
            <Icon name="video" size={20} />
          </span>
          <a
            href={videoCallUrl(event)}
            target="_blank"
            rel="noopener noreferrer"
            class="text-sm font-medium underline"
            style="color: var(--color-accent-500)"
          >Join video call</a>
        </div>
      {/if}

      <!-- Description -->
      {#if event.description}
        <div class="pt-2 border-t" style="border-color: var(--border-color)">
          <div class="text-sm whitespace-pre-wrap" style="color: var(--text-secondary)">
            {event.description}
          </div>
        </div>
      {/if}

      <!-- Attendees -->
      {#if event.attendees && event.attendees.length > 0}
        <div class="pt-2 border-t" style="border-color: var(--border-color)">
          <h3 class="text-xs font-semibold uppercase tracking-wider mb-2" style="color: var(--text-tertiary)">
            Attendees ({event.attendees.length})
          </h3>
          <div class="space-y-1.5">
            {#each event.attendees as attendee}
              {@const rs = responseStatusIcon(attendee.response_status)}
              <div class="flex items-center gap-2">
                <span class="text-sm font-bold" style="color: {rs.color}">{rs.icon}</span>
                <div class="flex-1 min-w-0">
                  <span class="text-sm" style="color: var(--text-primary)">
                    {attendee.name || attendee.email}
                    {#if attendee.self}
                      <span class="text-xs" style="color: var(--text-tertiary)">(you)</span>
                    {/if}
                  </span>
                  {#if attendee.name && attendee.email}
                    <span class="text-xs ml-1" style="color: var(--text-tertiary)">{attendee.email}</span>
                  {/if}
                </div>
              </div>
            {/each}
          </div>
        </div>
      {/if}

      <!-- Open in Google Calendar -->
      {#if event.html_link}
        <div class="pt-3 border-t" style="border-color: var(--border-color)">
          <a
            href={event.html_link}
            target="_blank"
            rel="noopener noreferrer"
            class="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-fast"
            style="background: var(--bg-tertiary); color: var(--text-secondary)"
          >
            <Icon name="external-link" size={16} />
            Open in Google Calendar
          </a>
        </div>
      {/if}
    </div>
  </div>
</div>

<style>
  .event-detail-close {
    min-width: 40px;
    min-height: 40px;
  }

  @media (max-width: 767px) {
    .event-detail-dialog {
      width: calc(100% - 1rem);
      max-height: calc(100vh - 1rem);
    }
    .event-detail-close {
      min-width: 44px;
      min-height: 44px;
    }
  }
</style>
