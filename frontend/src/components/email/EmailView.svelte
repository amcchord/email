<script>
  import { currentPage, composeData } from '../../lib/stores.js';
  import Button from '../components/../common/Button.svelte';

  let { email = null, loading = false, onAction = null, onClose = null } = $props();

  function formatFullDate(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    return d.toLocaleDateString([], {
      weekday: 'long',
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  }

  function formatAddresses(addresses) {
    if (!addresses || addresses.length === 0) return '';
    return addresses.map(a => {
      if (typeof a === 'string') return a;
      if (a.name) return `${a.name} <${a.address}>`;
      return a.address;
    }).join(', ');
  }

  function handleReply() {
    if (!email) return;
    composeData.set({
      account_id: null,
      to: [email.reply_to || email.from_address],
      cc: [],
      subject: email.subject?.startsWith('Re:') ? email.subject : `Re: ${email.subject || ''}`,
      in_reply_to: email.message_id_header,
      thread_id: email.gmail_thread_id,
      body_html: '',
    });
    currentPage.set('compose');
  }

  function handleForward() {
    if (!email) return;
    composeData.set({
      account_id: null,
      to: [],
      cc: [],
      subject: email.subject?.startsWith('Fwd:') ? email.subject : `Fwd: ${email.subject || ''}`,
      body_html: `<br><br>---------- Forwarded message ----------<br>From: ${email.from_name || ''} &lt;${email.from_address || ''}&gt;<br>Date: ${formatFullDate(email.date)}<br>Subject: ${email.subject || ''}<br><br>${email.body_html || email.body_text || ''}`,
    });
    currentPage.set('compose');
  }

  const categoryLabels = {
    needs_response: '🔵 Needs Response',
    urgent: '🔴 Urgent',
    can_ignore: '⚪ Can Ignore',
    fyi: '🟢 FYI',
    awaiting_reply: '🟡 Awaiting Reply',
  };
</script>

<div class="h-full flex flex-col" style="background: var(--bg-secondary)">
  {#if loading}
    <div class="flex-1 flex items-center justify-center">
      <div class="w-6 h-6 border-2 rounded-full animate-spin" style="border-color: var(--border-color); border-top-color: var(--color-accent-500)"></div>
    </div>
  {:else if !email}
    <div class="flex-1 flex items-center justify-center">
      <p class="text-sm" style="color: var(--text-tertiary)">Select an email to read</p>
    </div>
  {:else}
    <!-- Header -->
    <div class="px-6 py-4 border-b shrink-0" style="border-color: var(--border-color)">
      <div class="flex items-start justify-between gap-4">
        <div class="flex-1 min-w-0">
          <h2 class="text-lg font-semibold leading-tight" style="color: var(--text-primary)">{email.subject || '(no subject)'}</h2>
          {#if email.ai_category}
            <span class="inline-block text-xs mt-1.5 px-2 py-0.5 rounded-full font-medium" style="background: var(--bg-tertiary); color: var(--text-secondary)">
              {categoryLabels[email.ai_category] || email.ai_category}
            </span>
          {/if}
        </div>
        <div class="flex items-center gap-1 shrink-0">
          <button
            onclick={() => onAction && onAction(email.is_starred ? 'unstar' : 'star', [email.id])}
            class="p-1.5 rounded-md transition-fast"
            style="color: {email.is_starred ? 'var(--color-accent-500)' : 'var(--text-tertiary)'}"
          >
            <svg class="w-5 h-5" fill={email.is_starred ? 'currentColor' : 'none'} stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z"/>
            </svg>
          </button>
          <button
            onclick={() => onAction && onAction('archive', [email.id])}
            class="p-1.5 rounded-md transition-fast"
            style="color: var(--text-tertiary)"
            title="Archive"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M20.25 7.5l-.625 10.632a2.25 2.25 0 01-2.247 2.118H6.622a2.25 2.25 0 01-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z"/>
            </svg>
          </button>
          <button
            onclick={() => onAction && onAction('trash', [email.id])}
            class="p-1.5 rounded-md transition-fast"
            style="color: var(--text-tertiary)"
            title="Delete"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0"/>
            </svg>
          </button>
          <button
            onclick={onClose}
            class="p-1.5 rounded-md transition-fast ml-2"
            style="color: var(--text-tertiary)"
            title="Close"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      </div>

      <!-- Sender info -->
      <div class="mt-4 flex items-start gap-3">
        <div class="w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold shrink-0" style="background: var(--bg-tertiary); color: var(--color-accent-600)">
          {(email.from_name || email.from_address || 'U')[0].toUpperCase()}
        </div>
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2">
            <span class="text-sm font-medium" style="color: var(--text-primary)">{email.from_name || email.from_address}</span>
            {#if email.from_name}
              <span class="text-xs" style="color: var(--text-tertiary)">&lt;{email.from_address}&gt;</span>
            {/if}
          </div>
          <div class="text-xs mt-0.5" style="color: var(--text-secondary)">
            To: {formatAddresses(email.to_addresses)}
            {#if email.cc_addresses?.length > 0}
              <br>Cc: {formatAddresses(email.cc_addresses)}
            {/if}
          </div>
          <div class="text-xs mt-0.5" style="color: var(--text-tertiary)">{formatFullDate(email.date)}</div>
        </div>
      </div>
    </div>

    <!-- AI Summary -->
    {#if email.ai_summary}
      <div class="px-6 py-3 border-b" style="border-color: var(--border-color); background: var(--bg-tertiary)">
        <div class="text-xs font-semibold mb-1" style="color: var(--color-accent-600)">AI Summary</div>
        <p class="text-sm" style="color: var(--text-primary)">{email.ai_summary}</p>
        {#if email.ai_action_items?.length > 0}
          <div class="mt-2">
            <div class="text-xs font-semibold mb-1" style="color: var(--color-accent-600)">Action Items</div>
            <ul class="text-sm space-y-0.5" style="color: var(--text-secondary)">
              {#each email.ai_action_items as item}
                <li class="flex items-start gap-1.5">
                  <span class="mt-1.5 w-1 h-1 rounded-full bg-accent-500 shrink-0"></span>
                  {item}
                </li>
              {/each}
            </ul>
          </div>
        {/if}
      </div>
    {/if}

    <!-- Body -->
    <div class="flex-1 overflow-y-auto px-6 py-4">
      {#if email.body_html}
        <div class="email-body prose max-w-none">
          {@html email.body_html}
        </div>
      {:else if email.body_text}
        <pre class="text-sm whitespace-pre-wrap font-sans" style="color: var(--text-primary)">{email.body_text}</pre>
      {:else}
        <p class="text-sm" style="color: var(--text-tertiary)">(No content)</p>
      {/if}

      <!-- Attachments -->
      {#if email.attachments?.length > 0}
        <div class="mt-6 pt-4 border-t" style="border-color: var(--border-color)">
          <div class="text-xs font-semibold mb-2" style="color: var(--text-secondary)">
            {email.attachments.length} attachment{email.attachments.length !== 1 ? 's' : ''}
          </div>
          <div class="flex flex-wrap gap-2">
            {#each email.attachments as att}
              <div class="flex items-center gap-2 px-3 py-2 rounded-lg border text-sm" style="border-color: var(--border-color); background: var(--bg-tertiary)">
                <svg class="w-4 h-4 shrink-0" style="color: var(--text-tertiary)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"/>
                </svg>
                <span class="truncate max-w-[200px]" style="color: var(--text-primary)">{att.filename || 'Attachment'}</span>
                {#if att.size_bytes}
                  <span class="text-xs" style="color: var(--text-tertiary)">
                    {#if att.size_bytes > 1048576}
                      {(att.size_bytes / 1048576).toFixed(1)} MB
                    {:else}
                      {(att.size_bytes / 1024).toFixed(0)} KB
                    {/if}
                  </span>
                {/if}
              </div>
            {/each}
          </div>
        </div>
      {/if}
    </div>

    <!-- Reply actions -->
    <div class="px-6 py-3 border-t shrink-0 flex gap-2" style="border-color: var(--border-color)">
      <Button size="sm" onclick={handleReply}>
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 15L3 9m0 0l6-6M3 9h12a6 6 0 010 12h-3" />
        </svg>
        Reply
      </Button>
      <Button size="sm" onclick={handleForward}>
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M15 15l6-6m0 0l-6-6m6 6H9a6 6 0 000 12h3" />
        </svg>
        Forward
      </Button>
    </div>
  {/if}
</div>

<style>
  :global(.email-body) {
    font-size: 14px;
    line-height: 1.6;
    word-break: break-word;
  }
  :global(.email-body img) {
    max-width: 100%;
    height: auto;
  }
  :global(.email-body a) {
    color: var(--color-accent-600);
    text-decoration: underline;
  }
  :global(.email-body table) {
    max-width: 100%;
    overflow-x: auto;
    display: block;
  }
  :global(.email-body blockquote) {
    border-left: 3px solid var(--border-color);
    padding-left: 12px;
    margin-left: 0;
    opacity: 0.8;
  }
</style>
