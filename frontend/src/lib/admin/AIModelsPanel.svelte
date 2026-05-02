<!--
  AI Models settings panel.
  Extracted from Admin.svelte to keep that page reviewable.

  Props:
    aiPrefs        – reactive object whose model fields the selects bind to
    allowedModels  – list of model IDs to render in each dropdown
    labels         – id -> display label map (from /api/auth/ai-preferences)
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
    saving = false,
    reprocessing = false,
    onSave,
    onReprocess,
    Button,
  } = $props();

  function modelLabel(id) {
    return labels[id] || id;
  }
</script>

<div class="space-y-6">
  <div class="rounded-xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
    <h3 class="text-sm font-semibold mb-1" style="color: var(--text-primary)">Chat AI Models</h3>
    <p class="text-xs mb-5" style="color: var(--text-tertiary)">
      Choose which Claude model to use for each phase of the "Talk to your Emails" chat feature.
      Opus gives the best quality, Haiku is fastest and cheapest.
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
          class="w-full h-9 px-3 rounded-lg text-sm outline-none border appearance-none cursor-pointer"
          style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
        >
          {#each allowedModels as model}
            <option value={model}>{modelLabel(model)}</option>
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
          class="w-full h-9 px-3 rounded-lg text-sm outline-none border appearance-none cursor-pointer"
          style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
        >
          {#each allowedModels as model}
            <option value={model}>{modelLabel(model)}</option>
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
          class="w-full h-9 px-3 rounded-lg text-sm outline-none border appearance-none cursor-pointer"
          style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
        >
          {#each allowedModels as model}
            <option value={model}>{modelLabel(model)}</option>
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
      Opus gives the best quality, Haiku is fastest and cheapest.
    </p>

    <div>
      <label for="ai-custom-prompt-model" class="block text-xs font-semibold mb-1.5 uppercase tracking-wider" style="color: var(--text-tertiary)">
        Model
      </label>
      <select
        id="ai-custom-prompt-model"
        bind:value={aiPrefs.custom_prompt_model}
        class="w-full h-9 px-3 rounded-lg text-sm outline-none border appearance-none cursor-pointer"
        style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
      >
        {#each allowedModels as model}
          <option value={model}>{modelLabel(model)}</option>
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
        class="w-full h-9 px-3 rounded-lg text-sm outline-none border appearance-none cursor-pointer"
        style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
      >
        {#each allowedModels as model}
          <option value={model}>{modelLabel(model)}</option>
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
      Sonnet 4.6 is recommended for its computer use capabilities.
    </p>

    <div>
      <label for="ai-unsubscribe-model" class="block text-xs font-semibold mb-1.5 uppercase tracking-wider" style="color: var(--text-tertiary)">
        Model
      </label>
      <select
        id="ai-unsubscribe-model"
        bind:value={aiPrefs.unsubscribe_model}
        class="w-full h-9 px-3 rounded-lg text-sm outline-none border appearance-none cursor-pointer"
        style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
      >
        {#each allowedModels as model}
          <option value={model}>{modelLabel(model)}</option>
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
          <th class="text-left py-2 text-xs font-semibold uppercase tracking-wider" style="color: var(--text-secondary)">Quality</th>
          <th class="text-left py-2 text-xs font-semibold uppercase tracking-wider" style="color: var(--text-secondary)">Speed</th>
          <th class="text-left py-2 text-xs font-semibold uppercase tracking-wider" style="color: var(--text-secondary)">Cost</th>
        </tr>
      </thead>
      <tbody>
        <tr class="border-b" style="border-color: var(--border-color)">
          <td class="py-2 font-medium" style="color: var(--text-primary)">Opus 4.7</td>
          <td class="py-2" style="color: var(--status-success)">Highest</td>
          <td class="py-2" style="color: var(--text-secondary)">Slower</td>
          <td class="py-2" style="color: var(--text-secondary)">$$$</td>
        </tr>
        <tr class="border-b" style="border-color: var(--border-color)">
          <td class="py-2 font-medium" style="color: var(--text-primary)">Sonnet 4.6</td>
          <td class="py-2" style="color: var(--color-accent-600)">High</td>
          <td class="py-2" style="color: var(--color-accent-600)">Balanced</td>
          <td class="py-2" style="color: var(--text-secondary)">$$</td>
        </tr>
        <tr>
          <td class="py-2 font-medium" style="color: var(--text-primary)">Haiku 4.5</td>
          <td class="py-2" style="color: var(--text-secondary)">Good</td>
          <td class="py-2" style="color: var(--status-success)">Fastest</td>
          <td class="py-2" style="color: var(--status-success)">$</td>
        </tr>
      </tbody>
    </table>
  </div>
</div>
