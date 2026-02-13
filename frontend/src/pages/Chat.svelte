<script>
  import { onMount } from 'svelte';
  import { marked } from 'marked';
  import { api } from '../lib/api.js';
  import { chatConversations, currentConversationId, showToast } from '../lib/stores.js';

  let messageInput = $state('');
  let isProcessing = $state(false);
  let conversations = $state([]);
  let currentPhase = $state(null); // 'plan' | 'execute' | 'verify' | 'clarification' | null
  let tasks = $state([]);
  let taskStatuses = $state({}); // { taskId: { status, summary, detail, error } }
  let finalContent = $state('');
  let renderedContent = $state('');
  let errorMessage = $state('');
  let clarificationQuestion = $state('');
  let activeConversationId = $state(null);
  let loadingConversation = $state(false);
  let conversationMessages = $state([]); // messages for the loaded conversation
  let messagesContainer = $state(null);
  let sidebarOpen = $state(true);

  // Configure marked for safe rendering
  marked.setOptions({
    breaks: true,
    gfm: true,
  });

  onMount(async () => {
    await loadConversations();
  });

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
    resetState();

    try {
      const data = await api.getConversation(id);
      conversationMessages = data.messages || [];

      // Find the last assistant message to display
      const lastAssistant = [...conversationMessages].reverse().find(m => m.role === 'assistant');
      if (lastAssistant) {
        if (lastAssistant.plan && lastAssistant.plan.tasks) {
          tasks = lastAssistant.plan.tasks;
          // Mark all tasks as completed for display
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
        resetState();
        activeConversationId = null;
        currentConversationId.set(null);
        conversationMessages = [];
      }
      showToast('Conversation deleted', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  function resetState() {
    currentPhase = null;
    tasks = [];
    taskStatuses = {};
    finalContent = '';
    renderedContent = '';
    errorMessage = '';
    clarificationQuestion = '';
  }

  function startNewChat() {
    resetState();
    activeConversationId = null;
    currentConversationId.set(null);
    conversationMessages = [];
    messageInput = '';
  }

  async function sendMessage() {
    const msg = messageInput.trim();
    if (!msg || isProcessing) return;

    messageInput = '';
    isProcessing = true;
    resetState();

    // Add user message to display
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

        // Parse SSE events from buffer
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
              // partial JSON, put back in buffer
            }
            eventType = '';
          } else if (line === '') {
            // Empty line = end of event, reset
            eventType = '';
          } else {
            // Incomplete line, put back in buffer
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
        [data.task_id]: {
          ...taskStatuses[data.task_id],
          status: 'in_progress',
          detail: '',
        },
      };
    } else if (eventType === 'task_progress') {
      taskStatuses = {
        ...taskStatuses,
        [data.task_id]: {
          ...taskStatuses[data.task_id],
          detail: data.detail || '',
        },
      };
    } else if (eventType === 'task_complete') {
      taskStatuses = {
        ...taskStatuses,
        [data.task_id]: {
          ...taskStatuses[data.task_id],
          status: 'completed',
          summary: data.summary || 'Done',
          detail: '',
        },
      };
    } else if (eventType === 'task_failed') {
      taskStatuses = {
        ...taskStatuses,
        [data.task_id]: {
          ...taskStatuses[data.task_id],
          status: 'failed',
          error: data.error || 'Unknown error',
          detail: '',
        },
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

    // Scroll to bottom
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

  function handleKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  // Track expanded task summaries
  let expandedTasks = $state({});

  function toggleTaskExpanded(taskId) {
    expandedTasks = { ...expandedTasks, [taskId]: !expandedTasks[taskId] };
  }

  // Download as markdown
  function downloadMarkdown() {
    if (!finalContent) return;
    const blob = new Blob([finalContent], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    // Use conversation title or fallback
    const title = conversations.find(c => c.id === activeConversationId)?.title || 'chat-response';
    const safeName = title.replace(/[^a-zA-Z0-9-_ ]/g, '').replace(/\s+/g, '-').substring(0, 60);
    a.download = `${safeName}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // Download as PDF -- renders HTML to canvas then to PDF
  let pdfGenerating = $state(false);

  async function downloadPDF() {
    if (!renderedContent || pdfGenerating) return;

    pdfGenerating = true;
    try {
      const { default: jsPDF } = await import('jspdf');
      const { default: html2canvas } = await import('html2canvas-pro');

      const title = conversations.find(c => c.id === activeConversationId)?.title || 'Chat Response';
      const safeName = title.replace(/[^a-zA-Z0-9\-_ ]/g, '').replace(/\s+/g, '-').substring(0, 60);

      // Create an offscreen container with print-optimized styles
      const container = document.createElement('div');
      container.style.cssText = 'position:absolute;left:-9999px;top:0;width:680px;';
      container.innerHTML = `
        <div style="
          font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
          font-size: 11px;
          line-height: 1.55;
          color: #1a1a1a;
          padding: 0;
        ">
          <style>
            .pdf-body h1 { font-size: 17px; font-weight: 700; margin: 0 0 10px 0; color: #111; border-bottom: 2px solid #e0e0e0; padding-bottom: 6px; }
            .pdf-body h2 { font-size: 14px; font-weight: 600; margin: 16px 0 6px 0; color: #222; }
            .pdf-body h3 { font-size: 12px; font-weight: 600; margin: 12px 0 5px 0; color: #333; }
            .pdf-body p { margin: 0 0 7px 0; }
            .pdf-body table { width: 100%; border-collapse: collapse; margin: 6px 0 12px 0; font-size: 10px; }
            .pdf-body th { text-align: left; padding: 5px 7px; border-bottom: 2px solid #ccc; font-weight: 600; background: #f5f5f5; }
            .pdf-body td { padding: 4px 7px; border-bottom: 1px solid #e5e5e5; vertical-align: top; }
            .pdf-body ul, .pdf-body ol { margin: 3px 0 7px 0; padding-left: 18px; }
            .pdf-body li { margin-bottom: 2px; }
            .pdf-body blockquote { border-left: 3px solid #d4a574; padding: 5px 10px; margin: 6px 0; background: #faf6f0; color: #555; font-size: 10px; }
            .pdf-body hr { border: none; border-top: 1px solid #ddd; margin: 14px 0; }
            .pdf-body code { font-size: 9px; padding: 1px 3px; background: #f0f0f0; border-radius: 2px; }
            .pdf-body img { max-width: 100%; height: auto; max-height: 200px; border-radius: 4px; margin: 5px 0; }
            .pdf-body a { color: #b5722a; text-decoration: none; }
            .pdf-body strong { font-weight: 600; }
            .pdf-body em { font-style: italic; color: #555; }
          </style>
          <div class="pdf-body">${renderedContent}</div>
          <div style="margin-top:20px;padding-top:6px;border-top:1px solid #ddd;font-size:8px;color:#999;text-align:center;">
            Generated from Mail Chat &middot; ${new Date().toLocaleDateString()}
          </div>
        </div>`;
      document.body.appendChild(container);

      // Wait a moment for styles and any images to settle
      await new Promise(r => setTimeout(r, 300));

      const canvas = await html2canvas(container.firstElementChild, {
        scale: 2,
        useCORS: true,
        allowTaint: true,
        logging: false,
        backgroundColor: '#ffffff',
      });

      document.body.removeChild(container);

      // Calculate PDF dimensions -- letter size (8.5 x 11 in), content area with margins
      const pageWidthPt = 612;  // 8.5in in points
      const pageHeightPt = 792; // 11in in points
      const marginPt = 54;      // 0.75in margins
      const contentWidthPt = pageWidthPt - (marginPt * 2);
      const contentHeightPt = pageHeightPt - (marginPt * 2);

      const imgWidth = canvas.width;
      const imgHeight = canvas.height;
      const ratio = contentWidthPt / imgWidth;
      const scaledHeight = imgHeight * ratio;

      // Calculate how many pages we need
      const totalPages = Math.ceil(scaledHeight / contentHeightPt);

      const pdf = new jsPDF({ unit: 'pt', format: 'letter' });

      for (let page = 0; page < totalPages; page++) {
        if (page > 0) {
          pdf.addPage();
        }

        // Calculate the source slice from the canvas for this page
        const sourceY = (page * contentHeightPt) / ratio;
        const sourceH = Math.min(contentHeightPt / ratio, imgHeight - sourceY);

        // Create a temporary canvas for this page slice
        const pageCanvas = document.createElement('canvas');
        pageCanvas.width = imgWidth;
        pageCanvas.height = Math.ceil(sourceH);
        const ctx = pageCanvas.getContext('2d');
        ctx.drawImage(canvas, 0, sourceY, imgWidth, sourceH, 0, 0, imgWidth, sourceH);

        const pageDataUrl = pageCanvas.toDataURL('image/jpeg', 0.95);
        const sliceHeightPt = sourceH * ratio;

        pdf.addImage(pageDataUrl, 'JPEG', marginPt, marginPt, contentWidthPt, sliceHeightPt);
      }

      pdf.save(`${safeName}.pdf`);
      showToast('PDF downloaded', 'success');
    } catch (err) {
      console.error('PDF generation failed:', err);
      showToast('Failed to generate PDF: ' + err.message, 'error');
    }
    pdfGenerating = false;
  }
</script>

<div class="h-full flex" style="background: var(--bg-primary)">
  <!-- Sidebar: conversation history -->
  {#if sidebarOpen}
    <div
      class="w-64 shrink-0 border-r flex flex-col h-full"
      style="background: var(--bg-secondary); border-color: var(--border-color)"
    >
      <!-- New Chat button -->
      <div class="p-3 border-b" style="border-color: var(--border-color)">
        <button
          onclick={startNewChat}
          class="w-full h-9 flex items-center justify-center gap-2 rounded-lg text-sm font-medium transition-fast"
          style="background: var(--color-accent-500); color: white"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          New Chat
        </button>
      </div>

      <!-- Conversation list -->
      <div class="flex-1 overflow-y-auto">
        {#if conversations.length === 0}
          <div class="p-4 text-center">
            <p class="text-xs" style="color: var(--text-tertiary)">No conversations yet</p>
          </div>
        {:else}
          {#each conversations as conv}
            <div
              role="button"
              tabindex="0"
              onclick={() => loadConversation(conv.id)}
              onkeydown={(e) => { if (e.key === 'Enter') loadConversation(conv.id); }}
              class="w-full text-left px-3 py-2.5 border-b transition-fast group relative cursor-pointer"
              style="border-color: var(--border-color); background: {activeConversationId === conv.id ? 'var(--bg-hover)' : 'transparent'}; color: var(--text-primary)"
            >
              <div class="text-sm truncate pr-6" style="color: {activeConversationId === conv.id ? 'var(--text-primary)' : 'var(--text-secondary)'}">
                {conv.title || 'Untitled'}
              </div>
              <div class="text-[10px] mt-0.5" style="color: var(--text-tertiary)">
                {formatDate(conv.created_at)}
              </div>
              <!-- Delete button -->
              <button
                onclick={(e) => { e.stopPropagation(); deleteConversation(conv.id); }}
                class="absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 p-1 rounded transition-fast"
                style="color: var(--text-tertiary)"
                title="Delete conversation"
              >
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          {/each}
        {/if}
      </div>
    </div>
  {/if}

  <!-- Main chat area -->
  <div class="flex-1 flex flex-col h-full min-w-0">
    <!-- Header -->
    <div class="h-14 flex items-center px-4 border-b shrink-0 gap-3" style="border-color: var(--border-color)">
      <button
        onclick={() => sidebarOpen = !sidebarOpen}
        class="p-1.5 rounded-md transition-fast"
        style="color: var(--text-secondary)"
        title="{sidebarOpen ? 'Hide sidebar' : 'Show sidebar'}"
      >
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
        </svg>
      </button>
      <h2 class="text-sm font-semibold" style="color: var(--text-primary)">
        Talk to your Emails
      </h2>
    </div>

    <!-- Messages area -->
    <div bind:this={messagesContainer} class="flex-1 overflow-y-auto p-4 space-y-4">
      {#if conversationMessages.length === 0 && !isProcessing}
        <!-- Empty state -->
        <div class="flex flex-col items-center justify-center h-full text-center px-4">
          <div class="w-16 h-16 rounded-2xl flex items-center justify-center mb-4" style="background: var(--color-accent-500)/10">
            <svg class="w-8 h-8" style="color: var(--color-accent-500)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.076-4.076a1.526 1.526 0 011.037-.443 48.282 48.282 0 005.68-.494c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
            </svg>
          </div>
          <h3 class="text-lg font-semibold mb-2" style="color: var(--text-primary)">Ask anything about your emails</h3>
          <p class="text-sm max-w-md" style="color: var(--text-secondary)">
            I can search through your emails, read them, and build comprehensive answers.
            Try asking about orders, deliveries, conversations, or any information in your inbox.
          </p>
          <div class="mt-6 flex flex-wrap gap-2 justify-center max-w-lg">
            {#each [
              'What furniture did I order in 2020?',
              'Summarize my recent conversations with John',
              'Find all receipts over $500 this year',
              'List all subscriptions I\'m paying for',
            ] as suggestion}
              <button
                onclick={() => { messageInput = suggestion; }}
                class="px-3 py-1.5 rounded-full text-xs border transition-fast"
                style="border-color: var(--border-color); color: var(--text-secondary); background: var(--bg-secondary)"
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
              <div class="max-w-2xl px-4 py-2.5 rounded-2xl rounded-br-md text-sm" style="background: var(--color-accent-500); color: white">
                {msg.content}
              </div>
            </div>
          {/if}
        {/each}

        <!-- Agent progress / response area -->
        {#if currentPhase || isProcessing}
          <div class="max-w-3xl">
            <!-- Phase 1: Planning -->
            {#if currentPhase === 'plan'}
              <div class="flex items-center gap-2 mb-3">
                <div class="w-5 h-5 rounded-full flex items-center justify-center animate-pulse" style="background: var(--color-accent-500)/20">
                  <div class="w-2.5 h-2.5 rounded-full" style="background: var(--color-accent-500)"></div>
                </div>
                <span class="text-sm font-medium" style="color: var(--text-primary)">Analyzing your question...</span>
              </div>
            {/if}

            <!-- Clarification question from the AI -->
            {#if currentPhase === 'clarification' && clarificationQuestion}
              <div class="mb-4 rounded-xl border overflow-hidden" style="border-color: var(--color-accent-500)/30; background: var(--color-accent-500)/5">
                <div class="px-4 py-3 flex items-start gap-3">
                  <div class="mt-0.5 shrink-0">
                    <svg class="w-5 h-5" style="color: var(--color-accent-600)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9 5.25h.008v.008H12v-.008z" />
                    </svg>
                  </div>
                  <div class="flex-1">
                    <div class="text-xs font-semibold uppercase tracking-wider mb-1" style="color: var(--color-accent-600)">
                      Quick question before I search
                    </div>
                    <div class="text-sm" style="color: var(--text-primary)">
                      {clarificationQuestion}
                    </div>
                    <div class="text-[10px] mt-2" style="color: var(--text-tertiary)">
                      Type your answer below and I'll get started.
                    </div>
                  </div>
                </div>
              </div>
            {/if}

            <!-- Task list -->
            {#if tasks.length > 0}
              <div class="mb-4 rounded-xl border overflow-hidden" style="border-color: var(--border-color); background: var(--bg-secondary)">
                <!-- Task list header -->
                <div class="px-4 py-2.5 border-b flex items-center justify-between" style="border-color: var(--border-color)">
                  <span class="text-xs font-semibold uppercase tracking-wider" style="color: var(--text-tertiary)">
                    Research Plan
                  </span>
                  {#if currentPhase === 'execute' || currentPhase === 'verify' || currentPhase === 'done'}
                    <span class="text-[10px] font-medium px-2 py-0.5 rounded-full" style="background: var(--color-accent-500)/15; color: var(--color-accent-600)">
                      {getCompletedCount()} / {tasks.length} tasks
                    </span>
                  {/if}
                </div>

                <!-- Tasks -->
                {#each tasks as task}
                  {@const status = taskStatuses[task.id] || { status: 'pending' }}
                  <div
                    class="px-4 py-3 border-b last:border-0 transition-all duration-300"
                    style="border-color: var(--border-color); {status.status === 'in_progress' ? 'background: var(--color-accent-500)/5' : ''}"
                  >
                    <div class="flex items-start gap-3">
                      <!-- Status icon -->
                      <div class="mt-0.5 shrink-0">
                        {#if status.status === 'pending'}
                          <div class="w-5 h-5 rounded-full border-2" style="border-color: var(--border-color)"></div>
                        {:else if status.status === 'in_progress'}
                          <div class="w-5 h-5 rounded-full border-2 border-t-transparent animate-spin" style="border-color: var(--color-accent-500)"></div>
                        {:else if status.status === 'completed'}
                          <div class="w-5 h-5 rounded-full flex items-center justify-center" style="background: #22c55e">
                            <svg class="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M4.5 12.75l6 6 9-13.5" />
                            </svg>
                          </div>
                        {:else if status.status === 'failed'}
                          <div class="w-5 h-5 rounded-full flex items-center justify-center" style="background: #ef4444">
                            <svg class="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M6 18L18 6M6 6l12 12" />
                            </svg>
                          </div>
                        {/if}
                      </div>

                      <!-- Task content -->
                      <div class="flex-1 min-w-0">
                        <div class="text-sm" style="color: var(--text-primary)">
                          <span class="font-medium" style="color: var(--text-tertiary)">#{task.id}</span>
                          {task.description}
                        </div>

                        <!-- Progress detail (during execution) -->
                        {#if status.status === 'in_progress' && status.detail}
                          <div class="mt-1 text-xs italic" style="color: var(--color-accent-600)">
                            {status.detail}
                          </div>
                        {/if}

                        <!-- Summary (when completed) -->
                        {#if status.status === 'completed' && status.summary}
                          <button
                            onclick={() => toggleTaskExpanded(task.id)}
                            class="mt-1 text-xs flex items-center gap-1 transition-fast"
                            style="color: var(--text-tertiary)"
                          >
                            <svg
                              class="w-3 h-3 transition-transform duration-200 {expandedTasks[task.id] ? 'rotate-90' : ''}"
                              fill="none" stroke="currentColor" viewBox="0 0 24 24"
                            >
                              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                            </svg>
                            {expandedTasks[task.id] ? 'Hide details' : 'Show details'}
                          </button>
                          {#if expandedTasks[task.id]}
                            <div class="mt-1.5 text-xs whitespace-pre-wrap rounded-lg p-2" style="color: var(--text-secondary); background: var(--bg-primary)">
                              {status.summary}
                            </div>
                          {/if}
                        {/if}

                        <!-- Error (when failed) -->
                        {#if status.status === 'failed' && status.error}
                          <div class="mt-1 text-xs" style="color: #ef4444">
                            {status.error}
                          </div>
                        {/if}
                      </div>
                    </div>
                  </div>
                {/each}
              </div>
            {/if}

            <!-- Phase 3: Verify indicator -->
            {#if currentPhase === 'verify'}
              <div class="flex items-center gap-2 mb-3">
                <div class="w-5 h-5 rounded-full flex items-center justify-center animate-pulse" style="background: #a855f7/20">
                  <div class="w-2.5 h-2.5 rounded-full" style="background: #a855f7"></div>
                </div>
                <span class="text-sm font-medium" style="color: var(--text-primary)">Verifying and composing answer...</span>
              </div>
            {/if}

            <!-- Final rendered answer -->
            {#if renderedContent}
              <!-- Download buttons -->
              <div class="flex items-center gap-2 mb-2">
                <span class="text-xs font-medium" style="color: var(--text-tertiary)">Download:</span>
                <button
                  onclick={downloadMarkdown}
                  class="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium border transition-fast"
                  style="border-color: var(--border-color); color: var(--text-secondary); background: var(--bg-secondary)"
                  title="Download as Markdown"
                >
                  <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                  Markdown
                </button>
                <button
                  onclick={downloadPDF}
                  disabled={pdfGenerating}
                  class="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium border transition-fast"
                  style="border-color: var(--border-color); color: var(--text-secondary); background: var(--bg-secondary); opacity: {pdfGenerating ? '0.6' : '1'}"
                  title="Download as PDF"
                >
                  {#if pdfGenerating}
                    <div class="w-3.5 h-3.5 border-2 rounded-full animate-spin" style="border-color: var(--border-color); border-top-color: var(--text-secondary)"></div>
                    Generating...
                  {:else}
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                    </svg>
                    PDF
                  {/if}
                </button>
              </div>

              <div
                class="prose prose-sm max-w-none rounded-xl border p-5 chat-markdown"
                style="border-color: var(--border-color); background: var(--bg-secondary); color: var(--text-primary)"
              >
                {@html renderedContent}
              </div>
            {/if}

            <!-- Error -->
            {#if errorMessage}
              <div class="rounded-xl border p-4 text-sm" style="border-color: #ef4444/30; background: #ef4444/5; color: #ef4444">
                {errorMessage}
              </div>
            {/if}
          </div>
        {/if}
      {/if}
    </div>

    <!-- Input area -->
    <div class="p-4 border-t shrink-0" style="border-color: var(--border-color)">
      <div class="max-w-3xl mx-auto">
        <div class="flex gap-2 items-end">
          <div class="flex-1 relative">
            <textarea
              bind:value={messageInput}
              onkeydown={handleKeydown}
              placeholder="Ask about your emails..."
              disabled={isProcessing}
              rows="1"
              class="w-full px-4 py-2.5 rounded-xl border text-sm resize-none outline-none transition-fast"
              style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-primary); min-height: 42px; max-height: 120px"
            ></textarea>
          </div>
          <button
            onclick={sendMessage}
            disabled={isProcessing || !messageInput.trim()}
            class="h-[42px] w-[42px] shrink-0 rounded-xl flex items-center justify-center transition-fast"
            style="background: {isProcessing || !messageInput.trim() ? 'var(--border-color)' : 'var(--color-accent-500)'}; color: white"
          >
            {#if isProcessing}
              <div class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
            {:else}
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
              </svg>
            {/if}
          </button>
        </div>
        {#if isProcessing}
          <div class="mt-2 text-[10px] text-center" style="color: var(--text-tertiary)">
            Processing... This may take a minute for complex queries.
          </div>
        {/if}
      </div>
    </div>
  </div>
</div>

<style>
  /* Markdown content styling */
  :global(.chat-markdown h1) {
    font-size: 1.25rem;
    font-weight: 700;
    margin-top: 1rem;
    margin-bottom: 0.5rem;
    color: var(--text-primary);
  }
  :global(.chat-markdown h2) {
    font-size: 1.1rem;
    font-weight: 600;
    margin-top: 0.75rem;
    margin-bottom: 0.5rem;
    color: var(--text-primary);
  }
  :global(.chat-markdown h3) {
    font-size: 1rem;
    font-weight: 600;
    margin-top: 0.5rem;
    margin-bottom: 0.25rem;
    color: var(--text-primary);
  }
  :global(.chat-markdown p) {
    margin-bottom: 0.5rem;
    line-height: 1.6;
  }
  :global(.chat-markdown ul),
  :global(.chat-markdown ol) {
    margin-bottom: 0.5rem;
    padding-left: 1.5rem;
  }
  :global(.chat-markdown li) {
    margin-bottom: 0.25rem;
  }
  :global(.chat-markdown table) {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 0.75rem;
    font-size: 0.8rem;
  }
  :global(.chat-markdown th) {
    text-align: left;
    padding: 0.5rem;
    border-bottom: 2px solid var(--border-color);
    font-weight: 600;
    color: var(--text-primary);
  }
  :global(.chat-markdown td) {
    padding: 0.5rem;
    border-bottom: 1px solid var(--border-color);
    color: var(--text-secondary);
  }
  :global(.chat-markdown img) {
    max-width: 100%;
    height: auto;
    max-height: 300px;
    border-radius: 0.5rem;
    margin: 0.5rem 0;
    object-fit: contain;
  }
  :global(.chat-markdown code) {
    font-size: 0.8rem;
    padding: 0.125rem 0.375rem;
    border-radius: 0.25rem;
    background: var(--bg-primary);
    color: var(--color-accent-600);
  }
  :global(.chat-markdown pre) {
    margin-bottom: 0.75rem;
    padding: 0.75rem;
    border-radius: 0.5rem;
    background: var(--bg-primary);
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
    padding-left: 0.75rem;
    margin: 0.5rem 0;
    color: var(--text-secondary);
    font-style: italic;
  }
  :global(.chat-markdown hr) {
    border: none;
    border-top: 1px solid var(--border-color);
    margin: 0.75rem 0;
  }
</style>
