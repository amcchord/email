<script>
  import Icon from './Icon.svelte';
  let { open = false, onclose = null, title = '', children } = $props();

  function handleBackdrop(e) {
    if (e.target === e.currentTarget && onclose) {
      onclose();
    }
  }

  function handleKeydown(e) {
    if (e.key === 'Escape' && onclose) {
      onclose();
    }
  }
</script>

<svelte:window onkeydown={handleKeydown} />

{#if open}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="fixed inset-0 z-50 flex items-center justify-center p-4"
    onclick={handleBackdrop}
  >
    <div class="absolute inset-0 bg-black/40 dark:bg-black/60"></div>
    <div
      class="relative w-full max-w-lg rounded-xl shadow-xl border animate-modal"
      style="background: var(--bg-secondary); border-color: var(--border-color)"
    >
      {#if title}
        <div class="flex items-center justify-between px-5 py-4 border-b" style="border-color: var(--border-color)">
          <h2 class="text-base font-semibold" style="color: var(--text-primary)">{title}</h2>
          <button onclick={onclose} class="p-1 rounded-md transition-fast" style="color: var(--text-tertiary)" aria-label="Close">
            <Icon name="x" size={20} />
          </button>
        </div>
      {/if}
      <div class="p-5">
        {@render children()}
      </div>
    </div>
  </div>
{/if}

<style>
  .animate-modal {
    animation: modalIn 200ms cubic-bezier(0.4, 0, 0.2, 1);
  }
  @keyframes modalIn {
    from { opacity: 0; transform: scale(0.97); }
    to { opacity: 1; transform: scale(1); }
  }
</style>
