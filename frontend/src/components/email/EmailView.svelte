<script>
  import { currentPage, composeData, showToast, pendingReplyDraft, accounts, todos, accountColorMap } from '../../lib/stores.js';
  import { theme } from '../../lib/theme.js';
  import { api } from '../../lib/api.js';
  import { get } from 'svelte/store';
  import Button from '../common/Button.svelte';

  let { email = null, loading = false, onAction = null, onClose = null, standalone = false } = $props();

  let iframeEl = $state(null);
  let unsubscribing = $state(false);
  let addingTodos = $state(false);
  let showTodoPrompt = $state(false);

  async function addAllTodos() {
    if (!email) return;
    addingTodos = true;
    try {
      const result = await api.createTodosFromEmail(email.id);
      if (result.created > 0) {
        todos.update(list => [...result.todos, ...list]);
        showToast(`Added ${result.created} action items to todos`, 'success');
      } else {
        showToast('Action items already in todos', 'info');
      }
    } catch (err) {
      showToast(err.message, 'error');
    }
    addingTodos = false;
    showTodoPrompt = false;
  }

  async function addSingleTodo(item) {
    if (!email) return;
    try {
      const todo = await api.createTodo({
        title: item,
        email_id: email.id,
        source: 'ai_action_item',
      });
      todos.update(list => [todo, ...list]);
      showToast('Added to todos', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  // Inline reply state
  let inlineReplyOpen = $state(false);
  let inlineReplyBody = $state('');
  let inlineReplySending = $state(false);
  let lastDraftEmailId = $state(null);
  let replyFromSuggestion = $state(false);

  // When the email changes, check if there's a pending reply draft for it
  $effect(() => {
    if (!email) {
      inlineReplyOpen = false;
      inlineReplyBody = '';
      lastDraftEmailId = null;
      replyFromSuggestion = false;
      return;
    }

    const draft = get(pendingReplyDraft);
    if (draft && draft.emailId === email.id) {
      inlineReplyOpen = true;
      inlineReplyBody = draft.body || '';
      replyFromSuggestion = !!draft.body;
      lastDraftEmailId = email.id;
      // Clear the pending draft so it doesn't re-trigger
      pendingReplyDraft.set(null);
    } else if (email.id !== lastDraftEmailId) {
      // Different email selected, close the inline reply
      inlineReplyOpen = false;
      inlineReplyBody = '';
      lastDraftEmailId = null;
      replyFromSuggestion = false;
    }
  });

  function openInlineReply() {
    inlineReplyOpen = true;
    lastDraftEmailId = email.id;
    // If empty and there's no text yet, don't pre-fill (user is manually replying)
  }

  function closeInlineReply() {
    inlineReplyOpen = false;
    inlineReplyBody = '';
    lastDraftEmailId = null;
    replyFromSuggestion = false;
  }

  async function sendInlineReply() {
    if (!email || !inlineReplyBody.trim()) return;
    inlineReplySending = true;
    try {
      // Find the account id for this email
      const accountList = get(accounts);
      let accountId = null;
      if (accountList.length === 1) {
        accountId = accountList[0].id;
      } else if (accountList.length > 1 && email.account_email) {
        // Match by account_email field to send from the correct account
        const matched = accountList.find(a => a.email === email.account_email);
        if (matched) {
          accountId = matched.id;
        } else {
          accountId = accountList[0].id;
        }
      } else if (accountList.length > 1) {
        accountId = accountList[0].id;
      }

      if (!accountId) {
        showToast('No account found to send from', 'error');
        inlineReplySending = false;
        return;
      }

      const subject = email.subject && email.subject.startsWith('Re:') ? email.subject : `Re: ${email.subject || ''}`;
      await api.sendEmail({
        account_id: accountId,
        to: [email.reply_to || email.from_address],
        cc: [],
        bcc: [],
        subject: subject,
        body_text: inlineReplyBody,
        body_html: `<p>${inlineReplyBody.replace(/\n/g, '<br>')}</p>`,
        in_reply_to: email.message_id_header || null,
        references: email.message_id_header || null,
        thread_id: email.gmail_thread_id || null,
      });
      showToast('Reply sent!', 'success');
      closeInlineReply();
      // If this email has action items, prompt to add to todos
      if (email.ai_action_items && email.ai_action_items.length > 0) {
        showTodoPrompt = true;
      }
    } catch (err) {
      showToast(err.message, 'error');
    }
    inlineReplySending = false;
  }

  // Write email HTML into a sandboxed iframe so its <style> tags can't leak
  $effect(() => {
    if (iframeEl && email && email.body_html) {
      const isDark = $theme === 'dark';
      const doc = iframeEl.contentDocument;
      if (doc) {
        doc.open();
        doc.write(`<!DOCTYPE html><html><head><style>
          body {
            margin: 0; padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            font-size: 14px; line-height: 1.6;
            color: ${isDark ? '#e4e4e7' : '#1a1a1a'};
            background: ${isDark ? '#18181b' : '#ffffff'};
            word-break: break-word;
          }
          img { max-width: 100%; height: auto; }
          a { color: ${isDark ? '#f59e0b' : '#b45309'}; }
          blockquote { border-left: 3px solid ${isDark ? '#3f3f46' : '#d4d4d8'}; padding-left: 12px; margin-left: 0; opacity: 0.8; }
          table { max-width: 100%; }
          pre { overflow-x: auto; }
        </style></head><body>${email.body_html}</body></html>`);
        doc.close();

        // Auto-resize iframe to content height
        function resize() {
          if (iframeEl && doc.body) {
            iframeEl.style.height = doc.body.scrollHeight + 'px';
          }
        }
        // Resize after images load
        const imgs = doc.querySelectorAll('img');
        if (imgs.length > 0) {
          let loaded = 0;
          imgs.forEach(img => {
            if (img.complete) {
              loaded++;
            } else {
              img.addEventListener('load', () => { loaded++; if (loaded >= imgs.length) resize(); });
              img.addEventListener('error', () => { loaded++; if (loaded >= imgs.length) resize(); });
            }
          });
          if (loaded >= imgs.length) resize();
        }
        // Initial resize with a small delay for rendering
        setTimeout(resize, 50);
        setTimeout(resize, 300);
      }
    }
  });

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
    inlineReplyOpen = true;
    lastDraftEmailId = email.id;
    // If user hasn't typed anything yet, pre-fill with suggested reply if available
    if (!inlineReplyBody.trim() && email.suggested_reply) {
      inlineReplyBody = email.suggested_reply;
      replyFromSuggestion = true;
    }
  }

  function handleFullCompose() {
    if (!email) return;
    composeData.set({
      account_id: null,
      to: [email.reply_to || email.from_address],
      cc: [],
      subject: email.subject?.startsWith('Re:') ? email.subject : `Re: ${email.subject || ''}`,
      in_reply_to: email.message_id_header,
      thread_id: email.gmail_thread_id,
      body_html: inlineReplyBody ? `<p>${inlineReplyBody.replace(/\n/g, '<br>')}</p>` : '',
    });
    closeInlineReply();
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

  function handlePopOut() {
    if (!email) return;
    const url = `/?view=email&id=${email.id}`;
    window.open(url, `email-${email.id}`, 'width=800,height=700,menubar=no,toolbar=no');
  }

  async function handleUnsubscribe() {
    if (!email) return;
    unsubscribing = true;
    try {
      const result = await api.unsubscribe(email.id);
      if (result.email_sent) {
        showToast(`Unsubscribe email sent to ${result.sent_to}`, 'success');
      } else if (result.url) {
        window.open(result.url, '_blank');
        showToast('Opened unsubscribe page in new tab', 'success');
      } else {
        showToast('No unsubscribe method available', 'error');
      }
    } catch (err) {
      showToast(err.message, 'error');
    }
    unsubscribing = false;
  }

  const categoryLabels = {
    urgent: '🔴 Urgent',
    can_ignore: '⚪ Can Ignore',
    fyi: '🟢 FYI',
    awaiting_reply: '🟡 Awaiting Reply',
  };

  const emailTypeLabels = {
    work: '💼 Work',
    personal: '🏠 Personal',
  };

  // Helper to determine if we should show recipient instead of sender
  function shouldShowRecipient(email) {
    return email && (email.is_sent || email.is_draft);
  }
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
          <div class="flex items-center gap-2 mt-1.5 flex-wrap">
            {#if email.ai_email_type}
              <span class="inline-block text-xs px-2 py-0.5 rounded-full font-medium {email.ai_email_type === 'work' ? 'bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-400' : 'bg-teal-100 dark:bg-teal-900/40 text-teal-700 dark:text-teal-400'}">
                {emailTypeLabels[email.ai_email_type] || email.ai_email_type}
              </span>
            {/if}
            {#if email.ai_category}
              <span class="inline-block text-xs px-2 py-0.5 rounded-full font-medium" style="background: var(--bg-tertiary); color: var(--text-secondary)">
                {categoryLabels[email.ai_category] || email.ai_category}
              </span>
            {/if}
            {#if email.needs_reply}
              <span class="inline-block text-xs px-2 py-0.5 rounded-full font-medium bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-400">
                Needs Reply
              </span>
            {/if}
            {#if email.is_subscription}
              <span class="inline-block text-xs px-2 py-0.5 rounded-full font-medium bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400">
                Subscription
              </span>
            {/if}
          </div>
        </div>
        <div class="flex items-center gap-1 shrink-0">
          <button
            onclick={() => onAction && onAction(email.is_starred ? 'unstar' : 'star', [email.id])}
            class="p-1.5 rounded-md transition-fast"
            style="color: {email.is_starred ? 'var(--color-accent-500)' : 'var(--text-tertiary)'}"
            title="Star"
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
          <!-- Pop out button -->
          {#if !standalone}
            <button
              onclick={handlePopOut}
              class="p-1.5 rounded-md transition-fast"
              style="color: var(--text-tertiary)"
              title="Open in new window"
            >
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
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
          {/if}
        </div>
      </div>

      <!-- Sender/Recipient info -->
      <div class="mt-4 flex items-start gap-3">
        <div class="w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold shrink-0" style="background: var(--bg-tertiary); color: var(--color-accent-600)">
          {#if shouldShowRecipient(email) && email.to_addresses?.length > 0}
            {(typeof email.to_addresses[0] === 'string' ? email.to_addresses[0] : (email.to_addresses[0].name || email.to_addresses[0].address || 'U'))[0].toUpperCase()}
          {:else}
            {(email.from_name || email.from_address || 'U')[0].toUpperCase()}
          {/if}
        </div>
        <div class="flex-1 min-w-0">
          {#if shouldShowRecipient(email)}
            <!-- Sent/Draft: show recipients first -->
            <div class="flex items-center gap-2">
              <span class="text-sm font-medium" style="color: var(--text-primary)">
                To: {formatAddresses(email.to_addresses) || '(No recipients)'}
              </span>
            </div>
            {#if email.cc_addresses?.length > 0}
              <div class="text-xs mt-0.5" style="color: var(--text-secondary)">
                Cc: {formatAddresses(email.cc_addresses)}
              </div>
            {/if}
            <div class="text-xs mt-0.5" style="color: var(--text-tertiary)">
              From: {email.from_name || email.from_address}
            </div>
          {:else}
            <!-- Received: show sender first -->
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
          {/if}
          <div class="text-xs mt-0.5" style="color: var(--text-tertiary)">{formatFullDate(email.date)}</div>
          {#if email.account_email && $accountColorMap[email.account_email]}
            <div class="flex items-center gap-1.5 mt-1">
              <span
                class="w-2 h-2 rounded-full shrink-0"
                style="background: {$accountColorMap[email.account_email].bg}"
              ></span>
              <span class="text-[11px]" style="color: var(--text-tertiary)">via {email.account_email}</span>
            </div>
          {/if}
        </div>
      </div>
    </div>

    <!-- AI Summary -->
    {#if email.ai_summary}
      <div class="px-6 py-3 border-b" style="border-color: var(--border-color); background: var(--bg-tertiary)">
        <div class="flex items-center justify-between mb-1">
          <div class="text-xs font-semibold" style="color: var(--color-accent-600)">AI Summary</div>
          {#if email.ai_model_used}
            <span class="text-[10px]" style="color: var(--text-tertiary)">
              {#if email.ai_model_used.includes('opus')}Opus
              {:else if email.ai_model_used.includes('sonnet')}Sonnet
              {:else if email.ai_model_used.includes('haiku')}Haiku
              {:else}{email.ai_model_used}
              {/if}
            </span>
          {/if}
        </div>
        <p class="text-sm" style="color: var(--text-primary)">{email.ai_summary}</p>
        {#if email.ai_action_items?.length > 0}
          <div class="mt-2">
            <div class="flex items-center justify-between mb-1">
              <div class="text-xs font-semibold" style="color: var(--color-accent-600)">Action Items</div>
              <button
                onclick={addAllTodos}
                disabled={addingTodos}
                class="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium transition-fast disabled:opacity-50"
                style="background: var(--bg-primary); color: var(--color-accent-600); border: 1px solid var(--border-color)"
              >
                {#if addingTodos}
                  <div class="w-3 h-3 border border-current/30 border-t-current rounded-full animate-spin"></div>
                {:else}
                  <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4.5v15m7.5-7.5h-15" />
                  </svg>
                {/if}
                Add All to Todos
              </button>
            </div>
            <ul class="text-sm space-y-1" style="color: var(--text-secondary)">
              {#each email.ai_action_items as item}
                <li class="flex items-start gap-1.5 group">
                  <span class="mt-1.5 w-1 h-1 rounded-full bg-accent-500 shrink-0"></span>
                  <span class="flex-1">{item}</span>
                  <button
                    onclick={() => addSingleTodo(item)}
                    class="opacity-0 group-hover:opacity-100 p-0.5 rounded transition-fast shrink-0"
                    style="color: var(--text-tertiary)"
                    title="Add to todos"
                  >
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4.5v15m7.5-7.5h-15" />
                    </svg>
                  </button>
                </li>
              {/each}
            </ul>
          </div>
        {/if}
      </div>
    {/if}

    <!-- Todo prompt after reply -->
    {#if showTodoPrompt && email.ai_action_items?.length > 0}
      <div class="px-6 py-3 border-b flex items-center gap-3" style="border-color: var(--border-color); background: var(--bg-tertiary)">
        <svg class="w-4 h-4 shrink-0" style="color: var(--color-accent-500)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <span class="text-xs" style="color: var(--text-primary)">Add {email.ai_action_items.length} action items to your todo list?</span>
        <button
          onclick={addAllTodos}
          disabled={addingTodos}
          class="px-3 py-1 rounded text-xs font-medium transition-fast disabled:opacity-50"
          style="background: var(--color-accent-500); color: white"
        >Add</button>
        <button
          onclick={() => showTodoPrompt = false}
          class="px-2 py-1 rounded text-xs transition-fast"
          style="color: var(--text-tertiary)"
        >Dismiss</button>
      </div>
    {/if}

    <!-- Body -->
    <div class="flex-1 overflow-y-auto px-6 py-4">
      {#if email.body_html}
        <iframe
          bind:this={iframeEl}
          title="Email content"
          sandbox="allow-same-origin allow-popups"
          class="w-full border-0"
          style="min-height: 100px; height: 300px"
        ></iframe>
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

    <!-- Inline Reply Composer -->
    {#if inlineReplyOpen}
      <div class="px-6 py-4 border-t shrink-0" style="border-color: var(--border-color); background: var(--bg-tertiary)">
        <div class="flex items-center justify-between mb-2">
          <div class="flex items-center gap-2">
            <svg class="w-4 h-4" style="color: var(--color-accent-500)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 15L3 9m0 0l6-6M3 9h12a6 6 0 010 12h-3" />
            </svg>
            <span class="text-xs font-semibold" style="color: var(--text-primary)">Reply to {email.from_name || email.from_address}</span>
          </div>
          <div class="flex items-center gap-1">
            <button
              onclick={handleFullCompose}
              class="p-1 rounded transition-fast"
              style="color: var(--text-tertiary)"
              title="Open in full composer"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
              </svg>
            </button>
            <button
              onclick={closeInlineReply}
              class="p-1 rounded transition-fast"
              style="color: var(--text-tertiary)"
              title="Close reply"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>
        {#if replyFromSuggestion}
          <div class="flex items-center gap-1.5 mb-2 px-1">
            <svg class="w-3.5 h-3.5 shrink-0" style="color: var(--color-accent-500)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
            </svg>
            <span class="text-[11px] font-medium" style="color: var(--color-accent-600)">AI-suggested reply — edit as needed</span>
          </div>
        {/if}
        <textarea
          bind:value={inlineReplyBody}
          placeholder="Write your reply..."
          class="w-full rounded-lg border p-3 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-accent-500/40"
          style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary); min-height: 100px; max-height: 200px"
          rows="4"
        ></textarea>
        <div class="flex items-center gap-2 mt-2">
          <button
            onclick={sendInlineReply}
            disabled={inlineReplySending || !inlineReplyBody.trim()}
            class="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-medium transition-fast disabled:opacity-50"
            style="background: var(--color-accent-500); color: white"
          >
            {#if inlineReplySending}
              <div class="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
              Sending...
            {:else}
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
              </svg>
              Send Reply
            {/if}
          </button>
          <span class="text-[10px]" style="color: var(--text-tertiary)">
            To: {email.reply_to || email.from_address}
          </span>
        </div>
      </div>
    {/if}

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
      {#if email.is_subscription && email.unsubscribe_info}
        <button
          onclick={handleUnsubscribe}
          disabled={unsubscribing}
          class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-fast ml-auto disabled:opacity-50"
          style="background: #ef4444; color: white"
        >
          {#if unsubscribing}
            <div class="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
          {:else}
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
            </svg>
          {/if}
          Unsubscribe
        </button>
      {/if}
    </div>
  {/if}
</div>

