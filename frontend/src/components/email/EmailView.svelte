<script>
  import { onDestroy, onMount } from 'svelte';
  import { currentPage, composeData, showToast, pendingReplyDraft, accounts, todos, accountColorMap } from '../../lib/stores.js';
  import { commandPaletteOpen, helpModalOpen, registerActions } from '../../lib/shortcutStore.js';
  import { theme } from '../../lib/theme.js';
  import { api } from '../../lib/api.js';
  import {
    MAX_ACTIVE_ATTACHMENT_REQUESTS,
    canStartAttachmentDownload,
    isCurrentAttachmentRequest,
    isRetryableAttachmentError,
    safeClientFilename,
    saveAttachmentBlob,
  } from '../../lib/attachmentDownload.js';
  import {
    attachmentPreviewHint,
    attachmentSafetyNotice,
    attachmentTypeLabel,
    isCurrentAttachmentPreviewRequest,
    materializeAttachmentPreview,
    releaseAttachmentPreview,
  } from '../../lib/attachmentPreview.js';
  import { sanitizeHtml } from '../../lib/sanitize.js';
  import { get } from 'svelte/store';
  import Button from '../common/Button.svelte';
  import Icon from '../common/Icon.svelte';
  import AttachmentPreview from './AttachmentPreview.svelte';

  let { email = null, loading = false, onAction = null, onClose = null, standalone = false } = $props();

  let iframeEl = $state(null);
  let unsubscribing = $state(false);
  let addingTodos = $state(false);
  let showTodoPrompt = $state(false);
  let downloadingAttachmentIds = $state(new Set());
  let attachmentTransferKinds = $state(new Map());
  let attachmentFeedback = $state(new Map());
  let attachmentRequestGeneration = 0;
  let attachmentPreviewGeneration = 0;
  let attachmentEmailId = null;
  let attachmentAbortControllers = new Map();
  let attachmentPreview = $state(null);
  let attachmentPreviewReturnFocus = $state(null);

  onMount(() => registerActions({
    'inbox.reply': {
      run: handleReply,
      isEnabled: () => Boolean(email) && !loading,
      disabledReason: 'Wait for the selected email to load',
    },
    'inbox.forward': {
      run: handleForward,
      isEnabled: () => Boolean(email) && !loading,
      disabledReason: 'Wait for the selected email to load',
    },
  }));

  onDestroy(() => {
    closeAttachmentPreview();
    abortAttachmentRequests();
  });

  function abortAttachmentRequests() {
    for (const controller of attachmentAbortControllers.values()) controller.abort();
    attachmentAbortControllers = new Map();
    attachmentTransferKinds = new Map();
  }

  $effect(() => {
    const nextEmailId = email?.id ?? null;
    if (nextEmailId !== attachmentEmailId) {
      closeAttachmentPreview();
      abortAttachmentRequests();
      attachmentEmailId = nextEmailId;
      attachmentRequestGeneration += 1;
      downloadingAttachmentIds = new Set();
      attachmentTransferKinds = new Map();
      attachmentFeedback = new Map();
    }
  });

  function formatAttachmentSize(sizeBytes) {
    if (!Number.isFinite(sizeBytes) || sizeBytes <= 0) return 'size unavailable';
    if (sizeBytes >= 1048576) return `${(sizeBytes / 1048576).toFixed(1)} MB`;
    return `${Math.max(1, Math.ceil(sizeBytes / 1024))} KB`;
  }

  function attachmentAccessibleLabel(attachment, transferKind, isTerminal, transferCapReached) {
    const action = transferKind === 'download'
      ? 'Downloading'
      : (transferKind === 'preview'
        ? 'Download unavailable while preparing preview for'
        : (isTerminal || transferCapReached ? 'Download unavailable for' : 'Download'));
    const filename = safeClientFilename(attachment.filename);
    const contentType = attachmentTypeLabel(attachment);
    return `${action} ${filename}, ${contentType}, ${formatAttachmentSize(attachment.size_bytes)}`;
  }

  function previewAccessibleLabel(attachment, transferKind, isTerminal, transferCapReached) {
    const filename = safeClientFilename(attachment.filename);
    const action = transferKind === 'preview'
      ? 'Loading preview for'
      : (transferKind === 'download'
        ? 'Preview unavailable while downloading'
        : (isTerminal || transferCapReached ? 'Preview unavailable for' : 'Preview'));
    return `${action} ${filename}, ${attachmentTypeLabel(attachment)}, ${formatAttachmentSize(attachment.size_bytes)}`;
  }

  function setAttachmentFeedback(attachmentId, feedback) {
    attachmentFeedback = new Map(attachmentFeedback).set(attachmentId, feedback);
  }

  function previewRequestIsCurrent(requestedEmailId, attachmentId, previewGeneration) {
    return isCurrentAttachmentPreviewRequest({
      requestedEmailId,
      requestedAttachmentId: attachmentId,
      requestedGeneration: previewGeneration,
      currentEmailId: email?.id ?? null,
      currentAttachmentId: attachmentPreview?.attachment?.id,
      currentGeneration: attachmentPreviewGeneration,
    });
  }

  function releaseCurrentAttachmentPreview() {
    releaseAttachmentPreview(attachmentPreview?.preview);
  }

  function cancelCurrentPreviewTransfer() {
    const previewAttachmentId = attachmentPreview?.attachment?.id;
    if (attachmentTransferKinds.get(previewAttachmentId) !== 'preview') return;
    const controller = previewAttachmentId
      ? attachmentAbortControllers.get(previewAttachmentId)
      : null;
    controller?.abort();
    if (previewAttachmentId && controller) {
      const nextControllers = new Map(attachmentAbortControllers);
      nextControllers.delete(previewAttachmentId);
      attachmentAbortControllers = nextControllers;
      const nextIds = new Set(downloadingAttachmentIds);
      nextIds.delete(previewAttachmentId);
      downloadingAttachmentIds = nextIds;
      const nextKinds = new Map(attachmentTransferKinds);
      nextKinds.delete(previewAttachmentId);
      attachmentTransferKinds = nextKinds;
    }
  }

  function closeAttachmentPreview() {
    attachmentPreviewGeneration += 1;
    cancelCurrentPreviewTransfer();
    releaseCurrentAttachmentPreview();
    attachmentPreview = null;
  }

  function attachmentPreviewState(attachment, mode, extras = {}) {
    return {
      attachment,
      mode,
      displayName: safeClientFilename(attachment.filename),
      typeLabel: attachmentTypeLabel(attachment),
      sizeLabel: formatAttachmentSize(attachment.size_bytes),
      notice: attachmentSafetyNotice(attachment),
      preview: null,
      error: null,
      downloadMode: null,
      downloadError: null,
      ...extras,
    };
  }

  async function openAttachmentPreview(attachment, returnFocusTarget = null) {
    if (!email) return;
    if (returnFocusTarget instanceof HTMLElement) {
      attachmentPreviewReturnFocus = returnFocusTarget;
    }
    commandPaletteOpen.set(false);
    helpModalOpen.set(false);
    cancelCurrentPreviewTransfer();
    releaseCurrentAttachmentPreview();
    const requestedEmailId = email.id;
    const previewGeneration = ++attachmentPreviewGeneration;
    const hint = attachmentPreviewHint(attachment);
    if (!hint) {
      attachmentPreview = attachmentPreviewState(attachment, 'unsupported');
      return;
    }
    if (!canStartAttachmentDownload(downloadingAttachmentIds, attachment.id)) {
      attachmentPreview = attachmentPreviewState(attachment, 'error', {
        error: {
          retryable: true,
          message: downloadingAttachmentIds.has(attachment.id)
            ? 'This attachment is already being transferred.'
            : 'Three other attachment transfers are active. Try again when one finishes.',
        },
      });
      return;
    }

    const abortController = new AbortController();
    attachmentAbortControllers = new Map(attachmentAbortControllers).set(
      attachment.id,
      abortController,
    );
    downloadingAttachmentIds = new Set(downloadingAttachmentIds).add(attachment.id);
    attachmentTransferKinds = new Map(attachmentTransferKinds).set(attachment.id, 'preview');
    attachmentPreview = attachmentPreviewState(attachment, 'loading');
    try {
      const result = await api.previewAttachment(
        requestedEmailId,
        attachment.id,
        { signal: abortController.signal },
      );
      const preview = await materializeAttachmentPreview(result, { expectedKind: hint });
      if (!previewRequestIsCurrent(requestedEmailId, attachment.id, previewGeneration)) {
        releaseAttachmentPreview(preview);
        return;
      }
      if (preview.kind === 'pdf') {
        releaseAttachmentPreview(preview);
        preview.blob = null;
        preview.objectUrl = null;
        preview.sourceUrl = api.attachmentPreviewUrl(requestedEmailId, attachment.id);
      }
      attachmentPreview = attachmentPreviewState(attachment, 'ready', { preview });
    } catch (err) {
      if (err?.name !== 'AbortError'
        && previewRequestIsCurrent(requestedEmailId, attachment.id, previewGeneration)) {
        attachmentPreview = attachmentPreviewState(attachment, 'error', {
          notice: err?.status === 415
            ? {
              tone: 'danger',
              label: 'File contents could not be verified',
              detail: 'The attachment bytes did not match the expected preview type. Download only if you expected this file.',
              requiresConfirmation: true,
            }
            : attachmentSafetyNotice(attachment),
          error: {
            retryable: isRetryableAttachmentError(err?.status),
            message: err?.message || 'The preview could not be prepared.',
          },
        });
      }
    } finally {
      if (attachmentAbortControllers.get(attachment.id) === abortController) {
        const nextControllers = new Map(attachmentAbortControllers);
        nextControllers.delete(attachment.id);
        attachmentAbortControllers = nextControllers;
        const nextIds = new Set(downloadingAttachmentIds);
        nextIds.delete(attachment.id);
        downloadingAttachmentIds = nextIds;
        const nextKinds = new Map(attachmentTransferKinds);
        nextKinds.delete(attachment.id);
        attachmentTransferKinds = nextKinds;
      }
    }
  }

  async function downloadAttachment(
    attachment,
    confirmed = false,
    returnFocusTarget = null,
  ) {
    if (!email) return;
    const previewNotice = attachmentPreview?.attachment?.id === attachment.id
      ? attachmentPreview.notice
      : null;
    const safetyNotice = attachmentSafetyNotice(attachment) || previewNotice;
    if (safetyNotice?.requiresConfirmation && !confirmed) {
      if (returnFocusTarget instanceof HTMLElement) {
        attachmentPreviewReturnFocus = returnFocusTarget;
      }
      commandPaletteOpen.set(false);
      helpModalOpen.set(false);
      releaseCurrentAttachmentPreview();
      attachmentPreview = attachmentPreviewState(attachment, 'confirm', {
        notice: safetyNotice,
      });
      return;
    }
    const downloadDialogGeneration = attachmentPreviewGeneration;
    const downloadDialogIsCurrent = () => (
      attachmentPreview?.attachment?.id === attachment.id
      && attachmentPreviewGeneration === downloadDialogGeneration
    );
    if (!canStartAttachmentDownload(downloadingAttachmentIds, attachment.id)) {
      const message = downloadingAttachmentIds.has(attachment.id)
        ? 'This attachment is already being transferred.'
        : `Wait for one of the ${MAX_ACTIVE_ATTACHMENT_REQUESTS} active attachment transfers to finish.`;
      if (downloadDialogIsCurrent()) {
        attachmentPreview = { ...attachmentPreview, downloadMode: 'error', downloadError: message };
      }
      return;
    }
    const requestedEmailId = email.id;
    const requestGeneration = attachmentRequestGeneration;
    const filename = safeClientFilename(attachment.filename);
    const abortController = new AbortController();
    attachmentAbortControllers = new Map(attachmentAbortControllers).set(
      attachment.id,
      abortController,
    );
    downloadingAttachmentIds = new Set(downloadingAttachmentIds).add(attachment.id);
    attachmentTransferKinds = new Map(attachmentTransferKinds).set(attachment.id, 'download');
    if (downloadDialogIsCurrent()) {
      attachmentPreview = { ...attachmentPreview, downloadMode: 'loading', downloadError: null };
    }
    setAttachmentFeedback(attachment.id, {
      emailId: requestedEmailId,
      type: 'status',
      message: `Downloading ${filename}…`,
    });
    const requestIsCurrent = () => (
      attachmentAbortControllers.get(attachment.id) === abortController
      && isCurrentAttachmentRequest({
        requestedEmailId,
        requestGeneration,
        currentEmailId: email?.id ?? null,
        currentGeneration: attachmentRequestGeneration,
      })
    );
    let downloadSucceeded = false;
    try {
      const content = await api.downloadAttachment(
        requestedEmailId,
        attachment.id,
        { signal: abortController.signal },
      );
      if (!requestIsCurrent()) return;
      saveAttachmentBlob(content, filename);
      downloadSucceeded = true;
      setAttachmentFeedback(attachment.id, {
        emailId: requestedEmailId,
        type: 'status',
        message: `Download started for ${filename}`,
      });
      if (downloadDialogIsCurrent()) {
        attachmentPreview = { ...attachmentPreview, downloadMode: 'success', downloadError: null };
      }
    } catch (err) {
      if (err?.name !== 'AbortError' && requestIsCurrent()) {
        const message = `Couldn’t download ${filename}. ${err.message || 'Try again.'}`;
        setAttachmentFeedback(attachment.id, {
          emailId: requestedEmailId,
          type: 'error',
          retryable: isRetryableAttachmentError(err?.status),
          message,
        });
        if (downloadDialogIsCurrent()) {
          attachmentPreview = { ...attachmentPreview, downloadMode: 'error', downloadError: message };
        }
      }
    } finally {
      if (attachmentAbortControllers.get(attachment.id) === abortController) {
        const nextControllers = new Map(attachmentAbortControllers);
        nextControllers.delete(attachment.id);
        attachmentAbortControllers = nextControllers;
        const nextIds = new Set(downloadingAttachmentIds);
        nextIds.delete(attachment.id);
        downloadingAttachmentIds = nextIds;
        const nextKinds = new Map(attachmentTransferKinds);
        nextKinds.delete(attachment.id);
        attachmentTransferKinds = nextKinds;
      }
    }
    if (confirmed && downloadSucceeded && downloadDialogIsCurrent()) closeAttachmentPreview();
  }

  async function handleUnignore() {
    if (!email) return;
    try {
      await api.unignoreNeedsReply(email.id);
      email.needs_reply_ignored = false;
      showToast('Restored to needs reply', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

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
  let replyIntent = $state(null); // tracks which reply option intent was selected

  // When the email changes, check if there's a pending reply draft for it
  $effect(() => {
    if (!email) {
      inlineReplyOpen = false;
      inlineReplyBody = '';
      lastDraftEmailId = null;
      replyFromSuggestion = false;
      replyIntent = null;
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
      replyIntent = null;
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
    replyIntent = null;
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
        </style></head><body>${sanitizeHtml(email.body_html)}</body></html>`);
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

  function handleReplyOption(option) {
    if (!email || !option) return;
    inlineReplyOpen = true;
    lastDraftEmailId = email.id;
    inlineReplyBody = option.body || '';
    replyFromSuggestion = true;
    replyIntent = option.intent || null;
  }

  // Intent label mapping for the suggestion banner
  const intentLabels = {
    accept: 'acceptance',
    decline: 'decline',
    defer: 'deferral',
    not_relevant: 'pass',
    custom: 'reply',
  };

  // Intent style mapping for the reply option buttons in the AI summary
  const intentButtonStyles = {
    accept: 'bg-emerald-50 dark:bg-emerald-500/20 border-emerald-200 dark:border-emerald-500/30 text-emerald-700 dark:text-emerald-300',
    decline: 'bg-red-50 dark:bg-red-500/15 border-red-200 dark:border-red-500/30 text-red-700 dark:text-red-300',
    defer: 'bg-amber-50 dark:bg-amber-500/20 border-amber-200 dark:border-amber-500/30 text-amber-700 dark:text-amber-300',
    not_relevant: 'bg-gray-50 dark:bg-gray-700/40 border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-300',
    custom: 'bg-blue-50 dark:bg-blue-500/20 border-blue-200 dark:border-blue-500/30 text-blue-700 dark:text-blue-300',
  };

  function resolveAccountId() {
    const accountList = get(accounts);
    if (accountList.length === 1) {
      return accountList[0].id;
    }
    if (accountList.length > 1 && email && email.account_email) {
      const matched = accountList.find(a => a.email === email.account_email);
      if (matched) {
        return matched.id;
      }
    }
    if (accountList.length > 0) {
      return accountList[0].id;
    }
    return null;
  }

  function handleFullCompose() {
    if (!email) return;
    composeData.set({
      draft_key: `reply:${email.account_id || 'account'}:${email.id}`,
      account_id: resolveAccountId(),
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
      draft_key: `forward:${email.account_id || 'account'}:${email.id}`,
      account_id: resolveAccountId(),
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
              <span class="inline-block text-xs px-2 py-0.5 rounded-full font-medium {email.ai_email_type === 'work' ? 'bg-purple-100 dark:bg-purple-500/20 text-purple-700 dark:text-purple-300' : 'bg-teal-100 dark:bg-teal-500/20 text-teal-700 dark:text-teal-300'}">
                {emailTypeLabels[email.ai_email_type] || email.ai_email_type}
              </span>
            {/if}
            {#if email.ai_category}
              <span class="inline-block text-xs px-2 py-0.5 rounded-full font-medium" style="background: var(--bg-tertiary); color: var(--text-secondary)">
                {categoryLabels[email.ai_category] || email.ai_category}
              </span>
            {/if}
            {#if email.needs_reply}
              {#if email.needs_reply_ignored}
                <span class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium bg-gray-100 dark:bg-gray-700/50 text-gray-500 dark:text-gray-300">
                  Needs Reply: Ignored
                  <button
                    onclick={handleUnignore}
                    class="ml-0.5 hover:text-blue-600 dark:hover:text-blue-400 transition-fast"
                    title="Restore to needs reply"
                  >
                    <Icon name="rotate-ccw" size={12} />
                  </button>
                </span>
              {:else}
                <span class="inline-block text-xs px-2 py-0.5 rounded-full font-medium bg-blue-100 dark:bg-blue-500/20 text-blue-700 dark:text-blue-300">
                  Needs Reply
                </span>
              {/if}
            {/if}
            {#if email.is_subscription}
              <span class="inline-block text-xs px-2 py-0.5 rounded-full font-medium bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-300">
                Subscription
              </span>
            {/if}
          </div>
        </div>
        <div class="flex items-center gap-1 shrink-0">
          <button
            onclick={() => onAction && onAction(email.is_starred ? 'unstar' : 'star', [email.id])}
            class="min-w-11 min-h-11 inline-flex items-center justify-center rounded-md transition-fast"
            style="color: {email.is_starred ? 'var(--color-accent-500)' : 'var(--text-tertiary)'}"
            title={email.is_starred ? 'Unstar' : 'Star'}
            aria-label={email.is_starred ? 'Unstar email' : 'Star email'}
            data-shortcut="email.star"
          >
            <Icon name="star" size={20} />
          </button>
          {#if !email.is_trash && !email.is_spam}
            <button
              onclick={() => onAction && onAction('archive', [email.id])}
              class="min-w-11 min-h-11 inline-flex items-center justify-center rounded-md transition-fast"
              style="color: var(--text-tertiary)"
              title="Archive"
              aria-label="Archive email"
              data-shortcut="email.archive"
            >
              <Icon name="archive" size={20} />
            </button>
          {/if}
          {#if email.is_spam}
            <button
              onclick={() => onAction && onAction('unspam', [email.id])}
              class="min-w-11 min-h-11 inline-flex items-center justify-center rounded-md transition-fast"
              style="color: var(--color-accent-600)"
              title="Mark as not spam"
              aria-label="Mark email as not spam"
            >
              <Icon name="shield-check" size={20} />
            </button>
          {/if}
          <button
            onclick={() => onAction && onAction(email.is_trash ? 'untrash' : 'trash', [email.id])}
            class="min-w-11 min-h-11 inline-flex items-center justify-center rounded-md transition-fast"
            style="color: var(--text-tertiary)"
            title={email.is_trash ? 'Restore from trash' : 'Move to trash'}
            aria-label={email.is_trash ? 'Restore email from trash' : 'Move email to trash'}
            data-shortcut="email.trash"
          >
            <Icon name={email.is_trash ? 'rotate-ccw' : 'trash-2'} size={20} />
          </button>
          <!-- Pop out button -->
          {#if !standalone}
            <button
              onclick={handlePopOut}
              class="hidden sm:inline-flex min-w-11 min-h-11 items-center justify-center rounded-md transition-fast"
              style="color: var(--text-tertiary)"
              title="Open in new window"
              aria-label="Open email in new window"
              data-shortcut="email.popout"
            >
              <Icon name="external-link" size={20} />
            </button>
            <button
              onclick={onClose}
              class="min-w-11 min-h-11 inline-flex items-center justify-center rounded-md transition-fast ml-1"
              style="color: var(--text-tertiary)"
              title="Close"
              aria-label="Close email"
            >
              <Icon name="x" size={20} />
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
                  <Icon name="plus" size={12} />
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
                    <Icon name="plus" size={14} />
                  </button>
                </li>
              {/each}
            </ul>
          </div>
        {/if}
        {#if email.reply_options?.length > 0}
          <div class="mt-2">
            <div class="text-xs font-semibold mb-1.5" style="color: var(--color-accent-600)">Quick Replies</div>
            <div class="flex flex-wrap gap-2">
              {#each email.reply_options as option}
                <button
                  onclick={() => handleReplyOption(option)}
                  class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all duration-150 cursor-pointer {intentButtonStyles[option.intent] || intentButtonStyles.custom}"
                  title={option.body}
                >
                  {#if option.intent === 'accept'}
                    <Icon name="check" size={14} />
                  {:else if option.intent === 'decline'}
                    <Icon name="x" size={14} />
                  {:else if option.intent === 'defer'}
                    <Icon name="clock" size={14} />
                  {:else if option.intent === 'not_relevant'}
                    <Icon name="slash" size={14} />
                  {:else}
                    <Icon name="corner-up-left" size={14} />
                  {/if}
                  {option.label}
                </button>
              {/each}
            </div>
          </div>
        {:else if email.suggested_reply}
          <div class="mt-2">
            <div class="text-xs font-semibold mb-1" style="color: var(--color-accent-600)">Suggested Reply</div>
            <p class="text-sm italic" style="color: var(--text-secondary)">"{email.suggested_reply}"</p>
          </div>
        {/if}
      </div>
    {/if}

    <!-- Todo prompt after reply -->
    {#if showTodoPrompt && email.ai_action_items?.length > 0}
      <div class="px-6 py-3 border-b flex items-center gap-3" style="border-color: var(--border-color); background: var(--bg-tertiary)">
        <span class="shrink-0" style="color: var(--color-accent-500)">
          <Icon name="check-circle" size={16} />
        </span>
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
          <div class="grid grid-cols-1 gap-2 2xl:grid-cols-2">
            {#each email.attachments as att (att.id)}
              {@const feedback = attachmentFeedback.get(att.id)}
              {@const transferKind = attachmentTransferKinds.get(att.id)}
              {@const isDownloading = transferKind === 'download'}
              {@const isPreviewing = transferKind === 'preview'}
              {@const isBusy = Boolean(transferKind)}
              {@const transferCapReached = !isBusy && downloadingAttachmentIds.size >= MAX_ACTIVE_ATTACHMENT_REQUESTS}
              {@const isTerminal = feedback?.type === 'error' && !feedback.retryable}
              {@const previewHint = attachmentPreviewHint(att)}
              {@const safetyNotice = attachmentSafetyNotice(att)}
              {@const displayName = safeClientFilename(att.filename)}
              <div
                class="min-w-0 max-w-full rounded-xl border p-3"
                style="border-color: var(--border-color); background: var(--bg-tertiary)"
                role="group"
                aria-label="Attachment {displayName}"
              >
                <div class="flex min-w-0 items-start gap-3">
                  <span
                    class="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg"
                    style="color: var(--color-accent-600); background: var(--bg-primary)"
                    aria-hidden="true"
                  >
                    <Icon name={previewHint === 'image' ? 'image' : (previewHint === 'pdf' ? 'file-text' : 'paperclip')} size={17} />
                  </span>
                  <div class="min-w-0 flex-1">
                    <div class="truncate text-sm font-medium" style="color: var(--text-primary)" title={displayName}>
                      {displayName}
                    </div>
                    <div class="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-xs" style="color: var(--text-tertiary)">
                      <span>{attachmentTypeLabel(att)}</span>
                      <span aria-hidden="true">·</span>
                      <span>{formatAttachmentSize(att.size_bytes)}</span>
                      {#if att.is_inline}
                        <span aria-hidden="true">·</span>
                        <span>Inline</span>
                      {/if}
                    </div>
                  </div>
                  <div class="flex shrink-0 gap-1">
                    {#if previewHint}
                      <button
                        type="button"
                        class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg border transition-fast disabled:opacity-50"
                        style="border-color: var(--border-color); color: var(--text-secondary); background: var(--bg-primary)"
                        aria-label={previewAccessibleLabel(att, transferKind, isTerminal, transferCapReached)}
                        title={transferCapReached ? 'Wait for another attachment transfer to finish' : 'Preview'}
                        disabled={isBusy || isTerminal || transferCapReached}
                        onclick={(event) => openAttachmentPreview(att, event.currentTarget)}
                      >
                        <span class:animate-spin={isPreviewing}>
                          <Icon name={isPreviewing ? 'loader' : 'eye'} size={17} />
                        </span>
                      </button>
                    {/if}
                    <button
                      type="button"
                      class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg border transition-fast disabled:opacity-50"
                      style="border-color: var(--border-color); color: var(--text-secondary); background: var(--bg-primary)"
                      aria-label={attachmentAccessibleLabel(att, transferKind, isTerminal, transferCapReached)}
                      title={transferCapReached ? 'Wait for another attachment transfer to finish' : 'Download'}
                      disabled={isBusy || isTerminal || transferCapReached}
                      aria-busy={isDownloading}
                      onclick={(event) => downloadAttachment(att, false, event.currentTarget)}
                    >
                      <span class:animate-spin={isDownloading}>
                        <Icon name={isDownloading ? 'loader' : 'download'} size={17} />
                      </span>
                    </button>
                  </div>
                </div>
                {#if safetyNotice}
                  <div
                    class="mt-2 flex min-w-0 items-start gap-1.5 rounded-md px-2 py-1.5 text-xs"
                    style={safetyNotice.tone === 'danger'
                      ? 'color: var(--status-error); background: var(--bg-primary)'
                      : (safetyNotice.tone === 'caution'
                        ? 'color: var(--status-warning-text); background: var(--status-warning-bg); border: 1px solid var(--status-warning-border)'
                        : 'color: var(--text-tertiary); background: var(--bg-primary)')}
                  >
                    <span class="mt-0.5 shrink-0" aria-hidden="true">
                      <Icon name={safetyNotice.tone === 'danger' ? 'alert-triangle' : 'info'} size={13} />
                    </span>
                    <span class="min-w-0 break-words">
                      <strong>{safetyNotice.label}.</strong> {safetyNotice.detail}
                    </span>
                  </div>
                {/if}
                {#if feedback?.emailId === email.id}
                  <div
                    class="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 px-1 text-xs"
                    class:rounded-md={feedback.type === 'error'}
                    class:border={feedback.type === 'error'}
                    class:py-1={feedback.type === 'error'}
                    style={feedback.type === 'error'
                      ? 'border-color: var(--status-error); color: var(--status-error); background: var(--bg-tertiary)'
                      : 'color: var(--text-secondary)'}
                    role={feedback.type === 'error' ? 'alert' : 'status'}
                    aria-live={feedback.type === 'error' ? 'assertive' : 'polite'}
                    aria-atomic="true"
                  >
                    <span class="min-w-0 break-words">{feedback.message}</span>
                    {#if feedback.type === 'error' && feedback.retryable}
                      <button
                        type="button"
                        class="min-h-11 shrink-0 rounded-md border px-3 font-medium"
                        style="border-color: currentColor"
                        aria-label="Retry download {displayName}"
                        onclick={() => downloadAttachment(att)}
                      >Retry</button>
                    {/if}
                  </div>
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
            <span style="color: var(--color-accent-500)">
              <Icon name="corner-up-left" size={16} />
            </span>
            <span class="text-xs font-semibold" style="color: var(--text-primary)">Reply to {email.from_name || email.from_address}</span>
          </div>
          <div class="flex items-center gap-1">
            <button
              onclick={handleFullCompose}
              class="p-1 rounded transition-fast"
              style="color: var(--text-tertiary)"
              title="Open in full composer"
            >
              <Icon name="external-link" size={16} />
            </button>
            <button
              onclick={closeInlineReply}
              class="p-1 rounded transition-fast"
              style="color: var(--text-tertiary)"
              title="Close reply"
            >
              <Icon name="x" size={16} />
            </button>
          </div>
        </div>
        {#if replyFromSuggestion}
          <div class="flex items-center gap-1.5 mb-2 px-1">
            <svg class="w-3.5 h-3.5 shrink-0" style="color: var(--color-accent-500)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
            </svg>
            <span class="text-[11px] font-medium" style="color: var(--color-accent-600)">
              {#if replyIntent}
                AI-suggested {intentLabels[replyIntent] || 'reply'} — edit as needed
              {:else}
                AI-suggested reply — edit as needed
              {/if}
            </span>
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
              <Icon name="send" size={14} />
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
      <Button size="sm" class="min-h-11" onclick={handleReply}>
        <Icon name="corner-up-left" size={16} />
        Reply
      </Button>
      <Button size="sm" class="min-h-11" onclick={handleForward}>
        <Icon name="corner-up-right" size={16} />
        Forward
      </Button>
      {#if email.is_subscription && email.unsubscribe_info}
        <button
          onclick={handleUnsubscribe}
          disabled={unsubscribing}
          class="min-h-11 flex items-center gap-1.5 px-3 rounded-lg text-xs font-medium transition-fast ml-auto disabled:opacity-50"
          style="background: var(--status-error); color: white"
        >
          {#if unsubscribing}
            <div class="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
          {:else}
            <Icon name="slash" size={16} />
          {/if}
          Unsubscribe
        </button>
      {/if}
    </div>
  {/if}
</div>

{#if attachmentPreview && email}
  <AttachmentPreview
    viewerState={attachmentPreview}
    attachments={email.attachments || []}
    returnFocusTarget={attachmentPreviewReturnFocus}
    onclose={closeAttachmentPreview}
    onselect={openAttachmentPreview}
    onretry={openAttachmentPreview}
    ondownload={downloadAttachment}
  />
{/if}
