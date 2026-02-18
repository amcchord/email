<script>
  import { accountColorMap } from '../../lib/stores.js';
  import Icon from '../common/Icon.svelte';

  let { event, onclose = null } = $props();

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
      const end = formatDateOnly(event.end_date);
      if (start === end || !event.end_date) return `${start} (All day)`;
      return `${start} - ${end} (All day)`;
    }
    const start = formatDateTime(event.start_time);
    const end = event.end_time ? new Date(event.end_time).toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
    }) : '';
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

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<div class="fixed inset-0 z-50 flex items-center justify-center" onclick={onclose}>
  <div class="absolute inset-0 bg-black/40"></div>
  <div
    class="relative z-10 w-full max-w-lg max-h-[80vh] overflow-y-auto rounded-xl border shadow-2xl"
    style="background: var(--bg-primary); border-color: var(--border-color)"
    onclick={(e) => e.stopPropagation()}
  >
    <!-- Header -->
    <div class="flex items-start justify-between p-5 border-b" style="border-color: var(--border-color)">
      <div class="flex-1 min-w-0 pr-4">
        <h2 class="text-lg font-semibold leading-tight" style="color: var(--text-primary)">
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
        onclick={onclose}
        class="p-1 rounded-md transition-fast"
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
          {#if event.timezone}
            <div class="text-xs mt-0.5" style="color: var(--text-tertiary)">{event.timezone}</div>
          {/if}
        </div>
      </div>

      <!-- Location -->
      {#if event.location}
        <div class="flex items-start gap-3">
          <span class="shrink-0 mt-0.5" style="color: var(--text-tertiary)">
            <Icon name="map-pin" size={20} />
          </span>
          <span class="text-sm" style="color: var(--text-primary)">{event.location}</span>
        </div>
      {/if}

      <!-- Video call link -->
      {#if event.hangout_link}
        <div class="flex items-center gap-3">
          <span class="shrink-0" style="color: var(--text-tertiary)">
            <Icon name="video" size={20} />
          </span>
          <a
            href={event.hangout_link}
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
