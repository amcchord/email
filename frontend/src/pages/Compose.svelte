<script>
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { api } from '../lib/api.js';
  import { currentPage, composeData, accounts, selectedAccountId as globalSelectedAccountId, showToast } from '../lib/stores.js';
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
  let attachments = $state([]);
  let autosaveStatus = $state('');
  let autosaveReady = $state(false);
  let fileInput = $state(null);
  const LOCAL_DRAFT_KEY = 'composeLocalDraftV1';

  let senderAccount = $derived(accountList.find(account => account.id === Number(selectedAccountId)) || null);
  let recipientChips = $derived(parseRecipients(to));
  let totalAttachmentBytes = $derived(attachments.reduce((sum, item) => sum + item.size, 0));

  function parseRecipients(value) {
    return (value || '').split(/[;,]/).map(item => item.trim()).filter(Boolean);
  }

  function chooseSender(list, contextAccountId = null) {
    if (!list.length) return null;
    const savedId = Number(localStorage.getItem('composeLastAccountId'));
    const preferredId = contextAccountId || get(globalSelectedAccountId) || savedId;
    return list.find(account => account.id === Number(preferredId))?.id
      || list.find(account => /primary/i.test(account.description || ''))?.id
      || list.find(account => account.email.endsWith('@mcchord.net'))?.id
      || list[0].id;
  }

  function restoreLocalDraft() {
    if (get(composeData)) return;
    try {
      const draft = JSON.parse(localStorage.getItem(LOCAL_DRAFT_KEY) || 'null');
      if (!draft || !(draft.to || draft.subject || draft.body_html)) return;
      to = draft.to || '';
      cc = draft.cc || '';
      bcc = draft.bcc || '';
      subject = draft.subject || '';
      bodyHtml = draft.body_html || '';
      initialContent = bodyHtml;
      if (accountList.some(account => account.id === Number(draft.account_id))) {
        selectedAccountId = Number(draft.account_id);
      }
      showCcBcc = Boolean(cc || bcc);
      autosaveStatus = `Restored local draft from ${new Date(draft.saved_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`;
    } catch {
      localStorage.removeItem(LOCAL_DRAFT_KEY);
    }
  }

  onMount(() => {
    const unsubAccounts = accounts.subscribe(v => {
      accountList = v;
      if (v.length > 0 && !selectedAccountId) {
        selectedAccountId = chooseSender(v, get(composeData)?.account_id);
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
      'compose.discard': () => discardDraft(),
      'compose.cc': () => { showCcBcc = !showCcBcc; },
      'compose.bcc': () => { showCcBcc = !showCcBcc; },
    });

    queueMicrotask(() => {
      restoreLocalDraft();
      autosaveReady = true;
    });

    return () => {
      unsubAccounts();
      unsub();
      composeData.set(null);
      cleanupShortcuts();
    };
  });

  function handleEditorUpdate(html) {
    bodyHtml = html;
  }

  $effect(() => {
    if (!autosaveReady) return;
    const draft = {
      account_id: selectedAccountId, to, cc, bcc, subject,
      body_html: bodyHtml, saved_at: new Date().toISOString(),
    };
    autosaveStatus = 'Saving locally…';
    const timer = setTimeout(() => {
      try {
        localStorage.setItem(LOCAL_DRAFT_KEY, JSON.stringify(draft));
        autosaveStatus = `Saved locally at ${new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`;
      } catch {
        autosaveStatus = 'Local autosave unavailable';
      }
    }, 650);
    return () => clearTimeout(timer);
  });

  $effect(() => {
    if (selectedAccountId) localStorage.setItem('composeLastAccountId', String(selectedAccountId));
  });

  function removeRecipient(address) {
    to = parseRecipients(to).filter(item => item !== address).join(', ');
  }

  async function addAttachments(event) {
    const files = Array.from(event.currentTarget.files || []);
    if (!files.length) return;
    const nextTotal = totalAttachmentBytes + files.reduce((sum, file) => sum + file.size, 0);
    if (attachments.length + files.length > 10 || nextTotal > 18 * 1024 * 1024) {
      showToast('Attach up to 10 files totaling 18 MB', 'error');
      event.currentTarget.value = '';
      return;
    }
    const encoded = await Promise.all(files.map(file => new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve({
        filename: file.name,
        content_type: file.type || 'application/octet-stream',
        data_base64: String(reader.result).split(',')[1] || '',
        size: file.size,
      });
      reader.onerror = reject;
      reader.readAsDataURL(file);
    })));
    attachments = [...attachments, ...encoded];
    event.currentTarget.value = '';
  }

  function removeAttachment(index) {
    attachments = attachments.filter((_, itemIndex) => itemIndex !== index);
  }

  function discardDraft() {
    localStorage.removeItem(LOCAL_DRAFT_KEY);
    composeData.set(null);
    currentPage.set('inbox');
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
        to: parseRecipients(to),
        cc: parseRecipients(cc),
        bcc: parseRecipients(bcc),
        subject: subject,
        body_html: bodyHtml,
        body_text: bodyHtml.replace(/<[^>]*>/g, ''),
        attachments: attachments.map(({ size, ...item }) => item),
      };

      // Include reply metadata if present
      let cd;
      composeData.subscribe(v => cd = v)();
      if (cd) {
        if (cd.in_reply_to) data.in_reply_to = cd.in_reply_to;
        if (cd.thread_id) data.thread_id = cd.thread_id;
      }

      await api.sendEmail(data);
      localStorage.removeItem(LOCAL_DRAFT_KEY);
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
        to: parseRecipients(to),
        cc: parseRecipients(cc),
        bcc: parseRecipients(bcc),
        subject: subject,
        body_html: bodyHtml,
        body_text: bodyHtml.replace(/<[^>]*>/g, ''),
        is_draft: true,
        attachments: attachments.map(({ size, ...item }) => item),
      });
      localStorage.removeItem(LOCAL_DRAFT_KEY);
      showToast('Draft saved', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
  }
</script>

<div class="h-full flex flex-col" style="background: var(--bg-secondary)">
  <!-- Header -->
  <div class="compose-header min-h-14 flex items-center justify-between px-6 border-b shrink-0" style="border-color: var(--border-color)">
    <div class="flex items-center gap-3">
      <button
        onclick={() => { currentPage.set('inbox'); composeData.set(null); }}
        class="p-1.5 rounded-md transition-fast"
        style="color: var(--text-secondary)"
        aria-label="Back to inbox; keep local draft"
      >
        <Icon name="arrow-left" size={20} />
      </button>
      <h2 class="text-base font-semibold" style="color: var(--text-primary)">New Message</h2>
    </div>
    <div class="flex items-center gap-2">
      {#if autosaveStatus}
        <span class="autosave-label text-[11px]" style="color: var(--text-tertiary)">{autosaveStatus}</span>
      {/if}
      <Button size="sm" onclick={discardDraft}>Discard</Button>
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
        <div class="compose-field flex items-center min-w-0 px-6 min-h-10 border-b" style="border-color: var(--border-subtle)">
          <label for="compose-from" class="text-sm w-16 shrink-0" style="color: var(--text-secondary)">From</label>
          <select
            id="compose-from"
            bind:value={selectedAccountId}
            class="min-w-0 flex-1 h-full text-sm outline-none border-0"
            style="background: transparent; color: var(--text-primary)"
          >
            {#each accountList as acct}
              <option value={acct.id}>{acct.description ? `${acct.description} — ` : ''}{acct.email}</option>
            {/each}
          </select>
          {#if senderAccount}
            <span class="sender-context text-[11px] px-2 py-1 rounded-full shrink-0" style="background: var(--bg-tertiary); color: var(--text-secondary)">
              Sending as {senderAccount.short_label || senderAccount.description || senderAccount.email.split('@')[0]}
            </span>
          {/if}
        </div>
      {/if}

      <!-- To -->
      <div class="compose-field flex items-start px-6 min-h-10 py-1 border-b" style="border-color: var(--border-subtle)">
        <label for="compose-to" class="text-sm w-16 shrink-0" style="color: var(--text-secondary)">To</label>
        <div class="flex-1 min-w-0">
          <input
            type="text"
            id="compose-to"
            bind:value={to}
            placeholder="recipient@example.com"
            class="w-full h-8 text-sm outline-none"
            style="background: transparent; color: var(--text-primary)"
            aria-describedby="recipient-help"
          />
          {#if recipientChips.length > 0}
            <div class="flex flex-wrap gap-1 pb-1" id="recipient-help">
              {#each recipientChips as address}
                <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px]" style="background: var(--bg-tertiary); color: var(--text-secondary)">
                  {address}
                  <button onclick={() => removeRecipient(address)} aria-label="Remove recipient {address}"><Icon name="x" size={11} /></button>
                </span>
              {/each}
            </div>
          {/if}
        </div>
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
        <div class="compose-field flex items-center px-6 h-10 border-b" style="border-color: var(--border-subtle)">
          <label for="compose-cc" class="text-sm w-16 shrink-0" style="color: var(--text-secondary)">Cc</label>
          <input
            type="text"
            id="compose-cc"
            bind:value={cc}
            class="flex-1 h-full text-sm outline-none"
            style="background: transparent; color: var(--text-primary)"
          />
        </div>
        <div class="compose-field flex items-center px-6 h-10 border-b" style="border-color: var(--border-subtle)">
          <label for="compose-bcc" class="text-sm w-16 shrink-0" style="color: var(--text-secondary)">Bcc</label>
          <input
            type="text"
            id="compose-bcc"
            bind:value={bcc}
            class="flex-1 h-full text-sm outline-none"
            style="background: transparent; color: var(--text-primary)"
          />
        </div>
      {/if}

      <!-- Subject -->
      <div class="compose-field flex items-center px-6 h-10" style="border-color: var(--border-subtle)">
        <label for="compose-subject" class="text-sm w-16 shrink-0" style="color: var(--text-secondary)">Subject</label>
        <input
          type="text"
          id="compose-subject"
          bind:value={subject}
          placeholder="Subject"
          class="flex-1 h-full text-sm outline-none"
          style="background: transparent; color: var(--text-primary)"
        />
      </div>

      <div class="compose-field flex items-start gap-2 px-6 py-2 border-t" style="border-color: var(--border-subtle)">
        <label for="compose-files" class="text-sm w-16 shrink-0 pt-1" style="color: var(--text-secondary)">Files</label>
        <div class="flex-1 min-w-0">
          <input id="compose-files" bind:this={fileInput} type="file" multiple class="hidden" onchange={addAttachments} />
          <button
            onclick={() => fileInput?.click()}
            class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-xs font-medium"
            style="border-color: var(--border-color); color: var(--text-secondary)"
          >
            <Icon name="paperclip" size={14} /> Attach files
          </button>
          {#if attachments.length > 0}
            <div class="flex flex-wrap gap-1.5 mt-2">
              {#each attachments as attachment, index}
                <span class="inline-flex items-center gap-1.5 max-w-full px-2 py-1 rounded-md text-xs" style="background: var(--bg-tertiary); color: var(--text-secondary)">
                  <span class="truncate max-w-[220px]">{attachment.filename}</span>
                  <span class="text-[10px] opacity-70">{Math.ceil(attachment.size / 1024)} KB</span>
                  <button onclick={() => removeAttachment(index)} aria-label="Remove attachment {attachment.filename}"><Icon name="x" size={12} /></button>
                </span>
              {/each}
              <span class="text-[10px] self-center" style="color: var(--text-tertiary)">{(totalAttachmentBytes / 1024 / 1024).toFixed(1)} of 18 MB</span>
            </div>
          {/if}
        </div>
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

<style>
  @media (max-width: 767px) {
    .compose-header {
      padding: 0.5rem;
      gap: 0.5rem;
      flex-wrap: wrap;
    }
    .compose-header h2,
    .autosave-label,
    .sender-context {
      display: none;
    }
    .compose-field {
      padding-left: 0.75rem;
      padding-right: 0.75rem;
    }
    .compose-field > label {
      width: 3.25rem;
    }
  }
</style>
