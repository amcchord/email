<script>
  import { onDestroy, onMount, tick } from 'svelte';
  import { captureAuthenticatedSession, createAuthenticatedSessionGuard, currentPage, composeData, isAuthenticatedSessionCurrent, showToast, pendingReplyDraft, accounts, labels as labelsStore, todos, accountColorMap } from '../../lib/stores.js';
  import { commandPaletteOpen, helpModalOpen, registerActions } from '../../lib/shortcutStore.js';
  import { api } from '../../lib/api.js';
  import { submitOutboundSend } from '../../lib/outboundSend.js';
  import { restoreOutboundComposeDraft } from '../../lib/outboundDraftRecovery.js';
  import { createIndexedDbDraftStorage } from '../../lib/draftStorage.js';
  import {
    createDurableReplyController,
    replyBodyText,
    replyTextHtml,
  } from '../../lib/durableReply.js';
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
  import { sanitizeComposeHtml } from '../../lib/sanitize.js';
  import {
    buildReplyEnvelope,
    REPLY_ENVELOPE_MODES,
    REPLY_ENVELOPE_UNAVAILABLE,
    replyCompletionStillCurrent,
    resolveReplySourceAccount,
  } from '../../lib/replyEnvelope.js';
  import { get } from 'svelte/store';
  import Button from '../common/Button.svelte';
  import Icon from '../common/Icon.svelte';
  import AttachmentPreview from './AttachmentPreview.svelte';
  import DraftStatus from './DraftStatus.svelte';
  import EmailHtmlFrame from './EmailHtmlFrame.svelte';
  import SendSplitButton from '../common/SendSplitButton.svelte';
  import InlineSnippetMenu from './InlineSnippetMenu.svelte';
  import SnippetPicker from './SnippetPicker.svelte';
  import SignatureControl from './SignatureControl.svelte';
  import { safeLabelColor, visibleUserLabels } from '../../lib/labelWorkflows.js';
  import {
    canArchiveAfterSend,
    sendArchiveAcceptedMessage,
    withArchiveAfterSend,
  } from '../../lib/sendArchive.js';
  import { insertSnippetText } from '../../lib/personalSnippets.js';
  import {
    findInlineSnippetTrigger,
    replaceInlineSnippetText,
  } from '../../lib/inlineSnippetExpansion.js';
  import {
    browserFollowUpTimeZone,
    followUpPolicyForAccount,
    followUpRequestFields,
    followUpSendSummary,
    normalizeFollowUpPolicyList,
    normalizeFollowUpReminderMode,
  } from '../../lib/followUpReminders.js';
  import {
    accountSignatureFor,
    authoritativeSignatureSnapshot,
    normalizeAccountSignatureList,
    normalizeSignatureMode,
    normalizeSignatureSnapshot,
    signatureSnapshotAfterModeChange,
    signatureSnapshotFromPolicy,
  } from '../../lib/accountSignatures.js';

  let {
    email = null,
    loading = false,
    onAction = null,
    onLabel = null,
    allowMove = false,
    onSnooze = null,
    onClose = null,
    onGuardChange = null,
    standalone = false,
  } = $props();

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
  let inlineReplyMode = $state(REPLY_ENVELOPE_MODES.REPLY);
  let inlineReplyTextarea = $state(null);
  let snippetPickerOpen = $state(false);
  let snippetSelection = null;
  let inlineSnippetMenuHandle = $state(null);
  let inlineSnippetTrigger = $state(null);
  let inlineSnippetA11y = $state({ expanded: false, controls: null, activeDescendant: null });
  let inlineSnippetActivation = 0;
  let inlineSnippetComposing = false;
  let dismissedInlineSnippetSignature = null;
  let primaryReplyButton = $state(null);
  let openingManagedDraft = $state(false);
  let draftOpenMessage = $state('');

  let replyEnvelopeResult = $derived(buildReplyEnvelope({
    message: email,
    accounts: $accounts,
    mode: REPLY_ENVELOPE_MODES.REPLY,
  }));
  let userLabelState = $derived(visibleUserLabels(email, $labelsStore, $accounts, 4));
  let replyAllEnvelopeResult = $derived(buildReplyEnvelope({
    message: email,
    accounts: $accounts,
    mode: REPLY_ENVELOPE_MODES.REPLY_ALL,
  }));
  let activeReplyEnvelopeResult = $derived(
    inlineReplyMode === REPLY_ENVELOPE_MODES.REPLY_ALL
      ? replyAllEnvelopeResult
      : replyEnvelopeResult,
  );
  let showReplyAll = $derived(
    replyAllEnvelopeResult.available
      && replyAllEnvelopeResult.envelope.to.length + replyAllEnvelopeResult.envelope.cc.length > 1,
  );
  let inlineReplyActionLabel = $derived(
    inlineReplyMode === REPLY_ENVELOPE_MODES.REPLY_ALL ? 'Send Reply All' : 'Send Reply',
  );
  let inlineReplyCanArchive = $derived(
    activeReplyEnvelopeResult.available
      && canArchiveAfterSend({ source_email_id: email?.id }),
  );
  let replySourceResult = $derived(resolveReplySourceAccount({
    message: email,
    accounts: $accounts,
  }));
  const sessionGuard = createAuthenticatedSessionGuard();
  let durableDraftStorage = null;
  let durableReply = $state.raw(null);
  let durableReplyController = $state.raw(null);
  let unsubscribeDurableReply = null;
  let durableReplyState = $state({ status: 'pristine', canSend: false, snapshot: {} });
  let durableReplyOpening = $state(false);
  let durableReplyError = $state('');
  let inlineReplySendMode = $state('send');
  let durableReplyEmailId = null;
  let durableReplyMode = null;
  let replyReturnFocus = null;
  let durableReplyRelease = Promise.resolve();
  let followUpPolicies = $state([]);
  let followUpPoliciesLoaded = $state(false);
  let followUpMode = $state('default');
  let followUpTimeZone = $state(browserFollowUpTimeZone());
  let selectedFollowUpPolicy = $derived(followUpPolicyForAccount(
    followUpPolicies,
    activeReplyEnvelopeResult?.envelope?.account_id,
  ));
  let followUpAvailable = $derived(
    followUpPoliciesLoaded && activeReplyEnvelopeResult.available && Boolean(selectedFollowUpPolicy),
  );
  let followUpDefault = $derived(Boolean(selectedFollowUpPolicy?.enabled));
  let followUpSummary = $derived(followUpSendSummary(selectedFollowUpPolicy));
  let signaturePolicies = $state([]);
  let signaturePoliciesLoaded = $state(false);
  let signaturePoliciesFailed = $state(false);
  let signatureUnsignedAcknowledged = $state(false);
  let signaturePolicyLoadGeneration = 0;
  let signatureMode = $state('disabled');
  let signatureSnapshot = $state.raw(null);
  let signatureInitialized = $state(false);
  let selectedSignaturePolicy = $derived(accountSignatureFor(
    signaturePolicies,
    activeReplyEnvelopeResult?.envelope?.account_id,
  ));
  let signatureReady = $derived(
    signaturePoliciesLoaded
      || (signaturePoliciesFailed && signatureUnsignedAcknowledged),
  );

  function sessionIsCurrent() {
    return sessionGuard.isCurrent();
  }

  function loadSignaturePolicies() {
    const requestGeneration = ++signaturePolicyLoadGeneration;
    signaturePoliciesLoaded = false;
    signaturePoliciesFailed = false;
    signatureUnsignedAcknowledged = false;
    return api.listAccountSignatures()
      .then(response => {
        if (requestGeneration !== signaturePolicyLoadGeneration || !sessionIsCurrent()) return;
        signaturePolicies = normalizeAccountSignatureList(response).accounts;
        signaturePoliciesLoaded = true;
        if (signatureInitialized && signatureMode === 'default' && !signatureSnapshot) {
          signatureSnapshot = signatureSnapshotFromPolicy(selectedSignaturePolicy);
          persistInlineReply();
        }
      })
      .catch(() => {
        if (requestGeneration !== signaturePolicyLoadGeneration || !sessionIsCurrent()) return;
        signaturePolicies = [];
        signaturePoliciesFailed = true;
      });
  }

  function replyUnavailableMessage(reason) {
    if (reason === REPLY_ENVELOPE_UNAVAILABLE.SOURCE_ACCOUNT_INACTIVE) {
      return 'The source account is inactive. Reconnect it before replying.';
    }
    if (
      reason === REPLY_ENVELOPE_UNAVAILABLE.SOURCE_ACCOUNT_IDENTITY_MISSING
      || reason === REPLY_ENVELOPE_UNAVAILABLE.SOURCE_ACCOUNT_NOT_FOUND
    ) {
      return "This message's source account is unavailable. Refresh accounts or reconnect the matching account before replying.";
    }
    if (
      reason === REPLY_ENVELOPE_UNAVAILABLE.SOURCE_ACCOUNT_MISMATCH
      || reason === REPLY_ENVELOPE_UNAVAILABLE.SOURCE_ACCOUNT_AMBIGUOUS
      || reason === REPLY_ENVELOPE_UNAVAILABLE.SOURCE_ACCOUNT_IDENTITY_INVALID
    ) {
      return 'The sending account could not be verified. Refresh accounts before replying.';
    }
    return 'Reply recipients could not be verified. Refresh the message before sending.';
  }

  onMount(() => registerActions({
    'inbox.reply': {
      run: handleReply,
      isEnabled: () => Boolean(email) && !loading && replyEnvelopeResult.available,
      disabledReason: () => loading
        ? 'Wait for the selected email to load'
        : replyUnavailableMessage(replyEnvelopeResult.reason),
    },
    'inbox.forward': {
      run: handleForward,
      isEnabled: () => Boolean(email) && !loading && replySourceResult.available,
      disabledReason: () => loading
        ? 'Wait for the selected email to load'
        : replyUnavailableMessage(replySourceResult.reason),
    },
    'inbox.sendArchive': {
      run: () => sendInlineReply(null, { archiveAfterSend: true }),
      isEnabled: () => (
        inlineReplyOpen
        && inlineReplyCanArchive
        && Boolean(inlineReplyBody.trim())
        && durableReplyState.canSend
        && signatureReady
        && !inlineReplySending
        && !durableReplyError
      ),
      disabledReason: () => {
        if (!inlineReplyOpen || !inlineReplyCanArchive) return 'Open a verified reply first';
        if (!inlineReplyBody.trim()) return 'Write a reply first';
        if (durableReplyError) return 'Retry the saved reply before sending';
        if (!durableReplyState.canSend) return 'Reply is not ready to send';
        return inlineReplySending ? 'Reply is already sending' : 'Reply is unavailable';
      },
    },
    'inbox.snippets': {
      run: () => {
        capturePersonalSnippetSelection();
        snippetPickerOpen = true;
      },
      isEnabled: () => (
        inlineReplyOpen
        && Boolean(inlineReplyTextarea)
        && !durableReplyOpening
        && !durableReplyError
        && !durableReplyState.discardInProgress
        && !durableReplyState.sendInProgress
      ),
      disabledReason: () => !inlineReplyOpen
        ? 'Open a reply first'
        : durableReplyError
          ? 'Retry the saved reply before inserting a snippet'
          : 'Reply editor is still opening',
    },
  }));

  onMount(() => {
    let disposed = false;
    void api.listFollowUpPolicies()
      .then(response => {
        if (disposed || !sessionIsCurrent()) return;
        followUpPolicies = normalizeFollowUpPolicyList(response).accounts;
        followUpPoliciesLoaded = true;
      })
      .catch(() => {
        if (disposed || !sessionIsCurrent()) return;
        followUpPolicies = [];
        followUpPoliciesLoaded = false;
      });
    return () => { disposed = true; };
  });

  onMount(() => {
    void loadSignaturePolicies();
    return () => { signaturePolicyLoadGeneration += 1; };
  });

  onDestroy(() => {
    const release = releaseDurableReply({ flush: true });
    onGuardChange?.(null);
    sessionGuard.dispose();
    void Promise.resolve(release).finally(() => durableDraftStorage?.close?.());
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
    return sessionIsCurrent() && isCurrentAttachmentPreviewRequest({
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
    if (!email || !sessionIsCurrent()) return;
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
      if (sessionIsCurrent()
        && attachmentAbortControllers.get(attachment.id) === abortController) {
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
    if (!email || !sessionIsCurrent()) return;
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
      sessionIsCurrent()
      && attachmentPreview?.attachment?.id === attachment.id
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
      sessionIsCurrent()
      && attachmentAbortControllers.get(attachment.id) === abortController
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
      if (sessionIsCurrent()
        && attachmentAbortControllers.get(attachment.id) === abortController) {
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
    if (!email || !sessionIsCurrent()) return;
    try {
      await api.unignoreNeedsReply(email.id);
      if (!sessionIsCurrent()) return;
      email.needs_reply_ignored = false;
      showToast('Restored to needs reply', 'success');
    } catch (err) {
      if (sessionIsCurrent()) showToast(err.message, 'error');
    }
  }

  async function addAllTodos() {
    if (!email || !sessionIsCurrent()) return;
    addingTodos = true;
    try {
      const result = await api.createTodosFromEmail(email.id);
      if (!sessionIsCurrent()) return;
      if (result.created > 0) {
        todos.update(list => [...result.todos, ...list]);
        showToast(`Added ${result.created} action items to todos`, 'success');
      } else {
        showToast('Action items already in todos', 'info');
      }
    } catch (err) {
      if (sessionIsCurrent()) showToast(err.message, 'error');
    }
    if (!sessionIsCurrent()) return;
    addingTodos = false;
    showTodoPrompt = false;
  }

  async function addSingleTodo(item) {
    if (!email || !sessionIsCurrent()) return;
    try {
      const todo = await api.createTodo({
        title: item,
        email_id: email.id,
      });
      if (!sessionIsCurrent()) return;
      todos.update(list => [todo, ...list]);
      showToast('Added to todos', 'success');
    } catch (err) {
      if (sessionIsCurrent()) showToast(err.message, 'error');
    }
  }

  // Inline reply state
  let inlineReplyOpen = $state(false);
  let inlineReplyBody = $state('');
  let inlineReplySending = $state(false);
  let lastDraftEmailId = null;
  let observedInlineReplyEmailId = null;
  let replyFromSuggestion = $state(false);
  let replyIntent = $state(null); // tracks which reply option intent was selected
  let inlineReplyGeneration = 0;

  function releaseDurableReply({ flush = false } = {}) {
    const controller = durableReplyController;
    unsubscribeDurableReply?.();
    unsubscribeDurableReply = null;
    durableReply = null;
    durableReplyController = null;
    durableReplyEmailId = null;
    durableReplyMode = null;
    if (!controller) return durableReplyRelease;
    if (flush) {
      durableReplyRelease = controller.flush().catch(() => {}).finally(() => controller.dispose());
      return durableReplyRelease;
    }
    controller.dispose();
    durableReplyRelease = Promise.resolve();
    return durableReplyRelease;
  }

  async function prepareInlineReplyTransition() {
    const controller = durableReplyController;
    if (!controller) return true;
    if (durableReplyOpening) {
      showToast('Wait for the saved reply to finish opening.', 'info');
      return false;
    }
    const before = controller.getState();
    if (before.discardInProgress) {
      showToast('Undo the discard or wait for it to finish before leaving this reply.', 'info');
      return false;
    }
    if (before.sendInProgress) {
      showToast('Wait while the send is being confirmed.', 'info');
      return false;
    }
    persistInlineReply();
    if (durableReplyError) {
      showToast('Reply is only in this open editor. Copy it or retry before leaving.', 'error');
      return false;
    }
    try {
      await controller.flush();
    } catch (error) {
      durableReplyError = error?.message || 'Reply could not be saved safely.';
      showToast('Reply is not safely saved yet. Retry before leaving.', 'error');
      return false;
    }
    const state = controller.getState();
    if (state?.error?.phase === 'local') {
      durableReplyError = state.error.message || 'Local draft storage failed.';
      showToast('Reply is only in this open editor. Copy it or retry before leaving.', 'error');
      return false;
    }
    return true;
  }

  $effect(() => {
    if (typeof onGuardChange !== 'function') return;
    onGuardChange(prepareInlineReplyTransition);
    return () => onGuardChange(null);
  });

  function ensureDurableStorage() {
    if (durableDraftStorage) return durableDraftStorage;
    durableDraftStorage = createIndexedDbDraftStorage();
    return durableDraftStorage;
  }

  function persistInlineReply() {
    if (!durableReplyController || durableReplyOpening || durableReplyError) return false;
    try {
      durableReplyController.update(durableReply.snapshot(
        replyTextHtml(inlineReplyBody),
        inlineReplyBody,
        {
          followUpReminder: followUpMode,
          followUpTimeZone: followUpRequestFields({
            mode: followUpMode,
            policy: selectedFollowUpPolicy,
            timeZone: followUpTimeZone,
          }).follow_up_time_zone,
          signatureInitialized,
          signatureMode,
          signatureSnapshot,
        },
      ));
      return true;
    } catch (error) {
      durableReplyError = error?.message || 'Reply could not be saved safely.';
      return false;
    }
  }

  async function focusInlineReply() {
    await tick();
    inlineReplyTextarea?.focus();
  }

  async function openDurableReply(mode, { seedBody = null } = {}) {
    if (!email || !sessionIsCurrent()) return false;
    const reply = mode === REPLY_ENVELOPE_MODES.REPLY_ALL
      ? replyAllEnvelopeResult
      : replyEnvelopeResult;
    if (!reply.available) {
      showToast(replyUnavailableMessage(reply.reason), 'error');
      return false;
    }
    if (
      durableReplyController
      && durableReplyEmailId === email.id
      && durableReplyMode === mode
    ) {
      inlineReplyOpen = true;
      await focusInlineReply();
      return true;
    }

    const emailAtStart = email;
    const generationAtStart = ++inlineReplyGeneration;
    const priorBody = inlineReplyBody;
    if (!(await prepareInlineReplyTransition())) return false;
    releaseDurableReply();
    if (!sessionIsCurrent() || email?.id !== emailAtStart.id) return false;
    durableReplyOpening = true;
    durableReplyError = '';
    followUpMode = 'default';
    followUpTimeZone = browserFollowUpTimeZone();
    signatureInitialized = true;
    signatureUnsignedAcknowledged = false;
    signatureMode = 'default';
    signatureSnapshot = signatureSnapshotFromPolicy(selectedSignaturePolicy);
    inlineReplyOpen = true;
    inlineReplyMode = mode;
    lastDraftEmailId = email.id;
    replyReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    try {
      const storage = ensureDurableStorage();
      const owner = createDurableReplyController({
        userId: sessionGuard.userId,
        storage,
        api,
        envelope: reply.envelope,
        captureSession: captureAuthenticatedSession,
        isSessionCurrent: isAuthenticatedSessionCurrent,
        onDiscard: () => {
          if (email?.id !== emailAtStart.id) return;
          const focusTarget = replyReturnFocus;
          inlineReplyBody = '';
          inlineReplyOpen = false;
          lastDraftEmailId = null;
          releaseDurableReply();
          replyReturnFocus = null;
          void tick().then(() => {
            if (focusTarget?.isConnected) focusTarget.focus();
          });
        },
      });
      durableReply = owner;
      durableReplyController = owner.controller;
      durableReplyEmailId = email.id;
      durableReplyMode = mode;
      unsubscribeDurableReply = owner.controller.subscribe(state => {
        if (durableReplyController !== owner.controller || !sessionIsCurrent()) return;
        durableReplyState = state;
        const frozenSignature = authoritativeSignatureSnapshot(state.snapshot?.signature_snapshot);
        if (frozenSignature) {
          signatureSnapshot = frozenSignature;
          signatureInitialized = true;
        }
      });
      const initialBody = seedBody ?? priorBody;
      const initialFollowUp = followUpRequestFields({
        mode: followUpMode,
        policy: selectedFollowUpPolicy,
        timeZone: followUpTimeZone,
      });
      const state = await owner.open(owner.snapshot(replyTextHtml(initialBody), initialBody, {
        followUpReminder: initialFollowUp.follow_up_reminder,
        followUpTimeZone: initialFollowUp.follow_up_time_zone,
        signatureInitialized,
        signatureMode,
        signatureSnapshot,
      }));
      if (
        !sessionIsCurrent()
        || durableReplyController !== owner.controller
        || email?.id !== emailAtStart.id
        || generationAtStart !== inlineReplyGeneration
      ) return false;
      const savedBody = state.snapshot?.body_text || replyBodyText(state.snapshot?.body_html || '');
      inlineReplyBody = savedBody || initialBody || '';
      followUpMode = normalizeFollowUpReminderMode(state.snapshot?.follow_up_reminder);
      followUpTimeZone = state.snapshot?.follow_up_time_zone || browserFollowUpTimeZone();
      signatureInitialized = state.snapshot?.signature_initialized === true
        || Boolean(state.snapshot?.signature_snapshot);
      signatureMode = signatureInitialized
        ? normalizeSignatureMode(state.snapshot?.signature_mode)
        : 'disabled';
      signatureSnapshot = normalizeSignatureSnapshot(state.snapshot?.signature_snapshot);
      if (!savedBody && initialBody) persistInlineReply();
      durableReplyState = owner.controller.getState();
      durableReplyOpening = false;
      await focusInlineReply();
      return true;
    } catch (error) {
      if (sessionIsCurrent() && email?.id === emailAtStart.id) {
        durableReplyOpening = false;
        durableReplyError = error?.message || 'Reply drafts are unavailable.';
        showToast('Couldn’t open a safely saved reply. Try again.', 'error');
      }
      return false;
    }
  }

  function advanceInlineReplyGeneration() {
    inlineReplyGeneration += 1;
  }

  // When the email changes, check if there's a pending reply draft for it
  $effect(() => {
    const emailId = email?.id ?? null;
    if (emailId === observedInlineReplyEmailId) return;
    observedInlineReplyEmailId = emailId;
    advanceInlineReplyGeneration();
    if (!email) {
      releaseDurableReply({ flush: true });
      inlineReplyOpen = false;
      inlineReplyBody = '';
      lastDraftEmailId = null;
      replyFromSuggestion = false;
      replyIntent = null;
      inlineReplyMode = REPLY_ENVELOPE_MODES.REPLY;
      followUpMode = 'default';
      followUpTimeZone = browserFollowUpTimeZone();
      signatureInitialized = false;
      signatureMode = 'disabled';
      signatureSnapshot = null;
      return;
    }

    const draft = get(pendingReplyDraft);
    if (draft && draft.emailId === email.id) {
      replyFromSuggestion = !!draft.body;
      inlineReplyMode = REPLY_ENVELOPE_MODES.REPLY;
      followUpMode = 'default';
      followUpTimeZone = browserFollowUpTimeZone();
      signatureInitialized = false;
      signatureMode = 'disabled';
      signatureSnapshot = null;
      lastDraftEmailId = email.id;
      // Clear the pending draft so it doesn't re-trigger
      pendingReplyDraft.set(null);
      void openDurableReply(REPLY_ENVELOPE_MODES.REPLY, { seedBody: draft.body || '' });
    } else if (email.id !== lastDraftEmailId) {
      // Different email selected, close the inline reply
      releaseDurableReply({ flush: true });
      inlineReplyOpen = false;
      inlineReplyBody = '';
      lastDraftEmailId = null;
      replyFromSuggestion = false;
      replyIntent = null;
      inlineReplyMode = REPLY_ENVELOPE_MODES.REPLY;
      followUpMode = 'default';
      followUpTimeZone = browserFollowUpTimeZone();
      signatureInitialized = false;
      signatureMode = 'disabled';
      signatureSnapshot = null;
    }
  });

  async function openInlineReply() {
    advanceInlineReplyGeneration();
    inlineReplyMode = REPLY_ENVELOPE_MODES.REPLY;
    if (!replyEnvelopeResult.available) {
      showToast(replyUnavailableMessage(replyEnvelopeResult.reason), 'error');
      return;
    }
    await openDurableReply(REPLY_ENVELOPE_MODES.REPLY);
    // If empty and there's no text yet, don't pre-fill (user is manually replying)
  }

  async function closeInlineReply() {
    advanceInlineReplyGeneration();
    const controller = durableReplyController;
    const focusTarget = replyReturnFocus;
    if (!(await prepareInlineReplyTransition())) return false;
    inlineReplyOpen = false;
    lastDraftEmailId = null;
    replyFromSuggestion = false;
    replyIntent = null;
    inlineReplyMode = REPLY_ENVELOPE_MODES.REPLY;
    releaseDurableReply();
    inlineReplyBody = '';
    followUpMode = 'default';
    followUpTimeZone = browserFollowUpTimeZone();
    signatureInitialized = false;
    signatureMode = 'disabled';
    signatureSnapshot = null;
    const finalState = controller?.getState();
    showToast(
      finalState?.status === 'conflict'
        ? 'Reply kept. Review its versions from Drafts.'
        : finalState?.status === 'offline' || finalState?.status === 'failed'
          ? 'Reply saved on this device. Sync still needs attention.'
          : 'Reply saved. Continue it from Drafts.',
      'success',
    );
    await tick();
    if (focusTarget?.isConnected) focusTarget.focus();
    return true;
  }

  async function sendInlineReply(schedule = null, { archiveAfterSend = false } = {}) {
    if (!email || !inlineReplyBody.trim() || !sessionIsCurrent() || !durableReplyController) return false;
    if (!signatureReady) {
      showToast('Wait for this account’s signature settings to finish loading.', 'info');
      return false;
    }
    const replyAtStart = activeReplyEnvelopeResult;
    if (!replyAtStart.available) {
      showToast(replyUnavailableMessage(replyAtStart.reason), 'error');
      return false;
    }
    if (archiveAfterSend && !inlineReplyCanArchive) {
      showToast('Open a verified reply before using Send & archive.', 'error');
      return false;
    }
    const emailAtStart = email;
    const emailIdAtStart = email.id;
    const bodyAtStart = inlineReplyBody;
    const generationAtStart = inlineReplyGeneration;
    if (!persistInlineReply()) return false;
    try {
      await durableReplyController.markSending(true);
    } catch (error) {
      if (sessionIsCurrent()) showToast(error?.message || 'Reply must be saved before sending.', 'error');
      return false;
    }
    const controllerAtStart = durableReplyController;
    const replyOwnerAtStart = durableReply;
    const sendReturnFocus = replyReturnFocus;
    let payload = withArchiveAfterSend(replyOwnerAtStart.sendPayload(), archiveAfterSend);
    const restoreDraft = {
      draft_key: `client:${payload.client_draft_id}`,
      ...payload,
    };
    // Recovered drafts never remember an explicit Send & archive invocation.
    delete restoreDraft.archive_source_after_send;
    if (schedule?.scheduledFor) {
      payload.scheduled_for = schedule.scheduledFor;
      payload.schedule_timezone = schedule.scheduleTimezone;
    }
    let editorReleased = false;
    const releaseEditor = () => {
      if (editorReleased || !sessionIsCurrent()) return;
      editorReleased = true;
      const sentDraftStillActive = replyCompletionStillCurrent({
        capturedGeneration: generationAtStart,
        currentGeneration: inlineReplyGeneration,
        capturedEmailId: emailIdAtStart,
        currentEmailId: email?.id,
        capturedBody: bodyAtStart,
        currentBody: inlineReplyBody,
      });
      if (sentDraftStillActive) {
        inlineReplyOpen = false;
        inlineReplyBody = '';
        releaseDurableReply();
        replyReturnFocus = null;
        void tick().then(() => {
          if (sendReturnFocus?.isConnected) sendReturnFocus.focus();
          else primaryReplyButton?.focus?.();
        });
      }
    };
    inlineReplySending = true;
    inlineReplySendMode = schedule ? 'schedule' : (archiveAfterSend ? 'archive' : 'send');
    try {
      const operation = await submitOutboundSend(payload, {
        onAccepted: () => {
          if (archiveAfterSend && sessionIsCurrent()) {
            showToast(
              sendArchiveAcceptedMessage({ scheduled: Boolean(schedule?.scheduledFor) }),
              'info',
              6000,
            );
          }
        },
        onSent: () => {
          void durableDraftStorage?.delete?.(sessionGuard.userId, payload.client_draft_id);
          if (
            sessionIsCurrent()
            && email?.id === emailIdAtStart
            && emailAtStart.ai_action_items?.length > 0
          ) {
            showTodoPrompt = true;
          }
        },
        onRestore: (operation, reason) => restoreOutboundComposeDraft(restoreDraft, operation, reason),
      });
      if (!sessionIsCurrent()) return false;
      if (operation) {
        await controllerAtStart.markSendUncertain(operation);
        releaseEditor();
        return true;
      }
    } catch (err) {
      if (sessionIsCurrent()) showToast(err.message, 'error');
      return false;
    } finally {
      if (sessionIsCurrent()) {
        inlineReplySending = false;
        inlineReplySendMode = 'send';
        await controllerAtStart?.markSending(false);
      }
    }
    return false;
  }

  function handleSignatureChange(mode) {
    if (!signaturePoliciesLoaded || durableReplyOpening || durableReplyState.sendInProgress) return;
    signatureInitialized = true;
    signatureMode = normalizeSignatureMode(mode);
    signatureSnapshot = signatureSnapshotAfterModeChange({
      mode: signatureMode,
      policy: selectedSignaturePolicy,
      snapshot: signatureSnapshot,
    });
    persistInlineReply();
  }

  function handleContinueWithoutSignature() {
    if (!signaturePoliciesFailed || durableReplyOpening || durableReplyState.sendInProgress) return;
    signatureUnsignedAcknowledged = true;
    signatureMode = 'disabled';
    persistInlineReply();
  }

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

  async function handleReply() {
    if (!email) return;
    advanceInlineReplyGeneration();
    inlineReplyMode = REPLY_ENVELOPE_MODES.REPLY;
    if (!replyEnvelopeResult.available) {
      showToast(replyUnavailableMessage(replyEnvelopeResult.reason), 'error');
      return;
    }
    const suggested = !inlineReplyBody.trim() && email.suggested_reply ? email.suggested_reply : null;
    const opened = await openDurableReply(REPLY_ENVELOPE_MODES.REPLY, { seedBody: suggested });
    if (!opened) return;
    // If user hasn't typed anything yet, pre-fill with suggested reply if available
    if (!inlineReplyBody.trim() && email.suggested_reply) {
      inlineReplyBody = email.suggested_reply;
      replyFromSuggestion = true;
      persistInlineReply();
    }
  }

  async function handleReplyAll() {
    if (!email) return;
    advanceInlineReplyGeneration();
    inlineReplyMode = REPLY_ENVELOPE_MODES.REPLY_ALL;
    if (!replyAllEnvelopeResult.available) {
      showToast(replyUnavailableMessage(replyAllEnvelopeResult.reason), 'error');
      return;
    }
    const suggested = !inlineReplyBody.trim() && email.suggested_reply ? email.suggested_reply : null;
    const opened = await openDurableReply(REPLY_ENVELOPE_MODES.REPLY_ALL, { seedBody: suggested });
    if (!opened) return;
    if (!inlineReplyBody.trim() && email.suggested_reply) {
      inlineReplyBody = email.suggested_reply;
      replyFromSuggestion = true;
      persistInlineReply();
    }
  }

  async function handleReplyOption(option) {
    if (!email || !option) return;
    advanceInlineReplyGeneration();
    inlineReplyMode = REPLY_ENVELOPE_MODES.REPLY;
    if (!replyEnvelopeResult.available) {
      showToast(replyUnavailableMessage(replyEnvelopeResult.reason), 'error');
      return;
    }
    const opened = await openDurableReply(REPLY_ENVELOPE_MODES.REPLY, { seedBody: option.body || '' });
    if (!opened) return;
    inlineReplyBody = option.body || '';
    replyFromSuggestion = true;
    replyIntent = option.intent || null;
    persistInlineReply();
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

  async function handleFullCompose() {
    if (!email) return;
    const reply = activeReplyEnvelopeResult;
    if (!reply.available) {
      showToast(replyUnavailableMessage(reply.reason), 'error');
      return;
    }
    if (!durableReplyController || !durableReply) {
      const opened = await openDurableReply(inlineReplyMode);
      if (!opened) return;
    }
    persistInlineReply();
    try {
      await durableReplyController.flush();
    } catch (error) {
      showToast(error?.message || 'Reply must be safely saved before opening full Compose.', 'error');
      return;
    }
    const state = durableReplyController.getState();
    if (state?.error?.phase === 'local') {
      durableReplyError = state.error.message || 'Local draft storage failed.';
      showToast('Reply is only in this open editor. Retry before opening full Compose.', 'error');
      return;
    }
    composeData.set(durableReply.composeData());
    inlineReplyOpen = false;
    releaseDurableReply();
    currentPage.set('compose');
  }

  async function discardInlineReply() {
    if (!durableReplyController) return;
    const discardOwner = durableReplyController;
    await discardOwner.discard({ delayMs: 10000 });
    showToast('Reply discarded', 'info', 10000, {
      actionLabel: 'Undo',
      onAction: () => discardOwner.undoDiscard(),
    });
  }

  async function requestEmailClose() {
    if (await prepareInlineReplyTransition()) onClose?.();
  }

  function retryInlineDraft() {
    durableReplyError = '';
    void durableReplyController?.retry();
  }

  function undoInlineDiscard() {
    void durableReplyController?.undoDiscard();
  }

  function handleInlineReplyKeydown(event) {
    if (inlineSnippetMenuHandle?.handleKeydown?.(event)) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      void closeInlineReply();
      return;
    }
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      event.stopPropagation();
      if (durableReplyState.canSend && inlineReplyBody.trim()) {
        void sendInlineReply(null, { archiveAfterSend: event.shiftKey });
      }
    }
  }

  function setReaderInlineSnippetTrigger(next) {
    if (!next) {
      inlineSnippetTrigger = null;
      return;
    }
    const signature = `${next.from}:${next.to}:${next.token}`;
    if (signature === dismissedInlineSnippetSignature) {
      inlineSnippetTrigger = null;
      return;
    }
    dismissedInlineSnippetSignature = null;
    const activation = inlineSnippetTrigger?.from === next.from
      ? inlineSnippetTrigger.activation
      : ++inlineSnippetActivation;
    inlineSnippetTrigger = { ...next, activation };
  }

  function dismissReaderInlineSnippet() {
    dismissedInlineSnippetSignature = inlineSnippetTrigger
      ? `${inlineSnippetTrigger.from}:${inlineSnippetTrigger.to}:${inlineSnippetTrigger.token}`
      : null;
    inlineSnippetTrigger = null;
  }

  function readerInlineSnippetTrigger(editor = inlineReplyTextarea) {
    if (
      !editor
      || typeof document.execCommand !== 'function'
      || inlineSnippetComposing
      || editor.selectionStart !== editor.selectionEnd
      || !inlineReplyOpen
      || editor.disabled
      || durableReplyError
      || !activeReplyEnvelopeResult.available
    ) return null;
    const parsed = findInlineSnippetTrigger(inlineReplyBody, editor.selectionStart);
    if (!parsed) return null;
    const rectangle = editor.getBoundingClientRect();
    return {
      ...parsed,
      kind: 'textarea',
      anchor: {
        left: rectangle.left + Math.min(24, rectangle.width / 8),
        top: rectangle.bottom - 8,
        bottom: rectangle.bottom,
      },
    };
  }

  function publishReaderInlineSnippetTrigger(editor = inlineReplyTextarea) {
    setReaderInlineSnippetTrigger(readerInlineSnippetTrigger(editor));
  }

  function handleInlineReplyInput(event) {
    advanceInlineReplyGeneration();
    persistInlineReply();
    if (event.isComposing) setReaderInlineSnippetTrigger(null);
    else publishReaderInlineSnippetTrigger(event.currentTarget);
  }

  function replaceReaderInlineSnippet(snippet) {
    const editor = inlineReplyTextarea;
    const trigger = inlineSnippetTrigger;
    const current = readerInlineSnippetTrigger(editor);
    if (
      !editor
      || !trigger
      || !current
      || current.from !== trigger.from
      || current.to !== trigger.to
      || current.token !== trigger.token
      || !sessionIsCurrent()
    ) return false;
    const replacement = replaceInlineSnippetText(
      inlineReplyBody,
      trigger,
      snippet?.body_text,
    );
    if (!replacement) return false;
    editor.focus({ preventScroll: true });
    editor.setSelectionRange(trigger.from, trigger.to);
    const insertedWithNativeUndo = document.execCommand?.(
      'insertText',
      false,
      replacement.inserted,
    ) === true;
    // Keep the existing picker as the compatibility path rather than silently
    // degrading the inline shortcut to a non-undoable programmatic mutation.
    if (!insertedWithNativeUndo) return false;
    setReaderInlineSnippetTrigger(null);
    editor.setSelectionRange(replacement.caret, replacement.caret);
    return true;
  }

  function readerInlineSnippetA11yChanged(state) {
    inlineSnippetA11y = state || { expanded: false, controls: null, activeDescendant: null };
  }

  function handleInlineSnippetCompositionStart() {
    inlineSnippetComposing = true;
    setReaderInlineSnippetTrigger(null);
  }

  function handleInlineSnippetCompositionEnd() {
    inlineSnippetComposing = false;
    publishReaderInlineSnippetTrigger();
  }

  $effect(() => {
    if (
      !inlineReplyOpen
      || durableReplyOpening
      || durableReplyError
      || !activeReplyEnvelopeResult.available
      || durableReplyState.discardInProgress
      || durableReplyState.sendInProgress
      || durableReplyState.status === 'conflict'
    ) setReaderInlineSnippetTrigger(null);
  });

  function capturePersonalSnippetSelection() {
    const editor = inlineReplyTextarea;
    if (!editor || !inlineReplyOpen) return false;
    snippetSelection = {
      start: editor.selectionStart,
      end: editor.selectionEnd,
    };
    return true;
  }

  async function insertPersonalSnippet(snippet) {
    const editor = inlineReplyTextarea;
    if (!editor || !inlineReplyOpen) return false;
    const selection = snippetSelection;
    snippetSelection = null;
    const result = insertSnippetText(
      inlineReplyBody,
      snippet?.body_text,
      selection?.start ?? editor.selectionStart,
      selection?.end ?? editor.selectionEnd,
    );
    inlineReplyBody = result.value;
    advanceInlineReplyGeneration();
    if (!persistInlineReply()) return false;
    await tick();
    if (editor.isConnected) {
      editor.focus({ preventScroll: true });
      editor.setSelectionRange(result.caret, result.caret);
    }
    showToast(`Inserted “${snippet.name}”`, 'success');
    return true;
  }

  async function openManagedDraft() {
    if (!email?.is_draft || openingManagedDraft || !sessionIsCurrent()) return;
    const emailIdAtStart = email.id;
    openingManagedDraft = true;
    draftOpenMessage = '';
    try {
      const detail = await api.getComposeDraftByEmail(email.id);
      if (!sessionIsCurrent() || email?.id !== emailIdAtStart || !detail?.client_draft_id) return;
      composeData.set({
        ...detail,
        client_draft_id: detail.client_draft_id,
        draft_key: `client:${detail.client_draft_id}`,
        intent_key: `provider:${detail.client_draft_id}`,
        draft_revision: detail.revision,
        draft_state: detail.state,
      });
      currentPage.set('compose');
    } catch (error) {
      if (!sessionIsCurrent()) return;
      draftOpenMessage = error?.status === 404
        ? 'This provider draft was not created by this app, so it remains read-only here.'
        : error?.message || 'This draft could not be opened for editing.';
    } finally {
      if (sessionIsCurrent()) openingManagedDraft = false;
    }
  }

  function handleForward() {
    if (!email) return;
    const source = replySourceResult;
    if (!source.available) {
      showToast(replyUnavailableMessage(source.reason), 'error');
      return;
    }
    const forwardedBody = email.body_html
      ? sanitizeComposeHtml(email.body_html)
      : String(email.body_text || '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('\n', '<br>');
    const forwardedFromName = String(email.from_name || '')
      .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
    const forwardedFromAddress = String(email.from_address || '')
      .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
    const forwardedSubject = String(email.subject || '')
      .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
    const forwardedText = String(email.body_text || '').trim();
    const quoteHtml = `---------- Forwarded message ----------<br>From: ${forwardedFromName} &lt;${forwardedFromAddress}&gt;<br>Date: ${formatFullDate(email.date)}<br>Subject: ${forwardedSubject}<br><br>${forwardedBody}`;
    const quoteText = `---------- Forwarded message ----------\nFrom: ${String(email.from_name || '')} <${String(email.from_address || '')}>\nDate: ${formatFullDate(email.date)}\nSubject: ${String(email.subject || '')}\n\n${forwardedText}`;
    composeData.set({
      draft_key: `forward:${email.account_id || 'account'}:${email.id}`,
      account_id: source.sourceAccount.id,
      to: [],
      cc: [],
      subject: email.subject?.startsWith('Fwd:') ? email.subject : `Fwd: ${email.subject || ''}`,
      body_html: '',
      body_text: '',
      composition_kind: 'forward',
      signature_mode: 'default',
      signature_initialized: true,
      quoted_html: quoteHtml,
      quoted_text: quoteText,
    });
    currentPage.set('compose');
  }

  function handlePopOut() {
    if (!email) return;
    const url = `/?view=email&id=${email.id}`;
    window.open(url, `email-${email.id}`, 'width=800,height=700,menubar=no,toolbar=no');
  }

  async function handleUnsubscribe() {
    if (!email || !sessionIsCurrent()) return;
    unsubscribing = true;
    try {
      const result = await api.unsubscribe(email.id);
      if (!sessionIsCurrent()) return;
      if (result.email_sent) {
        showToast(`Unsubscribe email sent to ${result.sent_to}`, 'success');
      } else if (result.url) {
        window.open(result.url, '_blank');
        showToast('Opened unsubscribe page in new tab', 'success');
      } else {
        showToast('No unsubscribe method available', 'error');
      }
    } catch (err) {
      if (sessionIsCurrent()) showToast(err.message, 'error');
    } finally {
      if (sessionIsCurrent()) unsubscribing = false;
    }
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
      <div class="email-reader-header flex items-start justify-between gap-4">
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
            {#each userLabelState.labels as label}
              <span
                class="max-w-36 truncate rounded-full px-2 py-0.5 text-xs font-medium"
                style="background: {safeLabelColor(label.color_bg, 'var(--bg-tertiary)')}; color: {safeLabelColor(label.color_text, 'var(--text-secondary)')}"
                title={label.name}
              >{label.name}</span>
            {/each}
            {#if userLabelState.overflow > 0}
              <span class="text-xs" style="color: var(--text-tertiary)" title={`${userLabelState.overflow} more labels`}>+{userLabelState.overflow}</span>
            {/if}
          </div>
        </div>
        <div class="email-reader-actions flex max-w-[55%] shrink-0 flex-wrap items-center justify-end gap-1">
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
          {#if onLabel}
            <button
              onclick={() => onLabel('apply', [email])}
              class="min-w-11 min-h-11 inline-flex items-center justify-center rounded-md transition-fast"
              style="color: var(--text-tertiary)"
              title="Apply or remove label · L"
              aria-label="Apply or remove label"
              data-shortcut="inbox.label"
            ><Icon name="tag" size={20} /></button>
            {#if allowMove}
              <button
                onclick={() => onLabel('move', [email])}
                class="min-w-11 min-h-11 inline-flex items-center justify-center rounded-md transition-fast"
                style="color: var(--text-tertiary)"
                title="Move out of Inbox to label · V"
                aria-label="Move email out of Inbox to label"
                data-shortcut="inbox.move"
              ><Icon name="folder" size={20} /></button>
            {/if}
          {/if}
          {#if onSnooze && !email.is_draft && !email.is_trash && !email.is_spam}
            <button
              onclick={() => onSnooze(email)}
              class="min-w-11 min-h-11 inline-flex items-center justify-center rounded-md transition-fast"
              style="color: {email.snooze_id ? 'var(--color-accent-600)' : 'var(--text-tertiary)'}"
              title={email.snooze_id ? 'Change reminder' : 'Snooze · H'}
              aria-label={email.snooze_id ? 'Change snooze reminder' : 'Snooze email and remind me later'}
              data-shortcut="inbox.snooze"
            >
              <Icon name="clock" size={20} />
            </button>
          {/if}
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
              onclick={requestEmailClose}
              class="reader-close-action min-w-11 min-h-11 inline-flex items-center justify-center rounded-md transition-fast ml-1"
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
        <EmailHtmlFrame
          html={email.body_html}
          contentKey={email.id}
          title="Message from {email.from_name || email.from_address || 'unknown sender'}"
          minHeight="100px"
        />
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
      <div class="inline-reply px-6 py-4 border-t shrink-0" style="border-color: var(--border-color); background: var(--bg-tertiary)" data-durable-reply data-client-draft-id={durableReplyState.clientDraftId || undefined}>
        <div class="flex items-start justify-between gap-3 mb-2">
          <div class="flex min-w-0 items-center gap-2">
            <span style="color: var(--color-accent-500)">
              <Icon name="corner-up-left" size={16} />
            </span>
            {#if activeReplyEnvelopeResult.available}
              <div
                class="text-xs leading-relaxed"
                style="color: var(--text-primary)"
                data-reply-envelope="inbox"
              >
                <div><strong>From:</strong> {activeReplyEnvelopeResult.sourceAccount.email}</div>
                <div><strong>To:</strong> {activeReplyEnvelopeResult.envelope.to.join(', ')}</div>
                {#if activeReplyEnvelopeResult.envelope.cc.length > 0}
                  <div><strong>Cc:</strong> {activeReplyEnvelopeResult.envelope.cc.join(', ')}</div>
                {/if}
                {#if inlineReplyMode === REPLY_ENVELOPE_MODES.REPLY_ALL}
                  <div class="mt-0.5 font-semibold" style="color: var(--color-accent-600)">Reply All</div>
                {/if}
              </div>
            {:else}
              <p
                class="text-xs font-medium"
                style="color: var(--status-error)"
                role="alert"
                data-reply-unavailable="inbox"
              >{replyUnavailableMessage(activeReplyEnvelopeResult.reason)}</p>
            {/if}
          </div>
          <div class="flex items-center gap-1">
            <button
              onclick={discardInlineReply}
              disabled={!durableReplyController || durableReplyOpening || durableReplyState.discardInProgress || durableReplyState.sendInProgress}
              class="inline-flex min-h-11 min-w-11 items-center justify-center rounded transition-fast disabled:opacity-50"
              style="color: var(--text-tertiary)"
              aria-label="Discard reply"
              title="Discard reply · Undo available for 10 seconds"
            >
              <Icon name="trash-2" size={16} />
            </button>
            <button
              onclick={handleFullCompose}
              disabled={!activeReplyEnvelopeResult.available || durableReplyOpening || Boolean(durableReplyError)}
              class="inline-flex min-h-11 min-w-11 items-center justify-center rounded transition-fast"
              class:opacity-50={!activeReplyEnvelopeResult.available}
              style="color: var(--text-tertiary)"
              aria-label="Open reply in full composer"
              title={activeReplyEnvelopeResult.available
                ? 'Open in full composer'
                : replyUnavailableMessage(activeReplyEnvelopeResult.reason)}
            >
              <Icon name="external-link" size={16} />
            </button>
            <button
              onclick={closeInlineReply}
              disabled={durableReplyOpening}
              class="inline-flex min-h-11 min-w-11 items-center justify-center rounded transition-fast"
              style="color: var(--text-tertiary)"
              aria-label="Close and keep reply"
              title="Close and keep reply · Escape"
            >
              <Icon name="x" size={16} />
            </button>
          </div>
        </div>
        <div class="mb-2 min-h-5">
          {#if durableReplyOpening}
            <span class="text-xs" style="color: var(--text-secondary)" role="status">Opening saved reply…</span>
          {:else if durableReplyError}
            <span id="inline-reply-save-error" class="inline-flex flex-wrap items-center gap-2 text-xs" style="color: var(--status-error)" role="alert">
              <span>Not safely saved. Copy your reply before leaving.</span>
              <button type="button" class="min-h-11 rounded-lg border px-3 font-semibold" onclick={retryInlineDraft}>Retry</button>
            </span>
          {:else}
            <DraftStatus
              state={durableReplyState}
              compact
              onretry={retryInlineDraft}
              onundo={undoInlineDiscard}
              onreview={handleFullCompose}
            />
          {/if}
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
        <div class="relative">
          <textarea
            bind:this={inlineReplyTextarea}
            bind:value={inlineReplyBody}
            oninput={handleInlineReplyInput}
            onkeydown={handleInlineReplyKeydown}
            onkeyup={() => publishReaderInlineSnippetTrigger()}
            onclick={() => publishReaderInlineSnippetTrigger()}
            onblur={() => setReaderInlineSnippetTrigger(null)}
            oncompositionstart={handleInlineSnippetCompositionStart}
            oncompositionend={handleInlineSnippetCompositionEnd}
            placeholder="Write your reply..."
            role="combobox"
            aria-autocomplete="list"
            aria-label="Reply message"
            aria-describedby={durableReplyError ? 'inline-reply-save-error' : undefined}
            aria-expanded={inlineSnippetA11y.expanded}
            aria-controls={inlineSnippetA11y.expanded ? inlineSnippetA11y.controls : undefined}
            aria-activedescendant={inlineSnippetA11y.expanded ? inlineSnippetA11y.activeDescendant : undefined}
            disabled={!activeReplyEnvelopeResult.available || durableReplyOpening || durableReplyState.discardInProgress || durableReplyState.sendInProgress || durableReplyState.status === 'conflict'}
            class="w-full rounded-lg border p-3 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-accent-500/40"
            style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary); min-height: 100px; max-height: 200px"
            rows="4"
          ></textarea>
          <InlineSnippetMenu
            bind:this={inlineSnippetMenuHandle}
            active={inlineSnippetTrigger}
            menuId="inline-snippets-reader"
            onchoose={replaceReaderInlineSnippet}
            ondismiss={dismissReaderInlineSnippet}
            ona11ychange={readerInlineSnippetA11yChanged}
          />
        </div>
        <SignatureControl
          initialized={signatureInitialized}
          mode={signatureMode}
          compositionKind="reply"
          policy={selectedSignaturePolicy}
          snapshot={signatureSnapshot}
          compact={true}
          disabled={durableReplyOpening || durableReplyState.sendInProgress || durableReplyState.discardInProgress}
          loadError={signaturePoliciesFailed}
          unsignedAcknowledged={signatureUnsignedAcknowledged}
          onchange={handleSignatureChange}
          onretry={loadSignaturePolicies}
          oncontinueunsigned={handleContinueWithoutSignature}
        />
        <div class="reply-actions flex items-center gap-2 mt-2">
          <SnippetPicker
            bind:open={snippetPickerOpen}
            compact={true}
            shortcutId="inbox.snippets"
            disabled={!activeReplyEnvelopeResult.available || durableReplyOpening || Boolean(durableReplyError) || durableReplyState.discardInProgress || durableReplyState.sendInProgress}
            oncapture={capturePersonalSnippetSelection}
            oninsert={insertPersonalSnippet}
          />
          <SendSplitButton
            label={inlineReplyActionLabel}
            disabled={!inlineReplyBody.trim() || !activeReplyEnvelopeResult.available || !durableReplyState.canSend || Boolean(durableReplyError) || !signatureReady}
            busy={inlineReplySending}
            busyLabel={inlineReplySendMode === 'schedule' ? 'Scheduling…' : 'Sending…'}
            onsend={() => sendInlineReply()}
            canArchiveAfterSend={inlineReplyCanArchive}
            onsendarchive={() => sendInlineReply(null, { archiveAfterSend: true })}
            onschedule={schedule => sendInlineReply(schedule, { archiveAfterSend: schedule.archiveAfterSend })}
            {followUpAvailable}
            {followUpMode}
            {followUpDefault}
            {followUpSummary}
            onfollowupchange={mode => {
              followUpMode = normalizeFollowUpReminderMode(mode);
              persistInlineReply();
            }}
          />
          <span class="text-[11px]" style="color: var(--text-tertiary)">⌘↵ Send · ⌘⇧↵ Send &amp; archive · Esc Close and keep</span>
        </div>
      </div>
    {/if}

    <!-- Reply actions -->
    <div class="px-6 py-3 border-t shrink-0 flex gap-2" style="border-color: var(--border-color)">
      {#if email.is_draft}
        <Button size="sm" class="min-h-11" onclick={openManagedDraft} disabled={openingManagedDraft}>
          <Icon name="edit-3" size={16} />
          {openingManagedDraft ? 'Opening…' : 'Edit draft'}
        </Button>
        {#if draftOpenMessage}
          <p class="min-w-0 self-center text-xs" style="color: var(--text-secondary)" role="status">
            {draftOpenMessage}
          </p>
        {/if}
      {:else}
        <Button bind:element={primaryReplyButton} size="sm" class="min-h-11" onclick={handleReply} disabled={!replyEnvelopeResult.available}>
        <Icon name="corner-up-left" size={16} />
        Reply
        </Button>
        {#if showReplyAll}
          <Button size="sm" class="min-h-11" onclick={handleReplyAll} disabled={!replyAllEnvelopeResult.available}>
            <Icon name="users" size={16} />
            Reply All
          </Button>
        {/if}
        <Button size="sm" class="min-h-11" onclick={handleForward} disabled={!replySourceResult.available}>
          <Icon name="corner-up-right" size={16} />
          Forward
        </Button>
        {#if !replyEnvelopeResult.available}
          <p
            class="min-w-0 self-center text-xs"
            style="color: var(--status-error)"
            role="status"
            data-reply-unavailable="inbox"
          >{replyUnavailableMessage(replyEnvelopeResult.reason)}</p>
        {/if}
      {/if}
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

<style>
  @media (max-width: 640px) {
    .email-reader-header {
      flex-direction: column;
      gap: 0.5rem;
    }
    .email-reader-actions {
      width: 100%;
      max-width: none;
      flex-wrap: nowrap;
      justify-content: flex-start;
      overflow-x: auto;
      overscroll-behavior-inline: contain;
      padding-bottom: 0.125rem;
      scrollbar-width: thin;
    }
    .email-reader-actions > :global(button) {
      flex: 0 0 2.75rem;
    }
    .email-reader-actions > :global(.reader-close-action) {
      order: -1;
      margin-left: 0;
    }
  }
</style>
