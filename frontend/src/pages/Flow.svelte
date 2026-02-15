<script>
  import { onMount } from 'svelte';
  import { marked } from 'marked';
  import { api } from '../lib/api.js';
  import { chatConversations, currentConversationId, showToast, currentPage, currentMailbox, selectedEmailId, pendingReplyDraft, accounts, composeData } from '../lib/stores.js';
  import { get } from 'svelte/store';
  import Icon from '../components/common/Icon.svelte';
  import RichEditor from '../components/email/RichEditor.svelte';

  // --- Day Summary State ---
  let summaryLoading = $state(true);
  let upcomingEvents = $state([]);
  let pendingTodos = $state([]);
  let needsReplyEmails = $state([]);
  let needsReplyTotal = $state(0);
  let urgentCount = $state(0);
  let trendsSummary = $state('');

  // --- New sections state ---
  let awaitingResponse = $state([]);
  let awaitingResponseTotal = $state(0);
  let activeThreads = $state([]);

  // --- Chat State ---
  let chatCollapsed = $state(localStorage.getItem('flowChatCollapsed') === 'true');
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
  let chatHistoryOpen = $state(false);
  let expandedTasks = $state({});

  // --- Reply View State ---
  let replyViewOpen = $state(false);
  let activeReplyIndex = $state(0);
  let selectedReplyEmail = $state(null);
  let threadData = $state(null);
  let threadLoading = $state(false);
  let replyBodyHtml = $state('');
  let inlineReplySending = $state(false);
  let replyIntent = $state(null);
  let collapsedMessages = $state({});
  let archiveAfterSend = $state(true);
  let initialReplyContent = $state('');
  let selectedOptionIndex = $state(-1);
  let editorKey = $state(0);

  let hasReplyContent = $derived(replyBodyHtml && replyBodyHtml.replace(/<[^>]*>/g, '').trim().length > 0);

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

  // Configure marked
  marked.setOptions({ breaks: true, gfm: true });

  // Persist chat collapsed state
  $effect(() => {
    localStorage.setItem('flowChatCollapsed', String(chatCollapsed));
  });

  onMount(async () => {
    await Promise.all([
      loadDaySummary(),
      loadConversations(),
      loadAwaitingResponse(),
      loadActiveThreads(),
    ]);
  });

  // ============ Day Summary ============

  async function loadDaySummary() {
    summaryLoading = true;
    const results = await Promise.allSettled([
      api.getUpcomingEvents(1),
      api.getTodos({ status: 'pending' }),
      api.getNeedsReply({ limit: 20 }),
      api.getAITrends(),
    ]);

    if (results[0].status === 'fulfilled') {
      upcomingEvents = (results[0].value.events || []).slice(0, 5);
    }
    if (results[1].status === 'fulfilled') {
      pendingTodos = (results[1].value.todos || results[1].value || []).slice(0, 10);
    }
    if (results[2].status === 'fulfilled') {
      needsReplyEmails = results[2].value.emails || [];
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
      awaitingResponse = data.emails || [];
      awaitingResponseTotal = data.total || 0;
    } catch {
      // ignore
    }
  }

  async function loadActiveThreads() {
    try {
      const data = await api.getThreadDigests({ page_size: 8, sort: 'recent' });
      activeThreads = (data.digests || []).slice(0, 6);
    } catch {
      // ignore
    }
  }

  // ============ Chat Logic ============

  async function loadConversations() {
    try {
      const data = await api.getConversations();
      conversations = data;
      chatConversations.set(data);
    } catch {
      // ignore
    }
  }

  async function loadConversation(id) {
    loadingConversation = true;
    activeConversationId = id;
    currentConversationId.set(id);
    chatHistoryOpen = false;
    resetChatState();

    try {
      const data = await api.getConversation(id);
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
          renderedContent = marked.parse(lastAssistant.content);
        }
        currentPhase = 'done';
      }
    } catch (err) {
      showToast(err.message, 'error');
    }
    loadingConversation = false;
  }

  async function deleteConversation(id) {
    try {
      await api.deleteConversation(id);
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
      showToast(err.message, 'error');
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
    chatHistoryOpen = false;
  }

  async function sendMessage() {
    const msg = messageInput.trim();
    if (!msg || isProcessing) return;

    messageInput = '';
    isProcessing = true;
    resetChatState();

    conversationMessages = [...conversationMessages, { role: 'user', content: msg }];

    try {
      const response = await api.chatStream(msg, activeConversationId);

      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: 'Request failed' }));
        throw new Error(err.detail || `HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
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
      errorMessage = err.message;
      showToast(err.message, 'error');
    }

    isProcessing = false;
    await loadConversations();
  }

  function handleSSEEvent(eventType, data) {
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
      renderedContent = marked.parse(finalContent);
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
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
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
    currentMailbox.set('ALL');
    currentPage.set('inbox');
    setTimeout(() => {
      selectedEmailId.set(emailId);
    }, 0);
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
    urgent: { bg: 'bg-red-100 dark:bg-red-900/40', text: 'text-red-700 dark:text-red-400' },
    can_ignore: { bg: 'bg-gray-100 dark:bg-gray-800', text: 'text-gray-600 dark:text-gray-400' },
    fyi: { bg: 'bg-emerald-100 dark:bg-emerald-900/40', text: 'text-emerald-700 dark:text-emerald-400' },
    awaiting_reply: { bg: 'bg-amber-100 dark:bg-amber-900/40', text: 'text-amber-700 dark:text-amber-400' },
  };

  function categoryLabel(cat) {
    if (!cat) return 'Unknown';
    return cat.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  const intentColors = {
    accept: 'bg-emerald-50 dark:bg-emerald-900/30 border-emerald-200 dark:border-emerald-800 text-emerald-700 dark:text-emerald-400',
    decline: 'bg-red-50 dark:bg-red-900/30 border-red-200 dark:border-red-800 text-red-700 dark:text-red-400',
    defer: 'bg-amber-50 dark:bg-amber-900/30 border-amber-200 dark:border-amber-800 text-amber-700 dark:text-amber-400',
    not_relevant: 'bg-gray-50 dark:bg-gray-800/50 border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400',
    custom: 'bg-blue-50 dark:bg-blue-900/30 border-blue-200 dark:border-blue-800 text-blue-700 dark:text-blue-400',
  };

  const intentCardStyles = {
    accept: {
      bg: 'bg-emerald-50 dark:bg-emerald-900/30',
      border: 'border-emerald-200 dark:border-emerald-800',
      text: 'text-emerald-700 dark:text-emerald-400',
    },
    decline: {
      bg: 'bg-red-50 dark:bg-red-900/30',
      border: 'border-red-200 dark:border-red-800',
      text: 'text-red-700 dark:text-red-400',
    },
    defer: {
      bg: 'bg-amber-50 dark:bg-amber-900/30',
      border: 'border-amber-200 dark:border-amber-800',
      text: 'text-amber-700 dark:text-amber-400',
    },
    not_relevant: {
      bg: 'bg-gray-50 dark:bg-gray-800/50',
      border: 'border-gray-200 dark:border-gray-700',
      text: 'text-gray-600 dark:text-gray-400',
    },
    custom: {
      bg: 'bg-blue-50 dark:bg-blue-900/30',
      border: 'border-blue-200 dark:border-blue-800',
      text: 'text-blue-700 dark:text-blue-400',
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
    scheduling: { bg: 'bg-purple-100 dark:bg-purple-900/40', text: 'text-purple-700 dark:text-purple-400' },
    discussion: { bg: 'bg-blue-100 dark:bg-blue-900/40', text: 'text-blue-700 dark:text-blue-400' },
    notification: { bg: 'bg-gray-100 dark:bg-gray-800', text: 'text-gray-600 dark:text-gray-400' },
    transactional: { bg: 'bg-amber-100 dark:bg-amber-900/40', text: 'text-amber-700 dark:text-amber-400' },
  };

  // ============ Reply View Logic ============

  async function openReplyView(email, index, option) {
    selectedReplyEmail = email;
    activeReplyIndex = index;
    replyViewOpen = true;
    threadLoading = true;
    threadData = null;
    replyBodyHtml = '';
    replyIntent = null;
    collapsedMessages = {};
    selectedOptionIndex = -1;

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
    }
    editorKey++;

    if (email.gmail_thread_id) {
      try {
        const data = await api.getThread(email.gmail_thread_id);
        threadData = data;
        if (data.emails && data.emails.length > 1) {
          let collapsed = {};
          for (let i = 0; i < data.emails.length - 1; i++) {
            collapsed[data.emails[i].id] = true;
          }
          collapsedMessages = collapsed;
        }
      } catch (err) {
        showToast('Failed to load thread: ' + err.message, 'error');
      }
    }
    threadLoading = false;
  }

  function closeReplyView() {
    replyViewOpen = false;
    selectedReplyEmail = null;
    threadData = null;
    replyBodyHtml = '';
    replyIntent = null;
    collapsedMessages = {};
    selectedOptionIndex = -1;
    initialReplyContent = '';
  }

  function selectReplyOption(option, optIdx) {
    initialReplyContent = '<p>' + (option.body || '').replace(/\n/g, '</p><p>') + '</p>';
    replyBodyHtml = initialReplyContent;
    replyIntent = option.intent || null;
    selectedOptionIndex = optIdx;
    editorKey++;
  }

  function clearReplyOption() {
    initialReplyContent = '';
    replyBodyHtml = '';
    replyIntent = null;
    selectedOptionIndex = -1;
    editorKey++;
  }

  function toggleMessageCollapse(msgId) {
    collapsedMessages = { ...collapsedMessages, [msgId]: !collapsedMessages[msgId] };
  }

  function handleEditorUpdate(html) {
    replyBodyHtml = html;
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
    if (!selectedReplyEmail) return;
    try {
      await api.emailActions([selectedReplyEmail.id], 'archive');
      showToast('Email archived', 'success');
      removeCurrentAndAdvance();
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function trashCurrentEmail() {
    if (!selectedReplyEmail) return;
    try {
      await api.emailActions([selectedReplyEmail.id], 'trash');
      showToast('Moved to trash', 'success');
      removeCurrentAndAdvance();
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  function removeCurrentAndAdvance() {
    const removedId = selectedReplyEmail.id;
    needsReplyEmails = needsReplyEmails.filter(e => e.id !== removedId);
    if (needsReplyTotal > 0) needsReplyTotal -= 1;

    if (needsReplyEmails.length === 0) {
      closeReplyView();
      return;
    }

    const newIdx = Math.min(activeReplyIndex, needsReplyEmails.length - 1);
    openReplyView(needsReplyEmails[newIdx], newIdx);
  }

  function openInCompose() {
    if (!selectedReplyEmail) return;
    const email = selectedReplyEmail;
    const subject = email.subject && email.subject.startsWith('Re:') ? email.subject : 'Re: ' + (email.subject || '');

    let messageIdHeader = null;
    if (threadData && threadData.emails && threadData.emails.length > 0) {
      const lastMsg = threadData.emails[threadData.emails.length - 1];
      messageIdHeader = lastMsg.message_id_header;
    }

    composeData.set({
      to: [email.from_address],
      subject: subject,
      body_html: replyBodyHtml || '',
      in_reply_to: messageIdHeader || null,
      thread_id: email.gmail_thread_id || null,
    });
    currentPage.set('compose');
  }

  async function sendReply() {
    if (!selectedReplyEmail) return;
    const plainText = replyBodyHtml ? replyBodyHtml.replace(/<[^>]*>/g, '').trim() : '';
    if (!plainText) return;

    inlineReplySending = true;
    try {
      const accountList = get(accounts);
      let accountId = null;
      if (accountList.length === 1) {
        accountId = accountList[0].id;
      } else if (accountList.length > 1 && selectedReplyEmail.account_email) {
        const matched = accountList.find(a => a.email === selectedReplyEmail.account_email);
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

      const email = selectedReplyEmail;
      const subject = email.subject && email.subject.startsWith('Re:') ? email.subject : 'Re: ' + (email.subject || '');

      let messageIdHeader = null;
      if (threadData && threadData.emails && threadData.emails.length > 0) {
        const lastMsg = threadData.emails[threadData.emails.length - 1];
        messageIdHeader = lastMsg.message_id_header;
      }

      await api.sendEmail({
        account_id: accountId,
        to: [email.from_address],
        cc: [],
        bcc: [],
        subject: subject,
        body_text: plainText,
        body_html: replyBodyHtml,
        in_reply_to: messageIdHeader || null,
        references: messageIdHeader || null,
        thread_id: email.gmail_thread_id || null,
      });
      showToast('Reply sent!', 'success');

      // Archive if toggled
      if (archiveAfterSend) {
        try {
          await api.emailActions([email.id], 'archive');
        } catch {
          // silent fail on archive
        }
      }

      removeCurrentAndAdvance();
    } catch (err) {
      showToast(err.message, 'error');
    }
    inlineReplySending = false;
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
</script>

<div class="h-full flex" style="background: var(--bg-primary)">

  <!-- ============ LEFT SIDEBAR: CHAT ============ -->
  <div
    class="h-full shrink-0 flex flex-col border-r transition-all duration-300"
    style="border-color: var(--border-color); background: var(--bg-secondary); width: {chatCollapsed ? '48px' : '340px'}"
  >
    {#if chatCollapsed}
      <!-- Collapsed: just an icon button -->
      <div class="flex flex-col items-center pt-3 gap-2">
        <button
          onclick={() => { chatCollapsed = false; }}
          class="w-9 h-9 rounded-lg flex items-center justify-center transition-fast"
          style="background: var(--color-accent-500)/10; color: var(--color-accent-500)"
          title="Open chat"
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
          <div class="relative">
            <button
              onclick={() => { chatHistoryOpen = !chatHistoryOpen; }}
              class="p-1 rounded-md transition-fast"
              style="color: var(--text-tertiary)"
              title="History"
            >
              <Icon name="clock" size={14} />
              {#if conversations.length > 0}
                <span class="absolute -top-0.5 -right-0.5 w-3 h-3 rounded-full text-[8px] font-bold flex items-center justify-center" style="background: var(--color-accent-500); color: white">{conversations.length > 9 ? '9+' : conversations.length}</span>
              {/if}
            </button>

            {#if chatHistoryOpen}
              <!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
              <div class="fixed inset-0 z-40" onclick={() => { chatHistoryOpen = false; }}></div>
              <div
                class="absolute left-0 top-full mt-1 z-50 w-72 max-h-80 rounded-lg border shadow-lg overflow-hidden"
                style="background: var(--bg-secondary); border-color: var(--border-color)"
              >
                <div class="px-3 py-2 border-b flex items-center justify-between" style="border-color: var(--border-color)">
                  <span class="text-[10px] font-semibold uppercase tracking-wider" style="color: var(--text-tertiary)">Conversations</span>
                  <button
                    onclick={startNewChat}
                    class="text-[10px] px-2 py-0.5 rounded font-medium transition-fast"
                    style="background: var(--color-accent-500); color: white"
                  >New Chat</button>
                </div>
                <div class="overflow-y-auto max-h-64">
                  {#if conversations.length === 0}
                    <div class="p-4 text-center text-xs" style="color: var(--text-tertiary)">No conversations yet</div>
                  {:else}
                    {#each conversations as conv}
                      <div
                        role="button"
                        tabindex="0"
                        onclick={() => loadConversation(conv.id)}
                        onkeydown={(e) => { if (e.key === 'Enter') loadConversation(conv.id); }}
                        class="px-3 py-2 border-b transition-fast group relative cursor-pointer"
                        style="border-color: var(--border-color); background: {activeConversationId === conv.id ? 'var(--bg-hover)' : 'transparent'}"
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
                  {/if}
                </div>
              </div>
            {/if}
          </div>
          <button
            onclick={() => { chatCollapsed = true; }}
            class="p-1 rounded-md transition-fast"
            style="color: var(--text-tertiary)"
            title="Collapse chat"
          >
            <Icon name="chevrons-left" size={14} />
          </button>
        </div>
      </div>

      <!-- Active conversation label -->
      {#if activeConversationId}
        <div class="px-3 py-1.5 border-b" style="border-color: var(--border-color)">
          <span class="text-[10px] px-2 py-0.5 rounded-full" style="background: var(--bg-tertiary); color: var(--text-tertiary)">
            {conversations.find(c => c.id === activeConversationId)?.title || 'Conversation'}
          </span>
        </div>
      {/if}

      <!-- Chat Messages -->
      <div bind:this={messagesContainer} class="flex-1 overflow-y-auto p-3 space-y-3">
        {#if conversationMessages.length === 0 && !isProcessing}
          <!-- Empty state -->
          <div class="flex flex-col items-center justify-center py-6 text-center px-2">
            <div class="w-10 h-10 rounded-xl flex items-center justify-center mb-2" style="background: var(--color-accent-500)/10; color: var(--color-accent-500)">
              <Icon name="zap" size={20} />
            </div>
            <h3 class="text-xs font-semibold mb-1" style="color: var(--text-primary)">Ask about your emails</h3>
            <p class="text-[10px] mb-3" style="color: var(--text-secondary)">
              Search, summarize, and get insights.
            </p>
            <div class="flex flex-col gap-1.5 w-full">
              {#each [
                'Summarize my unread emails',
                'What needs my attention?',
                'Find recent receipts',
              ] as suggestion}
                <button
                  onclick={() => { messageInput = suggestion; }}
                  class="px-2.5 py-1.5 rounded-lg text-[10px] border transition-fast text-left"
                  style="border-color: var(--border-color); color: var(--text-secondary); background: var(--bg-primary)"
                >
                  {suggestion}
                </button>
              {/each}
            </div>
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
                            <div class="w-3 h-3 rounded-full flex items-center justify-center" style="background: #22c55e">
                              <svg class="w-2 h-2 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M4.5 12.75l6 6 9-13.5" />
                              </svg>
                            </div>
                          {:else if status.status === 'failed'}
                            <div class="w-3 h-3 rounded-full flex items-center justify-center" style="background: #ef4444">
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
                <div class="rounded-lg border p-3 text-xs" style="border-color: #ef4444/30; background: #ef4444/5; color: #ef4444">
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
        <div class="flex items-center gap-2 shrink-0">
          <span class="text-[11px] font-medium tabular-nums" style="color: var(--text-tertiary)">{activeReplyIndex + 1} of {needsReplyEmails.length}</span>
          <div class="flex items-center gap-0.5">
            <button
              onclick={goToPrevReply}
              disabled={activeReplyIndex <= 0}
              class="p-1 rounded-md transition-fast"
              style="color: {activeReplyIndex <= 0 ? 'var(--border-color)' : 'var(--text-secondary)'}"
              title="Previous email"
            >
              <Icon name="chevron-left" size={16} />
            </button>
            <button
              onclick={goToNextReply}
              disabled={activeReplyIndex >= needsReplyEmails.length - 1}
              class="p-1 rounded-md transition-fast"
              style="color: {activeReplyIndex >= needsReplyEmails.length - 1 ? 'var(--border-color)' : 'var(--text-secondary)'}"
              title="Next email"
            >
              <Icon name="chevron-right" size={16} />
            </button>
          </div>
        </div>
      </div>

      <!-- Top/Bottom Resizable Layout -->
      <div class="flex-1 flex flex-col min-h-0" bind:this={replyContainerEl} style="{isDraggingDivider ? 'user-select: none; cursor: row-resize' : ''}">
        <!-- TOP PANE: Thread Context -->
        <div class="flex flex-col overflow-hidden" style="height: {topPanePercent}%">
          <!-- Email Header -->
          <div class="px-5 py-2.5 border-b shrink-0" style="border-color: var(--border-color)">
            <div class="flex items-center gap-2 mb-0.5">
              {#if selectedReplyEmail.category}
                <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 {categoryColors[selectedReplyEmail.category]?.bg || ''} {categoryColors[selectedReplyEmail.category]?.text || ''}">
                  {categoryLabel(selectedReplyEmail.category)}
                </span>
              {/if}
              <h3 class="text-sm font-semibold" style="color: var(--text-primary)">{selectedReplyEmail.subject || '(no subject)'}</h3>
            </div>
            <div class="flex items-center gap-2 text-xs" style="color: var(--text-secondary)">
              <span class="font-medium">{selectedReplyEmail.from_name || selectedReplyEmail.from_address}</span>
              <span style="color: var(--text-tertiary)">{formatRelativeDate(selectedReplyEmail.date)}</span>
            </div>
          </div>

          <!-- AI Summary -->
          {#if selectedReplyEmail.summary}
            <div class="px-5 py-2.5 border-b shrink-0" style="border-color: var(--border-color); background: var(--bg-secondary)">
              <div class="flex items-center gap-1.5 mb-1">
                <span style="color: var(--color-accent-500)"><Icon name="zap" size={12} /></span>
                <span class="text-[10px] font-semibold uppercase tracking-wider" style="color: var(--color-accent-600)">AI Summary</span>
              </div>
              <p class="text-xs leading-relaxed" style="color: var(--text-secondary)">{selectedReplyEmail.summary}</p>
              {#if selectedReplyEmail.action_items && selectedReplyEmail.action_items.length > 0}
                <div class="flex flex-wrap gap-x-4 gap-y-0.5 mt-1.5">
                  {#each selectedReplyEmail.action_items as item}
                    <span class="text-[10px] flex items-center gap-1" style="color: var(--text-secondary)">
                      <span class="w-1 h-1 rounded-full shrink-0" style="background: var(--color-accent-500)"></span>
                      {item}
                    </span>
                  {/each}
                </div>
              {/if}
            </div>
          {/if}

          <!-- Thread Messages -->
          <div class="flex-1 overflow-y-auto px-5 py-3 space-y-2">
            {#if threadLoading}
              <div class="flex items-center justify-center py-10">
                <div class="w-5 h-5 border-2 rounded-full animate-spin" style="border-color: var(--border-color); border-top-color: var(--color-accent-500)"></div>
              </div>
            {:else if threadData && threadData.emails}
              {#each threadData.emails as msg, msgIdx}
                {@const isCollapsed = collapsedMessages[msg.id]}
                {@const isLast = msgIdx === threadData.emails.length - 1}
                <div class="rounded-lg border overflow-hidden" style="border-color: var(--border-color)">
                  <!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
                  <div
                    class="px-4 py-2 flex items-center gap-2 cursor-pointer transition-fast"
                    style="background: {isLast ? 'var(--bg-secondary)' : 'var(--bg-tertiary)'}"
                    onclick={() => toggleMessageCollapse(msg.id)}
                  >
                    <div class="flex-1 min-w-0">
                      <div class="flex items-center gap-2">
                        <span class="text-xs font-medium" style="color: var(--text-primary)">{msg.from_name || msg.from_address}</span>
                        {#if msg.is_sent}
                          <span class="text-[9px] px-1.5 py-0.5 rounded-full" style="background: var(--bg-tertiary); color: var(--text-tertiary)">You</span>
                        {/if}
                        <span class="text-[10px]" style="color: var(--text-tertiary)">{formatEmailDate(msg.date)}</span>
                      </div>
                      {#if isCollapsed && msg.body_text}
                        <div class="text-[10px] truncate mt-0.5" style="color: var(--text-tertiary)">{msg.body_text.slice(0, 120)}</div>
                      {/if}
                    </div>
                    <span style="color: var(--text-tertiary)"><Icon name={isCollapsed ? 'chevron-down' : 'chevron-up'} size={14} /></span>
                  </div>

                  {#if !isCollapsed}
                    <div class="px-4 py-3 text-sm thread-message-body" style="color: var(--text-primary); max-height: 300px; overflow-y: auto">
                      {#if msg.body_text}
                        <pre class="whitespace-pre-wrap font-sans text-xs" style="color: var(--text-secondary)">{msg.body_text}</pre>
                      {:else if msg.body_html}
                        <div class="text-xs" style="color: var(--text-secondary)">{stripHtml(msg.body_html)}</div>
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
          <!-- Reply Options as horizontal cards -->
          {#if selectedReplyEmail.reply_options && selectedReplyEmail.reply_options.length > 0}
            <div class="px-5 py-2.5 border-b shrink-0" style="border-color: var(--border-color)">
              <div class="flex items-center gap-1.5 mb-2">
                <span style="color: var(--color-accent-500)"><Icon name="zap" size={12} /></span>
                <span class="text-[10px] font-semibold uppercase tracking-wider" style="color: var(--color-accent-600)">AI Reply Options</span>
              </div>
              <div class="flex gap-2 overflow-x-auto pb-1">
                {#each selectedReplyEmail.reply_options as option, optIdx}
                  {@const isSelected = selectedOptionIndex === optIdx}
                  {@const intentStyle = intentCardStyles[option.intent] || intentCardStyles.custom}
                  <!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
                  <div
                    onclick={() => selectReplyOption(option, optIdx)}
                    class="rounded-lg border p-3 cursor-pointer transition-fast shrink-0 {intentStyle.bg} {intentStyle.border}"
                    style="width: 260px; {isSelected ? 'box-shadow: 0 0 0 2px var(--color-accent-500)' : 'opacity: 0.8'}"
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
                    <p class="text-[11px] leading-relaxed line-clamp-3 {intentStyle.text}" style="opacity: 0.75">{option.body}</p>
                  </div>
                {/each}
              </div>
            </div>
          {:else if selectedReplyEmail.suggested_reply}
            <div class="px-5 py-2.5 border-b shrink-0" style="border-color: var(--border-color); background: var(--bg-secondary)">
              <div class="flex items-center gap-1.5 mb-1">
                <span style="color: var(--color-accent-500)"><Icon name="zap" size={12} /></span>
                <span class="text-[10px] font-semibold uppercase tracking-wider" style="color: var(--color-accent-600)">Suggested Reply</span>
              </div>
              <p class="text-xs italic leading-relaxed mb-2" style="color: var(--text-secondary)">"{selectedReplyEmail.suggested_reply}"</p>
              <button
                onclick={() => { initialReplyContent = '<p>' + selectedReplyEmail.suggested_reply.replace(/\n/g, '</p><p>') + '</p>'; editorKey++; replyIntent = 'custom'; selectedOptionIndex = -1; }}
                class="text-[10px] font-medium px-2.5 py-1 rounded-md border transition-fast shrink-0"
                style="border-color: var(--border-color); color: var(--color-accent-600)"
              >
                Use this
              </button>
            </div>
          {/if}

          <!-- AI Suggestion Banner -->
          {#if replyIntent}
            <div class="px-5 py-1.5 border-b shrink-0 flex items-center justify-between" style="border-color: var(--border-color); background: color-mix(in srgb, var(--color-accent-500) 8%, transparent)">
              <div class="flex items-center gap-1.5">
                <svg class="w-3.5 h-3.5 shrink-0" style="color: var(--color-accent-500)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
                </svg>
                <span class="text-[11px] font-medium" style="color: var(--color-accent-600)">
                  AI-suggested {intentLabels[replyIntent] || 'reply'} -- edit as needed
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
          {/if}

          <!-- Rich Text Editor -->
          <div class="flex-1 min-h-0 flex flex-col overflow-hidden">
            {#key editorKey}
              <RichEditor
                content={initialReplyContent}
                onUpdate={handleEditorUpdate}
                placeholder="Write your reply..."
              />
            {/key}
          </div>

          <!-- Action Bar -->
          <div class="px-4 py-2.5 border-t shrink-0 flex items-center justify-between" style="border-color: var(--border-color); background: var(--bg-secondary)">
            <div class="flex items-center gap-2">
              <!-- Archive after send toggle -->
              <label class="flex items-center gap-1.5 cursor-pointer select-none">
                <input
                  type="checkbox"
                  bind:checked={archiveAfterSend}
                  class="w-3.5 h-3.5 rounded border accent-current"
                  style="accent-color: var(--color-accent-500)"
                />
                <span class="text-[10px] font-medium" style="color: var(--text-secondary)">Archive after send</span>
              </label>

              <div class="w-px h-4 mx-1" style="background: var(--border-color)"></div>

              <!-- Triage Actions -->
              <button
                onclick={skipEmail}
                class="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium transition-fast hover-bg-subtle"
                style="color: var(--text-secondary)"
                title="Skip to next email"
              >
                <Icon name="fast-forward" size={12} />
                Skip
              </button>
              <button
                onclick={archiveCurrentEmail}
                class="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium transition-fast hover-bg-subtle"
                style="color: var(--text-secondary)"
                title="Archive without replying"
              >
                <Icon name="archive" size={12} />
                Archive
              </button>
              <button
                onclick={trashCurrentEmail}
                class="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium transition-fast hover-bg-subtle"
                style="color: var(--text-secondary)"
                title="Move to trash"
              >
                <Icon name="trash-2" size={12} />
              </button>
            </div>

            <div class="flex items-center gap-2">
              <button
                onclick={openInCompose}
                class="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-fast border"
                style="border-color: var(--border-color); color: var(--text-secondary)"
              >
                <Icon name="external-link" size={12} />
                Full Compose
              </button>
              <button
                onclick={sendReply}
                disabled={inlineReplySending || !hasReplyContent}
                class="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-medium transition-fast"
                style="background: {inlineReplySending || !hasReplyContent ? 'var(--border-color)' : 'var(--color-accent-500)'}; color: white"
              >
                {#if inlineReplySending}
                  <div class="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
                  Sending...
                {:else}
                  <Icon name="send" size={12} />
                  Send Reply
                {/if}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  {:else}
  <div class="flex-1 h-full overflow-y-auto">
    <div class="max-w-5xl mx-auto px-4 py-5 space-y-5">

      <!-- ============ DAY SUMMARY STRIP ============ -->
      <div class="flex flex-wrap gap-3">
        <!-- Calendar Events Card -->
        <div class="flex-1 min-w-[200px] rounded-xl border p-4" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <div class="flex items-center gap-2 mb-2">
            <div class="w-7 h-7 rounded-lg flex items-center justify-center" style="background: rgba(139, 92, 246, 0.15)">
              <span style="color: #8b5cf6"><Icon name="calendar" size={16} /></span>
            </div>
            <div>
              <div class="text-lg font-bold leading-none" style="color: var(--text-primary)">{upcomingEvents.length}</div>
              <div class="text-[10px] font-medium uppercase tracking-wider" style="color: var(--text-tertiary)">Events Today</div>
            </div>
          </div>
          {#if upcomingEvents.length > 0}
            <div class="space-y-1.5">
              {#each upcomingEvents.slice(0, 3) as evt}
                <div class="flex items-start gap-2 text-xs" style="color: var(--text-secondary)">
                  <span class="font-medium shrink-0" style="color: var(--color-accent-600)">{formatEventTime(evt.start_time)}</span>
                  <div class="min-w-0">
                    <div class="truncate font-medium" style="color: var(--text-primary)">{evt.summary || 'Untitled event'}</div>
                    {#if evt.location}
                      <div class="text-[10px] truncate" style="color: var(--text-tertiary)">{evt.location}</div>
                    {/if}
                  </div>
                </div>
              {/each}
              {#if upcomingEvents.length > 3}
                <button
                  onclick={() => currentPage.set('calendar')}
                  class="text-[10px] font-medium transition-fast"
                  style="color: var(--color-accent-500)"
                >+{upcomingEvents.length - 3} more</button>
              {/if}
            </div>
          {:else}
            <div class="text-xs" style="color: var(--text-tertiary)">No events today</div>
          {/if}
        </div>

        <!-- Todos Card - only show if there are pending tasks -->
        {#if pendingTodos.length > 0}
          <div class="flex-1 min-w-[200px] rounded-xl border p-4" style="background: var(--bg-secondary); border-color: var(--border-color)">
            <div class="flex items-center gap-2 mb-2">
              <div class="w-7 h-7 rounded-lg flex items-center justify-center" style="background: rgba(245, 158, 11, 0.15)">
                <span style="color: #f59e0b"><Icon name="check-circle" size={16} /></span>
              </div>
              <div>
                <div class="text-lg font-bold leading-none" style="color: var(--text-primary)">{pendingTodos.length}</div>
                <div class="text-[10px] font-medium uppercase tracking-wider" style="color: var(--text-tertiary)">Pending Tasks</div>
              </div>
            </div>
            <div class="space-y-1">
              {#each pendingTodos.slice(0, 3) as todo}
                <div class="text-xs truncate" style="color: var(--text-secondary)">{todo.title || todo.description || 'Untitled task'}</div>
              {/each}
              {#if pendingTodos.length > 3}
                <div class="text-[10px]" style="color: var(--text-tertiary)">+{pendingTodos.length - 3} more</div>
              {/if}
            </div>
          </div>
        {/if}

        <!-- Needs Reply Summary Card -->
        <div class="flex-1 min-w-[200px] rounded-xl border p-4" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <div class="flex items-center gap-2 mb-2">
            <div class="w-7 h-7 rounded-lg flex items-center justify-center" style="background: rgba(59, 130, 246, 0.15)">
              <span style="color: #3b82f6"><Icon name="corner-up-left" size={16} /></span>
            </div>
            <div>
              <div class="text-lg font-bold leading-none" style="color: var(--text-primary)">{needsReplyTotal}</div>
              <div class="text-[10px] font-medium uppercase tracking-wider" style="color: var(--text-tertiary)">Need Reply</div>
            </div>
          </div>
          {#if needsReplyEmails.length > 0}
            <div class="space-y-1">
              {#each needsReplyEmails.slice(0, 3) as email}
                <div class="text-xs truncate" style="color: var(--text-secondary)">
                  <span class="font-medium" style="color: var(--text-primary)">{email.from_name || email.from_address}</span>
                </div>
              {/each}
            </div>
          {:else}
            <div class="text-xs" style="color: var(--text-tertiary)">All caught up</div>
          {/if}
        </div>

        <!-- Urgent / AI Summary Card -->
        <div class="flex-1 min-w-[200px] rounded-xl border p-4" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <div class="flex items-center gap-2 mb-2">
            <div class="w-7 h-7 rounded-lg flex items-center justify-center" style="background: rgba(239, 68, 68, 0.15)">
              <span style="color: #ef4444"><Icon name="alert-triangle" size={16} /></span>
            </div>
            <div>
              <div class="text-lg font-bold leading-none" style="color: var(--text-primary)">{urgentCount}</div>
              <div class="text-[10px] font-medium uppercase tracking-wider" style="color: var(--text-tertiary)">Urgent</div>
            </div>
          </div>
          {#if trendsSummary}
            <div class="text-xs line-clamp-3" style="color: var(--text-secondary)">{trendsSummary}</div>
          {:else}
            <div class="text-xs" style="color: var(--text-tertiary)">No urgent items</div>
          {/if}
        </div>
      </div>

      <!-- ============ NEEDS REPLY - CORE SECTION ============ -->
      <div class="rounded-xl border overflow-hidden" style="background: var(--bg-secondary); border-color: var(--border-color)">
        <div class="px-4 py-3 border-b flex items-center justify-between" style="border-color: var(--border-color)">
          <div class="flex items-center gap-2">
            <span style="color: var(--color-accent-500)"><Icon name="inbox" size={16} /></span>
            <h2 class="text-sm font-semibold" style="color: var(--text-primary)">Needs Reply</h2>
          </div>
          {#if needsReplyTotal > 0}
            <span class="text-[10px] px-2 py-0.5 rounded-full font-medium" style="background: rgba(239, 68, 68, 0.15); color: #ef4444">{needsReplyTotal} total</span>
          {/if}
        </div>

        {#if needsReplyEmails.length > 0}
          <div class="divide-y" style="border-color: var(--border-color)">
            {#each needsReplyEmails as email, idx}
              <div class="px-4 py-3 transition-fast hover-bg-subtle">
                <div class="flex items-start gap-3">
                  <div class="flex-1 min-w-0">
                    <!-- Top row: category + subject -->
                    <div class="flex items-center gap-2 mb-1">
                      {#if email.category}
                        <span class="text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 {categoryColors[email.category]?.bg || ''} {categoryColors[email.category]?.text || ''}">
                          {categoryLabel(email.category)}
                        </span>
                      {/if}
                      <span class="text-sm font-medium truncate" style="color: var(--text-primary)">{email.subject || '(no subject)'}</span>
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
                      <p class="text-xs mb-2 line-clamp-2" style="color: var(--text-tertiary)">{email.snippet}</p>
                    {/if}

                    <!-- Reply options -->
                    {#if email.reply_options && email.reply_options.length > 0}
                      <div class="flex flex-wrap gap-1.5">
                        {#each email.reply_options as option}
                          <button
                            onclick={() => openReplyView(email, idx, option)}
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

                  <!-- Action buttons -->
                  <div class="flex flex-col gap-1.5 shrink-0">
                    <button
                      onclick={() => openReplyView(email, idx)}
                      class="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-fast"
                      style="background: var(--color-accent-500); color: white"
                    >
                      <Icon name="corner-up-left" size={12} />
                      Reply
                    </button>
                    <button
                      onclick={() => goToEmail(email.id)}
                      class="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-fast border"
                      style="border-color: var(--border-color); color: var(--text-secondary)"
                    >
                      <Icon name="external-link" size={12} />
                      Open
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
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <!-- Waiting For Response -->
        <div class="rounded-xl border p-4" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <div class="flex items-center justify-between mb-3">
            <div class="flex items-center gap-2">
              <span style="color: #f59e0b"><Icon name="clock" size={14} /></span>
              <h3 class="text-sm font-semibold" style="color: var(--text-primary)">Waiting For Response</h3>
            </div>
            {#if awaitingResponseTotal > 0}
              <span class="text-[10px] px-2 py-0.5 rounded-full font-medium" style="background: rgba(245, 158, 11, 0.15); color: #f59e0b">{awaitingResponseTotal}</span>
            {/if}
          </div>
          {#if awaitingResponse.length > 0}
            <div class="space-y-2">
              {#each awaitingResponse as email}
                <!-- svelte-ignore a11y_click_events_have_key_events -->
                <!-- svelte-ignore a11y_no_static_element_interactions -->
                <div
                  class="p-2.5 rounded-lg cursor-pointer transition-fast"
                  style="background: var(--bg-primary)"
                  onclick={() => goToEmail(email.id)}
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
              <p class="text-xs mt-2" style="color: var(--text-tertiary)">No pending responses</p>
            </div>
          {/if}
        </div>

        <!-- Active Threads -->
        <div class="rounded-xl border p-4" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <div class="flex items-center gap-2 mb-3">
            <span style="color: #8b5cf6"><Icon name="message-circle" size={14} /></span>
            <h3 class="text-sm font-semibold" style="color: var(--text-primary)">Active Threads</h3>
          </div>
          {#if activeThreads.length > 0}
            <div class="space-y-2">
              {#each activeThreads as thread}
                <div class="p-2.5 rounded-lg" style="background: var(--bg-primary)">
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

  /* Divider hover state via group */
  .group:hover > div {
    background: var(--text-tertiary) !important;
  }

  .thread-message-body pre {
    font-family: inherit;
  }

  /* Divide-y with theme colors */
  .divide-y > * + * {
    border-top: 1px solid var(--border-color);
  }
</style>
