<!--
  AI Models settings panel.
  Extracted from Admin.svelte to keep that page reviewable.

  Props:
    aiPrefs        – reactive object whose model fields the selects bind to
    allowedModels  – list of model IDs to render in each dropdown
    labels         – id -> display label map (from /api/auth/ai-preferences)
    effortLevels   – model id -> supported reasoning-effort values
    modelsByPreference – preference field -> compatible model IDs
    saving         – disables save buttons while a save is in flight
    reprocessing   – disables the reprocess button while it's in flight
    onSave         – called when any "Save" button is clicked
    onReprocess    – called when the "Reprocess with this model" button is clicked
    Button         – the shared Button component (passed in to avoid a second import path)
-->
<script>
  let {
    aiPrefs = $bindable(),
    allowedModels = [],
    labels = {},
    effortLevels = {},
    modelsByPreference = {},
    saving = false,
    reprocessing = false,
    onSave,
    onReprocess,
    Button,
  } = $props();

  function modelLabel(id) {
    return labels[id] || id;
  }

  function modelsFor(preference) {
    return modelsByPreference[preference] || allowedModels;
  }

  function effortsFor(model) {
    return effortLevels[model] || [];
  }

  function effortLabel(effort) {
    const labels = {
      none: 'None — fastest',
      low: 'Low — efficient',
      medium: 'Medium — balanced',
      high: 'High — thorough',
      xhigh: 'Extra high — demanding work',
      max: 'Max — quality first',
    };
    return labels[effort] || effort;
  }

  function reconcileEffort(modelKey, effortKey) {
    const levels = effortsFor(aiPrefs[modelKey]);
    if (!levels.includes(aiPrefs[effortKey])) {
      aiPrefs[effortKey] = levels.includes('medium') ? 'medium' : levels[0];
    }
  }
</script>

<div class="space-y-6">
  <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
    <h3 class="text-sm font-semibold mb-1" style="color: var(--text-primary)">Chat AI Models</h3>
    <p class="text-xs mb-5" style="color: var(--text-tertiary)">
      Choose a provider model and reasoning effort for each phase of "Talk to your Emails."
      The defaults spend more compute on the final answer than on parallel retrieval.
    </p>

    <div class="space-y-5">
      <div>
        <label for="ai-plan-model" class="block text-xs font-semibold mb-1.5 uppercase tracking-wider" style="color: var(--text-tertiary)">
          Plan
        </label>
        <p class="text-[11px] mb-2" style="color: var(--text-tertiary)">
          Analyzes your question and builds a research task list.
        </p>
        <select
          id="ai-plan-model"
          bind:value={aiPrefs.chat_plan_model}
          onchange={() => reconcileEffort('chat_plan_model', 'chat_plan_effort')}
          class="w-full h-9 px-3 rounded-lg text-sm outline-none border appearance-none cursor-pointer"
          style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
        >
          {#each modelsFor('chat_plan_model') as model}
            <option value={model}>{modelLabel(model)}</option>
          {/each}
        </select>
        <label for="ai-plan-effort" class="block text-xs font-semibold mt-3 mb-1.5 uppercase tracking-wider" style="color: var(--text-tertiary)">
          Reasoning effort
        </label>
        <select
          id="ai-plan-effort"
          bind:value={aiPrefs.chat_plan_effort}
          class="w-full h-9 px-3 rounded-lg text-sm outline-none border appearance-none cursor-pointer"
          style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
        >
          {#each effortsFor(aiPrefs.chat_plan_model) as effort}
            <option value={effort}>{effortLabel(effort)}</option>
          {/each}
        </select>
      </div>

      <div>
        <label for="ai-execute-model" class="block text-xs font-semibold mb-1.5 uppercase tracking-wider" style="color: var(--text-tertiary)">
          Research
        </label>
        <p class="text-[11px] mb-2" style="color: var(--text-tertiary)">
          Searches and reads your emails to complete each task in the plan.
        </p>
        <select
          id="ai-execute-model"
          bind:value={aiPrefs.chat_execute_model}
          onchange={() => reconcileEffort('chat_execute_model', 'chat_execute_effort')}
          class="w-full h-9 px-3 rounded-lg text-sm outline-none border appearance-none cursor-pointer"
          style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
        >
          {#each modelsFor('chat_execute_model') as model}
            <option value={model}>{modelLabel(model)}</option>
          {/each}
        </select>
        <label for="ai-execute-effort" class="block text-xs font-semibold mt-3 mb-1.5 uppercase tracking-wider" style="color: var(--text-tertiary)">
          Reasoning effort
        </label>
        <select
          id="ai-execute-effort"
          bind:value={aiPrefs.chat_execute_effort}
          class="w-full h-9 px-3 rounded-lg text-sm outline-none border appearance-none cursor-pointer"
          style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
        >
          {#each effortsFor(aiPrefs.chat_execute_model) as effort}
            <option value={effort}>{effortLabel(effort)}</option>
          {/each}
        </select>
      </div>

      <div>
        <label for="ai-verify-model" class="block text-xs font-semibold mb-1.5 uppercase tracking-wider" style="color: var(--text-tertiary)">
          Answer
        </label>
        <p class="text-[11px] mb-2" style="color: var(--text-tertiary)">
          Verifies completeness and writes the final formatted answer.
        </p>
        <select
          id="ai-verify-model"
          bind:value={aiPrefs.chat_verify_model}
          onchange={() => reconcileEffort('chat_verify_model', 'chat_verify_effort')}
          class="w-full h-9 px-3 rounded-lg text-sm outline-none border appearance-none cursor-pointer"
          style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
        >
          {#each modelsFor('chat_verify_model') as model}
            <option value={model}>{modelLabel(model)}</option>
          {/each}
        </select>
        <label for="ai-verify-effort" class="block text-xs font-semibold mt-3 mb-1.5 uppercase tracking-wider" style="color: var(--text-tertiary)">
          Reasoning effort
        </label>
        <select
          id="ai-verify-effort"
          bind:value={aiPrefs.chat_verify_effort}
          class="w-full h-9 px-3 rounded-lg text-sm outline-none border appearance-none cursor-pointer"
          style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
        >
          {#each effortsFor(aiPrefs.chat_verify_model) as effort}
            <option value={effort}>{effortLabel(effort)}</option>
          {/each}
        </select>
      </div>
    </div>

    <div class="mt-5 flex items-center gap-3">
      <Button variant="primary" size="sm" onclick={onSave} disabled={saving}>
        {saving ? 'Saving...' : 'Save Preferences'}
      </Button>
      <span class="text-[10px]" style="color: var(--text-tertiary)">
        Changes take effect on the next chat conversation.
      </span>
    </div>
  </div>

  <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
    <h3 class="text-sm font-semibold mb-1" style="color: var(--text-primary)">Custom Prompt Model</h3>
    <p class="text-xs mb-5" style="color: var(--text-tertiary)">
      Used when generating replies from custom prompts in the Flow view.
      Medium effort on a balanced model is a good fit for concise, natural replies.
    </p>

    <div>
      <label for="ai-custom-prompt-model" class="block text-xs font-semibold mb-1.5 uppercase tracking-wider" style="color: var(--text-tertiary)">
        Model
      </label>
      <select
        id="ai-custom-prompt-model"
        bind:value={aiPrefs.custom_prompt_model}
        onchange={() => reconcileEffort('custom_prompt_model', 'custom_prompt_effort')}
        class="w-full h-9 px-3 rounded-lg text-sm outline-none border appearance-none cursor-pointer"
        style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
      >
        {#each modelsFor('custom_prompt_model') as model}
          <option value={model}>{modelLabel(model)}</option>
        {/each}
      </select>
      <label for="ai-custom-prompt-effort" class="block text-xs font-semibold mt-3 mb-1.5 uppercase tracking-wider" style="color: var(--text-tertiary)">
        Reasoning effort
      </label>
      <select
        id="ai-custom-prompt-effort"
        bind:value={aiPrefs.custom_prompt_effort}
        class="w-full h-9 px-3 rounded-lg text-sm outline-none border appearance-none cursor-pointer"
        style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
      >
        {#each effortsFor(aiPrefs.custom_prompt_model) as effort}
          <option value={effort}>{effortLabel(effort)}</option>
        {/each}
      </select>
    </div>

    <div class="mt-5 flex items-center gap-3">
      <Button variant="primary" size="sm" onclick={onSave} disabled={saving}>
        {saving ? 'Saving...' : 'Save'}
      </Button>
      <span class="text-[10px]" style="color: var(--text-tertiary)">
        Changes take effect on the next custom prompt generation.
      </span>
    </div>
  </div>

  <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
    <h3 class="text-sm font-semibold mb-1" style="color: var(--text-primary)">Email Processing Model</h3>
    <p class="text-xs mb-5" style="color: var(--text-tertiary)">
      Used for email categorization, summarization, action items, and suggested replies.
      Changing this model affects new analyses. Use "Reprocess" to re-analyze emails with the new model.
    </p>

    <div>
      <label for="ai-agentic-model" class="block text-xs font-semibold mb-1.5 uppercase tracking-wider" style="color: var(--text-tertiary)">
        Model
      </label>
      <select
        id="ai-agentic-model"
        bind:value={aiPrefs.agentic_model}
        onchange={() => reconcileEffort('agentic_model', 'agentic_effort')}
        class="w-full h-9 px-3 rounded-lg text-sm outline-none border appearance-none cursor-pointer"
        style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
      >
        {#each modelsFor('agentic_model') as model}
          <option value={model}>{modelLabel(model)}</option>
        {/each}
      </select>
      <label for="ai-agentic-effort" class="block text-xs font-semibold mt-3 mb-1.5 uppercase tracking-wider" style="color: var(--text-tertiary)">
        Reasoning effort
      </label>
      <select
        id="ai-agentic-effort"
        bind:value={aiPrefs.agentic_effort}
        class="w-full h-9 px-3 rounded-lg text-sm outline-none border appearance-none cursor-pointer"
        style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
      >
        {#each effortsFor(aiPrefs.agentic_model) as effort}
          <option value={effort}>{effortLabel(effort)}</option>
        {/each}
      </select>
    </div>

    <div class="mt-5 flex items-center gap-3">
      <Button variant="primary" size="sm" onclick={onSave} disabled={saving}>
        {saving ? 'Saving...' : 'Save'}
      </Button>
      <button
        onclick={onReprocess}
        disabled={reprocessing}
        class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-fast disabled:opacity-50"
        style="background: var(--bg-primary); color: var(--text-primary); border: 1px solid var(--border-color)"
      >
        {#if reprocessing}
          <div class="w-3.5 h-3.5 border-2 rounded-full animate-spin" style="border-color: var(--border-color); border-top-color: var(--color-accent-500)"></div>
          Reprocessing...
        {:else}
          Reprocess with this model
        {/if}
      </button>
      <span class="text-[10px]" style="color: var(--text-tertiary)">
        Re-analyzes emails previously processed with a different model.
      </span>
    </div>
  </div>

  <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
    <h3 class="text-sm font-semibold mb-1" style="color: var(--text-primary)">Unsubscribe Model</h3>
    <p class="text-xs mb-5" style="color: var(--text-tertiary)">
      Used for AI-powered browser automation when unsubscribing from mailing lists.
      Claude Sonnet 5 at medium effort is the default for reliable Computer Use without frontier-model cost.
    </p>

    <div>
      <label for="ai-unsubscribe-model" class="block text-xs font-semibold mb-1.5 uppercase tracking-wider" style="color: var(--text-tertiary)">
        Model
      </label>
      <select
        id="ai-unsubscribe-model"
        bind:value={aiPrefs.unsubscribe_model}
        onchange={() => reconcileEffort('unsubscribe_model', 'unsubscribe_effort')}
        class="w-full h-9 px-3 rounded-lg text-sm outline-none border appearance-none cursor-pointer"
        style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
      >
        {#each modelsFor('unsubscribe_model') as model}
          <option value={model}>{modelLabel(model)}</option>
        {/each}
      </select>
      <label for="ai-unsubscribe-effort" class="block text-xs font-semibold mt-3 mb-1.5 uppercase tracking-wider" style="color: var(--text-tertiary)">
        Reasoning effort
      </label>
      <select
        id="ai-unsubscribe-effort"
        bind:value={aiPrefs.unsubscribe_effort}
        class="w-full h-9 px-3 rounded-lg text-sm outline-none border appearance-none cursor-pointer"
        style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
      >
        {#each effortsFor(aiPrefs.unsubscribe_model) as effort}
          <option value={effort}>{effortLabel(effort)}</option>
        {/each}
      </select>
    </div>

    <div class="mt-5 flex items-center gap-3">
      <Button variant="primary" size="sm" onclick={onSave} disabled={saving}>
        {saving ? 'Saving...' : 'Save'}
      </Button>
      <span class="text-[10px]" style="color: var(--text-tertiary)">
        Changes apply to the next unsubscribe action.
      </span>
    </div>
  </div>

  <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
    <h3 class="text-sm font-semibold mb-3" style="color: var(--text-primary)">Model Comparison</h3>
    <table class="w-full text-sm">
      <thead>
        <tr class="border-b" style="border-color: var(--border-color)">
          <th class="text-left py-2 text-xs font-semibold uppercase tracking-wider" style="color: var(--text-secondary)">Model</th>
          <th class="text-left py-2 text-xs font-semibold uppercase tracking-wider" style="color: var(--text-secondary)">Provider</th>
          <th class="text-left py-2 text-xs font-semibold uppercase tracking-wider" style="color: var(--text-secondary)">Best fit here</th>
          <th class="text-left py-2 text-xs font-semibold uppercase tracking-wider" style="color: var(--text-secondary)">Start at</th>
        </tr>
      </thead>
      <tbody>
        <tr class="border-b" style="border-color: var(--border-color)">
          <td class="py-2 font-medium" style="color: var(--text-primary)">GPT-5.6 Sol</td>
          <td class="py-2" style="color: var(--text-secondary)">OpenAI</td>
          <td class="py-2" style="color: var(--text-secondary)">Final synthesis</td>
          <td class="py-2" style="color: var(--status-success)">High</td>
        </tr>
        <tr class="border-b" style="border-color: var(--border-color)">
          <td class="py-2 font-medium" style="color: var(--text-primary)">GPT-5.6 Terra</td>
          <td class="py-2" style="color: var(--text-secondary)">OpenAI</td>
          <td class="py-2" style="color: var(--text-secondary)">Planning + writing</td>
          <td class="py-2" style="color: var(--status-success)">Medium</td>
        </tr>
        <tr class="border-b" style="border-color: var(--border-color)">
          <td class="py-2 font-medium" style="color: var(--text-primary)">GPT-5.6 Luna</td>
          <td class="py-2" style="color: var(--text-secondary)">OpenAI</td>
          <td class="py-2" style="color: var(--text-secondary)">Bulk + parallel work</td>
          <td class="py-2" style="color: var(--status-success)">Low</td>
        </tr>
        <tr class="border-b" style="border-color: var(--border-color)">
          <td class="py-2 font-medium" style="color: var(--text-primary)">Claude Fable 5</td>
          <td class="py-2" style="color: var(--text-secondary)">Anthropic</td>
          <td class="py-2" style="color: var(--text-secondary)">Hard long-horizon work</td>
          <td class="py-2" style="color: var(--status-success)">High</td>
        </tr>
        <tr class="border-b" style="border-color: var(--border-color)">
          <td class="py-2 font-medium" style="color: var(--text-primary)">Claude Opus 5</td>
          <td class="py-2" style="color: var(--text-secondary)">Anthropic</td>
          <td class="py-2" style="color: var(--text-secondary)">Agentic reasoning</td>
          <td class="py-2" style="color: var(--status-success)">High</td>
        </tr>
        <tr>
          <td class="py-2 font-medium" style="color: var(--text-primary)">Claude Sonnet 5</td>
          <td class="py-2" style="color: var(--text-secondary)">Anthropic</td>
          <td class="py-2" style="color: var(--text-secondary)">Computer Use + chat</td>
          <td class="py-2" style="color: var(--status-success)">Medium</td>
        </tr>
      </tbody>
    </table>
  </div>
</div>
