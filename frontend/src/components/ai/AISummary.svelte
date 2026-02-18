<script>
  import Icon from '../common/Icon.svelte';
  let { summary = '', actionItems = [], suggestedReply = '', replyOptions = null, onSelectReplyOption = null } = $props();

  const intentStyles = {
    accept: {
      bg: 'bg-emerald-50 dark:bg-emerald-500/20',
      border: 'border-emerald-200 dark:border-emerald-500/30',
      text: 'text-emerald-700 dark:text-emerald-300',
      hoverBg: 'hover:bg-emerald-100 dark:hover:bg-emerald-500/20',
      icon: 'check',
    },
    decline: {
      bg: 'bg-red-50 dark:bg-red-500/20',
      border: 'border-red-200 dark:border-red-500/30',
      text: 'text-red-700 dark:text-red-300',
      hoverBg: 'hover:bg-red-100 dark:hover:bg-red-500/20',
      icon: 'x',
    },
    defer: {
      bg: 'bg-amber-50 dark:bg-amber-500/20',
      border: 'border-amber-200 dark:border-amber-500/30',
      text: 'text-amber-700 dark:text-amber-300',
      hoverBg: 'hover:bg-amber-100 dark:hover:bg-amber-500/20',
      icon: 'clock',
    },
    not_relevant: {
      bg: 'bg-gray-50 dark:bg-gray-700/40',
      border: 'border-gray-200 dark:border-gray-700',
      text: 'text-gray-600 dark:text-gray-300',
      hoverBg: 'hover:bg-gray-100 dark:hover:bg-gray-700/50',
      icon: 'minus',
    },
    custom: {
      bg: 'bg-blue-50 dark:bg-blue-500/20',
      border: 'border-blue-200 dark:border-blue-500/30',
      text: 'text-blue-700 dark:text-blue-300',
      hoverBg: 'hover:bg-blue-100 dark:hover:bg-blue-500/20',
      icon: 'reply',
    },
  };

  function getStyle(intent) {
    return intentStyles[intent] || intentStyles.custom;
  }

  function handleOptionClick(option) {
    if (onSelectReplyOption) {
      onSelectReplyOption(option);
    }
  }
</script>

{#if summary}
  <div class="rounded-lg border p-4 space-y-3" style="background: var(--bg-tertiary); border-color: var(--border-color)">
    <div class="flex items-center gap-2">
      <span class="text-xs font-semibold tracking-wider uppercase" style="color: var(--color-accent-600)">AI Analysis</span>
    </div>

    <p class="text-sm" style="color: var(--text-primary)">{summary}</p>

    {#if actionItems.length > 0}
      <div>
        <span class="text-xs font-semibold" style="color: var(--text-secondary)">Action Items</span>
        <ul class="mt-1 space-y-1">
          {#each actionItems as item}
            <li class="text-sm flex items-start gap-2" style="color: var(--text-primary)">
              <span class="mt-1.5 w-1.5 h-1.5 rounded-full bg-accent-500 shrink-0"></span>
              {item}
            </li>
          {/each}
        </ul>
      </div>
    {/if}

    {#if replyOptions && replyOptions.length > 0}
      <div>
        <span class="text-xs font-semibold" style="color: var(--text-secondary)">Quick Replies</span>
        <div class="mt-2 flex flex-wrap gap-2">
          {#each replyOptions as option}
            {@const style = getStyle(option.intent)}
            <button
              onclick={() => handleOptionClick(option)}
              class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all duration-150 cursor-pointer {style.bg} {style.border} {style.text} {style.hoverBg}"
              title={option.body}
            >
              {#if option.intent === 'accept'}
                <Icon name="check" size={14} />
              {:else if option.intent === 'decline'}
                <Icon name="x" size={14} />
              {:else if option.intent === 'defer'}
                <Icon name="clock" size={14} />
              {:else if option.intent === 'not_relevant'}
                <Icon name="slash" size={14} />
              {:else}
                <Icon name="corner-up-left" size={14} />
              {/if}
              {option.label}
            </button>
          {/each}
        </div>
      </div>
    {:else if suggestedReply}
      <div>
        <span class="text-xs font-semibold" style="color: var(--text-secondary)">Suggested Reply</span>
        <p class="mt-1 text-sm italic" style="color: var(--text-secondary)">"{suggestedReply}"</p>
      </div>
    {/if}
  </div>
{/if}
