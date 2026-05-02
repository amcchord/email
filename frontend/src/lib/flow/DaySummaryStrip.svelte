<!--
  Day Summary Strip — the four "today at a glance" cards at the top of the
  Flow dashboard. Extracted from Flow.svelte to keep that page reviewable.

  Props are pure data + a couple of helpers; nothing is bound back. The
  component is read-only, so any state changes still happen in the parent.
-->
<script>
  import Icon from '../../components/common/Icon.svelte';

  let {
    upcomingEvents = [],
    pendingTodos = [],
    needsReplyTotal = 0,
    needsReplyEmails = [],
    urgentCount = 0,
    trendsSummary = '',
    formatEventTime,
    onOpenCalendar,
  } = $props();
</script>

<div class="flex flex-wrap gap-3">
  <div class="flex-1 min-w-[200px] rounded-xl border p-4" style="background: var(--bg-secondary); border-color: var(--border-color)">
    <div class="flex items-center gap-2 mb-2">
      <div class="w-7 h-7 rounded-lg flex items-center justify-center" style="background: rgba(139, 92, 246, 0.15)">
        <span style="color: #8b5cf6"><Icon name="calendar" size={16} /></span>
      </div>
      <div>
        <div class="text-lg font-bold leading-none" style="color: var(--text-primary)">{upcomingEvents.length}</div>
        <div class="text-[10px] font-medium uppercase tracking-wider" style="color: var(--text-tertiary)">Events Today</div>
      </div>
    </div>
    {#if upcomingEvents.length > 0}
      <div class="space-y-1.5">
        {#each upcomingEvents.slice(0, 3) as evt}
          <div class="flex items-start gap-2 text-xs" style="color: var(--text-secondary)">
            <span class="font-medium shrink-0" style="color: var(--color-accent-600)">{formatEventTime(evt.start_time)}</span>
            <div class="min-w-0">
              <div class="truncate font-medium" style="color: var(--text-primary)">{evt.summary || 'Untitled event'}</div>
              {#if evt.location}
                <div class="text-[10px] truncate" style="color: var(--text-tertiary)">{evt.location}</div>
              {/if}
            </div>
          </div>
        {/each}
        {#if upcomingEvents.length > 3}
          <button
            onclick={onOpenCalendar}
            class="text-[10px] font-medium transition-fast"
            style="color: var(--color-accent-500)"
          >+{upcomingEvents.length - 3} more</button>
        {/if}
      </div>
    {:else}
      <div class="text-xs" style="color: var(--text-tertiary)">No events today</div>
    {/if}
  </div>

  {#if pendingTodos.length > 0}
    <div class="flex-1 min-w-[200px] rounded-xl border p-4" style="background: var(--bg-secondary); border-color: var(--border-color)">
      <div class="flex items-center gap-2 mb-2">
        <div class="w-7 h-7 rounded-lg flex items-center justify-center" style="background: rgba(245, 158, 11, 0.15)">
          <span style="color: var(--status-warning)"><Icon name="check-circle" size={16} /></span>
        </div>
        <div>
          <div class="text-lg font-bold leading-none" style="color: var(--text-primary)">{pendingTodos.length}</div>
          <div class="text-[10px] font-medium uppercase tracking-wider" style="color: var(--text-tertiary)">Pending Tasks</div>
        </div>
      </div>
      <div class="space-y-1">
        {#each pendingTodos.slice(0, 3) as todo}
          <div class="text-xs truncate" style="color: var(--text-secondary)">{todo.title || todo.description || 'Untitled task'}</div>
        {/each}
        {#if pendingTodos.length > 3}
          <div class="text-[10px]" style="color: var(--text-tertiary)">+{pendingTodos.length - 3} more</div>
        {/if}
      </div>
    </div>
  {/if}

  <div class="flex-1 min-w-[200px] rounded-xl border p-4" style="background: var(--bg-secondary); border-color: var(--border-color)">
    <div class="flex items-center gap-2 mb-2">
      <div class="w-7 h-7 rounded-lg flex items-center justify-center" style="background: rgba(59, 130, 246, 0.15)">
        <span style="color: var(--status-info)"><Icon name="corner-up-left" size={16} /></span>
      </div>
      <div>
        <div class="text-lg font-bold leading-none" style="color: var(--text-primary)">{needsReplyTotal}</div>
        <div class="text-[10px] font-medium uppercase tracking-wider" style="color: var(--text-tertiary)">Need Reply</div>
      </div>
    </div>
    {#if needsReplyEmails.length > 0}
      <div class="space-y-1">
        {#each needsReplyEmails.slice(0, 3) as email}
          <div class="text-xs truncate" style="color: var(--text-secondary)">
            <span class="font-medium" style="color: var(--text-primary)">{email.from_name || email.from_address}</span>
          </div>
        {/each}
      </div>
    {:else}
      <div class="text-xs" style="color: var(--text-tertiary)">All caught up</div>
    {/if}
  </div>

  <div class="flex-1 min-w-[200px] rounded-xl border p-4" style="background: var(--bg-secondary); border-color: var(--border-color)">
    <div class="flex items-center gap-2 mb-2">
      <div class="w-7 h-7 rounded-lg flex items-center justify-center" style="background: rgba(239, 68, 68, 0.15)">
        <span style="color: var(--status-error)"><Icon name="alert-triangle" size={16} /></span>
      </div>
      <div>
        <div class="text-lg font-bold leading-none" style="color: var(--text-primary)">{urgentCount}</div>
        <div class="text-[10px] font-medium uppercase tracking-wider" style="color: var(--text-tertiary)">Urgent</div>
      </div>
    </div>
    {#if trendsSummary}
      <div class="text-xs line-clamp-3" style="color: var(--text-secondary)">{trendsSummary}</div>
    {:else}
      <div class="text-xs" style="color: var(--text-tertiary)">No urgent items</div>
    {/if}
  </div>
</div>
