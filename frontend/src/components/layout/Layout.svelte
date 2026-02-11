<script>
  import Sidebar from './Sidebar.svelte';
  import TopBar from './TopBar.svelte';
  import { sidebarCollapsed } from '../../lib/stores.js';

  let { children } = $props();
</script>

<div class="h-screen flex overflow-hidden" style="background: var(--bg-primary)">
  <Sidebar />
  <div class="flex-1 flex flex-col min-w-0">
    <TopBar />
    <main class="flex-1 overflow-hidden">
      {@render children()}
    </main>
  </div>
</div>
