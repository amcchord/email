<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import {
    emails, emailsLoading, emailsTotal, currentPageNum,
    currentMailbox, selectedEmailId, selectedAccountId,
    searchQuery, showToast,
  } from '../lib/stores.js';
  import EmailList from '../components/email/EmailList.svelte';
  import EmailView from '../components/email/EmailView.svelte';

  let selectedEmail = $state(null);
  let emailLoading = $state(false);
  let pageSize = 50;
  let mounted = $state(false);

  onMount(() => {
    mounted = true;
    loadEmails();
  });

  $effect(() => {
    void $currentMailbox;
    void $selectedAccountId;
    void $searchQuery;
    if (!mounted) return;
    currentPageNum.set(1);
    selectedEmailId.set(null);
    selectedEmail = null;
    loadEmails();
  });

  $effect(() => {
    if ($selectedEmailId) {
      loadEmail($selectedEmailId);
    } else {
      selectedEmail = null;
    }
  });

  async function loadEmails() {
    emailsLoading.set(true);
    try {
      const params = {
        mailbox: $currentMailbox,
        page: $currentPageNum,
        page_size: pageSize,
      };
      if ($selectedAccountId) {
        params.account_id = $selectedAccountId;
      }
      if ($searchQuery) {
        params.search = $searchQuery;
      }
      const result = await api.listEmails(params);
      emails.set(result.emails);
      emailsTotal.set(result.total);
    } catch (err) {
      if (err.message !== 'Unauthorized') {
        showToast(err.message, 'error');
      }
    }
    emailsLoading.set(false);
  }

  async function loadEmail(id) {
    emailLoading = true;
    try {
      selectedEmail = await api.getEmail(id);
      // Mark as read
      if (!selectedEmail.is_read) {
        await api.emailActions([id], 'mark_read');
        emails.update(list => list.map(e => {
          if (e.id === id) {
            return { ...e, is_read: true };
          }
          return e;
        }));
      }
    } catch (err) {
      showToast(err.message, 'error');
    }
    emailLoading = false;
  }

  async function handleAction(action, emailIds) {
    try {
      await api.emailActions(emailIds, action);
      showToast(`${action.replace('_', ' ')} applied`, 'success');
      await loadEmails();
      if (action === 'trash' || action === 'spam' || action === 'archive') {
        selectedEmailId.set(null);
      }
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  function handlePageChange(newPage) {
    currentPageNum.set(newPage);
    loadEmails();
  }
</script>

<div class="h-full flex">
  <!-- Email List -->
  <div
    class="flex flex-col border-r overflow-hidden"
    style="border-color: var(--border-color); width: {$selectedEmailId ? '380px' : '100%'}; min-width: {$selectedEmailId ? '380px' : 'auto'}"
  >
    <EmailList
      emails={$emails}
      loading={$emailsLoading}
      total={$emailsTotal}
      page={$currentPageNum}
      {pageSize}
      selectedId={$selectedEmailId}
      onSelect={(id) => selectedEmailId.set(id)}
      onAction={handleAction}
      onPageChange={handlePageChange}
    />
  </div>

  <!-- Email View -->
  {#if $selectedEmailId}
    <div class="flex-1 min-w-0 overflow-hidden">
      <EmailView
        email={selectedEmail}
        loading={emailLoading}
        onAction={handleAction}
        onClose={() => selectedEmailId.set(null)}
      />
    </div>
  {/if}
</div>
