<script>
  import feather from 'feather-icons';

  let { name, size = 20, strokeWidth = 2, class: className = '' } = $props();

  function getIconSvg(iconName, iconSize, sw) {
    if (!iconName || !feather.icons[iconName]) {
      return '';
    }
    return feather.icons[iconName].toSvg({
      width: iconSize,
      height: iconSize,
      'stroke-width': sw,
      class: className
    });
  }
</script>

{@html getIconSvg(name, size, strokeWidth)}
