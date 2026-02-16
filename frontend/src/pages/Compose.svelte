<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { currentPage, composeData, accounts, showToast } from '../lib/stores.js';
  import { registerActions } from '../lib/shortcutStore.js';
  import Button from '../components/common/Button.svelte';
  import Icon from '../components/common/Icon.svelte';
  import RichEditor from '../components/email/RichEditor.svelte';

  let to = $state('');
  let cc = $state('');
  let bcc = $state('');
  let subject = $state('');
  let bodyHtml = $state('');
  let showCcBcc = $state(false);
  let sending = $state(false);
  let selectedAccountId = $state(null);
  let accountList = $state([]);
  let initialContent = $state('');

  onMount(() => {
    accounts.subscribe(v => {
      accountList = v;
      if (v.length > 0 && !selectedAccountId) {
        selectedAccountId = v[0].id;
      }
    });

    // Pre-fill from composeData (reply/forward)
    const unsub = composeData.subscribe(data => {
      if (data) {
        if (data.to) to = data.to.join(', ');
        if (data.cc) cc = data.cc.join(', ');
        if (data.subject) subject = data.subject;
        if (data.body_html) {
          initialContent = data.body_html;
          bodyHtml = data.body_html;
        }
        if (data.account_id) selectedAccountId = data.account_id;
      }
    });

    // Register keyboard shortcut actions for the Compose page
    const cleanupShortcuts = registerActions({
      'compose.send': () => handleSend(),
      'compose.draft': () => handleSaveDraft(),
      'compose.discard': () => currentPage.set('inbox'),
      'compose.cc': () => { showCcBcc = !showCcBcc; },
      'compose.bcc': () => { showCcBcc = !showCcBcc; },
    });

    return () => {
      unsub();
      composeData.set(null);
      cleanupShortcuts();
    };
  });

  function handleEditorUpdate(html) {
    bodyHtml = html;
  }

  async function handleSend() {
    if (!to.trim()) {
      showToast('Please add recipients', 'error');
      return;
    }
    if (!selectedAccountId) {
      showToast('Please select an account', 'error');
      return;
    }

    sending = true;
    try {
      const data = {
        account_id: selectedAccountId,
        to: to.split(',').map(s => s.trim()).filter(Boolean),
        cc: cc ? cc.split(',').map(s => s.trim()).filter(Boolean) : [],
        bcc: bcc ? bcc.split(',').map(s => s.trim()).filter(Boolean) : [],
        subject: subject,
        body_html: bodyHtml,
        body_text: bodyHtml.replace(/<[^>]*>/g, ''),
      };

      // Include reply metadata if present
      let cd;
      composeData.subscribe(v => cd = v)();
      if (cd) {
        if (cd.in_reply_to) data.in_reply_to = cd.in_reply_to;
        if (cd.thread_id) data.thread_id = cd.thread_id;
      }

      await api.sendEmail(data);
      showToast('Email sent', 'success');
      currentPage.set('inbox');
      composeData.set(null);
    } catch (err) {
      showToast(err.message, 'error');
    }
    sending = false;
  }

  async function handleSaveDraft() {
    if (!selectedAccountId) return;
    try {
      await api.saveDraft({
        account_id: selectedAccountId,
        to: to.split(',').map(s => s.trim()).filter(Boolean),
        cc: cc ? cc.split(',').map(s => s.trim()).filter(Boolean) : [],
        bcc: bcc ? bcc.split(',').map(s => s.trim()).filter(Boolean) : [],
        subject: subject,
        body_html: bodyHtml,
        body_text: bodyHtml.replace(/<[^>]*>/g, ''),
        is_draft: true,
      });
      showToast('Draft saved', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
  }
</script>

<div class="h-full flex flex-col" style="background: var(--bg-secondary)">
  <!-- Header -->
  <div class="h-14 flex items-center justify-between px-6 border-b shrink-0" style="border-color: var(--border-color)">
    <div class="flex items-center gap-3">
      <button
        onclick={() => { currentPage.set('inbox'); composeData.set(null); }}
        class="p-1.5 rounded-md transition-fast"
        style="color: var(--text-secondary)"
      >
        <Icon name="arrow-left" size={20} />
      </button>
      <h2 class="text-base font-semibold" style="color: var(--text-primary)">New Message</h2>
    </div>
    <div class="flex gap-2">
      <Button size="sm" onclick={handleSaveDraft}>Save Draft</Button>
      <Button variant="primary" size="sm" onclick={handleSend} disabled={sending}>
        {#if sending}
          Sending...
        {:else}
          Send
        {/if}
      </Button>
    </div>
  </div>

  <!-- Form -->
  <div class="flex-1 overflow-y-auto flex flex-col">
    <div class="border-b shrink-0" style="border-color: var(--border-color)">
      <!-- From -->
      {#if accountList.length > 0}
        <div class="flex items-center px-6 h-10 border-b" style="border-color: var(--border-subtle)">
          <label class="text-sm w-16 shrink-0" style="color: var(--text-secondary)">From</label>
          <select
            bind:value={selectedAccountId}
            class="flex-1 h-full text-sm outline-none border-0"
            style="background: transparent; color: var(--text-primary)"
          >
            {#each accountList as acct}
              <option value={acct.id}>{acct.email}</option>
            {/each}
          </select>
        </div>
      {/if}

      <!-- To -->
      <div class="flex items-center px-6 h-10 border-b" style="border-color: var(--border-subtle)">
        <label class="text-sm w-16 shrink-0" style="color: var(--text-secondary)">To</label>
        <input
          type="text"
          bind:value={to}
          placeholder="recipient@example.com"
          class="flex-1 h-full text-sm outline-none"
          style="background: transparent; color: var(--text-primary)"
        />
        {#if !showCcBcc}
          <button
            onclick={() => showCcBcc = true}
            class="text-xs"
            style="color: var(--text-tertiary)"
          >Cc/Bcc</button>
        {/if}
      </div>

      <!-- Cc/Bcc -->
      {#if showCcBcc}
        <div class="flex items-center px-6 h-10 border-b" style="border-color: var(--border-subtle)">
          <label class="text-sm w-16 shrink-0" style="color: var(--text-secondary)">Cc</label>
          <input
            type="text"
            bind:value={cc}
            class="flex-1 h-full text-sm outline-none"
            style="background: transparent; color: var(--text-primary)"
          />
        </div>
        <div class="flex items-center px-6 h-10 border-b" style="border-color: var(--border-subtle)">
          <label class="text-sm w-16 shrink-0" style="color: var(--text-secondary)">Bcc</label>
          <input
            type="text"
            bind:value={bcc}
            class="flex-1 h-full text-sm outline-none"
            style="background: transparent; color: var(--text-primary)"
          />
        </div>
      {/if}

      <!-- Subject -->
      <div class="flex items-center px-6 h-10" style="border-color: var(--border-subtle)">
        <label class="text-sm w-16 shrink-0" style="color: var(--text-secondary)">Subject</label>
        <input
          type="text"
          bind:value={subject}
          placeholder="Subject"
          class="flex-1 h-full text-sm outline-none"
          style="background: transparent; color: var(--text-primary)"
        />
      </div>
    </div>

    <!-- Rich Editor Body -->
    <RichEditor
      content={initialContent}
      onUpdate={handleEditorUpdate}
      placeholder="Write your message..."
    />
  </div>
</div>
