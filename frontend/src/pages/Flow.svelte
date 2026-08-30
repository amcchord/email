<script>
  import { onMount, tick } from 'svelte';
  import { marked } from 'marked';
  import { api } from '../lib/api.js';
  import { sanitizeMarkdown } from '../lib/sanitize.js';
  import { chatConversations, createAuthenticatedSessionGuard, captureAuthenticatedSession, isAuthenticatedSessionCurrent, currentConversationId, showToast, currentPage, currentMailbox, selectedEmailId, pendingReplyDraft, accounts, composeData, threadOrder, accountColorMap } from '../lib/stores.js';
  import { get } from 'svelte/store';
  import { registerActions } from '../lib/shortcutStore.js';
  import { lastEvent } from '../lib/realtime.js';
  import Icon from '../components/common/Icon.svelte';
  import DaySummaryStrip from '../lib/flow/DaySummaryStrip.svelte';
  import { addPendingReplyId, capturedReplyStillActive, isCurrentFlowThreadRequest, newestThreadMessage, reconcileNeedsReplyRemoval, removePendingReplyId, replyDraftAccountKey } from '../lib/flow/replyActionState.js';
  import DeferredRichEditor from '../components/email/DeferredRichEditor.svelte';
  import { cleanEmailText } from '../lib/emailText.js';
  import {
    buildReplyEnvelope,
    normalizeReplyAddress,
    REPLY_ENVELOPE_MODES,
    REPLY_ENVELOPE_UNAVAILABLE,
    resolveReplySourceAccount,
  } from '../lib/replyEnvelope.js';
  import EmailHtmlFrame from '../components/email/EmailHtmlFrame.svelte';
  import { submitOutboundSend } from '../lib/outboundSend.js';
  import { restoreOutboundComposeDraft } from '../lib/outboundDraftRecovery.js';
  import { createIndexedDbDraftStorage } from '../lib/draftStorage.js';
  import { createDurableReplyController } from '../lib/durableReply.js';
  import DraftStatus from '../components/email/DraftStatus.svelte';
  import SendSplitButton from '../components/common/SendSplitButton.svelte';

  // --- Day Summary State ---
  let summaryLoading = $state(true);
  let upcomingEvents = $state([]);
  let pendingTodos = $state([]);
  let needsReplyEmails = $state([]);
  let needsReplyTotal = $state(0);
  let hideFyi = $state(localStorage.getItem('flowHideFyi') !== 'false');
  let urgentCount = $state(0);
  let trendsSummary = $state('');

  // --- New sections state ---
  let awaitingResponse = $state([]);
  let awaitingResponseTotal = $state(0);
  let activeThreads = $state([]);

  // --- Chat State ---
  let chatCollapsed = $state(
    localStorage.getItem('flowChatCollapsed') === 'true' ||
    (typeof window !== 'undefined' && window.matchMedia('(max-width: 767px)').matches)
  );
  let messageInput = $state('');
  let isProcessing = $state(false);
  let conversations = $state([]);
  let currentPhase = $state(null);
  let tasks = $state([]);
  let taskStatuses = $state({});
  let finalContent = $state('');
  let renderedContent = $state('');
  let errorMessage = $state('');
  let clarificationQuestion = $state('');
  let activeConversationId = $state(null);
  let loadingConversation = $state(false);
  let conversationMessages = $state([]);
  let messagesContainer = $state(null);
  let expandedTasks = $state({});
  let sessionGuard = null;
  let streamAbortController = null;
  let conversationLoadGeneration = 0;

  function sessionIsCurrent() {
    return Boolean(sessionGuard?.isCurrent());
  }

  // --- Reply View State ---
  let replyViewOpen = $state(false);
  let viewSource = $state('needs_reply'); // 'needs_reply' | 'awaiting' | 'thread'
  let activeReplyIndex = $state(0);
  let selectedReplyEmail = $state(null);
  let threadData = $state(null);
  let threadLoading = $state(false);
  let replyBodyHtml = $state('');
  let inlineReplySending = $state(false);
  let inlineReplySendMode = $state('send');
  let ignoringReplyEmailIds = $state([]);
  let replyIntent = $state(null);
  let collapsedMessages = $state({});
  let archiveAfterSend = $state(true);
  let initialReplyContent = $state('');
  let selectedOptionIndex = $state(-1);
  let editorKey = $state(0);
  let writingSurfaceReady = $state(false);
  let threadLoadGeneration = 0;
  let durableReplyStorage = null;
  let durableReply = $state.raw(null);
  let durableReplyController = $state.raw(null);
  let durableReplyState = $state({ status: 'pristine', canSend: false, snapshot: {} });
  let durableReplyOpening = $state(false);
  let durableReplyError = $state('');
  let durableReplySourceId = null;
  let unsubscribeDurableReply = null;
  let durableReplyRelease = Promise.resolve();
  let replyReturnFocus = null;

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
    if (reason === REPLY_ENVELOPE_UNAVAILABLE.THREAD_DETAILS_UNAVAILABLE) {
      return 'The full conversation could not be verified. Refresh the conversation before replying.';
    }
    return 'Reply recipients could not be verified. Refresh the conversation before sending.';
  }

  // --- Keyboard navigation state for dashboard ---
  // Sections: 'needs_reply', 'awaiting', 'threads'
  let focusedSection = $state('needs_reply');
  let highlightedIndex = $state(-1);

  // Get the items for the currently focused section
  function getSectionItems(section) {
    if (section === 'needs_reply') return needsReplyEmails;
    if (section === 'awaiting') return awaitingResponse;
    if (section === 'threads') return activeThreads;
    return [];
  }

  const sectionOrder = ['needs_reply', 'awaiting', 'threads'];

  function cycleSectionForward() {
    const currentIdx = sectionOrder.indexOf(focusedSection);
    // Find next section that has items
    for (let i = 1; i <= sectionOrder.length; i++) {
      const nextIdx = (currentIdx + i) % sectionOrder.length;
      const section = sectionOrder[nextIdx];
      if (getSectionItems(section).length > 0) {
        focusedSection = section;
        highlightedIndex = 0;
        scrollHighlightedIntoView();
        return;
      }
    }
  }

  function cycleSectionBackward() {
    const currentIdx = sectionOrder.indexOf(focusedSection);
    for (let i = 1; i <= sectionOrder.length; i++) {
      const nextIdx = (currentIdx - i + sectionOrder.length) % sectionOrder.length;
      const section = sectionOrder[nextIdx];
      if (getSectionItems(section).length > 0) {
        focusedSection = section;
        highlightedIndex = 0;
        scrollHighlightedIntoView();
        return;
      }
    }
  }

  function navigateHighlight(direction) {
    const items = getSectionItems(focusedSection);
    if (items.length === 0) return;

    if (highlightedIndex === -1) {
      highlightedIndex = 0;
    } else {
      const next = highlightedIndex + direction;
      if (next < 0) {
        // At the top, try going to previous section
        cycleSectionBackward();
        const newItems = getSectionItems(focusedSection);
        if (newItems.length > 0) {
          highlightedIndex = newItems.length - 1;
        }
        scrollHighlightedIntoView();
        return;
      } else if (next >= items.length) {
        // At the bottom, try going to next section
        cycleSectionForward();
        scrollHighlightedIntoView();
        return;
      } else {
        highlightedIndex = next;
      }
    }
    scrollHighlightedIntoView();
  }

  function openHighlighted() {
    const items = getSectionItems(focusedSection);
    if (highlightedIndex < 0 || highlightedIndex >= items.length) return;

    const item = items[highlightedIndex];
    if (focusedSection === 'needs_reply') {
      openReplyView(item, highlightedIndex, null);
    } else if (focusedSection === 'awaiting') {
      openThreadInFlow(item.gmail_thread_id, { subject: item.subject, from_name: item.to_name, date: item.date, id: item.id, snippet: item.snippet, account_id: item.account_id, account_email: item.account_email }, 'awaiting');
    } else if (focusedSection === 'threads') {
      openThreadInFlow(item.thread_id, { subject: item.subject, summary: item.summary, date: item.latest_date, account_id: item.account_id }, 'thread');
    }
  }

  function scrollHighlightedIntoView() {
    // Use requestAnimationFrame so the DOM has updated
    requestAnimationFrame(() => {
      const el = document.querySelector(`[data-flow-item="${focusedSection}-${highlightedIndex}"]`);
      if (el) {
        el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    });
  }

  // --- Custom prompt state ---
  let customPromptOpen = $state(false);
  let customPromptText = $state('');
  let customPromptLoading = $state(false);
  let lastCustomPrompt = $state('');
  let editingCustomPrompt = $state(false);

  // --- Resizable pane state ---
  let topPanePercent = $state(parseFloat(localStorage.getItem('flowTopPanePercent')) || 40);
  let isDraggingDivider = $state(false);
  let replyContainerEl = $state(null);

  $effect(() => {
    localStorage.setItem('flowTopPanePercent', String(topPanePercent));
  });

  function startDividerDrag(e) {
    e.preventDefault();
    isDraggingDivider = true;

    function onMouseMove(ev) {
      if (!replyContainerEl) return;
      const rect = replyContainerEl.getBoundingClientRect();
      const y = ev.clientY - rect.top;
      const pct = (y / rect.height) * 100;
      topPanePercent = Math.min(75, Math.max(15, pct));
    }

    function onMouseUp() {
      isDraggingDivider = false;
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    }

    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
  }

  // --- Resizable sidebar state ---
  let chatWidthPx = $state(parseInt(localStorage.getItem('flowChatWidthPx')) || 340);
  let isDraggingSidebar = $state(false);

  $effect(() => {
    localStorage.setItem('flowChatWidthPx', String(chatWidthPx));
  });

  function startSidebarDrag(e) {
    e.preventDefault();
    isDraggingSidebar = true;

    function onMouseMove(ev) {
      const x = ev.clientX;
      chatWidthPx = Math.min(600, Math.max(200, x));
    }

    function onMouseUp() {
      isDraggingSidebar = false;
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    }

    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
  }

  // --- Resizable bottom columns state ---
  let bottomLeftPercent = $state(parseFloat(localStorage.getItem('flowBottomLeftPercent')) || 50);
  let isDraggingBottomCol = $state(false);
  let bottomColContainerEl = $state(null);

  $effect(() => {
    localStorage.setItem('flowBottomLeftPercent', String(bottomLeftPercent));
  });

  function startBottomColDrag(e) {
    e.preventDefault();
    isDraggingBottomCol = true;

    function onMouseMove(ev) {
      if (!bottomColContainerEl) return;
      const rect = bottomColContainerEl.getBoundingClientRect();
      const x = ev.clientX - rect.left;
      const pct = (x / rect.width) * 100;
      bottomLeftPercent = Math.min(75, Math.max(25, pct));
    }

    function onMouseUp() {
      isDraggingBottomCol = false;
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    }

    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
  }

  // Configure marked
  marked.setOptions({ breaks: true, gfm: true });

  // Persist chat collapsed state
  $effect(() => {
    localStorage.setItem('flowChatCollapsed', String(chatCollapsed));
  });

  onMount(() => {
    sessionGuard = createAuthenticatedSessionGuard();
    // Register keyboard shortcut actions for the Flow page
    const cleanupShortcuts = registerActions({
      'flow.next': () => {
        if (replyViewOpen) {
          goToNextReply();
        } else {
          navigateHighlight(1);
        }
      },
      'flow.prev': () => {
        if (replyViewOpen) {
          goToPrevReply();
        } else {
          navigateHighlight(-1);
        }
      },
      'flow.nextSection': {
        run: cycleSectionForward,
        isEnabled: () => !replyViewOpen,
        disabledReason: 'Close the reply editor before moving between sections',
      },
      'flow.prevSection': {
        run: cycleSectionBackward,
        isEnabled: () => !replyViewOpen,
        disabledReason: 'Close the reply editor before moving between sections',
      },
      'flow.open': () => {
        if (replyViewOpen) return;
        if (highlightedIndex >= 0) {
          openHighlighted();
        } else if (needsReplyEmails.length > 0) {
          openReplyView(needsReplyEmails[0], 0, null);
        }
      },
      'flow.skip': () => {
        if (replyViewOpen) skipEmail();
      },
      'flow.ignore': {
        run: () => ignoreCurrentEmail(),
        isEnabled: () => Boolean(replyViewOpen && selectedReplyEmail)
          && !ignoringReplyEmailIds.includes(selectedReplyEmail.id),
        disabledReason: () => selectedReplyEmail && ignoringReplyEmailIds.includes(selectedReplyEmail.id)
          ? 'Ignore is already in progress'
          : 'Open a needs-reply email first',
      },
      'flow.snooze': () => {
        if (replyViewOpen && selectedReplyEmail) openSnoozePopover(selectedReplyEmail.id);
      },
      'flow.newChat': () => startNewChat(),
      'flow.send': {
        run: () => sendReply(),
        isEnabled: () => canSendReply(),
        disabledReason: () => inlineReplySending
          ? 'Reply is already sending'
          : threadLoading
            ? 'Conversation details are still loading'
            : !writingSurfaceReady
              ? 'Reply editor is still opening'
              : replyContext && !replyContext.available
                ? replyUnavailableMessage(replyContext.reason)
                : 'Open a reply and enter a message first',
      },
      'flow.back': () => {
        if (replyViewOpen) {
          closeReplyView();
        } else if (highlightedIndex >= 0) {
          highlightedIndex = -1;
        }
      },
      'flow.replyOption1': () => {
        if (replyViewOpen && selectedReplyEmail?.reply_options?.[0]) {
          selectReplyOption(selectedReplyEmail.reply_options[0], 0);
        }
      },
      'flow.replyOption2': () => {
        if (replyViewOpen && selectedReplyEmail?.reply_options?.[1]) {
          selectReplyOption(selectedReplyEmail.reply_options[1], 1);
        }
      },
      'flow.replyOption3': () => {
        if (replyViewOpen && selectedReplyEmail?.reply_options?.[2]) {
          selectReplyOption(selectedReplyEmail.reply_options[2], 2);
        }
      },
      'flow.replyOption4': () => {
        if (replyViewOpen && selectedReplyEmail?.reply_options?.[3]) {
          selectReplyOption(selectedReplyEmail.reply_options[3], 3);
        }
      },
      'flow.customReply': () => {
        if (replyViewOpen && selectedReplyEmail?.reply_options?.length > 0) {
          customPromptOpen = !customPromptOpen;
        }
      },
    });

    void Promise.all([
      loadDaySummary(),
      loadConversations(),
      loadAwaitingResponse(),
      loadActiveThreads(),
    ]);

    try {
      durableReplyStorage = createIndexedDbDraftStorage();
    } catch (error) {
      durableReplyError = error?.message || 'Draft storage is unavailable.';
    }

    return () => {
      const release = releaseFlowDurableReply({ flush: true });
      sessionGuard.dispose();
      void Promise.resolve(release).finally(() => durableReplyStorage?.close?.());
      conversationLoadGeneration += 1;
      streamAbortController?.abort();
      streamAbortController = null;
      cleanupShortcuts();
    };
  });

  $effect(() => {
    const evt = $lastEvent;
    if (!evt || !sessionIsCurrent()) return;
    if (evt.type === 'new_emails' || evt.type === 'emails_updated') {
      loadDaySummary();
      loadAwaitingResponse();
      loadActiveThreads();
    }
  });

  // ============ Day Summary ============

  async function loadDaySummary() {
    summaryLoading = true;
    const results = await Promise.allSettled([
      api.getUpcomingEvents(1),
      api.getTodos({ status: 'pending' }),
      api.getNeedsReply({ limit: 20, ...(hideFyi ? { exclude_category: 'fyi' } : {}) }),
      api.getAITrends(),
    ]);
    if (!sessionIsCurrent()) return;

    if (results[0].status === 'fulfilled') {
      upcomingEvents = (results[0].value.events || []).slice(0, 5);
    }
    if (results[1].status === 'fulfilled') {
      pendingTodos = (results[1].value.todos || results[1].value || []).slice(0, 10);
    }
    if (results[2].status === 'fulfilled') {
      const priority = { urgent: 0, awaiting_reply: 1, fyi: 3, can_ignore: 4 };
      needsReplyEmails = [...(results[2].value.emails || [])].sort((a, b) => {
        const categoryDelta = (priority[a.category] ?? 2) - (priority[b.category] ?? 2);
        return categoryDelta || new Date(b.date || 0) - new Date(a.date || 0);
      });
      needsReplyTotal = results[2].value.total || 0;
    }
    if (results[3].status === 'fulfilled') {
      trendsSummary = results[3].value.summary || '';
      if (results[3].value.needs_attention) {
        urgentCount = results[3].value.needs_attention.filter(e => e.category === 'urgent').length;
      }
    }
    summaryLoading = false;
  }

  async function loadAwaitingResponse() {
    try {
      const data = await api.getAwaitingResponse({ limit: 10 });
      if (!sessionIsCurrent()) return;
      awaitingResponse = data.emails || [];
      awaitingResponseTotal = data.total || 0;
    } catch {
      // ignore
    }
  }

  async function loadActiveThreads() {
    try {
      const data = await api.getThreadDigests({ page_size: 8, sort: 'recent' });
      if (!sessionIsCurrent()) return;
      activeThreads = (data.digests || []).slice(0, 6);
    } catch {
      // ignore
    }
  }

  // ============ Chat Logic ============

  async function loadConversations() {
    try {
      const data = await api.getConversations();
      if (!sessionIsCurrent()) return;
      conversations = data;
      chatConversations.set(data);
    } catch {
      // ignore
    }
  }

  async function loadConversation(id) {
    if (!sessionIsCurrent()) return;
    const loadGeneration = ++conversationLoadGeneration;
    loadingConversation = true;
    activeConversationId = id;
    currentConversationId.set(id);
    resetChatState();

    try {
      const data = await api.getConversation(id);
      if (!sessionIsCurrent() || loadGeneration !== conversationLoadGeneration) return;
      conversationMessages = data.messages || [];

      const lastAssistant = [...conversationMessages].reverse().find(m => m.role === 'assistant');
      if (lastAssistant) {
        if (lastAssistant.plan && lastAssistant.plan.tasks) {
          tasks = lastAssistant.plan.tasks;
          let statuses = {};
          for (const t of tasks) {
            const result = lastAssistant.task_results
              ? lastAssistant.task_results[String(t.id)]
              : null;
            statuses[t.id] = {
              status: 'completed',
              summary: result || 'Completed',
              detail: '',
              error: null,
            };
          }
          taskStatuses = statuses;
        }
        if (lastAssistant.content) {
          finalContent = lastAssistant.content;
          renderedContent = sanitizeMarkdown(marked.parse(lastAssistant.content));
        }
        currentPhase = 'done';
      }
    } catch (err) {
      if (sessionIsCurrent() && loadGeneration === conversationLoadGeneration) {
        showToast(err.message, 'error');
      }
    }
    if (sessionIsCurrent() && loadGeneration === conversationLoadGeneration) {
      loadingConversation = false;
    }
  }

  async function deleteConversation(id) {
    try {
      await api.deleteConversation(id);
      if (!sessionIsCurrent()) return;
      conversations = conversations.filter(c => c.id !== id);
      chatConversations.set(conversations);
      if (activeConversationId === id) {
        resetChatState();
        activeConversationId = null;
        currentConversationId.set(null);
        conversationMessages = [];
      }
      showToast('Conversation deleted', 'success');
    } catch (err) {
      if (sessionIsCurrent()) showToast(err.message, 'error');
    }
  }

  function resetChatState() {
    currentPhase = null;
    tasks = [];
    taskStatuses = {};
    finalContent = '';
    renderedContent = '';
    errorMessage = '';
    clarificationQuestion = '';
  }

  function startNewChat() {
    resetChatState();
    activeConversationId = null;
    currentConversationId.set(null);
    conversationMessages = [];
    messageInput = '';
  }

  async function sendMessage() {
    const msg = messageInput.trim();
    if (!msg || isProcessing || !sessionIsCurrent()) return;

    messageInput = '';
    isProcessing = true;
    resetChatState();

    conversationMessages = [...conversationMessages, { role: 'user', content: msg }];
    const controller = new AbortController();
    streamAbortController = controller;

    try {
      const response = await api.chatStream(msg, activeConversationId, {
        signal: controller.signal,
      });
      if (!sessionIsCurrent() || streamAbortController !== controller) return;

      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: 'Request failed' }));
        throw new Error(err.detail || `HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (!sessionIsCurrent() || streamAbortController !== controller) {
          await reader.cancel().catch(() => {});
          return;
        }
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = '';
        let eventType = '';

        for (let i = 0; i < lines.length; i++) {
          const line = lines[i];

          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith('data: ')) {
            const dataStr = line.slice(6);
            try {
              const data = JSON.parse(dataStr);
              handleSSEEvent(eventType, data);
            } catch {
              // partial JSON
            }
            eventType = '';
          } else if (line === '') {
            eventType = '';
          } else {
            buffer = lines.slice(i).join('\n');
            break;
          }
        }
      }

    } catch (err) {
      if (sessionIsCurrent() && streamAbortController === controller && err.name !== 'AbortError') {
        errorMessage = err.message;
        showToast(err.message, 'error');
      }
    } finally {
      if (sessionIsCurrent() && streamAbortController === controller) {
        streamAbortController = null;
      }
    }

    if (!sessionIsCurrent()) return;
    isProcessing = false;
    await loadConversations();
  }

  function handleSSEEvent(eventType, data) {
    if (!sessionIsCurrent()) return;
    if (eventType === 'phase') {
      currentPhase = data.phase;
    } else if (eventType === 'plan_ready') {
      tasks = data.tasks || [];
      let statuses = {};
      for (const t of tasks) {
        statuses[t.id] = { status: 'pending', summary: '', detail: '', error: null };
      }
      taskStatuses = statuses;
    } else if (eventType === 'task_start') {
      taskStatuses = {
        ...taskStatuses,
        [data.task_id]: { ...taskStatuses[data.task_id], status: 'in_progress', detail: '' },
      };
    } else if (eventType === 'task_progress') {
      taskStatuses = {
        ...taskStatuses,
        [data.task_id]: { ...taskStatuses[data.task_id], detail: data.detail || '' },
      };
    } else if (eventType === 'task_complete') {
      taskStatuses = {
        ...taskStatuses,
        [data.task_id]: { ...taskStatuses[data.task_id], status: 'completed', summary: data.summary || 'Done', detail: '' },
      };
    } else if (eventType === 'task_failed') {
      taskStatuses = {
        ...taskStatuses,
        [data.task_id]: { ...taskStatuses[data.task_id], status: 'failed', error: data.error || 'Unknown error', detail: '' },
      };
    } else if (eventType === 'clarification') {
      clarificationQuestion = data.question || '';
      currentPhase = 'clarification';
    } else if (eventType === 'content') {
      finalContent = data.text || '';
      renderedContent = sanitizeMarkdown(marked.parse(finalContent));
    } else if (eventType === 'done') {
      if (currentPhase !== 'clarification') {
        currentPhase = 'done';
      }
    } else if (eventType === 'conversation_id') {
      activeConversationId = data.conversation_id;
      currentConversationId.set(data.conversation_id);
    } else if (eventType === 'error') {
      errorMessage = data.message || 'An error occurred';
    }

    if (messagesContainer) {
      requestAnimationFrame(() => {
        if (sessionIsCurrent() && messagesContainer) {
          messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }
      });
    }
  }

  function getCompletedCount() {
    let count = 0;
    for (const key of Object.keys(taskStatuses)) {
      if (taskStatuses[key].status === 'completed' || taskStatuses[key].status === 'failed') {
        count++;
      }
    }
    return count;
  }

  function toggleTaskExpanded(taskId) {
    expandedTasks = { ...expandedTasks, [taskId]: !expandedTasks[taskId] };
  }

  function handleKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  function formatDate(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    const now = new Date();
    const diffMs = now - d;
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffDays === 0) {
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } else if (diffDays === 1) {
      return 'Yesterday';
    } else if (diffDays < 7) {
      return d.toLocaleDateString([], { weekday: 'short' });
    }
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  }

  function formatEventTime(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  }

  function formatRelativeDate(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    const now = new Date();
    const diffMs = now - d;
    const diffMins = Math.floor(diffMs / (1000 * 60));
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays === 1) return 'yesterday';
    if (diffDays < 7) return `${diffDays}d ago`;
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  }

  // Navigate to an email in the inbox
  function goToEmail(emailId) {
    if (!sessionIsCurrent()) return;
    currentMailbox.set('ALL');
    selectedEmailId.set(emailId);
    currentPage.set('inbox');
  }

  function downloadMarkdown() {
    if (!finalContent) return;
    const blob = new Blob([finalContent], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    const title = conversations.find(c => c.id === activeConversationId)?.title || 'chat-response';
    const safeName = title.replace(/[^a-zA-Z0-9-_ ]/g, '').replace(/\s+/g, '-').substring(0, 60);
    a.download = `${safeName}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  let hasActiveChat = $derived(conversationMessages.length > 0 || isProcessing);

  const categoryColors = {
    urgent: { bg: 'bg-red-100 dark:bg-red-500/20', text: 'text-red-700 dark:text-red-300' },
    can_ignore: { bg: 'bg-gray-100 dark:bg-gray-700/50', text: 'text-gray-600 dark:text-gray-300' },
    fyi: { bg: 'bg-emerald-100 dark:bg-emerald-500/20', text: 'text-emerald-700 dark:text-emerald-300' },
    awaiting_reply: { bg: 'bg-amber-100 dark:bg-amber-500/20', text: 'text-amber-700 dark:text-amber-300' },
  };

  function categoryLabel(cat) {
    if (!cat) return 'Unknown';
    return cat.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  const intentColors = {
    accept: 'bg-emerald-50 dark:bg-emerald-500/15 border-emerald-200 dark:border-emerald-500/30 text-emerald-700 dark:text-emerald-300',
    decline: 'bg-red-50 dark:bg-red-500/15 border-red-200 dark:border-red-500/30 text-red-700 dark:text-red-300',
    defer: 'bg-amber-50 dark:bg-amber-500/15 border-amber-200 dark:border-amber-500/30 text-amber-700 dark:text-amber-300',
    not_relevant: 'bg-gray-50 dark:bg-gray-600/20 border-gray-200 dark:border-gray-600/30 text-gray-600 dark:text-gray-300',
    custom: 'bg-blue-50 dark:bg-blue-500/15 border-blue-200 dark:border-blue-500/30 text-blue-700 dark:text-blue-300',
  };

  const intentCardStyles = {
    accept: {
      bg: 'bg-emerald-50 dark:bg-emerald-500/15',
      border: 'border-emerald-200 dark:border-emerald-500/30',
      text: 'text-emerald-700 dark:text-emerald-300',
    },
    decline: {
      bg: 'bg-red-50 dark:bg-red-500/15',
      border: 'border-red-200 dark:border-red-500/30',
      text: 'text-red-700 dark:text-red-300',
    },
    defer: {
      bg: 'bg-amber-50 dark:bg-amber-500/15',
      border: 'border-amber-200 dark:border-amber-500/30',
      text: 'text-amber-700 dark:text-amber-300',
    },
    not_relevant: {
      bg: 'bg-gray-50 dark:bg-gray-600/20',
      border: 'border-gray-200 dark:border-gray-600/30',
      text: 'text-gray-600 dark:text-gray-300',
    },
    custom: {
      bg: 'bg-blue-50 dark:bg-blue-500/15',
      border: 'border-blue-200 dark:border-blue-500/30',
      text: 'text-blue-700 dark:text-blue-300',
    },
  };

  const intentLabels = {
    accept: 'acceptance',
    decline: 'decline',
    defer: 'deferral',
    not_relevant: 'pass',
    custom: 'reply',
  };

  function intentIcon(intent) {
    const icons = {
      accept: 'check',
      decline: 'x',
      defer: 'clock',
      not_relevant: 'slash',
      custom: 'corner-up-left',
    };
    return icons[intent] || 'corner-up-left';
  }

  const conversationTypeColors = {
    scheduling: { bg: 'bg-purple-100 dark:bg-purple-500/20', text: 'text-purple-700 dark:text-purple-300' },
    discussion: { bg: 'bg-blue-100 dark:bg-blue-500/20', text: 'text-blue-700 dark:text-blue-300' },
    notification: { bg: 'bg-gray-100 dark:bg-gray-700/50', text: 'text-gray-600 dark:text-gray-300' },
    transactional: { bg: 'bg-amber-100 dark:bg-amber-500/20', text: 'text-amber-700 dark:text-amber-300' },
  };

  // ============ Reply View Logic ============

  function rememberCurrentReplyDraft() {
    if (!durableReplyController || durableReplyOpening || durableReplyError) return false;
    if (
      durableReplyState.status === 'conflict'
      || durableReplyState.discardInProgress
      || durableReplyState.sendInProgress
    ) return false;
    try {
      durableReplyController.update(durableReply.snapshot(replyBodyHtml));
      return true;
    } catch (error) {
      durableReplyError = error?.message || 'Reply could not be saved safely.';
      return false;
    }
  }

  function releaseFlowDurableReply({ flush = false } = {}) {
    const controller = durableReplyController;
    unsubscribeDurableReply?.();
    unsubscribeDurableReply = null;
    durableReply = null;
    durableReplyController = null;
    durableReplySourceId = null;
    if (!controller) return durableReplyRelease;
    if (flush) {
      durableReplyRelease = controller.flush().catch(() => {}).finally(() => controller.dispose());
      return durableReplyRelease;
    }
    controller.dispose();
    durableReplyRelease = Promise.resolve();
    return durableReplyRelease;
  }

  async function prepareFlowReplyTransition() {
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
    rememberCurrentReplyDraft();
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

  async function openFlowDurableReply(requestGeneration, initialHtml = '') {
    if (
      !sessionIsCurrent()
      || requestGeneration !== threadLoadGeneration
      || !replyContext?.available
      || !durableReplyStorage
    ) return false;
    const context = replyContext;
    const sourceId = Number(context.envelope.source_email_id);
    if (
      durableReplyController
      && durableReplySourceId === sourceId
    ) return true;

    await releaseFlowDurableReply({ flush: true });
    if (!threadRequestIsCurrent(requestGeneration, {
      emailId: selectedReplyEmail?.id ?? null,
      threadId: selectedReplyEmail?.gmail_thread_id ?? null,
      source: viewSource,
    })) return false;
    durableReplyOpening = true;
    durableReplyError = '';
    const owner = createDurableReplyController({
      userId: sessionGuard.userId,
      storage: durableReplyStorage,
      api,
      envelope: context.envelope,
      captureSession: captureAuthenticatedSession,
      isSessionCurrent: isAuthenticatedSessionCurrent,
      onDiscard: () => {
        if (requestGeneration !== threadLoadGeneration || !sessionIsCurrent()) return;
        replyBodyHtml = '';
        initialReplyContent = '';
        void finishCloseReplyView();
      },
    });
    durableReply = owner;
    durableReplyController = owner.controller;
    durableReplySourceId = sourceId;
    unsubscribeDurableReply = owner.controller.subscribe(state => {
      if (durableReplyController !== owner.controller || !sessionIsCurrent()) return;
      durableReplyState = state;
    });
    try {
      const state = await owner.open(owner.snapshot(initialHtml));
      if (
        durableReplyController !== owner.controller
        || requestGeneration !== threadLoadGeneration
        || !sessionIsCurrent()
      ) return false;
      replyBodyHtml = state.snapshot?.body_html || initialHtml || '';
      initialReplyContent = replyBodyHtml;
      durableReplyState = owner.controller.getState();
      durableReplyOpening = false;
      remountReplyEditor();
      await tick();
      return true;
    } catch (error) {
      if (requestGeneration === threadLoadGeneration && sessionIsCurrent()) {
        durableReplyOpening = false;
        durableReplyError = error?.message || 'Reply drafts are unavailable.';
        showToast('Couldn’t open a safely saved reply. Try again.', 'error');
      }
      return false;
    }
  }

  function remountReplyEditor() {
    writingSurfaceReady = false;
    editorKey += 1;
  }

  function threadRequestIsCurrent(requestGeneration, { emailId = null, threadId = null, source = null } = {}) {
    return sessionIsCurrent() && isCurrentFlowThreadRequest({
      requestedGeneration: requestGeneration,
      currentGeneration: threadLoadGeneration,
      replyViewOpen: replyViewOpen && Boolean(selectedReplyEmail),
      requestedEmailId: emailId,
      activeEmailId: selectedReplyEmail?.id ?? null,
      requestedThreadId: threadId,
      activeThreadId: selectedReplyEmail?.gmail_thread_id ?? null,
      requestedSource: source,
      activeSource: viewSource,
    });
  }

  async function openReplyView(email, index, option) {
    if (!sessionIsCurrent()) return;
    if (!(await prepareFlowReplyTransition())) return false;
    if (!replyViewOpen) {
      replyReturnFocus = document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    }
    releaseFlowDurableReply();
    if (!sessionIsCurrent()) return;
    const requestGeneration = ++threadLoadGeneration;
    const emailId = email.id;
    selectedReplyEmail = {
      ...email,
      is_sent: email.is_sent ?? false,
      reply_draft_account_key: replyDraftAccountKey(email),
    };
    activeReplyIndex = index;
    viewSource = 'needs_reply';
    replyViewOpen = true;
    threadLoading = true;
    threadData = null;
    replyBodyHtml = '';
    replyIntent = null;
    collapsedMessages = {};
    selectedOptionIndex = -1;
    customPromptOpen = false;
    customPromptText = '';
    customPromptLoading = false;
    lastCustomPrompt = '';
    editingCustomPrompt = false;

    if (option) {
      initialReplyContent = '<p>' + (option.body || '').replace(/\n/g, '</p><p>') + '</p>';
      replyIntent = option.intent || null;
      replyBodyHtml = initialReplyContent;
      if (email.reply_options) {
        const optIdx = email.reply_options.indexOf(option);
        if (optIdx >= 0) selectedOptionIndex = optIdx;
      }
    } else {
      initialReplyContent = '';
      replyBodyHtml = initialReplyContent;
    }
    remountReplyEditor();

    if (email.gmail_thread_id) {
      try {
        const orderParam = get(threadOrder) === 'newest_first' ? 'desc' : 'asc';
        const source = resolveReplySourceAccount({ message: email, accounts: get(accounts) });
        if (!source.available) throw new Error(replyUnavailableMessage(source.reason));
        const data = await api.getThread(email.gmail_thread_id, orderParam, source.sourceAccount.id);
        if (!threadRequestIsCurrent(requestGeneration, { emailId })) return;
        threadData = data;
        if (data.emails && data.emails.length > 1) {
          let collapsed = {};
          const expandIdx = orderParam === 'desc' ? 0 : data.emails.length - 1;
          for (let i = 0; i < data.emails.length; i++) {
            if (i !== expandIdx) {
              collapsed[data.emails[i].id] = true;
            }
          }
          collapsedMessages = collapsed;
        }
      } catch (err) {
        if (threadRequestIsCurrent(requestGeneration, { emailId })) {
          showToast('Failed to load thread: ' + err.message, 'error');
        }
      }
    }
    if (threadRequestIsCurrent(requestGeneration, { emailId })) {
      threadLoading = false;
      await tick();
      await openFlowDurableReply(requestGeneration, initialReplyContent);
    }
  }

  async function openThreadInFlow(threadId, metadata, source) {
    if (!sessionIsCurrent()) return;
    if (!(await prepareFlowReplyTransition())) return false;
    if (!replyViewOpen) {
      replyReturnFocus = document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    }
    releaseFlowDurableReply();
    if (!sessionIsCurrent()) return;
    const requestGeneration = ++threadLoadGeneration;
    viewSource = source;
    replyViewOpen = true;
    threadLoading = true;
    threadData = null;
    replyBodyHtml = '';
    replyIntent = null;
    collapsedMessages = {};
    selectedOptionIndex = -1;
    initialReplyContent = '';
    activeReplyIndex = 0;
    customPromptOpen = false;
    customPromptText = '';
    customPromptLoading = false;
    lastCustomPrompt = '';
    editingCustomPrompt = false;

    // Build a minimal email-like object for the reply view header
    selectedReplyEmail = {
      subject: metadata.subject || '(no subject)',
      from_name: metadata.from_name || '',
      from_address: metadata.from_address || '',
      date: metadata.date || null,
      gmail_thread_id: threadId,
      id: metadata.id || null,
      snippet: metadata.snippet || '',
      summary: metadata.summary || '',
      account_id: metadata.account_id || null,
      account_email: metadata.account_email || null,
      is_sent: metadata.is_sent ?? source === 'awaiting',
      to_addresses: metadata.to_addresses || [],
      cc_addresses: metadata.cc_addresses || [],
      bcc_addresses: [],
      reply_to: metadata.reply_to || null,
      message_id_header: metadata.message_id_header || null,
      reply_options: null,
      suggested_reply: null,
      category: null,
      reply_draft_account_key: replyDraftAccountKey(metadata),
    };
    initialReplyContent = '';
    replyBodyHtml = initialReplyContent;
    remountReplyEditor();

    if (threadId) {
      try {
        const orderParam = get(threadOrder) === 'newest_first' ? 'desc' : 'asc';
        const sourceResolution = resolveReplySourceAccount({ message: selectedReplyEmail, accounts: get(accounts) });
        if (!sourceResolution.available) throw new Error(replyUnavailableMessage(sourceResolution.reason));
        const data = await api.getThread(threadId, orderParam, sourceResolution.sourceAccount.id);
        if (!threadRequestIsCurrent(requestGeneration, { threadId, source })) return;
        threadData = data;
        if (data.emails && data.emails.length > 1) {
          let collapsed = {};
          const expandIdx = orderParam === 'desc' ? 0 : data.emails.length - 1;
          for (let i = 0; i < data.emails.length; i++) {
            if (i !== expandIdx) {
              collapsed[data.emails[i].id] = true;
            }
          }
          collapsedMessages = collapsed;
        }

        // Keep the reply header aligned to the true newest inbound message
        // from this exact source account, regardless of display order.
        if (data.emails && data.emails.length > 0) {
          const sourceEmail = normalizeReplyAddress(selectedReplyEmail.account_email);
          const sourceAccountId = Number(selectedReplyEmail.account_id) || null;
          const sameSource = data.emails.filter(candidate => {
            if (sourceAccountId && candidate.account_id) {
              return Number(candidate.account_id) === sourceAccountId;
            }
            const candidateEmail = normalizeReplyAddress(candidate.account_email);
            return Boolean(sourceEmail && candidateEmail && sourceEmail === candidateEmail);
          });
          const latestInbound = newestThreadMessage(
            sameSource.filter(message => message.is_sent === false),
            get(threadOrder),
          );
          if (latestInbound) {
            selectedReplyEmail = {
              ...selectedReplyEmail,
              id: latestInbound.id,
              account_id: latestInbound.account_id,
              account_email: latestInbound.account_email,
              gmail_thread_id: latestInbound.gmail_thread_id || selectedReplyEmail.gmail_thread_id,
              is_sent: false,
              from_name: latestInbound.from_name || selectedReplyEmail.from_name,
              from_address: latestInbound.from_address || selectedReplyEmail.from_address,
              reply_to: latestInbound.reply_to || null,
              to_addresses: latestInbound.to_addresses || [],
              cc_addresses: latestInbound.cc_addresses || [],
              message_id_header: latestInbound.message_id_header || null,
              references_header: latestInbound.references_header || null,
              date: latestInbound.date || selectedReplyEmail.date,
            };
          }
        }
      } catch (err) {
        if (threadRequestIsCurrent(requestGeneration, { threadId, source })) {
          showToast('Failed to load thread: ' + err.message, 'error');
        }
      }
    }
    if (threadRequestIsCurrent(requestGeneration, { threadId, source })) {
      threadLoading = false;
      await tick();
      await openFlowDurableReply(requestGeneration, initialReplyContent);
    }
  }

  async function finishCloseReplyView({ toastMessage = '' } = {}) {
    const focusTarget = replyReturnFocus;
    const focusIndex = activeReplyIndex;
    threadLoadGeneration += 1;
    replyViewOpen = false;
    viewSource = 'needs_reply';
    selectedReplyEmail = null;
    threadData = null;
    replyBodyHtml = '';
    replyIntent = null;
    collapsedMessages = {};
    selectedOptionIndex = -1;
    initialReplyContent = '';
    customPromptOpen = false;
    customPromptText = '';
    customPromptLoading = false;
    lastCustomPrompt = '';
    editingCustomPrompt = false;
    writingSurfaceReady = false;
    releaseFlowDurableReply();
    if (toastMessage) showToast(toastMessage, 'success');
    await tick();
    if (focusTarget?.isConnected) focusTarget.focus();
    else document.querySelector(`[data-flow-item="needs_reply-${focusIndex}"]`)?.focus?.();
    replyReturnFocus = null;
    return true;
  }

  async function closeReplyView() {
    const hadDurableDraft = Boolean(durableReplyController);
    if (!(await prepareFlowReplyTransition())) return false;
    const state = durableReplyController?.getState();
    const toastMessage = hadDurableDraft
      ? state?.status === 'conflict'
        ? 'Reply kept. Review its versions from Drafts.'
        : state?.status === 'offline' || state?.status === 'failed'
          ? 'Reply saved on this device. Sync still needs attention.'
          : 'Reply saved. Continue it from Drafts.'
      : '';
    await finishCloseReplyView({ toastMessage });
    return true;
  }

  function selectReplyOption(option, optIdx) {
    initialReplyContent = '<p>' + (option.body || '').replace(/\n/g, '</p><p>') + '</p>';
    replyBodyHtml = initialReplyContent;
    replyIntent = option.intent || null;
    selectedOptionIndex = optIdx;
    rememberCurrentReplyDraft();
    remountReplyEditor();
  }

  function clearReplyOption() {
    initialReplyContent = '';
    replyBodyHtml = '';
    replyIntent = null;
    selectedOptionIndex = -1;
    customPromptOpen = false;
    customPromptText = '';
    lastCustomPrompt = '';
    editingCustomPrompt = false;
    rememberCurrentReplyDraft();
    remountReplyEditor();
  }

  async function generateCustomReply(promptOverride) {
    const promptToUse = (promptOverride || customPromptText).trim();
    if (!promptToUse || !selectedReplyEmail || customPromptLoading) return;
    const email = selectedReplyEmail;
    const requestGeneration = threadLoadGeneration;
    const sourceAtStart = viewSource;
    const requestIsCurrent = () => threadRequestIsCurrent(requestGeneration, {
      emailId: email.id ?? null,
      threadId: email.gmail_thread_id ?? null,
      source: sourceAtStart,
    });
    customPromptLoading = true;
    try {
      const result = await api.generateReply(email.id, promptToUse);
      if (!requestIsCurrent()) return;
      if (result && result.body) {
        lastCustomPrompt = promptToUse;
        editingCustomPrompt = false;
        if (result.is_new_email) {
          const bodyHtml = '<p>' + result.body.replace(/\n/g, '</p><p>') + '</p>';
          const source = resolveReplySourceAccount({ message: email, accounts: get(accounts) });
          if (!source.available) {
            showToast(replyUnavailableMessage(source.reason), 'error');
            return;
          }
          composeData.set({
            account_id: source.sourceAccount.id,
            to: result.to || [],
            cc: result.cc || [],
            subject: result.subject || '',
            body_html: bodyHtml,
          });
          customPromptOpen = false;
          customPromptText = '';
          currentPage.set('compose');
        } else {
          initialReplyContent = '<p>' + result.body.replace(/\n/g, '</p><p>') + '</p>';
          replyBodyHtml = initialReplyContent;
          replyIntent = 'custom';
          selectedOptionIndex = -1;
          customPromptOpen = false;
          customPromptText = '';
          rememberCurrentReplyDraft();
          remountReplyEditor();
        }
      }
    } catch (err) {
      if (requestIsCurrent()) console.error('Failed to generate custom reply:', err);
    } finally {
      if (requestIsCurrent()) customPromptLoading = false;
    }
  }

  function toggleMessageCollapse(msgId) {
    collapsedMessages = { ...collapsedMessages, [msgId]: !collapsedMessages[msgId] };
  }

  function handleEditorUpdate(html) {
    replyBodyHtml = html;
    rememberCurrentReplyDraft();
  }

  function useSuggestedReply() {
    if (!selectedReplyEmail?.suggested_reply) return;
    initialReplyContent = '<p>' + selectedReplyEmail.suggested_reply.replace(/\n/g, '</p><p>') + '</p>';
    replyBodyHtml = initialReplyContent;
    replyIntent = 'custom';
    selectedOptionIndex = -1;
    rememberCurrentReplyDraft();
    remountReplyEditor();
  }

  async function goToNextReply() {
    if (activeReplyIndex >= needsReplyEmails.length - 1) return;
    const nextIdx = activeReplyIndex + 1;
    await openReplyView(needsReplyEmails[nextIdx], nextIdx);
  }

  async function goToPrevReply() {
    if (activeReplyIndex <= 0) return;
    const prevIdx = activeReplyIndex - 1;
    await openReplyView(needsReplyEmails[prevIdx], prevIdx);
  }

  function skipEmail() {
    if (activeReplyIndex < needsReplyEmails.length - 1) {
      goToNextReply();
    } else if (activeReplyIndex > 0) {
      goToPrevReply();
    } else {
      closeReplyView();
    }
  }

  async function archiveCurrentEmail() {
    if (!selectedReplyEmail || !sessionIsCurrent()) return;
    if (!(await prepareFlowReplyTransition())) return;
    const emailId = selectedReplyEmail.id;
    try {
      await api.emailActions([emailId], 'archive');
      if (!sessionIsCurrent()) return;
      showToast('Email archived', 'success');
      removeEmailAndAdvance(emailId);
    } catch (err) {
      if (sessionIsCurrent()) showToast(err.message, 'error');
    }
  }

  async function trashCurrentEmail() {
    if (!selectedReplyEmail || !sessionIsCurrent()) return;
    if (!(await prepareFlowReplyTransition())) return;
    const emailId = selectedReplyEmail.id;
    try {
      await api.emailActions([emailId], 'trash');
      if (!sessionIsCurrent()) return;
      showToast('Moved to trash', 'success');
      removeEmailAndAdvance(emailId);
    } catch (err) {
      if (sessionIsCurrent()) showToast(err.message, 'error');
    }
  }

  async function ignoreCurrentEmail() {
    if (!selectedReplyEmail || !sessionIsCurrent()) return false;
    if (!(await prepareFlowReplyTransition())) return false;
    const emailId = selectedReplyEmail.id;
    const sourceAtStart = viewSource;
    const nextPending = addPendingReplyId(ignoringReplyEmailIds, emailId);
    if (nextPending === ignoringReplyEmailIds) return false;
    ignoringReplyEmailIds = nextPending;
    try {
      await api.ignoreNeedsReply(emailId);
      if (!sessionIsCurrent()) return false;
      showToast('Ignored — won\'t appear in needs reply', 'success');
      if (sourceAtStart === 'needs_reply') {
        removeEmailAndAdvance(emailId);
      } else {
        needsReplyEmails = needsReplyEmails.filter(e => e.id !== emailId);
        if (needsReplyTotal > 0) needsReplyTotal -= 1;
        if (capturedReplyStillActive(emailId, selectedReplyEmail?.id)) closeReplyView();
      }
      return true;
    } catch (err) {
      if (sessionIsCurrent()) showToast(err.message, 'error');
      return false;
    } finally {
      if (sessionIsCurrent()) {
        ignoringReplyEmailIds = removePendingReplyId(ignoringReplyEmailIds, emailId);
      }
    }
  }

  async function ignoreEmailFromList(emailId) {
    if (!sessionIsCurrent()) return;
    try {
      await api.ignoreNeedsReply(emailId);
      if (!sessionIsCurrent()) return;
      needsReplyEmails = needsReplyEmails.filter(e => e.id !== emailId);
      if (needsReplyTotal > 0) needsReplyTotal -= 1;
      showToast('Ignored — won\'t appear in needs reply', 'success');
    } catch (err) {
      if (sessionIsCurrent()) showToast(err.message, 'error');
    }
  }

  let snoozePopoverEmailId = $state(null);

  function openSnoozePopover(emailId) {
    if (snoozePopoverEmailId === emailId) {
      snoozePopoverEmailId = null;
    } else {
      snoozePopoverEmailId = emailId;
    }
  }

  function closeSnoozePopover() {
    snoozePopoverEmailId = null;
  }

  async function snoozeEmail(emailId, duration, fromReplyView) {
    if (!sessionIsCurrent()) return;
    if (fromReplyView && !(await prepareFlowReplyTransition())) return;
    const labels = { '1h': '1 hour', '3h': '3 hours', 'tomorrow': 'tomorrow morning', 'next_week': 'next week' };
    try {
      await api.snoozeNeedsReply(emailId, duration);
      if (!sessionIsCurrent()) return;
      snoozePopoverEmailId = null;
      showToast(`Snoozed until ${labels[duration]}`, 'success');
      if (fromReplyView && viewSource === 'needs_reply') {
        removeEmailAndAdvance(emailId);
      } else if (fromReplyView) {
        needsReplyEmails = needsReplyEmails.filter(e => e.id !== emailId);
        if (needsReplyTotal > 0) needsReplyTotal -= 1;
        closeReplyView();
      } else {
        needsReplyEmails = needsReplyEmails.filter(e => e.id !== emailId);
        if (needsReplyTotal > 0) needsReplyTotal -= 1;
      }
    } catch (err) {
      if (sessionIsCurrent()) showToast(err.message, 'error');
    }
  }

  function removeEmailAndAdvance(removedId) {
    const result = reconcileNeedsReplyRemoval({
      emails: needsReplyEmails,
      total: needsReplyTotal,
      removedId,
      activeEmailId: selectedReplyEmail?.id,
      activeIndex: activeReplyIndex,
    });
    if (!result.removed) return;
    needsReplyEmails = result.emails;
    needsReplyTotal = result.total;

    // A delayed completion after the reply view closes should update the
    // dashboard count without unexpectedly reopening another message.
    if (!replyViewOpen || !selectedReplyEmail) return;

    if (selectedReplyEmail && selectedReplyEmail.id !== removedId) {
      if (result.activeIndex >= 0) activeReplyIndex = result.activeIndex;
      return;
    }
    if (result.activeEmailId == null) {
      closeReplyView();
      return;
    }
    openReplyView(needsReplyEmails[result.activeIndex], result.activeIndex);
  }

  async function openInCompose() {
    if (!selectedReplyEmail || threadLoading) return;
    const context = replyContext;
    if (!context?.available) {
      showToast(replyUnavailableMessage(context?.reason), 'error');
      return;
    }

    if (!durableReplyController || !durableReply) {
      showToast('Wait for the saved reply to finish opening.', 'error');
      return;
    }
    rememberCurrentReplyDraft();
    try {
      await durableReplyController.flush();
    } catch (error) {
      durableReplyError = error?.message || 'Reply could not be saved safely.';
      showToast('Reply must be safely saved before opening full Compose.', 'error');
      return;
    }
    const state = durableReplyController.getState();
    if (state?.error?.phase === 'local') {
      durableReplyError = state.error.message || 'Local draft storage failed.';
      showToast('Reply is only in this open editor. Retry before opening full Compose.', 'error');
      return;
    }
    composeData.set(durableReply.composeData());
    releaseFlowDurableReply();
    currentPage.set('compose');
  }

  function canSendReply() {
    const plainText = replyBodyHtml ? replyBodyHtml.replace(/<[^>]*>/g, '').trim() : '';
    return replyViewOpen
      && Boolean(selectedReplyEmail)
      && Boolean(plainText)
      && writingSurfaceReady
      && !threadLoading
      && !inlineReplySending
      && Boolean(replyContext?.available)
      && Boolean(durableReplyController)
      && Boolean(durableReplyState.canSend)
      && !durableReplyOpening
      && !durableReplyError;
  }

  async function sendReply(schedule = null) {
    if (!canSendReply() || !sessionIsCurrent()) return false;
    const email = selectedReplyEmail;
    const bodyHtmlAtStart = replyBodyHtml;
    const plainText = bodyHtmlAtStart ? bodyHtmlAtStart.replace(/<[^>]*>/g, '').trim() : '';
    if (!plainText) return false;
    const requestGeneration = threadLoadGeneration;
    const sourceAtStart = viewSource;
    const archiveAtStart = archiveAfterSend;
    const contextAtStart = replyContext;
    if (!contextAtStart?.available) {
      showToast(replyUnavailableMessage(contextAtStart?.reason), 'error');
      return false;
    }
    if (!rememberCurrentReplyDraft()) return false;
    const controllerAtStart = durableReplyController;
    const ownerAtStart = durableReply;
    try {
      await controllerAtStart.markSending(true);
    } catch (error) {
      if (sessionIsCurrent()) showToast(error?.message || 'Reply must be saved before sending.', 'error');
      return false;
    }
    const payload = ownerAtStart.sendPayload();
    const restoreDraft = {
      draft_key: `client:${payload.client_draft_id}`,
      ...payload,
    };
    if (schedule?.scheduledFor) {
      payload.scheduled_for = schedule.scheduledFor;
      payload.schedule_timezone = schedule.scheduleTimezone;
    }
    if (archiveAtStart && sourceAtStart === 'needs_reply' && email.id) {
      payload.archive_source_after_send = true;
    }
    let editorReleased = false;
    const releaseEditor = () => {
      if (editorReleased || !sessionIsCurrent()) return;
      editorReleased = true;
      const replyStillActive = threadRequestIsCurrent(requestGeneration, {
        emailId: email.id ?? null,
        threadId: email.gmail_thread_id ?? null,
        source: sourceAtStart,
      });
      const sentDraftStillActive = replyStillActive && replyBodyHtml === bodyHtmlAtStart;
      if (sentDraftStillActive) replyBodyHtml = '';
      releaseFlowDurableReply();

      if (sourceAtStart === 'needs_reply') {
        if (!replyStillActive || sentDraftStillActive) removeEmailAndAdvance(email.id);
      } else if (sentDraftStillActive) {
        closeReplyView();
      }
    };

    inlineReplySending = true;
    inlineReplySendMode = schedule ? 'schedule' : 'send';
    try {
      const operation = await submitOutboundSend(payload, {
        onAccepted: () => {},
        onSent: () => {
          void durableReplyStorage?.delete?.(sessionGuard.userId, payload.client_draft_id);
        },
        onRestore: (operation, reason) => restoreOutboundComposeDraft(restoreDraft, operation, reason),
      });
      if (!sessionIsCurrent()) return false;
      if (operation) {
        await controllerAtStart.markSendUncertain(operation);
        releaseEditor();
      }
      return true;
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
  }

  async function discardFlowReply() {
    if (!durableReplyController) return;
    const discardOwner = durableReplyController;
    await discardOwner.discard({ delayMs: 10000 });
    showToast('Reply discarded', 'info', 10000, {
      actionLabel: 'Undo',
      onAction: () => discardOwner.undoDiscard(),
    });
  }

  function retryFlowDraft() {
    durableReplyError = '';
    void durableReplyController?.retry();
  }

  function undoFlowDiscard() {
    void durableReplyController?.undoDiscard();
  }

  function formatEmailDate(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    return d.toLocaleDateString([], {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  }

  function stripHtml(html) {
    if (!html) return '';
    const tmp = document.createElement('div');
    tmp.innerHTML = html;
    return tmp.textContent || tmp.innerText || '';
  }

  function formatAddresses(addresses) {
    if (!addresses || addresses.length === 0) return '';
    return addresses.map(a => {
      if (typeof a === 'string') return a;
      if (a.name) return `${a.name} <${a.address}>`;
      return a.address;
    }).join(', ');
  }

  function sameReplySource(candidate, source) {
    const sourceId = Number(source?.account_id) || null;
    const candidateId = Number(candidate?.account_id) || null;
    if (sourceId && candidateId) return sourceId === candidateId;
    const sourceEmail = normalizeReplyAddress(source?.account_email);
    const candidateEmail = normalizeReplyAddress(candidate?.account_email);
    return Boolean(sourceEmail && candidateEmail && sourceEmail === candidateEmail);
  }

  // Choose from this exact account only. Needs Reply targets the newest inbound
  // message; Awaiting Response follows up on the newest message, which is
  // normally the user's sent message and therefore targets its recipients.
  let replyMessage = $derived.by(() => {
    if (!selectedReplyEmail) return null;
    const source = {
      ...selectedReplyEmail,
      is_sent: selectedReplyEmail.is_sent ?? viewSource === 'awaiting',
    };
    const messages = Array.isArray(threadData?.emails)
      ? threadData.emails.filter(message => sameReplySource(message, source))
      : [];
    // A summary is not authoritative enough to send: it may omit Reply-To,
    // recipients, direction, or exact account identity. Thread fetch failures
    // therefore keep every reply path unavailable.
    if (messages.length === 0) return null;
    if (viewSource === 'awaiting') {
      return newestThreadMessage(messages, $threadOrder);
    }
    const inbound = messages.filter(message => message.is_sent === false);
    return newestThreadMessage(inbound, $threadOrder)
      || newestThreadMessage(messages, $threadOrder);
  });

  // One payload-ready envelope owns both the visible From/To/Cc context and
  // the eventual send request, so they cannot drift apart.
  let replyContext = $derived.by(() => {
    if (threadLoading) return null;
    if (!replyMessage) {
      const source = resolveReplySourceAccount({
        message: selectedReplyEmail,
        accounts: $accounts,
      });
      if (!source.available) return { ...source, message: null };
      return {
        available: false,
        reason: REPLY_ENVELOPE_UNAVAILABLE.THREAD_DETAILS_UNAVAILABLE,
        sourceAccount: null,
        envelope: null,
        message: null,
      };
    }
    const result = buildReplyEnvelope({
      message: replyMessage,
      accounts: $accounts,
      mode: REPLY_ENVELOPE_MODES.REPLY_ALL,
    });
    if (!result.available) return { ...result, message: replyMessage };
    return {
      ...result,
      message: replyMessage,
      sendingAccount: result.sourceAccount,
      accountColor: $accountColorMap[result.sourceAccount.email] || null,
      otherParticipantCount: Math.max(
        0,
        result.envelope.to.length + result.envelope.cc.length - 1,
      ),
    };
  });
  let replyActionLabel = $derived(
    replyContext?.available && replyContext.otherParticipantCount > 0
      ? 'Send Reply All'
      : 'Send Reply',
  );
</script>

<div
  class="flow-shell h-full flex relative"
  class:reply-view-open={replyViewOpen}
  style="background: var(--bg-primary); {isDraggingSidebar ? 'user-select: none; cursor: col-resize' : ''}{isDraggingBottomCol ? 'user-select: none; cursor: col-resize' : ''}"
>

  <!-- ============ LEFT SIDEBAR: CHAT ============ -->
  <div
    class="chat-pane h-full shrink-0 flex flex-col border-r {isDraggingSidebar ? '' : 'transition-all duration-300'}"
    class:chat-collapsed={chatCollapsed}
    style="border-color: var(--border-color); background: var(--bg-secondary); width: {chatCollapsed ? '48px' : chatWidthPx + 'px'}"
  >
    {#if chatCollapsed}
      <!-- Collapsed: just an icon button -->
      <div class="flex flex-col items-center pt-3 gap-2">
        <button
          onclick={() => { chatCollapsed = false; }}
          class="w-9 h-9 rounded-lg flex items-center justify-center transition-fast"
          style="background: var(--color-accent-500)/10; color: var(--color-accent-500)"
          title="Open chat"
          aria-label="Open email assistant"
        >
          <Icon name="message-square" size={18} />
        </button>
      </div>
    {:else}
      <!-- Chat Header -->
      <div class="px-3 py-2.5 border-b flex items-center justify-between shrink-0" style="border-color: var(--border-color)">
        <div class="flex items-center gap-2 min-w-0">
          <span class="shrink-0" style="color: var(--color-accent-500)"><Icon name="message-square" size={16} /></span>
          <span class="text-xs font-semibold truncate" style="color: var(--text-primary)">Talk to your Emails</span>
        </div>
        <div class="flex items-center gap-1 shrink-0">
          {#if hasActiveChat}
            <button
              onclick={startNewChat}
              class="p-1 rounded-md transition-fast"
              style="color: var(--text-tertiary)"
              title="New conversation"
            >
              <Icon name="plus" size={14} />
            </button>
          {/if}
          <button
            onclick={() => { chatCollapsed = true; }}
            class="p-1 rounded-md transition-fast"
            style="color: var(--text-tertiary)"
            title="Collapse chat"
            aria-label="Close email assistant"
          >
            <Icon name="chevrons-left" size={14} />
          </button>
        </div>
      </div>

      <!-- Active conversation label -->
      {#if activeConversationId}
        <div class="px-3 py-1.5 border-b flex items-center gap-2" style="border-color: var(--border-color)">
          <button
            onclick={startNewChat}
            class="flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10px] font-medium transition-fast shrink-0"
            style="color: var(--color-accent-600)"
            title="Back to conversations"
          >
            <Icon name="arrow-left" size={12} />
            Back
          </button>
          <span class="text-[10px] px-2 py-0.5 rounded-full truncate" style="background: var(--bg-tertiary); color: var(--text-tertiary)">
            {conversations.find(c => c.id === activeConversationId)?.title || 'Conversation'}
          </span>
        </div>
      {/if}

      <!-- Chat Messages -->
      <div bind:this={messagesContainer} class="flex-1 overflow-y-auto p-3 space-y-3">
        {#if conversationMessages.length === 0 && !isProcessing}
          <!-- Empty state with conversation history -->
          <div class="flex flex-col px-1">
            <div class="flex items-center justify-between mb-2">
              <span class="text-[10px] font-semibold uppercase tracking-wider" style="color: var(--text-tertiary)">History</span>
              {#if conversations.length > 0}
                <button
                  onclick={startNewChat}
                  class="text-[10px] px-2 py-0.5 rounded font-medium transition-fast"
                  style="background: var(--color-accent-500); color: white"
                >New Chat</button>
              {/if}
            </div>
            {#if conversations.length === 0}
              <div class="flex flex-col items-center justify-center py-8 text-center">
                <div class="w-10 h-10 rounded-xl flex items-center justify-center mb-2" style="background: var(--color-accent-500)/10; color: var(--color-accent-500)">
                  <Icon name="zap" size={20} />
                </div>
                <h3 class="text-xs font-semibold mb-1" style="color: var(--text-primary)">Ask about your emails</h3>
                <p class="text-[10px]" style="color: var(--text-secondary)">
                  Search, summarize, and get insights.
                </p>
              </div>
            {:else}
              <div class="flex flex-col gap-1">
                {#each conversations as conv}
                  <div
                    role="button"
                    tabindex="0"
                    onclick={() => loadConversation(conv.id)}
                    onkeydown={(e) => { if (e.key === 'Enter') loadConversation(conv.id); }}
                    class="px-2.5 py-2 rounded-lg transition-fast group relative cursor-pointer"
                    style="background: {activeConversationId === conv.id ? 'var(--bg-hover)' : 'var(--bg-primary)'};"
                  >
                    <div class="text-xs truncate pr-5" style="color: {activeConversationId === conv.id ? 'var(--text-primary)' : 'var(--text-secondary)'}">
                      {conv.title || 'Untitled'}
                    </div>
                    <div class="text-[9px] mt-0.5" style="color: var(--text-tertiary)">
                      {formatDate(conv.created_at)}
                    </div>
                    <button
                      onclick={(e) => { e.stopPropagation(); deleteConversation(conv.id); }}
                      class="absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 p-0.5 rounded transition-fast"
                      style="color: var(--text-tertiary)"
                      title="Delete"
                    >
                      <Icon name="x" size={12} />
                    </button>
                  </div>
                {/each}
              </div>
            {/if}
          </div>
        {:else}
          <!-- Messages -->
          {#each conversationMessages as msg}
            {#if msg.role === 'user'}
              <div class="flex justify-end">
                <div class="max-w-[260px] px-3 py-2 rounded-xl rounded-br-sm text-xs" style="background: var(--color-accent-500); color: white">
                  {msg.content}
                </div>
              </div>
            {/if}
          {/each}

          <!-- Agent progress / response area -->
          {#if currentPhase || isProcessing}
            <div>
              <!-- Planning -->
              {#if currentPhase === 'plan'}
                <div class="flex items-center gap-2 mb-2">
                  <div class="w-4 h-4 rounded-full flex items-center justify-center animate-pulse" style="background: var(--color-accent-500)/20">
                    <div class="w-2 h-2 rounded-full" style="background: var(--color-accent-500)"></div>
                  </div>
                  <span class="text-xs" style="color: var(--text-primary)">Analyzing...</span>
                </div>
              {/if}

              <!-- Clarification -->
              {#if currentPhase === 'clarification' && clarificationQuestion}
                <div class="mb-3 rounded-lg border overflow-hidden" style="border-color: var(--color-accent-500)/30; background: var(--color-accent-500)/5">
                  <div class="px-3 py-2 flex items-start gap-2">
                    <span class="mt-0.5 shrink-0" style="color: var(--color-accent-600)"><Icon name="help-circle" size={14} /></span>
                    <div class="flex-1">
                      <div class="text-[10px] font-semibold uppercase tracking-wider mb-0.5" style="color: var(--color-accent-600)">Quick question</div>
                      <div class="text-xs" style="color: var(--text-primary)">{clarificationQuestion}</div>
                    </div>
                  </div>
                </div>
              {/if}

              <!-- Task list -->
              {#if tasks.length > 0}
                <div class="mb-3 rounded-lg border overflow-hidden" style="border-color: var(--border-color); background: var(--bg-primary)">
                  <div class="px-3 py-2 border-b flex items-center justify-between" style="border-color: var(--border-color)">
                    <span class="text-[10px] font-semibold uppercase tracking-wider" style="color: var(--text-tertiary)">Plan</span>
                    {#if currentPhase === 'execute' || currentPhase === 'verify' || currentPhase === 'done'}
                      <span class="text-[9px] font-medium px-1.5 py-0.5 rounded-full" style="background: var(--color-accent-500)/15; color: var(--color-accent-600)">
                        {getCompletedCount()}/{tasks.length}
                      </span>
                    {/if}
                  </div>
                  {#each tasks as task}
                    {@const status = taskStatuses[task.id] || { status: 'pending' }}
                    <div
                      class="px-3 py-2 border-b last:border-0"
                      style="border-color: var(--border-color); {status.status === 'in_progress' ? 'background: var(--color-accent-500)/5' : ''}"
                    >
                      <div class="flex items-start gap-2">
                        <div class="mt-0.5 shrink-0">
                          {#if status.status === 'pending'}
                            <div class="w-3 h-3 rounded-full border-2" style="border-color: var(--border-color)"></div>
                          {:else if status.status === 'in_progress'}
                            <div class="w-3 h-3 rounded-full border-2 border-t-transparent animate-spin" style="border-color: var(--color-accent-500)"></div>
                          {:else if status.status === 'completed'}
                            <div class="w-3 h-3 rounded-full flex items-center justify-center" style="background: var(--status-success)">
                              <svg class="w-2 h-2 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M4.5 12.75l6 6 9-13.5" />
                              </svg>
                            </div>
                          {:else if status.status === 'failed'}
                            <div class="w-3 h-3 rounded-full flex items-center justify-center" style="background: var(--status-error)">
                              <svg class="w-2 h-2 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M6 18L18 6M6 6l12 12" />
                              </svg>
                            </div>
                          {/if}
                        </div>
                        <div class="flex-1 min-w-0">
                          <div class="text-[10px]" style="color: var(--text-primary)">{task.description}</div>
                          {#if status.status === 'in_progress' && status.detail}
                            <div class="mt-0.5 text-[9px] italic" style="color: var(--color-accent-600)">{status.detail}</div>
                          {/if}
                          {#if status.status === 'completed' && status.summary}
                            <button
                              onclick={() => toggleTaskExpanded(task.id)}
                              class="mt-0.5 text-[9px] flex items-center gap-0.5 transition-fast"
                              style="color: var(--text-tertiary)"
                            >
                              <svg class="w-2 h-2 transition-transform duration-200 {expandedTasks[task.id] ? 'rotate-90' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                              </svg>
                              {expandedTasks[task.id] ? 'Hide' : 'Details'}
                            </button>
                            {#if expandedTasks[task.id]}
                              <div class="mt-1 text-[9px] whitespace-pre-wrap rounded p-1.5" style="color: var(--text-secondary); background: var(--bg-secondary)">{status.summary}</div>
                            {/if}
                          {/if}
                        </div>
                      </div>
                    </div>
                  {/each}
                </div>
              {/if}

              <!-- Verify -->
              {#if currentPhase === 'verify'}
                <div class="flex items-center gap-2 mb-2">
                  <div class="w-4 h-4 rounded-full flex items-center justify-center animate-pulse" style="background: #a855f7/20">
                    <div class="w-2 h-2 rounded-full" style="background: #a855f7"></div>
                  </div>
                  <span class="text-xs" style="color: var(--text-primary)">Composing answer...</span>
                </div>
              {/if}

              <!-- Final answer -->
              {#if renderedContent}
                <div class="flex items-center gap-1 mb-1">
                  <button
                    onclick={downloadMarkdown}
                    class="flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-medium border transition-fast"
                    style="border-color: var(--border-color); color: var(--text-secondary); background: var(--bg-primary)"
                  >
                    <Icon name="download" size={10} />
                    Download
                  </button>
                </div>
                <div
                  class="prose prose-sm max-w-none rounded-lg border p-3 chat-markdown text-xs"
                  style="border-color: var(--border-color); background: var(--bg-primary); color: var(--text-primary)"
                >
                  {@html renderedContent}
                </div>
              {/if}

              <!-- Error -->
              {#if errorMessage}
                <div class="rounded-lg border p-3 text-xs" style="border-color: var(--status-error-border); background: var(--status-error-bg); color: var(--status-error)">
                  {errorMessage}
                </div>
              {/if}
            </div>
          {/if}
        {/if}
      </div>

      <!-- Chat Input -->
      <div class="px-3 py-2 border-t shrink-0" style="border-color: var(--border-color)">
        <div class="flex gap-1.5 items-end">
          <div class="flex-1 relative">
            <textarea
              bind:value={messageInput}
              onkeydown={handleKeydown}
              placeholder="Ask anything..."
              disabled={isProcessing}
              rows="1"
              class="w-full px-3 py-2 rounded-lg border text-xs resize-none outline-none transition-fast"
              style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary); min-height: 36px; max-height: 100px"
            ></textarea>
          </div>
          <button
            onclick={sendMessage}
            disabled={isProcessing || !messageInput.trim()}
            class="h-[36px] w-[36px] shrink-0 rounded-lg flex items-center justify-center transition-fast"
            style="background: {isProcessing || !messageInput.trim() ? 'var(--border-color)' : 'var(--color-accent-500)'}; color: white"
          >
            {#if isProcessing}
              <div class="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
            {:else}
              <Icon name="send" size={14} />
            {/if}
          </button>
        </div>
      </div>
    {/if}
  </div>

  <!-- Sidebar Resize Handle -->
  {#if !chatCollapsed}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="shrink-0 flex items-center justify-center cursor-col-resize col-resize-handle"
      style="width: 7px; background: var(--bg-secondary); border-left: 1px solid var(--border-color); border-right: 1px solid var(--border-color); {isDraggingSidebar ? 'user-select: none' : ''}"
      onmousedown={startSidebarDrag}
    >
      <div
        class="h-10 w-1 rounded-full transition-fast"
        style="background: {isDraggingSidebar ? 'var(--color-accent-500)' : 'var(--border-color)'}"
      ></div>
    </div>
  {/if}

  <!-- ============ MAIN CONTENT ============ -->
  {#if replyViewOpen && selectedReplyEmail}
    <!-- ============ FULL-WIDTH REPLY VIEW ============ -->
    <div class="flex-1 h-full flex flex-col min-w-0" style="background: var(--bg-primary)">
      <!-- Top Navigation Bar -->
      <div class="px-4 py-2 border-b shrink-0 flex items-center justify-between" style="border-color: var(--border-color); background: var(--bg-secondary)">
        <button
          onclick={closeReplyView}
          class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-fast"
          style="color: var(--text-secondary)"
        >
          <Icon name="arrow-left" size={14} />
          Back to Flow
        </button>
        <div class="flex-1 min-w-0 mx-4">
          <h2 class="text-sm font-semibold truncate text-center" style="color: var(--text-primary)">{selectedReplyEmail.subject || '(no subject)'}</h2>
        </div>
        {#if viewSource === 'needs_reply'}
          <div class="flex items-center gap-2 shrink-0">
            <span class="text-[11px] font-medium tabular-nums" style="color: var(--text-tertiary)">{activeReplyIndex + 1} of {needsReplyEmails.length}</span>
            <div class="flex items-center gap-0.5">
              <button
                onclick={goToPrevReply}
                disabled={activeReplyIndex <= 0}
                class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md transition-fast"
                style="color: {activeReplyIndex <= 0 ? 'var(--border-color)' : 'var(--text-secondary)'}"
                aria-label="Previous email"
                title="Previous email"
              >
                <Icon name="chevron-left" size={16} />
              </button>
              <button
                onclick={goToNextReply}
                disabled={activeReplyIndex >= needsReplyEmails.length - 1}
                class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md transition-fast"
                style="color: {activeReplyIndex >= needsReplyEmails.length - 1 ? 'var(--border-color)' : 'var(--text-secondary)'}"
                aria-label="Next email"
                title="Next email"
              >
                <Icon name="chevron-right" size={16} />
              </button>
            </div>
          </div>
        {:else}
          <div class="flex items-center gap-1.5 shrink-0">
            <span class="text-[10px] px-2 py-0.5 rounded-full font-medium" style="background: var(--bg-tertiary); color: var(--text-tertiary)">
              {viewSource === 'awaiting' ? 'Waiting for response' : 'Thread'}
            </span>
          </div>
        {/if}
      </div>

      <!-- Top/Bottom Resizable Layout -->
      <div class="flex-1 flex flex-col min-h-0" bind:this={replyContainerEl} style="{isDraggingDivider ? 'user-select: none; cursor: row-resize' : ''}">
        {#if isDraggingDivider}
          <div class="fixed inset-0 z-50" style="cursor: row-resize"></div>
        {/if}
        <!-- TOP PANE: Thread Context -->
        <div class="overflow-y-auto" style="height: {topPanePercent}%">
          <!-- Email Header -->
          <div class="px-5 py-2.5 border-b" style="border-color: var(--border-color)">
            <div class="flex items-center gap-2 mb-0.5">
              {#if selectedReplyEmail.category}
                <span class="text-xs px-1.5 py-0.5 rounded-full font-medium shrink-0 {categoryColors[selectedReplyEmail.category]?.bg || ''} {categoryColors[selectedReplyEmail.category]?.text || ''}">
                  {categoryLabel(selectedReplyEmail.category)}
                </span>
              {/if}
              <h3 class="text-base font-semibold" style="color: var(--text-primary)">{selectedReplyEmail.subject || '(no subject)'}</h3>
            </div>
            <div class="flex items-center gap-2 text-xs" style="color: var(--text-secondary)">
              <span class="font-medium">{selectedReplyEmail.from_name || selectedReplyEmail.from_address}</span>
              <span style="color: var(--text-tertiary)">{formatRelativeDate(selectedReplyEmail.date)}</span>
            </div>
          </div>

          <!-- AI Summary -->
          {#if selectedReplyEmail.summary}
            <div class="px-5 py-2.5 border-b" style="border-color: var(--border-color); background: var(--bg-secondary)">
              <div class="flex items-center gap-1.5 mb-1">
                <span style="color: var(--color-accent-500)"><Icon name="zap" size={12} /></span>
                <span class="text-[11px] font-semibold uppercase tracking-wider" style="color: var(--color-accent-600)">AI Summary</span>
              </div>
              <p class="text-sm leading-relaxed" style="color: var(--text-primary)">{selectedReplyEmail.summary}</p>
              {#if selectedReplyEmail.action_items && selectedReplyEmail.action_items.length > 0}
                <div class="flex flex-wrap gap-x-4 gap-y-0.5 mt-1.5">
                  {#each selectedReplyEmail.action_items as item}
                    <span class="text-xs flex items-center gap-1" style="color: var(--text-secondary)">
                      <span class="w-1 h-1 rounded-full shrink-0" style="background: var(--color-accent-500)"></span>
                      {item}
                    </span>
                  {/each}
                </div>
              {/if}
            </div>
          {/if}

          <!-- Thread Messages -->
          <div class="px-5 py-3 space-y-2">
            {#if threadLoading}
              <div class="flex items-center justify-center py-10">
                <div class="w-5 h-5 border-2 rounded-full animate-spin" style="border-color: var(--border-color); border-top-color: var(--color-accent-500)"></div>
              </div>
            {:else if threadData && threadData.emails}
              {#each threadData.emails as msg, msgIdx}
                {@const isCollapsed = collapsedMessages[msg.id]}
                {@const isNewest = $threadOrder === 'newest_first' ? msgIdx === 0 : msgIdx === threadData.emails.length - 1}
                <div class="rounded-lg border overflow-hidden" style="border-color: var(--border-color)">
                  <!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
                  <button
                    class="px-4 py-2 flex items-center gap-2 cursor-pointer transition-fast"
                    class:w-full={true}
                    class:text-left={true}
                    style="background: {isNewest ? 'var(--bg-secondary)' : 'var(--bg-tertiary)'}"
                    onclick={() => toggleMessageCollapse(msg.id)}
                    aria-expanded={!isCollapsed}
                    aria-label="{isCollapsed ? 'Expand' : 'Collapse'} message from {msg.from_name || msg.from_address}"
                  >
                    <div class="flex-1 min-w-0">
                      <div class="flex items-center gap-2">
                        <span class="text-xs font-medium" style="color: var(--text-primary)">{msg.from_name || msg.from_address}</span>
                        {#if msg.is_sent}
                          <span class="text-[9px] px-1.5 py-0.5 rounded-full" style="background: var(--bg-tertiary); color: var(--text-tertiary)">You</span>
                        {/if}
                        <span class="text-xs" style="color: var(--text-tertiary)">{formatEmailDate(msg.date)}</span>
                      </div>
                      {#if !isCollapsed && msg.to_addresses && msg.to_addresses.length > 0}
                        <div class="text-[11px] mt-0.5 truncate" style="color: var(--text-secondary)">
                          To: {formatAddresses(msg.to_addresses)}
                        </div>
                      {/if}
                      {#if !isCollapsed && msg.cc_addresses && msg.cc_addresses.length > 0}
                        <div class="text-[11px] truncate" style="color: var(--text-secondary)">
                          Cc: {formatAddresses(msg.cc_addresses)}
                        </div>
                      {/if}
                      {#if isCollapsed && msg.body_text}
                        <div class="text-xs truncate mt-0.5" style="color: var(--text-tertiary)">{msg.body_text.slice(0, 120)}</div>
                      {/if}
                    </div>
                    <span style="color: var(--text-tertiary)"><Icon name={isCollapsed ? 'chevron-down' : 'chevron-up'} size={14} /></span>
                  </button>

                  {#if !isCollapsed}
                    <div class="px-4 py-3 text-sm" style="background: var(--bg-secondary)">
                      {#if msg.body_html}
                        <EmailHtmlFrame
                          html={msg.body_html}
                          contentKey={msg.id}
                          title="Message from {msg.from_name || msg.from_address || 'unknown sender'}"
                          padding="8px"
                          minHeight="60px"
                        />
                      {:else if msg.body_text}
                        <pre class="whitespace-pre-wrap font-sans text-sm" style="color: var(--text-primary)">{msg.body_text}</pre>
                      {:else}
                        <p class="text-xs italic" style="color: var(--text-tertiary)">No content</p>
                      {/if}
                    </div>
                  {/if}
                </div>
              {/each}
            {:else}
              <div class="py-6 text-center text-xs" style="color: var(--text-tertiary)">
                Could not load thread
              </div>
            {/if}
          </div>
        </div>

        <!-- Resizable Divider -->
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div
          class="shrink-0 flex items-center justify-center cursor-row-resize group"
          style="height: 7px; background: var(--bg-secondary); border-top: 1px solid var(--border-color); border-bottom: 1px solid var(--border-color)"
          onmousedown={startDividerDrag}
        >
          <div
            class="w-10 h-1 rounded-full transition-fast"
            style="background: {isDraggingDivider ? 'var(--color-accent-500)' : 'var(--border-color)'}"
          ></div>
        </div>

        <!-- BOTTOM PANE: Response Workspace -->
        <div class="flex flex-col overflow-hidden" style="height: {100 - topPanePercent}%">
          <!-- Reply Context Bar: who we're replying to + sending account -->
          {#if replyContext}
            <div class="px-5 py-2 border-b shrink-0" style="border-color: var(--border-color); background: var(--bg-secondary)">
              {#if replyContext.available}
                <div
                  class="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1 text-xs"
                  style="color: var(--text-primary)"
                  data-reply-envelope="flow"
                >
                  <span class="inline-flex items-center gap-1.5">
                    {#if replyContext.accountColor}
                      <span class="w-2 h-2 rounded-full shrink-0" style="background: {replyContext.accountColor.bg}"></span>
                    {/if}
                    <strong>From:</strong> {replyContext.sourceAccount.email}
                  </span>
                  <span class="min-w-0 break-all"><strong>To:</strong> {replyContext.envelope.to.join(', ')}</span>
                  {#if replyContext.envelope.cc.length > 0}
                    <span class="min-w-0 break-all"><strong>Cc:</strong> {replyContext.envelope.cc.join(', ')}</span>
                  {/if}
                  {#if replyContext.otherParticipantCount > 0}
                    <span class="rounded-full px-1.5 py-0.5 text-[10px] font-medium" style="background: var(--bg-tertiary); color: var(--text-secondary)">Reply All</span>
                  {/if}
                </div>
              {:else}
                <p
                  class="text-xs font-medium"
                  style="color: var(--status-error)"
                  role="alert"
                  data-reply-unavailable="flow"
                >{replyUnavailableMessage(replyContext.reason)}</p>
              {/if}
            </div>
          {/if}

          <!-- Scrollable area: reply options + suggestion banner + editor -->
          <div class="flex-1 min-h-0 overflow-y-auto">

          <!-- Reply Options as horizontal cards -->
          {#if selectedReplyEmail.reply_options && selectedReplyEmail.reply_options.length > 0}
            <div class="px-5 py-2.5 border-b" style="border-color: var(--border-color)">
              <div class="flex items-center gap-1.5 mb-2">
                <span style="color: var(--color-accent-500)"><Icon name="zap" size={12} /></span>
                <span class="text-[11px] font-semibold uppercase tracking-wider" style="color: var(--color-accent-600)">AI Reply Options</span>
              </div>
              <div class="flex gap-2 overflow-x-auto pb-1">
                {#each selectedReplyEmail.reply_options as option, optIdx}
                  {@const isSelected = selectedOptionIndex === optIdx}
                  {@const intentStyle = intentCardStyles[option.intent] || intentCardStyles.custom}
                  <!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
                  <button
                    onclick={() => selectReplyOption(option, optIdx)}
                    data-shortcut="flow.replyOption{optIdx + 1}"
                    class="rounded-lg border p-3 cursor-pointer text-left transition-fast shrink-0 {intentStyle.bg} {intentStyle.border}"
                    style="width: 260px; {isSelected ? 'box-shadow: 0 0 0 2px var(--color-accent-500)' : ''}"
                  >
                    <div class="flex items-center justify-between mb-1">
                      <div class="flex items-center gap-1.5">
                        <Icon name={intentIcon(option.intent)} size={13} />
                        <span class="text-xs font-semibold {intentStyle.text}">{option.label}</span>
                      </div>
                      {#if isSelected}
                        <span class="text-[8px] px-1.5 py-0.5 rounded-full font-bold" style="background: var(--color-accent-500); color: white">SELECTED</span>
                      {/if}
                    </div>
                    <p class="text-xs leading-relaxed line-clamp-3 {intentStyle.text}">{option.body}</p>
                  </button>
                {/each}
                <!-- Custom prompt card -->
                <!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
                <button
                  onclick={() => { customPromptOpen = !customPromptOpen; }}
                  data-shortcut="flow.customReply"
                  class="rounded-lg border-2 border-dashed p-3 cursor-pointer transition-fast shrink-0 flex flex-col items-center justify-center gap-1.5"
                  style="width: 140px; border-color: var(--border-color); opacity: {customPromptOpen ? 1 : 0.8}; {customPromptOpen ? 'border-color: var(--color-accent-500); background: color-mix(in srgb, var(--color-accent-500) 5%, transparent)' : ''}"
                >
                  <Icon name="edit-3" size={16} />
                  <span class="text-[11px] font-medium" style="color: var(--text-secondary)">Custom...</span>
                </button>
              </div>
              {#if customPromptOpen}
                <div class="mt-2 flex items-center gap-2">
                  <input
                    type="text"
                    bind:value={customPromptText}
                    placeholder="e.g., Suggest meeting at a later date..."
                    class="flex-1 text-xs px-3 py-2 rounded-lg border outline-none"
                    style="border-color: var(--border-color); background: var(--bg-primary); color: var(--text-primary)"
                    disabled={customPromptLoading}
                    onkeydown={(e) => { if (e.key === 'Enter' && !customPromptLoading) generateCustomReply(); if (e.key === 'Escape') { customPromptOpen = false; customPromptText = ''; } }}
                  />
                  <button
                    onclick={() => generateCustomReply()}
                    disabled={customPromptLoading || !customPromptText.trim()}
                    class="px-3 py-2 rounded-lg text-xs font-medium transition-fast shrink-0 flex items-center gap-1.5"
                    style="background: var(--color-accent-500); color: white; opacity: {customPromptLoading || !customPromptText.trim() ? '0.5' : '1'}"
                  >
                    {#if customPromptLoading}
                      <span class="inline-block w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
                      Generating...
                    {:else}
                      <Icon name="zap" size={12} />
                      Generate
                    {/if}
                  </button>
                </div>
              {/if}
            </div>
          {:else if selectedReplyEmail.suggested_reply}
            <div class="px-5 py-2.5 border-b" style="border-color: var(--border-color); background: var(--bg-secondary)">
              <div class="flex items-center gap-1.5 mb-1">
                <span style="color: var(--color-accent-500)"><Icon name="zap" size={12} /></span>
                <span class="text-[10px] font-semibold uppercase tracking-wider" style="color: var(--color-accent-600)">Suggested Reply</span>
              </div>
              <p class="text-xs italic leading-relaxed mb-2" style="color: var(--text-secondary)">"{selectedReplyEmail.suggested_reply}"</p>
              <button
                onclick={useSuggestedReply}
                class="text-[10px] font-medium px-2.5 py-1 rounded-md border transition-fast shrink-0"
                style="border-color: var(--border-color); color: var(--color-accent-600)"
              >
                Use this
              </button>
            </div>
          {/if}

          <!-- AI Suggestion Banner -->
          {#if replyIntent}
            <div class="px-5 py-1.5 border-b" style="border-color: var(--border-color); background: color-mix(in srgb, var(--color-accent-500) 8%, transparent)">
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-1.5">
                  <svg class="w-3.5 h-3.5 shrink-0" style="color: var(--color-accent-500)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
                  </svg>
                  <span class="text-[11px] font-medium" style="color: var(--color-accent-600)">
                    {#if replyIntent === 'custom' && lastCustomPrompt}
                      AI-generated from custom prompt -- edit as needed
                    {:else}
                      AI-suggested {intentLabels[replyIntent] || 'reply'} -- edit as needed
                    {/if}
                  </span>
                </div>
                <button
                  onclick={clearReplyOption}
                  class="text-[10px] font-medium px-2 py-0.5 rounded transition-fast"
                  style="color: var(--text-tertiary)"
                >
                  Reset
                </button>
              </div>
              {#if replyIntent === 'custom' && lastCustomPrompt}
                <div class="mt-1.5 flex items-center gap-2">
                  {#if editingCustomPrompt}
                    <input
                      type="text"
                      bind:value={lastCustomPrompt}
                      class="flex-1 text-xs px-3 py-1.5 rounded-lg border outline-none"
                      style="border-color: var(--color-accent-400); background: var(--bg-primary); color: var(--text-primary)"
                      disabled={customPromptLoading}
                      onkeydown={(e) => {
                        if (e.key === 'Enter' && !customPromptLoading) { generateCustomReply(lastCustomPrompt); }
                        if (e.key === 'Escape') { editingCustomPrompt = false; }
                      }}
                    />
                    <button
                      onclick={() => generateCustomReply(lastCustomPrompt)}
                      disabled={customPromptLoading || !lastCustomPrompt.trim()}
                      class="px-2.5 py-1.5 rounded-lg text-[10px] font-medium transition-fast shrink-0 flex items-center gap-1"
                      style="background: var(--color-accent-500); color: white; opacity: {customPromptLoading || !lastCustomPrompt.trim() ? '0.5' : '1'}"
                    >
                      {#if customPromptLoading}
                        <span class="inline-block w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
                        Generating...
                      {:else}
                        <Icon name="zap" size={11} />
                        Regenerate
                      {/if}
                    </button>
                    <button
                      onclick={() => { editingCustomPrompt = false; }}
                      class="text-[10px] font-medium px-1.5 py-0.5 rounded transition-fast"
                      style="color: var(--text-tertiary)"
                    >
                      Cancel
                    </button>
                  {:else}
                    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions a11y_no_noninteractive_element_interactions -->
                    <button
                      class="flex-1 text-left text-xs italic leading-relaxed cursor-pointer rounded px-1 -mx-1 transition-fast hover-bg-subtle"
                      style="color: var(--text-secondary)"
                      onclick={() => { editingCustomPrompt = true; }}
                      title="Click to edit prompt"
                    >"{lastCustomPrompt}"</button>
                    <button
                      onclick={() => { editingCustomPrompt = true; }}
                      class="text-[10px] font-medium px-2 py-1 rounded-md border transition-fast shrink-0 flex items-center gap-1"
                      style="border-color: var(--border-color); color: var(--color-accent-600)"
                    >
                      <Icon name="edit-3" size={10} />
                      Edit & Regenerate
                    </button>
                  {/if}
                </div>
              {/if}
            </div>
          {/if}

          <!-- Rich Text Editor -->
          {#if threadLoading}
            <div class="m-5 rounded-lg border p-4 text-sm" style="border-color: var(--border-color); color: var(--text-secondary)" role="status">
              Loading and verifying the full conversation…
            </div>
          {:else if replyContext?.available && durableReplyOpening}
            <div class="m-5 rounded-lg border p-4 text-sm" style="border-color: var(--border-color); color: var(--text-secondary)" role="status">
              Opening and reconciling the saved reply…
            </div>
          {:else if replyContext?.available && (
            durableReplyState.status === 'conflict'
            || durableReplyState.discardInProgress
            || durableReplyState.sendInProgress
          )}
            <div class="m-5 rounded-lg border p-4 text-sm" style="border-color: var(--border-color); color: var(--text-secondary)" role="status">
              This reply is temporarily locked while its saved state is resolved.
            </div>
          {:else if replyContext?.available && durableReplyController}
            <div class="flex flex-col">
              {#key editorKey}
                <DeferredRichEditor
                  content={initialReplyContent}
                  onUpdate={handleEditorUpdate}
                  onReady={() => { writingSurfaceReady = true; }}
                  placeholder="Write your reply..."
                  externalScroll={true}
                  autofocus={true}
                  ariaLabel="Reply body"
                  surface="flow-reply"
                />
              {/key}
            </div>
          {:else if replyContext?.available}
            <div class="m-5 rounded-lg border p-4 text-sm" style="border-color: var(--border-color); color: var(--text-secondary)" role="status">
              Preparing a safely saved reply…
            </div>
          {:else}
            <div
              class="m-5 rounded-lg border p-4 text-sm"
              style="border-color: color-mix(in srgb, var(--status-error) 35%, var(--border-color)); color: var(--text-secondary); background: var(--bg-secondary)"
              role="status"
            >
              {replyUnavailableMessage(replyContext?.reason)} Reply editing stays disabled until verification succeeds.
            </div>
          {/if}

          </div><!-- end scrollable area -->

          <div class="min-h-8 border-t px-4 py-1.5" style="border-color: var(--border-color); background: var(--bg-secondary)">
            {#if durableReplyOpening}
              <span class="text-xs" style="color: var(--text-secondary)" role="status">Opening saved reply…</span>
            {:else if durableReplyError}
              <span class="inline-flex flex-wrap items-center gap-2 text-xs" style="color: var(--status-error)" role="alert">
                <span>Not safely saved. Copy your reply before leaving.</span>
                <button type="button" class="min-h-11 rounded-lg border px-3 font-semibold" onclick={retryFlowDraft}>Retry</button>
              </span>
            {:else if durableReplyController}
              <DraftStatus
                state={durableReplyState}
                compact
                onretry={retryFlowDraft}
                onundo={undoFlowDiscard}
                onreview={openInCompose}
              />
            {/if}
          </div>

          <!-- Action Bar -->
          <div class="flow-reply-actions px-4 py-2.5 border-t shrink-0 flex items-center justify-between" style="border-color: var(--border-color); background: var(--bg-secondary)">
            <div class="flow-triage-actions flex items-center gap-2">
              {#if viewSource === 'needs_reply'}
                <!-- Archive after send toggle -->
                <label class="flex items-center gap-1.5 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    bind:checked={archiveAfterSend}
                    class="w-3.5 h-3.5 rounded border accent-current"
                    style="accent-color: var(--color-accent-500)"
                  />
                  <span class="text-xs font-medium" style="color: var(--text-secondary)">Archive after send</span>
                </label>

                <div class="triage-separator w-px h-4 mx-1" style="background: var(--border-color)"></div>

                <!-- Triage Actions -->
                <button
                  onclick={skipEmail}
                  class="flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium transition-fast hover-bg-subtle"
                  style="color: var(--text-secondary)"
                  title="Skip to next email"
                >
                  <Icon name="fast-forward" size={12} />
                  Skip
                </button>
                <button
                  onclick={ignoreCurrentEmail}
                  disabled={ignoringReplyEmailIds.includes(selectedReplyEmail?.id)}
                  class="flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium transition-fast hover-bg-subtle"
                  style="color: var(--text-secondary)"
                  title="Ignore — remove from needs reply"
                  data-shortcut="flow.ignore"
                >
                  <Icon name="eye-off" size={12} />
                  Ignore
                </button>
                <div class="relative">
                  <button
                    onclick={() => openSnoozePopover(selectedReplyEmail?.id)}
                    class="flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium transition-fast hover-bg-subtle"
                    style="color: var(--text-secondary)"
                    title="Snooze — hide temporarily"
                    data-shortcut="flow.snooze"
                  >
                    <Icon name="clock" size={12} />
                    Snooze
                  </button>
                  {#if snoozePopoverEmailId === selectedReplyEmail?.id}
                    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
                    <div
                      class="absolute top-full left-0 mt-1 py-1 rounded-lg border shadow-lg z-50 min-w-[160px]"
                      style="background: var(--bg-secondary); border-color: var(--border-color)"
                    >
                      {#each [
                        { key: '1h', label: '1 hour' },
                        { key: '3h', label: '3 hours' },
                        { key: 'tomorrow', label: 'Tomorrow morning' },
                        { key: 'next_week', label: 'Next week' },
                      ] as option}
                        <button
                          onclick={() => snoozeEmail(selectedReplyEmail.id, option.key, true)}
                          class="w-full text-left px-3 py-1.5 text-xs transition-fast hover-bg-subtle"
                          style="color: var(--text-primary)"
                        >
                          {option.label}
                        </button>
                      {/each}
                    </div>
                  {/if}
                </div>
                <button
                  onclick={archiveCurrentEmail}
                  class="flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium transition-fast hover-bg-subtle"
                  style="color: var(--text-secondary)"
                  title="Archive without replying"
                >
                  <Icon name="archive" size={12} />
                  Archive
                </button>
                <button
                  onclick={trashCurrentEmail}
                  class="flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium transition-fast hover-bg-subtle"
                  style="color: var(--text-secondary)"
                  title="Move to trash"
                >
                  <Icon name="trash-2" size={12} />
                </button>
              {:else}
                <button
                  onclick={closeReplyView}
                  class="flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium transition-fast hover-bg-subtle"
                  style="color: var(--text-secondary)"
                  title="Back to Flow"
                >
                  <Icon name="arrow-left" size={12} />
                  Back
                </button>

                <div class="triage-separator w-px h-4 mx-1" style="background: var(--border-color)"></div>

                <button
                  onclick={ignoreCurrentEmail}
                  disabled={ignoringReplyEmailIds.includes(selectedReplyEmail?.id)}
                  class="flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium transition-fast hover-bg-subtle"
                  style="color: var(--text-secondary)"
                  title="Ignore — remove from needs reply"
                  data-shortcut="flow.ignore"
                >
                  <Icon name="eye-off" size={12} />
                  Ignore
                </button>
                <div class="relative">
                  <button
                    onclick={() => openSnoozePopover(selectedReplyEmail?.id)}
                    class="flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium transition-fast hover-bg-subtle"
                    style="color: var(--text-secondary)"
                    title="Snooze — hide temporarily"
                    data-shortcut="flow.snooze"
                  >
                    <Icon name="clock" size={12} />
                    Snooze
                  </button>
                  {#if snoozePopoverEmailId === selectedReplyEmail?.id}
                    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
                    <div
                      class="absolute top-full left-0 mt-1 py-1 rounded-lg border shadow-lg z-50 min-w-[160px]"
                      style="background: var(--bg-secondary); border-color: var(--border-color)"
                    >
                      {#each [
                        { key: '1h', label: '1 hour' },
                        { key: '3h', label: '3 hours' },
                        { key: 'tomorrow', label: 'Tomorrow morning' },
                        { key: 'next_week', label: 'Next week' },
                      ] as option}
                        <button
                          onclick={() => snoozeEmail(selectedReplyEmail.id, option.key, true)}
                          class="w-full text-left px-3 py-1.5 text-xs transition-fast hover-bg-subtle"
                          style="color: var(--text-primary)"
                        >
                          {option.label}
                        </button>
                      {/each}
                    </div>
                  {/if}
                </div>
              {/if}
            </div>

            <div class="flow-send-actions flex items-center gap-2">
              <button
                onclick={discardFlowReply}
                disabled={!durableReplyController || durableReplyOpening || durableReplyState.discardInProgress || durableReplyState.sendInProgress}
                class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg border transition-fast disabled:opacity-50"
                style="border-color: var(--border-color); color: var(--text-secondary)"
                aria-label="Discard reply"
                title="Discard reply · Undo available for 10 seconds"
              >
                <Icon name="trash-2" size={14} />
              </button>
              <button
                onclick={openInCompose}
                disabled={threadLoading || !replyContext?.available || !durableReplyController || Boolean(durableReplyError)}
                class="flex min-h-11 items-center gap-1 px-3 py-2 rounded-lg text-xs font-medium transition-fast border"
                style="border-color: var(--border-color); color: var(--text-secondary); opacity: {threadLoading || !replyContext?.available ? 0.5 : 1}"
                title={threadLoading
                  ? 'Wait for the thread to finish loading'
                  : replyContext?.available
                    ? 'Open in full composer'
                    : replyUnavailableMessage(replyContext?.reason)}
              >
                <Icon name="external-link" size={12} />
                Full Compose
              </button>
              <SendSplitButton
                label={replyActionLabel}
                disabled={!canSendReply()}
                busy={inlineReplySending}
                busyLabel={inlineReplySendMode === 'schedule' ? 'Scheduling…' : 'Sending…'}
                onsend={() => sendReply()}
                onschedule={schedule => sendReply(schedule)}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  {:else}
  <div class="flow-main flex-1 h-full overflow-y-auto min-w-0">
    <div class="flow-dashboard max-w-5xl mx-auto px-4 py-5 space-y-5">

      <!-- ============ DAY SUMMARY STRIP ============ -->
      <DaySummaryStrip
        {upcomingEvents}
        {pendingTodos}
        {needsReplyTotal}
        {needsReplyEmails}
        {urgentCount}
        {trendsSummary}
        {formatEventTime}
        onOpenCalendar={() => currentPage.set('calendar')}
      />

      <!-- ============ NEEDS REPLY - CORE SECTION ============ -->
      <div class="rounded-xl border overflow-hidden" style="background: var(--bg-secondary); border-color: {focusedSection === 'needs_reply' && highlightedIndex >= 0 ? 'var(--color-accent-500)' : 'var(--border-color)'}">
        <div class="px-4 py-3 border-b flex items-center justify-between" style="border-color: var(--border-color)">
          <div class="flex items-center gap-2">
            <span style="color: var(--color-accent-500)"><Icon name="inbox" size={16} /></span>
            <h2 class="text-sm font-semibold" style="color: var(--text-primary)">Needs Reply</h2>
          </div>
          <div class="flex items-center gap-2">
            <button
              onclick={() => { hideFyi = !hideFyi; localStorage.setItem('flowHideFyi', String(hideFyi)); loadDaySummary(); }}
              class="text-[10px] px-2 py-0.5 rounded-full font-medium border transition-fast cursor-pointer"
              style="border-color: {hideFyi ? 'var(--border-color)' : 'var(--color-emerald-200, #a7f3d0)'}; background: {hideFyi ? 'transparent' : 'var(--color-emerald-50, #ecfdf5)'}; color: {hideFyi ? 'var(--text-tertiary)' : 'var(--color-emerald-700, #047857)'}"
              title={hideFyi ? 'FYI emails hidden — click to show' : 'Showing FYI emails — click to hide'}
            >
              {hideFyi ? 'FYI hidden' : 'FYI shown'}
            </button>
            {#if needsReplyTotal > 0}
              <span class="text-[10px] px-2 py-0.5 rounded-full font-medium" style="background: var(--status-error-bg); color: var(--status-error)">{needsReplyTotal} total</span>
            {/if}
          </div>
        </div>

        {#if needsReplyEmails.length > 0}
          <div class="px-4 py-2 text-[11px] border-b" style="border-color: var(--border-color); color: var(--text-tertiary); background: var(--bg-primary)">
            Showing the {needsReplyEmails.length} highest-priority conversations, ranked by urgency and freshness.
          </div>
          <div class="px-2 py-2 space-y-1">
            {#each needsReplyEmails as email, idx}
              <!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
              <div
                class="px-3 py-2.5 rounded-lg transition-fast hover-bg-subtle cursor-pointer border-b last-child-no-border"
                style="border-color: color-mix(in srgb, var(--border-color) 50%, transparent); {focusedSection === 'needs_reply' && highlightedIndex === idx ? 'outline: 2px solid var(--color-accent-500); outline-offset: -2px; background: var(--bg-tertiary)' : ''}"
                data-flow-item="needs_reply-{idx}"
                onclick={() => openReplyView(email, idx)}
                onkeydown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openReplyView(email, idx); } }}
                role="button"
                tabindex="0"
                aria-label="Open {cleanEmailText(email.subject) || 'no subject'} from {email.from_name || email.from_address}"
              >
                <div class="flex items-start gap-3">
                  <div class="flex-1 min-w-0">
                    <!-- Top row: category + subject -->
                    <div class="flex items-center gap-2 mb-1">
                      {#if email.category}
                        <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 {categoryColors[email.category]?.bg || ''} {categoryColors[email.category]?.text || ''}">
                          {categoryLabel(email.category)}
                        </span>
                      {/if}
                      <span class="text-sm font-medium truncate" style="color: var(--text-primary)">{cleanEmailText(email.subject) || '(no subject)'}</span>
                    </div>

                    <!-- From + date -->
                    <div class="flex items-center gap-2 text-xs mb-1.5" style="color: var(--text-secondary)">
                      <span class="font-medium">{email.from_name || email.from_address}</span>
                      <span style="color: var(--text-tertiary)">{formatRelativeDate(email.date)}</span>
                    </div>

                    <!-- AI Summary -->
                    {#if email.summary}
                      <p class="text-xs mb-2 line-clamp-2" style="color: var(--text-secondary)">{email.summary}</p>
                    {:else if email.snippet}
                      <p class="text-xs mb-2 line-clamp-2" style="color: var(--text-tertiary)">{cleanEmailText(email.snippet)}</p>
                    {/if}

                    <!-- Reply options -->
                    {#if email.reply_options && email.reply_options.length > 0}
                      <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
                      <div class="flex flex-wrap gap-1.5">
                        {#each email.reply_options as option}
                          <button
                            onclick={(event) => { event.stopPropagation(); openReplyView(email, idx, option); }}
                            class="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-medium border transition-fast cursor-pointer {intentColors[option.intent] || intentColors.custom}"
                            title={option.body}
                          >
                            {option.label}
                          </button>
                        {/each}
                      </div>
                    {:else if email.suggested_reply}
                      <div class="mt-1 p-2 rounded-md text-[10px]" style="background: var(--bg-tertiary); color: var(--text-secondary)">
                        <span class="font-semibold" style="color: var(--color-accent-600)">Suggested:</span> {email.suggested_reply}
                      </div>
                    {/if}
                  </div>

                  <!-- Quick actions -->
                  <div class="shrink-0 flex flex-col gap-1">
                    <button
                      onclick={(event) => { event.stopPropagation(); ignoreEmailFromList(email.id); }}
                      class="flex items-center justify-center w-7 h-7 rounded-lg text-[10px] font-medium transition-fast hover-bg-subtle border"
                      style="border-color: var(--border-color); color: var(--text-tertiary)"
                      title="Ignore"
                    >
                      <Icon name="eye-off" size={12} />
                    </button>
                    <div class="relative">
                      <button
                        onclick={(event) => { event.stopPropagation(); openSnoozePopover(email.id); }}
                        class="flex items-center justify-center w-7 h-7 rounded-lg text-[10px] font-medium transition-fast hover-bg-subtle border"
                        style="border-color: var(--border-color); color: var(--text-tertiary)"
                        title="Snooze"
                      >
                        <Icon name="clock" size={12} />
                      </button>
                      {#if snoozePopoverEmailId === email.id}
                        <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
                        <div
                          class="absolute top-0 right-full mr-1 py-1 rounded-lg border shadow-lg z-50 min-w-[160px]"
                          style="background: var(--bg-secondary); border-color: var(--border-color)"
                        >
                          {#each [
                            { key: '1h', label: '1 hour' },
                            { key: '3h', label: '3 hours' },
                            { key: 'tomorrow', label: 'Tomorrow morning' },
                            { key: 'next_week', label: 'Next week' },
                          ] as option}
                            <button
                              onclick={(event) => { event.stopPropagation(); snoozeEmail(email.id, option.key, false); }}
                              class="w-full text-left px-3 py-1.5 text-xs transition-fast hover-bg-subtle"
                              style="color: var(--text-primary)"
                            >
                              {option.label}
                            </button>
                          {/each}
                        </div>
                      {/if}
                    </div>
                    <button
                      onclick={(event) => { event.stopPropagation(); goToEmail(email.id); }}
                      class="flex items-center justify-center w-7 h-7 rounded-lg text-[10px] font-medium transition-fast hover-bg-subtle border"
                      style="border-color: var(--border-color); color: var(--text-tertiary)"
                      title="Open in inbox"
                    >
                      <Icon name="external-link" size={12} />
                    </button>
                  </div>
                </div>
              </div>
            {/each}
          </div>
        {:else}
          <div class="flex flex-col items-center justify-center py-10">
            <span style="color: var(--text-tertiary); opacity: 0.3"><Icon name="check" size={32} /></span>
            <p class="text-sm mt-2" style="color: var(--text-tertiary)">All caught up!</p>
          </div>
        {/if}
      </div>

      <!-- ============ BOTTOM ROW: Waiting + Active Threads ============ -->
      <div class="flex flex-col lg:flex-row" bind:this={bottomColContainerEl} style="{isDraggingBottomCol ? 'user-select: none; cursor: col-resize' : ''}">
        <!-- Waiting For Response -->
        <div class="min-w-0 rounded-xl border p-4" style="background: var(--bg-secondary); border-color: var(--border-color); flex: 0 0 {bottomLeftPercent}%">
          <div class="flex items-center justify-between mb-3">
            <div class="flex items-center gap-2">
              <span style="color: var(--status-warning)"><Icon name="clock" size={14} /></span>
              <h3 class="text-sm font-semibold" style="color: var(--text-primary)">Waiting On Other Party</h3>
            </div>
            {#if awaitingResponseTotal > 0}
              <span class="text-[10px] px-2 py-0.5 rounded-full font-medium" style="background: var(--status-warning-bg); color: var(--status-warning)">{awaitingResponseTotal}</span>
            {/if}
          </div>
          {#if awaitingResponse.length > 0}
            <div class="space-y-2">
              {#each awaitingResponse as email, awIdx}
                <!-- svelte-ignore a11y_click_events_have_key_events -->
                <!-- svelte-ignore a11y_no_static_element_interactions -->
                <div
                  class="p-2.5 rounded-lg cursor-pointer transition-fast hover-bg-subtle"
                  style="background: var(--bg-primary); {focusedSection === 'awaiting' && highlightedIndex === awIdx ? 'outline: 2px solid var(--color-accent-500); outline-offset: -2px; background: var(--bg-tertiary)' : ''}"
                  data-flow-item="awaiting-{awIdx}"
                  onclick={() => openThreadInFlow(email.gmail_thread_id, { subject: email.subject, from_name: email.to_name, date: email.date, id: email.id, snippet: email.snippet, account_id: email.account_id, account_email: email.account_email }, 'awaiting')}
                >
                  <div class="text-xs font-medium truncate" style="color: var(--text-primary)">{email.subject || '(no subject)'}</div>
                  <div class="flex items-center gap-2 mt-0.5">
                    <span class="text-[10px]" style="color: var(--text-secondary)">
                      To: {email.to_name || 'recipient'}
                    </span>
                    <span class="text-[10px]" style="color: var(--text-tertiary)">{formatRelativeDate(email.date)}</span>
                  </div>
                  {#if email.snippet}
                    <p class="text-[10px] mt-1 line-clamp-1" style="color: var(--text-tertiary)">{email.snippet}</p>
                  {/if}
                </div>
              {/each}
            </div>
          {:else}
            <div class="flex flex-col items-center justify-center py-6">
              <span style="color: var(--text-tertiary); opacity: 0.3"><Icon name="check-circle" size={24} /></span>
              <p class="text-xs mt-2" style="color: var(--text-tertiary)">No emails waiting on others</p>
            </div>
          {/if}
        </div>

        <!-- Bottom Column Resize Handle (hidden on mobile, visible on lg+) -->
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div
          class="hidden lg:flex shrink-0 items-center justify-center cursor-col-resize col-resize-handle"
          style="width: 11px"
          onmousedown={startBottomColDrag}
        >
          <div
            class="h-10 w-1 rounded-full transition-fast"
            style="background: {isDraggingBottomCol ? 'var(--color-accent-500)' : 'var(--border-color)'}"
          ></div>
        </div>

        <!-- Active Threads -->
        <div class="min-w-0 rounded-xl border p-4 mt-4 lg:mt-0" style="background: var(--bg-secondary); border-color: var(--border-color); flex: 1 1 0%">
          <div class="flex items-center gap-2 mb-3">
            <span style="color: #8b5cf6"><Icon name="message-circle" size={14} /></span>
            <h3 class="text-sm font-semibold" style="color: var(--text-primary)">Active Threads</h3>
          </div>
          {#if activeThreads.length > 0}
            <div class="space-y-2">
              {#each activeThreads as thread, thIdx}
                <!-- svelte-ignore a11y_click_events_have_key_events -->
                <!-- svelte-ignore a11y_no_static_element_interactions -->
                <div
                  class="p-2.5 rounded-lg cursor-pointer transition-fast hover-bg-subtle"
                  style="background: var(--bg-primary); {focusedSection === 'threads' && highlightedIndex === thIdx ? 'outline: 2px solid var(--color-accent-500); outline-offset: -2px; background: var(--bg-tertiary)' : ''}"
                  data-flow-item="threads-{thIdx}"
                  onclick={() => openThreadInFlow(thread.thread_id, { subject: thread.subject, summary: thread.summary, date: thread.latest_date, account_id: thread.account_id }, 'thread')}
                >
                  <div class="flex items-center gap-2 mb-0.5">
                    {#if thread.conversation_type}
                      {@const typeColor = conversationTypeColors[thread.conversation_type] || conversationTypeColors.discussion}
                      <span class="text-[9px] px-1.5 py-0.5 rounded-full font-medium shrink-0 {typeColor.bg} {typeColor.text}">
                        {thread.conversation_type}
                      </span>
                    {/if}
                    <span class="text-xs font-medium truncate" style="color: var(--text-primary)">{thread.subject || '(no subject)'}</span>
                  </div>
                  <div class="flex items-center gap-3 text-[10px]" style="color: var(--text-tertiary)">
                    {#if thread.message_count}
                      <span>{thread.message_count} messages</span>
                    {/if}
                    {#if thread.participants}
                      <span>{thread.participants.length || thread.participants} people</span>
                    {/if}
                    {#if thread.latest_date}
                      <span>{formatRelativeDate(thread.latest_date)}</span>
                    {/if}
                  </div>
                  {#if thread.summary}
                    <p class="text-[10px] mt-1 line-clamp-2" style="color: var(--text-secondary)">{thread.summary}</p>
                  {/if}
                </div>
              {/each}
            </div>
          {:else}
            <div class="flex flex-col items-center justify-center py-6">
              <span style="color: var(--text-tertiary); opacity: 0.3"><Icon name="message-circle" size={24} /></span>
              <p class="text-xs mt-2" style="color: var(--text-tertiary)">No active threads</p>
            </div>
          {/if}
        </div>
      </div>

    </div>
  </div>
  {/if}

</div>

<style>
  /* Markdown content styling */
  :global(.chat-markdown h1) {
    font-size: 1rem;
    font-weight: 700;
    margin-top: 0.75rem;
    margin-bottom: 0.25rem;
    color: var(--text-primary);
  }
  :global(.chat-markdown h2) {
    font-size: 0.9rem;
    font-weight: 600;
    margin-top: 0.5rem;
    margin-bottom: 0.25rem;
    color: var(--text-primary);
  }
  :global(.chat-markdown h3) {
    font-size: 0.85rem;
    font-weight: 600;
    margin-top: 0.5rem;
    margin-bottom: 0.25rem;
    color: var(--text-primary);
  }
  :global(.chat-markdown p) {
    margin-bottom: 0.4rem;
    line-height: 1.5;
    font-size: 0.75rem;
  }
  :global(.chat-markdown ul),
  :global(.chat-markdown ol) {
    margin-bottom: 0.4rem;
    padding-left: 1.25rem;
    font-size: 0.75rem;
  }
  :global(.chat-markdown li) {
    margin-bottom: 0.15rem;
  }
  :global(.chat-markdown table) {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 0.5rem;
    font-size: 0.7rem;
  }
  :global(.chat-markdown th) {
    text-align: left;
    padding: 0.375rem;
    border-bottom: 2px solid var(--border-color);
    font-weight: 600;
    color: var(--text-primary);
  }
  :global(.chat-markdown td) {
    padding: 0.375rem;
    border-bottom: 1px solid var(--border-color);
    color: var(--text-secondary);
  }
  :global(.chat-markdown img) {
    max-width: 100%;
    height: auto;
    max-height: 200px;
    border-radius: 0.375rem;
    margin: 0.375rem 0;
    object-fit: contain;
  }
  :global(.chat-markdown code) {
    font-size: 0.7rem;
    padding: 0.1rem 0.3rem;
    border-radius: 0.2rem;
    background: var(--bg-secondary);
    color: var(--color-accent-600);
  }
  :global(.chat-markdown pre) {
    margin-bottom: 0.5rem;
    padding: 0.5rem;
    border-radius: 0.375rem;
    background: var(--bg-secondary);
    overflow-x: auto;
  }
  :global(.chat-markdown pre code) {
    padding: 0;
    background: transparent;
  }
  :global(.chat-markdown a) {
    color: var(--color-accent-600);
    text-decoration: underline;
  }
  :global(.chat-markdown blockquote) {
    border-left: 3px solid var(--border-color);
    padding-left: 0.5rem;
    margin: 0.375rem 0;
    color: var(--text-secondary);
    font-style: italic;
  }
  :global(.chat-markdown hr) {
    border: none;
    border-top: 1px solid var(--border-color);
    margin: 0.5rem 0;
  }

  .line-clamp-1 {
    display: -webkit-box;
    -webkit-line-clamp: 1;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .line-clamp-2 {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .line-clamp-3 {
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .hover-bg-subtle:hover {
    background: var(--bg-hover);
  }

  /* Horizontal divider hover state via group */
  .group:hover > div {
    background: var(--text-tertiary) !important;
  }

  /* Vertical column resize handle hover state */
  .col-resize-handle:hover > div {
    background: var(--text-tertiary) !important;
  }


  .last-child-no-border:last-child {
    border-bottom: none;
  }

  @media (max-width: 767px) {
    .chat-pane {
      position: absolute;
      inset: 0;
      z-index: 30;
      width: 100% !important;
      border-right: 0;
      box-shadow: 0 12px 32px rgba(0, 0, 0, 0.24);
    }
    .chat-pane.chat-collapsed {
      inset: 0.5rem auto auto 0.5rem;
      width: 44px !important;
      height: 44px;
      border: 1px solid var(--border-color);
      border-radius: 0.75rem;
      overflow: hidden;
      box-shadow: 0 4px 14px rgba(0, 0, 0, 0.14);
    }
    .flow-shell.reply-view-open .chat-pane {
      display: none;
    }
    .flow-reply-actions {
      flex-direction: column;
      align-items: stretch;
      gap: 0.5rem;
      padding: 0.5rem;
    }
    .flow-send-actions {
      order: -1;
      width: 100%;
    }
    .flow-send-actions > button {
      min-height: 2.75rem;
      flex: 1 1 0;
      justify-content: center;
    }
    .flow-triage-actions {
      width: 100%;
      flex-wrap: wrap;
      justify-content: center;
      gap: 0.25rem;
    }
    .flow-triage-actions label {
      min-height: 2.75rem;
      white-space: nowrap;
    }
    .flow-triage-actions button {
      min-height: 2.75rem;
    }
    .flow-triage-actions .triage-separator {
      display: none;
    }
    .col-resize-handle {
      display: none !important;
    }
    .flow-dashboard {
      padding: 4rem 0.75rem 1rem;
    }
    .flow-main {
      width: 100%;
    }
  }

</style>
