<script>
  let { category = '' } = $props();

  const styles = {
    urgent: { bg: 'bg-red-100 dark:bg-red-500/20', text: 'text-red-700 dark:text-red-300', label: 'Urgent' },
    can_ignore: { bg: 'bg-gray-100 dark:bg-gray-700/50', text: 'text-gray-600 dark:text-gray-300', label: 'Can Ignore' },
    fyi: { bg: 'bg-emerald-100 dark:bg-emerald-500/20', text: 'text-emerald-700 dark:text-emerald-300', label: 'FYI' },
    awaiting_reply: { bg: 'bg-amber-100 dark:bg-amber-500/20', text: 'text-amber-700 dark:text-amber-300', label: 'Awaiting Reply' },
  };

  let style = $derived(styles[category] || { bg: 'bg-gray-100', text: 'text-gray-600', label: category });
</script>

{#if category}
  <span class="inline-flex items-center text-[11px] px-2 py-0.5 rounded-full font-medium {style.bg} {style.text}">
    {style.label}
  </span>
{/if}
