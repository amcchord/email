<script>
  import Sidebar from './Sidebar.svelte';
  import TopBar from './TopBar.svelte';
  import { sidebarCollapsed, currentPage } from '../../lib/stores.js';

  let { children } = $props();

  let showSidebar = $derived($currentPage === 'inbox');
</script>

<div class="h-screen flex flex-col overflow-hidden" style="background: var(--bg-primary)">
  <!-- TopBar always full-width so tabs stay in the same position -->
  <TopBar />
  <div class="flex-1 flex overflow-hidden">
    {#if showSidebar}
      <Sidebar />
    {/if}
    <main class="flex-1 overflow-hidden">
      {@render children()}
    </main>
  </div>
</div>
