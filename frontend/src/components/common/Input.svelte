<script>
  let {
    type = 'text',
    value = $bindable(''),
    placeholder = '',
    label = '',
    id = '',
    disabled = false,
    class: className = '',
  } = $props();

  let inputId = $derived(id || `input-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-') || 'field'}`);
</script>

<div class="flex flex-col gap-1.5 {className}">
  {#if label}
    <label for={inputId} class="text-xs font-medium tracking-wide uppercase" style="color: var(--text-secondary)">{label}</label>
  {/if}
  <input
    {type}
    id={inputId}
    bind:value
    {placeholder}
    {disabled}
    class="h-9 px-3 rounded-lg text-sm outline-none border transition-fast w-full"
    style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
  />
</div>
