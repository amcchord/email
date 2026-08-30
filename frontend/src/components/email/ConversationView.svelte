<script>
  import { defaultThreadMessageId } from '../../lib/conversationInbox.js';
  import EmailView from './EmailView.svelte';

  let {
    conversation = null,
    thread = null,
    loading = false,
    onAction = null,
    onLabel = null,
    allowMove = false,
    onSnooze = null,
    onClose = null,
    onGuardChange = null,
  } = $props();

  let activeMessageId = $state(null);
  let transitionGuard = null;
  let messages = $derived(Array.isArray(thread?.emails) ? thread.emails : []);
  let activeMessage = $derived(
    messages.find(message => Number(message.id) === Number(activeMessageId))
      || messages[messages.length - 1]
      || null,
  );

  $effect(() => {
    void thread?.thread_id;
    activeMessageId = defaultThreadMessageId(thread);
  });

  function shortDate(value) {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleString([], {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  }

  function sender(message) {
    return message?.from_name || message?.from_address || 'Unknown sender';
  }

  async function selectMessage(messageId) {
    if (Number(messageId) === Number(activeMessageId)) return;
    if (transitionGuard && (await transitionGuard()) === false) return;
    activeMessageId = messageId;
  }

  function registerGuard(guard) {
    transitionGuard = typeof guard === 'function' ? guard : null;
    onGuardChange?.(transitionGuard);
  }

  function conversationAction(action) {
    if (!conversation?.id) return false;
    return onAction?.(action, [conversation.id]);
  }

  function conversationLabel(mode) {
    if (!conversation) return false;
    return onLabel?.(mode, [conversation]);
  }

  function conversationSnooze() {
    if (!conversation) return false;
    return onSnooze?.(conversation);
  }
</script>

<div class="flex h-full min-h-0 flex-col" data-conversation-reader={conversation?.conversation_key || ''}>
  {#if messages.length > 1}
    <section class="shrink-0 border-b px-3 py-2" style="border-color: var(--border-color); background: var(--bg-secondary)" aria-label="Conversation messages">
      <div class="mb-1 flex items-center gap-2 px-1">
        <span class="truncate text-xs font-semibold" style="color: var(--text-secondary)">
          {messages.length} messages · chronological
        </span>
        {#if conversation?.matched_count > 1}
          <span class="ml-auto text-[11px]" style="color: var(--text-tertiary)">{conversation.matched_count} matched this view</span>
        {/if}
      </div>
      <ol class="flex min-w-0 gap-2 overflow-x-auto pb-1" aria-label="Oldest to newest messages">
        {#each messages as message, index (message.id)}
          <li class="min-w-0 shrink-0">
            <button
              type="button"
              class="flex min-h-11 w-48 min-w-0 items-center gap-2 rounded-lg border px-3 py-2 text-left transition-fast sm:w-56"
              style="border-color: {Number(activeMessage?.id) === Number(message.id) ? 'var(--color-accent-500)' : 'var(--border-color)'}; background: {Number(activeMessage?.id) === Number(message.id) ? 'var(--bg-hover)' : 'var(--bg-primary)'}"
              aria-pressed={Number(activeMessage?.id) === Number(message.id)}
              aria-label={`Open message ${index + 1} of ${messages.length} from ${sender(message)}`}
              onclick={() => selectMessage(message.id)}
            >
              {#if !message.is_read}
                <span class="h-2 w-2 shrink-0 rounded-full bg-accent-500" aria-label="Unread"></span>
              {/if}
              <span class="min-w-0 flex-1">
                <span class="block truncate text-xs font-semibold" style="color: var(--text-primary)">{sender(message)}</span>
                <span class="block truncate text-[11px]" style="color: var(--text-tertiary)">{shortDate(message.date)}</span>
              </span>
              <span class="text-[10px]" style="color: var(--text-tertiary)" aria-hidden="true">{index + 1}/{messages.length}</span>
            </button>
          </li>
        {/each}
      </ol>
    </section>
  {/if}

  <div class="min-h-0 flex-1">
    <EmailView
      email={activeMessage}
      {loading}
      onAction={conversationAction}
      onLabel={conversationLabel}
      {allowMove}
      onSnooze={conversationSnooze}
      {onClose}
      onGuardChange={registerGuard}
    />
  </div>
</div>
