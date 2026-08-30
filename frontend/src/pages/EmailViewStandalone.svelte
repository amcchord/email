<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { createAuthenticatedSessionGuard, showToast } from '../lib/stores.js';
  import EmailView from '../components/email/EmailView.svelte';

  let { emailId = null } = $props();

  let email = $state(null);
  let loading = $state(true);
  let sessionGuard = null;
  let loadGeneration = 0;

  function standaloneSessionIsCurrent() {
    return Boolean(sessionGuard?.isCurrent());
  }

  onMount(() => {
    sessionGuard = createAuthenticatedSessionGuard();
    document.title = 'Mail';
    if (emailId) {
      void loadEmail(emailId);
    }
    return () => {
      loadGeneration += 1;
      sessionGuard.dispose();
      document.title = 'Mail';
    };
  });

  async function loadEmail(id) {
    if (!standaloneSessionIsCurrent()) return false;
    const requestGeneration = ++loadGeneration;
    loading = true;
    try {
      const result = await api.getEmail(id);
      if (!standaloneSessionIsCurrent() || requestGeneration !== loadGeneration) return false;
      email = result;
      // Update window title
      if (email && email.subject) {
        document.title = email.subject + ' - Mail';
      }
      // Mark as read
      if (email && !email.is_read) {
        await api.emailActions([id], 'mark_read');
        if (!standaloneSessionIsCurrent() || requestGeneration !== loadGeneration) return false;
      }
      return true;
    } catch (err) {
      if (standaloneSessionIsCurrent() && requestGeneration === loadGeneration) {
        showToast(err.message, 'error');
      }
      return false;
    } finally {
      if (standaloneSessionIsCurrent() && requestGeneration === loadGeneration) loading = false;
    }
  }

  async function handleAction(action, emailIds) {
    if (!standaloneSessionIsCurrent()) return false;
    try {
      await api.emailActions(emailIds, action);
      if (!standaloneSessionIsCurrent()) return false;
      showToast(`${action.replace('_', ' ')} applied`, 'success');
      // Reload to reflect changes
      if (emailId) {
        await loadEmail(emailId);
      }
      return true;
    } catch (err) {
      if (standaloneSessionIsCurrent()) showToast(err.message, 'error');
      return false;
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
