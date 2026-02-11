<script>
  let {
    type = 'text',
    value = $bindable(''),
    placeholder = '',
    label = '',
    disabled = false,
    class: className = '',
  } = $props();
</script>

<div class="flex flex-col gap-1.5 {className}">
  {#if label}
    <label class="text-xs font-medium tracking-wide uppercase" style="color: var(--text-secondary)">{label}</label>
  {/if}
  <input
    {type}
    bind:value
    {placeholder}
    {disabled}
    class="h-9 px-3 rounded-lg text-sm outline-none border transition-fast w-full"
    style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
  />
</div>
