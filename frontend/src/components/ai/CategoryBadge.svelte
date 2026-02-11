<script>
  let { category = '' } = $props();

  const styles = {
    needs_response: { bg: 'bg-blue-100 dark:bg-blue-900/40', text: 'text-blue-700 dark:text-blue-400', label: 'Needs Response' },
    urgent: { bg: 'bg-red-100 dark:bg-red-900/40', text: 'text-red-700 dark:text-red-400', label: 'Urgent' },
    can_ignore: { bg: 'bg-gray-100 dark:bg-gray-800', text: 'text-gray-600 dark:text-gray-400', label: 'Can Ignore' },
    fyi: { bg: 'bg-emerald-100 dark:bg-emerald-900/40', text: 'text-emerald-700 dark:text-emerald-400', label: 'FYI' },
    awaiting_reply: { bg: 'bg-amber-100 dark:bg-amber-900/40', text: 'text-amber-700 dark:text-amber-400', label: 'Awaiting Reply' },
  };

  let style = $derived(styles[category] || { bg: 'bg-gray-100', text: 'text-gray-600', label: category });
</script>

{#if category}
  <span class="inline-flex items-center text-[11px] px-2 py-0.5 rounded-full font-medium {style.bg} {style.text}">
    {style.label}
  </span>
{/if}
