<script>
  let {
    variant = 'default',
    size = 'md',
    disabled = false,
    onclick = null,
    type = 'button',
    class: className = '',
    children,
  } = $props();

  const baseStyles = 'inline-flex items-center justify-center font-medium rounded-lg transition-fast focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-50 disabled:cursor-not-allowed';

  const variants = {
    primary: 'bg-accent-600 text-white hover:bg-accent-700 focus-visible:outline-accent-500',
    default: 'border hover:opacity-80',
    ghost: 'hover:opacity-80',
    danger: 'bg-red-600 text-white hover:bg-red-700',
  };

  const sizes = {
    sm: 'h-7 px-2.5 text-xs gap-1.5',
    md: 'h-9 px-3.5 text-sm gap-2',
    lg: 'h-11 px-5 text-base gap-2.5',
  };
</script>

<button
  {type}
  {disabled}
  onclick={onclick}
  class="{baseStyles} {variants[variant]} {sizes[size]} {className}"
  style={variant === 'default' ? 'background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-primary)' : variant === 'ghost' ? 'color: var(--text-secondary)' : ''}
>
  {@render children()}
</button>
