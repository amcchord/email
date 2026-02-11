<script>
  let { message = '', type = 'info' } = $props();

  const colors = {
    success: 'bg-emerald-600 text-white',
    error: 'bg-red-600 text-white',
    info: 'bg-surface-800 text-white dark:bg-surface-200 dark:text-surface-900',
    warning: 'bg-amber-600 text-white',
  };
</script>

<div class="fixed bottom-6 right-6 z-50 animate-in" role="alert">
  <div class="px-4 py-3 rounded-lg shadow-lg text-sm font-medium {colors[type] || colors.info}">
    {message}
  </div>
</div>

<style>
  .animate-in {
    animation: slideUp 200ms cubic-bezier(0.4, 0, 0.2, 1);
  }
  @keyframes slideUp {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
  }
</style>
