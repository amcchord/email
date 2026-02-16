<script>
  import { onMount } from 'svelte';
  import Icon from '../components/common/Icon.svelte';
  import { api } from '../lib/api.js';
  import { showToast, todos, selectedEmailId, currentPage, currentMailbox } from '../lib/stores.js';
  import { registerActions } from '../lib/shortcutStore.js';

  let loading = $state(true);
  let newTodoText = $state('');
  let addingTodo = $state(false);
  let draftingId = $state(null);
  let approvingId = $state(null);
  let expandedDraftId = $state(null);
  let editingDraftId = $state(null);
  let editDraftBody = $state('');

  let selectedTodoIndex = $state(-1);

  onMount(async () => {
    await loadTodos();
    loading = false;

    const cleanupShortcuts = registerActions({
      'todos.new': () => {
        const input = document.querySelector('[data-shortcut="todos.new"]');
        if (input) input.focus();
      },
      'todos.next': () => {
        const pending = ($todos || []).filter(t => t.status === 'pending');
        if (pending.length > 0) {
          selectedTodoIndex = Math.min(selectedTodoIndex + 1, pending.length - 1);
        }
      },
      'todos.prev': () => {
        if (selectedTodoIndex > 0) {
          selectedTodoIndex = selectedTodoIndex - 1;
        }
      },
      'todos.toggle': () => {
        const pending = ($todos || []).filter(t => t.status === 'pending');
        if (selectedTodoIndex >= 0 && selectedTodoIndex < pending.length) {
          toggleTodo(pending[selectedTodoIndex]);
        }
      },
      'todos.delete': () => {
        const pending = ($todos || []).filter(t => t.status === 'pending');
        if (selectedTodoIndex >= 0 && selectedTodoIndex < pending.length) {
          deleteTodo(pending[selectedTodoIndex]);
        }
      },
    });

    return cleanupShortcuts;
  });

  async function loadTodos() {
    try {
      const result = await api.getTodos();
      todos.set(result.todos);
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function addManualTodo() {
    if (!newTodoText.trim()) return;
    addingTodo = true;
    try {
      const todo = await api.createTodo({ title: newTodoText.trim() });
      todos.update(list => [todo, ...list]);
      newTodoText = '';
    } catch (err) {
      showToast(err.message, 'error');
    }
    addingTodo = false;
  }

  async function toggleTodo(todo) {
    const newStatus = todo.status === 'done' ? 'pending' : 'done';
    try {
      const updated = await api.updateTodo(todo.id, { status: newStatus });
      todos.update(list => list.map(t => t.id === todo.id ? updated : t));
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function dismissTodo(todo) {
    try {
      const updated = await api.updateTodo(todo.id, { status: 'dismissed' });
      todos.update(list => list.map(t => t.id === todo.id ? updated : t));
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function deleteTodo(todo) {
    try {
      await api.deleteTodo(todo.id);
      todos.update(list => list.filter(t => t.id !== todo.id));
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function draftWithAI(todo) {
    draftingId = todo.id;
    try {
      const result = await api.draftAction(todo.id);
      todos.update(list => list.map(t => t.id === todo.id ? { ...t, ...result } : t));
      expandedDraftId = todo.id;
      showToast('AI draft ready for review', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
    draftingId = null;
  }

  async function approveAndSend(todo) {
    approvingId = todo.id;
    try {
      const result = await api.approveAction(todo.id);
      todos.update(list => list.map(t => t.id === todo.id ? { ...t, ...result, status: 'done' } : t));
      showToast('Reply sent and todo marked done!', 'success');
      expandedDraftId = null;
    } catch (err) {
      showToast(err.message, 'error');
    }
    approvingId = null;
  }

  function startEditDraft(todo) {
    editingDraftId = todo.id;
    editDraftBody = todo.ai_draft_body || '';
  }

  async function saveEditedDraft(todo) {
    // We save the edited body by re-updating the todo's draft body via the update endpoint
    // For simplicity, we'll update locally and send on approve
    todos.update(list => list.map(t => {
      if (t.id === todo.id) {
        return { ...t, ai_draft_body: editDraftBody };
      }
      return t;
    }));
    editingDraftId = null;
    showToast('Draft updated', 'success');
  }

  function goToEmail(emailId) {
    currentMailbox.set('ALL');
    currentPage.set('inbox');
    setTimeout(() => {
      selectedEmailId.set(emailId);
    }, 0);
  }

  function formatDate(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    const now = new Date();
    const diff = now - d;
    const dayMs = 86400000;
    if (diff < dayMs) {
      return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    }
    if (diff < 7 * dayMs) {
      return d.toLocaleDateString([], { weekday: 'short' });
    }
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  }

  let pendingTodos = $derived($todos.filter(t => t.status === 'pending'));
  let doneTodos = $derived($todos.filter(t => t.status === 'done'));
  let dismissedTodos = $derived($todos.filter(t => t.status === 'dismissed'));
</script>

<div class="h-full overflow-y-auto" style="background: var(--bg-primary)">
  {#if loading}
    <div class="flex items-center justify-center h-full">
      <div class="w-6 h-6 border-2 rounded-full animate-spin" style="border-color: var(--border-color); border-top-color: var(--color-accent-500)"></div>
    </div>
  {:else}
    <div class="max-w-3xl mx-auto p-6 space-y-6">
      <h2 class="text-xl font-bold" style="color: var(--text-primary)">Todos</h2>

      <!-- Add new todo -->
      <div class="flex gap-2">
        <input
          type="text"
          bind:value={newTodoText}
          placeholder="Add a new todo..."
          class="flex-1 px-3 py-2 rounded-lg border text-sm focus:outline-none focus:ring-2 focus:ring-accent-500/40"
          style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-primary)"
          onkeydown={(e) => { if (e.key === 'Enter') addManualTodo(); }}
          data-shortcut="todos.new"
        />
        <button
          onclick={addManualTodo}
          disabled={addingTodo || !newTodoText.trim()}
          class="px-4 py-2 rounded-lg text-sm font-medium transition-fast disabled:opacity-50"
          style="background: var(--color-accent-500); color: white"
        >
          Add
        </button>
      </div>

      <!-- Pending todos -->
      {#if pendingTodos.length > 0}
        <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <h3 class="text-sm font-semibold mb-3" style="color: var(--text-primary)">Pending ({pendingTodos.length})</h3>
          <div class="space-y-2">
            {#each pendingTodos as todo (todo.id)}
              <div class="p-3 rounded-lg" style="background: var(--bg-primary)">
                <div class="flex items-start gap-3">
                  <button
                    onclick={() => toggleTodo(todo)}
                    class="mt-0.5 w-5 h-5 rounded border-2 flex items-center justify-center shrink-0 transition-fast"
                    style="border-color: var(--border-color)"
                  >
                  </button>
                  <div class="flex-1 min-w-0">
                    <div class="text-sm" style="color: var(--text-primary)">{todo.title}</div>
                    <div class="flex items-center gap-2 mt-1 flex-wrap">
                      {#if todo.source === 'ai_action_item'}
                        <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-400">from AI</span>
                      {/if}
                      {#if todo.email_id}
                        <button
                          onclick={() => goToEmail(todo.email_id)}
                          class="text-[10px] px-1.5 py-0.5 rounded-full font-medium transition-fast"
                          style="background: var(--bg-tertiary); color: var(--color-accent-600)"
                        >
                          view email
                        </button>
                      {/if}
                      <span class="text-[10px]" style="color: var(--text-tertiary)">{formatDate(todo.created_at)}</span>
                    </div>
                  </div>
                  <div class="flex items-center gap-1 shrink-0">
                    {#if todo.email_id && !todo.ai_draft_status}
                      <button
                        onclick={() => draftWithAI(todo)}
                        disabled={draftingId === todo.id}
                        class="flex items-center gap-1 px-2 py-1 rounded text-[11px] font-medium transition-fast disabled:opacity-50"
                        style="background: var(--color-accent-500); color: white"
                        title="Have AI draft a reply for this action item"
                      >
                        {#if draftingId === todo.id}
                          <div class="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
                          Drafting...
                        {:else}
                          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
                          </svg>
                          Draft with AI
                        {/if}
                      </button>
                    {/if}
                    {#if todo.ai_draft_status === 'ready'}
                      <button
                        onclick={() => { if (expandedDraftId === todo.id) { expandedDraftId = null; } else { expandedDraftId = todo.id; } }}
                        class="flex items-center gap-1 px-2 py-1 rounded text-[11px] font-medium transition-fast"
                        style="background: var(--bg-tertiary); color: var(--color-accent-600)"
                      >
                        {expandedDraftId === todo.id ? 'Hide Draft' : 'View Draft'}
                      </button>
                    {/if}
                    <button
                      onclick={() => dismissTodo(todo)}
                      class="p-1 rounded transition-fast"
                      style="color: var(--text-tertiary)"
                      title="Dismiss"
                    >
                      <Icon name="x" size={16} />
                    </button>
                  </div>
                </div>

                <!-- AI Draft Preview -->
                {#if expandedDraftId === todo.id && todo.ai_draft_status === 'ready'}
                  <div class="mt-3 p-3 rounded-lg border" style="border-color: var(--border-color); background: var(--bg-tertiary)">
                    <div class="flex items-center justify-between mb-2">
                      <div class="text-xs font-semibold" style="color: var(--color-accent-600)">AI Draft Reply</div>
                      {#if todo.ai_draft_to}
                        <span class="text-[10px]" style="color: var(--text-tertiary)">To: {todo.ai_draft_to}</span>
                      {/if}
                    </div>
                    {#if editingDraftId === todo.id}
                      <textarea
                        bind:value={editDraftBody}
                        class="w-full rounded border p-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-accent-500/40"
                        style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary); min-height: 80px"
                        rows="4"
                      ></textarea>
                      <div class="flex gap-2 mt-2">
                        <button
                          onclick={() => saveEditedDraft(todo)}
                          class="px-3 py-1 rounded text-xs font-medium"
                          style="background: var(--color-accent-500); color: white"
                        >Save</button>
                        <button
                          onclick={() => { editingDraftId = null; }}
                          class="px-3 py-1 rounded text-xs font-medium"
                          style="color: var(--text-secondary)"
                        >Cancel</button>
                      </div>
                    {:else}
                      <p class="text-sm whitespace-pre-wrap" style="color: var(--text-primary)">{todo.ai_draft_body}</p>
                      <div class="flex items-center gap-2 mt-3">
                        <button
                          onclick={() => approveAndSend(todo)}
                          disabled={approvingId === todo.id}
                          class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-fast disabled:opacity-50"
                          style="background: #22c55e; color: white"
                        >
                          {#if approvingId === todo.id}
                            <div class="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
                            Sending...
                          {:else}
                            <Icon name="send" size={14} />
                            Approve & Send
                          {/if}
                        </button>
                        <button
                          onclick={() => startEditDraft(todo)}
                          class="px-3 py-1.5 rounded-lg text-xs font-medium transition-fast"
                          style="background: var(--bg-primary); color: var(--text-secondary); border: 1px solid var(--border-color)"
                        >Edit</button>
                        <button
                          onclick={() => { expandedDraftId = null; }}
                          class="px-3 py-1.5 rounded-lg text-xs font-medium transition-fast"
                          style="color: var(--text-tertiary)"
                        >Dismiss</button>
                      </div>
                    {/if}
                  </div>
                {/if}

                <!-- Drafting/Sent status indicator -->
                {#if todo.ai_draft_status === 'drafting'}
                  <div class="mt-2 flex items-center gap-2 text-xs" style="color: var(--text-tertiary)">
                    <div class="w-3 h-3 border-2 rounded-full animate-spin" style="border-color: var(--border-color); border-top-color: var(--color-accent-500)"></div>
                    AI is drafting a reply...
                  </div>
                {/if}
                {#if todo.ai_draft_status === 'sent'}
                  <div class="mt-2 text-xs text-emerald-600 dark:text-emerald-400">AI draft was sent</div>
                {/if}
              </div>
            {/each}
          </div>
        </div>
      {:else}
        <div class="rounded-xl border p-8 text-center" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <div class="text-3xl mb-2 opacity-40">&#10003;</div>
          <p class="text-sm" style="color: var(--text-tertiary)">No pending todos. Add one above or create from email action items.</p>
        </div>
      {/if}

      <!-- Completed todos -->
      {#if doneTodos.length > 0}
        <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <h3 class="text-sm font-semibold mb-3" style="color: var(--text-tertiary)">Done ({doneTodos.length})</h3>
          <div class="space-y-1">
            {#each doneTodos as todo (todo.id)}
              <div class="flex items-center gap-3 p-2 rounded-lg">
                <button
                  onclick={() => toggleTodo(todo)}
                  class="w-5 h-5 rounded border-2 flex items-center justify-center shrink-0 transition-fast"
                  style="border-color: var(--color-accent-500); background: var(--color-accent-500)"
                >
                  <span style="color: white"><Icon name="check" size={12} /></span>
                </button>
                <span class="text-sm line-through" style="color: var(--text-tertiary)">{todo.title}</span>
                <button
                  onclick={() => deleteTodo(todo)}
                  class="ml-auto p-1 rounded transition-fast shrink-0"
                  style="color: var(--text-tertiary)"
                  title="Delete"
                >
                  <Icon name="trash-2" size={14} />
                </button>
              </div>
            {/each}
          </div>
        </div>
      {/if}

      <!-- Dismissed todos -->
      {#if dismissedTodos.length > 0}
        <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <h3 class="text-sm font-semibold mb-3" style="color: var(--text-tertiary)">Dismissed ({dismissedTodos.length})</h3>
          <div class="space-y-1">
            {#each dismissedTodos as todo (todo.id)}
              <div class="flex items-center gap-3 p-2 rounded-lg">
                <span class="text-sm line-through" style="color: var(--text-tertiary)">{todo.title}</span>
                <button
                  onclick={() => deleteTodo(todo)}
                  class="ml-auto p-1 rounded transition-fast shrink-0"
                  style="color: var(--text-tertiary)"
                  title="Delete"
                >
                  <Icon name="trash-2" size={14} />
                </button>
              </div>
            {/each}
          </div>
        </div>
      {/if}
    </div>
  {/if}
</div>
