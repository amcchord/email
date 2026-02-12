<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { showToast } from '../lib/stores.js';
  import EmailView from '../components/email/EmailView.svelte';

  let { emailId = null } = $props();

  let email = $state(null);
  let loading = $state(true);

  onMount(async () => {
    if (emailId) {
      await loadEmail(emailId);
    }
  });

  async function loadEmail(id) {
    loading = true;
    try {
      email = await api.getEmail(id);
      // Update window title
      if (email && email.subject) {
        document.title = email.subject + ' - Mail';
      }
      // Mark as read
      if (email && !email.is_read) {
        await api.emailActions([id], 'mark_read');
      }
    } catch (err) {
      showToast(err.message, 'error');
    }
    loading = false;
  }

  async function handleAction(action, emailIds) {
    try {
      await api.emailActions(emailIds, action);
      showToast(`${action.replace('_', ' ')} applied`, 'success');
      // Reload to reflect changes
      if (emailId) {
        await loadEmail(emailId);
      }
    } catch (err) {
      showToast(err.message, 'error');
    }
  }
</script>

<div class="h-screen" style="background: var(--bg-primary)">
  <EmailView
    {email}
    {loading}
    onAction={handleAction}
    onClose={null}
    standalone={true}
  />
</div>
