<script>
  import { onMount } from 'svelte';
  import Icon from '../common/Icon.svelte';

  let { emailId = null, markSpam = true, onComplete = () => {} } = $props();

  let steps = $state([]);
  let currentStatus = $state('idle');
  let latestScreenshot = $state(null);
  let error = $state(null);

  // Not reactive -- just a plain variable so $effect doesn't track it
  let _abortController = null;

  async function startStream() {
    if (!emailId) return;
    steps = [];
    currentStatus = 'connecting';
    error = null;
    latestScreenshot = null;

    try {
      _abortController = new AbortController();
      const response = await fetch(`/api/ai/unsubscribe/${emailId}/stream?mark_spam=${markSpam}`, {
        credentials: 'include',
        signal: _abortController.signal,
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({ detail: 'Connection failed' }));
        error = errData.detail || 'Stream connection failed';
        currentStatus = 'failed';
        return;
      }

      currentStatus = 'in_progress';
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const event = JSON.parse(line.slice(6));
              steps = [...steps, event];

              if (event.screenshot) {
                latestScreenshot = event.screenshot;
              }
              if (event.status === 'success' || event.status === 'failed') {
                currentStatus = event.status;
              }
            } catch {
              // Skip malformed events
            }
          }
        }
      }

      if (currentStatus === 'in_progress') {
        currentStatus = 'success';
      }
    } catch (e) {
      if (e.name !== 'AbortError') {
        error = e.message;
        currentStatus = 'failed';
      }
    } finally {
      _abortController = null;
      onComplete(currentStatus);
    }
  }

  function cancel() {
    if (_abortController) {
      _abortController.abort();
      currentStatus = 'cancelled';
    }
  }

  onMount(() => {
    if (emailId) {
      startStream();
    }
    return () => {
      if (_abortController) {
        _abortController.abort();
      }
    };
  });

  function getStepIcon(step) {
    if (step.status === 'success') return 'check-circle';
    if (step.status === 'failed') return 'x-circle';
    if (step.step?.startsWith('analyzing')) return 'cpu';
    if (step.step?.startsWith('acting')) return 'mouse-pointer';
    if (step.step === 'navigating') return 'globe';
    if (step.step === 'starting') return 'play';
    if (step.step === 'spam') return 'alert-triangle';
    return 'loader';
  }

  function getStepColor(step) {
    if (step.status === 'success') return 'var(--status-success)';
    if (step.status === 'failed') return 'var(--status-error)';
    return 'var(--color-accent-500)';
  }
</script>

<div class="unsub-viewer">
  <!-- Progress Steps -->
  <div class="steps-container">
    {#each steps as step, i}
      <div class="step-item" class:step-success={step.status === 'success'} class:step-error={step.status === 'failed'}>
        <div class="step-icon" style="color: {getStepColor(step)}">
          <Icon name={getStepIcon(step)} size={16} />
        </div>
        <div class="step-content">
          <div class="step-message">{step.message}</div>
          {#if step.llm_reasoning}
            <div class="step-reasoning">{step.llm_reasoning}</div>
          {/if}
        </div>
      </div>
    {/each}

    {#if currentStatus === 'connecting' || currentStatus === 'in_progress'}
      <div class="step-item step-active">
        <div class="step-icon" style="color: var(--color-accent-500)">
          <div class="spinner">
            <Icon name="loader" size={16} />
          </div>
        </div>
        <div class="step-content">
          <div class="step-message" style="color: var(--text-tertiary)">
            {currentStatus === 'connecting' ? 'Connecting...' : 'Processing...'}
          </div>
        </div>
      </div>
    {/if}
  </div>

  <!-- Screenshot Preview -->
  {#if latestScreenshot}
    <div class="screenshot-container">
      <div class="screenshot-label">
        <Icon name="monitor" size={14} />
        <span>Browser View</span>
      </div>
      <div class="screenshot-frame">
        <img src="data:image/png;base64,{latestScreenshot}" alt="Unsubscribe page" />
      </div>
    </div>
  {/if}

  <!-- Error Display -->
  {#if error}
    <div class="error-banner">
      <Icon name="alert-circle" size={16} />
      <span>{error}</span>
    </div>
  {/if}

  <!-- Final Status -->
  {#if currentStatus === 'success'}
    <div class="status-banner status-success">
      <Icon name="check-circle" size={18} />
      <span>Successfully unsubscribed</span>
    </div>
  {:else if currentStatus === 'failed'}
    <div class="status-banner status-error">
      <Icon name="x-circle" size={18} />
      <span>Unsubscribe failed</span>
    </div>
  {/if}

  <!-- Cancel Button -->
  {#if currentStatus === 'in_progress' || currentStatus === 'connecting'}
    <button class="cancel-btn" onclick={cancel}>
      <Icon name="x" size={14} />
      Cancel
    </button>
  {/if}
</div>

<style>
  .unsub-viewer {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .steps-container {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .step-item {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 8px 12px;
    border-radius: 8px;
    background: var(--bg-tertiary);
    transition: all 0.2s ease;
  }

  .step-success {
    background: color-mix(in srgb, var(--status-success) 10%, var(--bg-tertiary));
  }

  .step-error {
    background: color-mix(in srgb, var(--status-error) 10%, var(--bg-tertiary));
  }

  .step-icon {
    flex-shrink: 0;
    margin-top: 2px;
  }

  .step-content {
    flex: 1;
    min-width: 0;
  }

  .step-message {
    font-size: 13px;
    color: var(--text-primary);
    line-height: 1.4;
  }

  .step-reasoning {
    font-size: 11px;
    color: var(--text-tertiary);
    margin-top: 4px;
    padding: 6px 8px;
    background: var(--bg-secondary);
    border-radius: 4px;
    font-style: italic;
    line-height: 1.4;
  }

  .spinner {
    animation: spin 1.5s linear infinite;
  }

  @keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }

  .screenshot-container {
    border: 1px solid var(--border-color);
    border-radius: 10px;
    overflow: hidden;
  }

  .screenshot-label {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 12px;
    background: var(--bg-tertiary);
    color: var(--text-secondary);
    font-size: 12px;
    font-weight: 500;
    border-bottom: 1px solid var(--border-color);
  }

  .screenshot-frame {
    background: #fff;
    max-height: 400px;
    overflow-y: auto;
  }

  .screenshot-frame img {
    width: 100%;
    display: block;
  }

  .error-banner {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    background: color-mix(in srgb, var(--status-error) 10%, var(--bg-tertiary));
    color: var(--status-error);
    border-radius: 8px;
    font-size: 13px;
  }

  .status-banner {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 16px;
    border-radius: 10px;
    font-size: 14px;
    font-weight: 600;
  }

  .status-success {
    background: color-mix(in srgb, var(--status-success) 12%, var(--bg-tertiary));
    color: var(--status-success);
  }

  .status-error {
    background: color-mix(in srgb, var(--status-error) 12%, var(--bg-tertiary));
    color: var(--status-error);
  }

  .cancel-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 8px 16px;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 500;
    background: var(--bg-tertiary);
    color: var(--text-secondary);
    border: 1px solid var(--border-color);
    cursor: pointer;
    transition: all 0.15s ease;
    align-self: center;
  }

  .cancel-btn:hover {
    background: var(--bg-hover);
    color: var(--text-primary);
  }
</style>
