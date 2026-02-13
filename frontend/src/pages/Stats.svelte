<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { showToast } from '../lib/stores.js';

  let stats = $state(null);
  let loading = $state(true);

  onMount(async () => {
    try {
      stats = await api.getStats();
    } catch (err) {
      showToast(err.message, 'error');
    }
    loading = false;
  });

  function maxCount(data, key) {
    if (!data || data.length === 0) return 1;
    return Math.max(...data.map(d => d[key]), 1);
  }

  const categoryColors = {
    urgent: '#ef4444',
    can_ignore: '#9ca3af',
    fyi: '#10b981',
    awaiting_reply: '#f59e0b',
  };

  function categoryLabel(cat) {
    if (!cat) return 'Unknown';
    return cat.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }
</script>

<div class="h-full overflow-y-auto" style="background: var(--bg-primary)">
  {#if loading}
    <div class="flex items-center justify-center h-full">
      <div class="w-6 h-6 border-2 rounded-full animate-spin" style="border-color: var(--border-color); border-top-color: var(--color-accent-500)"></div>
    </div>
  {:else if stats}
    <div class="max-w-6xl mx-auto p-6 space-y-6">
      <h2 class="text-xl font-bold" style="color: var(--text-primary)">Email Statistics</h2>

      <!-- Summary Cards -->
      <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div class="rounded-xl border p-4" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <div class="text-2xl font-bold" style="color: var(--text-primary)">{(stats.total_emails || 0).toLocaleString()}</div>
          <div class="text-xs mt-1" style="color: var(--text-secondary)">Total Emails</div>
        </div>
        <div class="rounded-xl border p-4" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <div class="text-2xl font-bold" style="color: var(--text-primary)">{(stats.total_unread || 0).toLocaleString()}</div>
          <div class="text-xs mt-1" style="color: var(--text-secondary)">Unread</div>
        </div>
        <div class="rounded-xl border p-4" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <div class="text-2xl font-bold" style="color: var(--text-primary)">{(stats.total_starred || 0).toLocaleString()}</div>
          <div class="text-xs mt-1" style="color: var(--text-secondary)">Starred</div>
        </div>
        <div class="rounded-xl border p-4" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <div class="text-2xl font-bold" style="color: var(--text-primary)">{stats.emails_per_day_avg || 0}</div>
          <div class="text-xs mt-1" style="color: var(--text-secondary)">Avg/Day (30d)</div>
        </div>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <!-- Volume Chart (Bar) -->
        <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <h3 class="text-sm font-semibold mb-4" style="color: var(--text-primary)">Email Volume (Last 30 Days)</h3>
          {#if stats.volume_by_day && stats.volume_by_day.length > 0}
            <div class="flex items-end gap-px h-40">
              {#each stats.volume_by_day as day}
                {@const max = maxCount(stats.volume_by_day, 'count')}
                {@const height = Math.max((day.count / max) * 100, 2)}
                <div class="flex-1 flex flex-col items-center group relative">
                  <div
                    class="w-full rounded-t transition-all duration-200"
                    style="height: {height}%; background: var(--color-accent-500); opacity: 0.8; min-height: 2px"
                  ></div>
                  <!-- Tooltip -->
                  <div class="absolute bottom-full mb-1 px-2 py-1 rounded text-[10px] font-medium opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap" style="background: var(--bg-tertiary); color: var(--text-primary); box-shadow: var(--shadow-md)">
                    {day.date}: {day.count}
                  </div>
                </div>
              {/each}
            </div>
            <div class="flex justify-between mt-2">
              <span class="text-[10px]" style="color: var(--text-tertiary)">
                {stats.volume_by_day[0]?.date || ''}
              </span>
              <span class="text-[10px]" style="color: var(--text-tertiary)">
                {stats.volume_by_day[stats.volume_by_day.length - 1]?.date || ''}
              </span>
            </div>
          {:else}
            <div class="h-40 flex items-center justify-center">
              <p class="text-sm" style="color: var(--text-tertiary)">No data yet</p>
            </div>
          {/if}
        </div>

        <!-- Top Senders -->
        <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <h3 class="text-sm font-semibold mb-4" style="color: var(--text-primary)">Top Senders</h3>
          {#if stats.top_senders && stats.top_senders.length > 0}
            <div class="space-y-2">
              {#each stats.top_senders as sender, i}
                {@const max = stats.top_senders[0].count}
                {@const width = Math.max((sender.count / max) * 100, 5)}
                <div class="flex items-center gap-3">
                  <span class="text-xs w-5 text-right font-medium" style="color: var(--text-tertiary)">{i + 1}</span>
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 mb-0.5">
                      <span class="text-xs truncate font-medium" style="color: var(--text-primary)">{sender.name}</span>
                      <span class="text-[10px] ml-auto shrink-0" style="color: var(--text-tertiary)">{sender.count}</span>
                    </div>
                    <div class="h-1.5 rounded-full overflow-hidden" style="background: var(--bg-tertiary)">
                      <div class="h-full rounded-full" style="width: {width}%; background: var(--color-accent-500); opacity: {1 - i * 0.07}"></div>
                    </div>
                  </div>
                </div>
              {/each}
            </div>
          {:else}
            <p class="text-sm" style="color: var(--text-tertiary)">No data yet</p>
          {/if}
        </div>

        <!-- Read vs Unread -->
        <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <h3 class="text-sm font-semibold mb-4" style="color: var(--text-primary)">Read vs Unread</h3>
          {#if stats.read_vs_unread}
            {@const total = stats.read_vs_unread.read + stats.read_vs_unread.unread}
            {@const readPct = total > 0 ? Math.round((stats.read_vs_unread.read / total) * 100) : 0}
            <div class="flex items-center gap-6">
              <!-- Simple donut via SVG -->
              <svg width="120" height="120" viewBox="0 0 120 120" class="shrink-0">
                <circle cx="60" cy="60" r="50" fill="none" stroke="var(--bg-tertiary)" stroke-width="14" />
                {#if total > 0}
                  <circle
                    cx="60" cy="60" r="50"
                    fill="none"
                    stroke="var(--color-accent-500)"
                    stroke-width="14"
                    stroke-dasharray="{readPct * 3.14} {(100 - readPct) * 3.14}"
                    stroke-dashoffset="78.5"
                    stroke-linecap="round"
                  />
                {/if}
                <text x="60" y="56" text-anchor="middle" font-size="20" font-weight="700" fill="var(--text-primary)">{readPct}%</text>
                <text x="60" y="72" text-anchor="middle" font-size="10" fill="var(--text-tertiary)">read</text>
              </svg>
              <div class="space-y-3">
                <div>
                  <div class="flex items-center gap-2">
                    <span class="w-3 h-3 rounded-full" style="background: var(--color-accent-500)"></span>
                    <span class="text-sm font-medium" style="color: var(--text-primary)">Read</span>
                  </div>
                  <span class="text-lg font-bold ml-5" style="color: var(--text-primary)">{(stats.read_vs_unread.read || 0).toLocaleString()}</span>
                </div>
                <div>
                  <div class="flex items-center gap-2">
                    <span class="w-3 h-3 rounded-full" style="background: var(--bg-tertiary)"></span>
                    <span class="text-sm font-medium" style="color: var(--text-primary)">Unread</span>
                  </div>
                  <span class="text-lg font-bold ml-5" style="color: var(--text-primary)">{(stats.read_vs_unread.unread || 0).toLocaleString()}</span>
                </div>
              </div>
            </div>
          {/if}
        </div>

        <!-- AI Category Distribution -->
        <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <h3 class="text-sm font-semibold mb-4" style="color: var(--text-primary)">AI Categories</h3>
          {#if stats.category_distribution && stats.category_distribution.length > 0}
            <div class="space-y-2">
              {#each stats.category_distribution as cat}
                {@const max = maxCount(stats.category_distribution, 'count')}
                {@const width = Math.max((cat.count / max) * 100, 5)}
                <div>
                  <div class="flex items-center justify-between mb-0.5">
                    <span class="text-xs font-medium" style="color: var(--text-primary)">{categoryLabel(cat.category)}</span>
                    <span class="text-xs" style="color: var(--text-tertiary)">{cat.count}</span>
                  </div>
                  <div class="h-2 rounded-full overflow-hidden" style="background: var(--bg-tertiary)">
                    <div class="h-full rounded-full" style="width: {width}%; background: {categoryColors[cat.category] || 'var(--color-accent-500)'}"></div>
                  </div>
                </div>
              {/each}
            </div>
          {:else}
            <div class="flex flex-col items-center justify-center py-8">
              <p class="text-sm" style="color: var(--text-tertiary)">No AI analyses yet</p>
              <p class="text-xs mt-1" style="color: var(--text-tertiary)">Configure Claude API key in Settings to enable</p>
            </div>
          {/if}
        </div>
      </div>
    </div>
  {/if}
</div>
