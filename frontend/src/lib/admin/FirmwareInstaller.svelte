<script>
  import { onDestroy, onMount } from 'svelte';
  import { createAuthenticatedSessionGuard } from '../stores.js';
  import {
    getTerminalFirmwareCatalog,
    getTerminalFirmwareReleaseEvidence,
    getTerminalOtaCapabilities,
  } from '../terminalFirmwareApi.js';
  import {
    createTerminalFirmwareDeviceSession,
    describeTerminalFirmwareInstallState,
    getTerminalInstallerLock,
    detectTerminalFirmwareSupport,
  } from '../terminalFirmwareInstaller.js';
  import {
    compileTerminalFirmwareInstallPlan,
    loadTerminalFirmwareInstallArtifacts,
  } from '../terminalFirmwareInstallPlan.js';
  import {
    TERMINAL_FIRMWARE_INSTALL_STATES,
    runTerminalFirmwareInstallWorkflow,
  } from '../terminalFirmwareInstallWorkflow.js';
  import { validateTerminalFirmwareCatalog } from '../terminalFirmwarePolicy.js';
  import { verifyTerminalFirmwareRelease } from '../terminalFirmwareVerifier.js';

  const sessionGuard = createAuthenticatedSessionGuard();
  const deviceSession = createTerminalFirmwareDeviceSession();
  const PRODUCTION_TRANSPORT_AVAILABLE = false;

  let loading = $state(true);
  let loadError = $state('');
  let audit = $state({ valid: false, errors: [], catalog: null });
  let releaseVerification = $state({});
  let otaCapabilities = $state({
    state: 'locked',
    effective_offer_enabled: false,
    blockers: ['Device OTA capability has not been checked.'],
  });
  let support = $state({ secureContext: false, webSerial: false, webLocks: false, supported: false, blockers: [] });
  let selectedReleaseId = $state('');
  let selectedModelName = $state('');
  let selectedHardwareRevision = $state('');
  let packageState = $state('idle');
  let packageDetail = $state('Choose an exact release, model, and physical hardware revision.');
  let packageProgress = $state({ completed: 0, total: 4, role: '' });
  let preparedPlan = $state(null);
  let workflowState = $state('preflight');
  let workflowErrorCode = $state('');
  let workflowProgress = $state(null);
  let deviceConnected = $state(false);
  let disconnecting = $state(false);
  let preflightController = null;
  let preflightGeneration = 0;
  let operationController = null;
  let lock = $derived(getTerminalInstallerLock(audit, support));
  let selectedRelease = $derived(
    audit.catalog?.releases?.find(release => release.release_id === selectedReleaseId) || null,
  );
  let selectedModel = $derived(
    selectedRelease?.models?.find(model => model.model === selectedModelName) || null,
  );
  let selectedVerification = $derived(releaseVerification[selectedReleaseId] || null);
  let preflightBlockers = $derived(selectionBlockers());
  let canPreparePackage = $derived(
    preflightBlockers.length === 0 && !['fetching', 'verifying'].includes(packageState),
  );
  let workflowPresentation = $derived(
    describeTerminalFirmwareInstallState(workflowState, workflowErrorCode),
  );

  function formatGitSha(value) {
    return typeof value === 'string' ? value.slice(0, 8) : 'unknown';
  }

  function formatReleaseDate(epoch) {
    if (!Number.isSafeInteger(epoch) || epoch <= 0) return 'Unknown build date';
    const date = new Date(epoch * 1000);
    if (Number.isNaN(date.getTime())) return 'Unknown build date';
    return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })
      .format(date);
  }

  function formatBytes(value) {
    if (!Number.isSafeInteger(value) || value < 0) return 'Unknown size';
    if (value < 1024) return `${value} B`;
    return `${(value / (1024 * 1024)).toFixed(2)} MB`;
  }

  function operatorToneStyle(tone) {
    if (tone === 'danger') {
      return 'background: var(--status-error-bg); border-color: var(--status-error-border); color: var(--status-error-text)';
    }
    if (tone === 'warning') {
      return 'background: var(--status-warning-bg); border-color: var(--status-warning-border); color: var(--status-warning-text)';
    }
    if (tone === 'success') {
      return 'background: var(--status-success-bg); border-color: var(--status-success-border); color: var(--status-success-text)';
    }
    return 'background: var(--bg-primary); border-color: var(--border-color); color: var(--text-secondary)';
  }

  function selectDefaults(releases) {
    const release = releases?.[0] || null;
    selectedReleaseId = release?.release_id || '';
    const model = release?.models?.find(candidate => ['E1001', 'E1002'].includes(candidate.model)) || null;
    selectedModelName = model?.model || '';
    selectedHardwareRevision = model?.hardware_revisions?.[0] || '';
    clearPreparedPackage();
  }

  function selectionBlockers() {
    const blockers = [];
    if (!selectedRelease) blockers.push('Select a signed firmware release.');
    if (selectedVerification?.state !== 'verified') {
      blockers.push('The exact manifest bytes and Ed25519 signature must verify in this browser.');
    }
    if (selectedRelease?.manifest_schema_version !== 2) blockers.push('Browser install requires manifest schema 2.');
    if (!selectedModel || !['E1001', 'E1002'].includes(selectedModel.model)) {
      blockers.push('Only E1001 and E1002 are eligible for browser install qualification.');
    }
    if (selectedModel && selectedModel.browser_flash_qualified !== true) {
      blockers.push('This model has not completed browser-flash qualification.');
    }
    if (selectedModel && selectedModel.install_eligible !== true) {
      blockers.push(...(selectedModel.blockers || ['Server-side browser install is locked.']));
    }
    if (!selectedHardwareRevision
      || !selectedModel?.hardware_revisions?.includes(selectedHardwareRevision)) {
      blockers.push('Confirm an approved physical hardware revision printed on the terminal.');
    }
    return [...new Set(blockers)];
  }

  function clearPreparedPackage() {
    preflightGeneration += 1;
    preflightController?.abort();
    preflightController = null;
    preparedPlan = null;
    packageState = 'idle';
    packageDetail = 'Choose an exact release, model, and physical hardware revision.';
    packageProgress = { completed: 0, total: 4, role: '' };
    if (!deviceConnected) {
      workflowState = 'preflight';
      workflowErrorCode = '';
      workflowProgress = null;
    }
  }

  function chooseRelease(event) {
    selectedReleaseId = event.currentTarget.value;
    const release = audit.catalog?.releases?.find(candidate => candidate.release_id === selectedReleaseId);
    const model = release?.models?.find(candidate => ['E1001', 'E1002'].includes(candidate.model)) || null;
    selectedModelName = model?.model || '';
    selectedHardwareRevision = model?.hardware_revisions?.[0] || '';
    clearPreparedPackage();
  }

  function chooseModel(event) {
    selectedModelName = event.currentTarget.value;
    const model = selectedRelease?.models?.find(candidate => candidate.model === selectedModelName);
    selectedHardwareRevision = model?.hardware_revisions?.[0] || '';
    clearPreparedPackage();
  }

  function chooseHardwareRevision(event) {
    selectedHardwareRevision = event.currentTarget.value;
    clearPreparedPackage();
  }

  async function preparePackage() {
    if (!canPreparePackage || !sessionGuard.isCurrent()) return;
    const generation = ++preflightGeneration;
    preflightController?.abort();
    preflightController = new AbortController();
    preparedPlan = null;
    packageState = 'fetching';
    packageDetail = 'Compiling the exact preserve-config plan before downloading any artifact bytes.';
    workflowState = 'fetching';
    workflowErrorCode = '';
    try {
      const plan = compileTerminalFirmwareInstallPlan({
        release: selectedRelease,
        verification: selectedVerification.result,
        model: selectedModelName,
        hardwareRevision: selectedHardwareRevision,
      });
      const loaded = await loadTerminalFirmwareInstallArtifacts(plan, {
        signal: preflightController.signal,
        onProgress(progress) {
          if (!sessionGuard.isCurrent() || generation !== preflightGeneration) return;
          packageProgress = progress;
          packageDetail = `Verified ${progress.role.replaceAll('_', ' ')} (${progress.completed} of ${progress.total}).`;
        },
      });
      if (!sessionGuard.isCurrent() || generation !== preflightGeneration) return;
      packageState = 'verifying';
      workflowState = 'verifying';
      preparedPlan = loaded;
      packageState = 'ready';
      packageDetail = 'All four artifacts passed exact byte-length and SHA-256 verification before device connection.';
      workflowState = 'awaiting_rom';
    } catch (error) {
      if (!sessionGuard.isCurrent() || generation !== preflightGeneration) return;
      if (error?.name === 'AbortError') {
        packageState = 'idle';
        packageDetail = 'Package preparation was cancelled before device connection.';
        workflowState = 'cancelled_before_write';
        return;
      }
      packageState = 'blocked';
      packageDetail = error?.message || 'Firmware package preflight failed closed.';
      workflowState = 'blocked';
      workflowErrorCode = error?.code || 'preflight_failed';
    } finally {
      if (generation === preflightGeneration) preflightController = null;
    }
  }

  // This is the only bridge from the operator UI to the pure workflow. No
  // production transport calls it until the physical HIL gate is complete.
  async function runPreparedInstall({ romTransport, applicationTransport }) {
    if (!preparedPlan || !PRODUCTION_TRANSPORT_AVAILABLE || !sessionGuard.isCurrent()) return null;
    operationController = new AbortController();
    deviceSession.attach({
      abortController: operationController,
      transports: [applicationTransport, romTransport],
    });
    deviceConnected = true;
    try {
      const result = await runTerminalFirmwareInstallWorkflow({
        preparedPlan,
        romTransport,
        applicationTransport,
        signal: operationController.signal,
        onState(event) {
          if (!sessionGuard.isCurrent() || !TERMINAL_FIRMWARE_INSTALL_STATES.includes(event.state)) return;
          workflowState = event.state;
          workflowErrorCode = event.code || '';
        },
        onProgress(progress) {
          if (sessionGuard.isCurrent()) workflowProgress = progress;
        },
      });
      workflowState = result.state;
      workflowErrorCode = result.error?.code || '';
      return result;
    } finally {
      await deviceSession.disconnect();
      operationController = null;
      deviceConnected = false;
    }
  }

  async function disconnectDevice() {
    disconnecting = true;
    operationController?.abort();
    await deviceSession.disconnect();
    operationController = null;
    deviceConnected = false;
    disconnecting = false;
  }

  async function loadCatalog() {
    loading = true;
    loadError = '';
    try {
      const catalog = await getTerminalFirmwareCatalog();
      if (!sessionGuard.isCurrent()) return;
      audit = validateTerminalFirmwareCatalog(catalog);
      if (!audit.valid) return;
      selectDefaults(audit.catalog.releases);
      releaseVerification = Object.fromEntries(
        audit.catalog.releases.map(release => [release.release_id, { state: 'checking', errors: [] }]),
      );
      for (const release of audit.catalog.releases) {
        try {
          const evidence = await getTerminalFirmwareReleaseEvidence(release.release_id);
          if (!sessionGuard.isCurrent()) return;
          const verification = await verifyTerminalFirmwareRelease({ release, ...evidence });
          if (!sessionGuard.isCurrent()) return;
          releaseVerification = {
            ...releaseVerification,
            [release.release_id]: {
              state: verification.valid ? 'verified' : 'locked',
              errors: verification.errors,
              result: verification,
            },
          };
        } catch (error) {
          if (!sessionGuard.isCurrent()) return;
          releaseVerification = {
            ...releaseVerification,
            [release.release_id]: {
              state: 'locked',
              errors: [error?.message || 'Exact signed metadata is unavailable.'],
              result: null,
            },
          };
        }
      }
    } catch (error) {
      if (!sessionGuard.isCurrent()) return;
      audit = { valid: false, errors: [], catalog: null };
      releaseVerification = {};
      loadError = error?.message || 'Firmware catalog is unavailable.';
    } finally {
      if (sessionGuard.isCurrent()) loading = false;
    }
  }

  async function loadOtaCapabilities() {
    try {
      const capabilities = await getTerminalOtaCapabilities();
      if (!sessionGuard.isCurrent()) return;
      otaCapabilities = capabilities;
    } catch (error) {
      if (!sessionGuard.isCurrent()) return;
      otaCapabilities = {
        state: 'locked',
        effective_offer_enabled: false,
        blockers: [error?.message || 'Device OTA capability is unavailable.'],
      };
    }
  }

  onMount(() => {
    support = detectTerminalFirmwareSupport();
    void loadCatalog();
    void loadOtaCapabilities();
  });

  onDestroy(() => {
    preflightGeneration += 1;
    preflightController?.abort();
    operationController?.abort();
    preparedPlan = null;
    void deviceSession.disconnect();
    sessionGuard.dispose();
  });
</script>

<section
  class="rounded-xl border p-5"
  style="background: var(--bg-secondary); border-color: var(--border-color)"
  aria-labelledby="browser-firmware-installer-title"
>
  <div class="flex flex-wrap items-start justify-between gap-3">
    <div>
      <h4 id="browser-firmware-installer-title" class="text-sm font-semibold" style="color: var(--text-primary)">
        Browser firmware installer
      </h4>
      <p class="text-[11px] mt-0.5 max-w-3xl" style="color: var(--text-tertiary)">
        Inspect signed releases and prepare a fully hashed preserve-config package in this browser. Device connection, erase, and flash remain locked until the physical recovery gate is complete.
      </p>
    </div>
    <span
      class="inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider"
      style="background: var(--status-warning-bg); border-color: var(--status-warning-border); color: var(--status-warning-text)"
    >Transport locked</span>
  </div>

  <div class="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-2" aria-label="Browser firmware prerequisites">
    {#each [
      { label: 'Secure HTTPS context', ready: support.secureContext },
      { label: 'Web Serial available', ready: support.webSerial },
      { label: 'Web Locks available', ready: support.webLocks },
    ] as item (item.label)}
      <div class="rounded-lg border px-3 py-2 text-xs" style="background: var(--bg-primary); border-color: var(--border-color)">
        <span aria-hidden="true" style="color: {item.ready ? 'var(--status-success, #10b981)' : 'var(--text-tertiary)'}">{item.ready ? '●' : '○'}</span>
        <span class="ml-1" style="color: var(--text-secondary)">{item.label}</span>
      </div>
    {/each}
  </div>

  <div
    class="mt-4 rounded-lg border px-3 py-3 text-xs"
    style="background: var(--bg-primary); border-color: var(--border-color)"
    aria-label="Device OTA capability"
  >
    <div class="flex flex-wrap items-baseline justify-between gap-2">
      <p class="font-semibold" style="color: var(--text-secondary)">Device OTA</p>
      <span class="text-[10px] font-semibold uppercase tracking-wider" style="color: var(--text-tertiary)">
        {otaCapabilities?.effective_offer_enabled ? 'Ready' : 'Locked'}
      </span>
    </div>
    {#if !otaCapabilities?.effective_offer_enabled}
      <ul class="mt-1.5 space-y-1 list-disc pl-4" style="color: var(--text-tertiary)">
        {#each (otaCapabilities?.blockers || []).slice(0, 4) as blocker}
          <li>{blocker}</li>
        {/each}
      </ul>
    {/if}
    <p class="mt-2 text-[10px]" style="color: var(--text-tertiary)">
      No update offer, firmware download, or device event endpoint is enabled by this status surface.
    </p>
  </div>

  {#if loading}
    <p class="mt-4 text-xs" style="color: var(--text-tertiary)" role="status">Checking the signed firmware catalog…</p>
  {:else if loadError}
    <div class="mt-4 rounded-lg border px-3 py-2 text-xs" style="background: var(--status-warning-bg); border-color: var(--status-warning-border); color: var(--status-warning-text)" role="status">
      Catalog unavailable: {loadError}
    </div>
  {:else if !audit.valid}
    <div class="mt-4 rounded-lg border px-3 py-2 text-xs" style="background: var(--status-error-bg); border-color: var(--status-error-border); color: var(--status-error-text)" role="alert">
      <p class="font-semibold">Catalog metadata failed the browser safety audit.</p>
      {#each audit.errors as error}
        <p class="mt-1">{error}</p>
      {/each}
    </div>
  {:else}
    <div class="mt-4">
      <div class="flex flex-wrap items-baseline justify-between gap-2">
        <h5 class="text-xs font-semibold" style="color: var(--text-primary)">Verified server catalog</h5>
        <span class="text-[10px]" style="color: var(--text-tertiary)">
          {audit.catalog.releases.length} approved {audit.catalog.releases.length === 1 ? 'release' : 'releases'}
        </span>
      </div>

      {#if audit.catalog.releases.length === 0}
        <p class="mt-2 text-xs" style="color: var(--text-tertiary)">No signed release has been staged for browser inspection.</p>
      {:else}
        <div class="mt-2 space-y-2">
          {#each audit.catalog.releases as release (release.release_id)}
            {@const verification = releaseVerification[release.release_id]}
            <article class="rounded-lg border p-3" style="background: var(--bg-primary); border-color: var(--border-color)">
              <div class="flex flex-wrap items-baseline justify-between gap-2">
                <div class="text-xs font-semibold" style="color: var(--text-primary)">{release.firmware_version}</div>
                <div class="text-[10px]" style="color: var(--text-tertiary)">{formatReleaseDate(release.source_date_epoch)}</div>
              </div>
              <div class="mt-1 text-[10px] font-mono break-all" style="color: var(--text-tertiary)">
                Git {formatGitSha(release.git_sha)} · key {release.signing_key_id} · manifest {release.release_id.slice(0, 12)}…
              </div>
              <div
                class="mt-2 rounded-md border px-2.5 py-2 text-[10px]"
                style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-secondary)"
                role="status"
              >
                {#if verification?.state === 'checking'}
                  Checking exact manifest bytes and detached signature…
                {:else if verification?.state === 'verified'}
                  Exact manifest bytes and Ed25519 signature verified in this browser. Flashing remains locked.
                {:else}
                  Browser signature preflight locked{verification?.errors?.[0] ? `: ${verification.errors[0]}` : '.'}
                {/if}
              </div>
              <div class="mt-2 flex flex-wrap gap-1.5">
                {#each release.models as model (model.model)}
                  <span
                    class="inline-flex rounded-full border px-2 py-1 text-[10px]"
                    style="border-color: var(--border-color); color: var(--text-secondary)"
                    title={model.blockers.join(' ') || 'Server-qualified release metadata'}
                  >
                    {model.model} · {model.browser_flash_qualified ? 'qualified metadata' : 'not qualified'}
                  </span>
                {/each}
              </div>
            </article>
          {/each}
        </div>
      {/if}
    </div>
  {/if}

  <div class="mt-4 rounded-lg border p-3 sm:p-4" style="background: var(--bg-primary); border-color: var(--border-color)" aria-labelledby="firmware-package-preflight-title">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h5 id="firmware-package-preflight-title" class="text-xs font-semibold" style="color: var(--text-primary)">Prepare an installation package</h5>
        <p class="mt-1 max-w-3xl text-[10px] leading-4" style="color: var(--text-tertiary)">
          Confirm the label printed on the terminal. USB identity cannot distinguish E1001, E1002, E1004, or a physical hardware revision.
        </p>
      </div>
      <span class="rounded-full border px-2 py-1 text-[10px] font-semibold uppercase tracking-wider" style={operatorToneStyle(workflowPresentation.tone)}>
        {workflowPresentation.title}
      </span>
    </div>

    <div class="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
      <label class="block" for="firmware-release-selection">
        <span class="text-[10px] font-semibold uppercase tracking-wider" style="color: var(--text-tertiary)">Signed release</span>
        <select
          id="firmware-release-selection"
          value={selectedReleaseId}
          onchange={chooseRelease}
          disabled={loading || !audit.valid || audit.catalog?.releases?.length === 0 || deviceConnected}
          class="mt-1 h-10 w-full rounded-lg border px-2 text-xs disabled:opacity-50"
          style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-primary)"
        >
          {#if !selectedReleaseId}<option value="">No release staged</option>{/if}
          {#each audit.catalog?.releases || [] as release (release.release_id)}
            <option value={release.release_id}>{release.firmware_version} · {formatGitSha(release.git_sha)}</option>
          {/each}
        </select>
      </label>

      <label class="block" for="firmware-model-selection">
        <span class="text-[10px] font-semibold uppercase tracking-wider" style="color: var(--text-tertiary)">Physical model</span>
        <select
          id="firmware-model-selection"
          value={selectedModelName}
          onchange={chooseModel}
          disabled={!selectedRelease || deviceConnected}
          class="mt-1 h-10 w-full rounded-lg border px-2 text-xs disabled:opacity-50"
          style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-primary)"
        >
          {#if !selectedModelName}<option value="">Select model</option>{/if}
          {#each selectedRelease?.models || [] as model (model.model)}
            <option value={model.model}>{model.model} · {model.partition_layout}</option>
          {/each}
        </select>
      </label>

      <label class="block" for="firmware-revision-selection">
        <span class="text-[10px] font-semibold uppercase tracking-wider" style="color: var(--text-tertiary)">Printed revision</span>
        <select
          id="firmware-revision-selection"
          value={selectedHardwareRevision}
          onchange={chooseHardwareRevision}
          disabled={!selectedModel || selectedModel.hardware_revisions.length === 0 || deviceConnected}
          class="mt-1 h-10 w-full rounded-lg border px-2 text-xs disabled:opacity-50"
          style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-primary)"
        >
          {#if !selectedHardwareRevision}<option value="">No approved revision</option>{/if}
          {#each selectedModel?.hardware_revisions || [] as revision (revision)}
            <option value={revision}>{revision}</option>
          {/each}
        </select>
      </label>
    </div>

    <div class="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2" aria-label="Firmware compatibility gates">
      {#each [
        { label: 'Exact signature', ready: selectedVerification?.state === 'verified' },
        { label: 'Manifest schema 2', ready: selectedRelease?.manifest_schema_version === 2 },
        { label: 'E1001/E1002 model', ready: ['E1001', 'E1002'].includes(selectedModelName) },
        { label: 'Server qualification', ready: selectedModel?.install_eligible === true },
        { label: 'Physical revision confirmed', ready: Boolean(selectedHardwareRevision && selectedModel?.hardware_revisions?.includes(selectedHardwareRevision)) },
        { label: 'Preserves NVS + LittleFS', ready: selectedModel?.artifacts?.every(artifact => artifact.preserves_nvs && artifact.preserves_littlefs) === true },
      ] as gate (gate.label)}
        <div class="rounded-md border px-2.5 py-2 text-[10px]" style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-secondary)">
          <span aria-hidden="true" style="color: {gate.ready ? 'var(--status-success, #10b981)' : 'var(--text-tertiary)'}">{gate.ready ? '●' : '○'}</span>
          <span class="ml-1">{gate.label}</span>
        </div>
      {/each}
    </div>

    {#if preflightBlockers.length > 0}
      <ul class="mt-3 space-y-1 rounded-md border p-3 text-[10px] list-disc pl-7" style="background: var(--status-warning-bg); border-color: var(--status-warning-border); color: var(--status-warning-text)">
        {#each preflightBlockers.slice(0, 6) as blocker}
          <li>{blocker}</li>
        {/each}
      </ul>
    {/if}

    <div class="mt-3 rounded-md border p-3 text-[10px]" style={operatorToneStyle(workflowPresentation.tone)} aria-live="polite">
      <p class="font-semibold">{workflowPresentation.title}</p>
      <p class="mt-1">{packageState === 'idle' ? workflowPresentation.detail : packageDetail}</p>
      {#if packageState === 'fetching' && packageProgress.completed > 0}
        <p class="mt-1 font-mono">{packageProgress.completed}/{packageProgress.total} · {packageProgress.role}</p>
      {/if}
      {#if workflowProgress?.role}
        <p class="mt-1 font-mono">Writing {workflowProgress.role} · {formatBytes(workflowProgress.bytesWritten || 0)}</p>
      {/if}
      {#if workflowErrorCode}<p class="mt-1 font-mono">{workflowErrorCode}</p>{/if}
    </div>

    {#if preparedPlan}
      <div class="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2" aria-label="Verified firmware segments">
        {#each preparedPlan.segments as segment (segment.role)}
          <div class="rounded-md border p-2.5" style="background: var(--bg-secondary); border-color: var(--border-color)">
            <div class="flex items-center justify-between gap-2 text-[10px]">
              <span class="font-semibold capitalize" style="color: var(--text-secondary)">{segment.role.replaceAll('_', ' ')}</span>
              <span class="font-mono" style="color: var(--text-tertiary)">0x{segment.offset.toString(16)}</span>
            </div>
            <p class="mt-1 text-[10px]" style="color: var(--text-tertiary)">{formatBytes(segment.size)} · SHA-256 {segment.sha256.slice(0, 12)}…</p>
          </div>
        {/each}
      </div>
    {/if}

    {#if workflowPresentation.recoveryRequired}
      <div class="mt-3 rounded-md border p-3 text-xs" style="background: var(--status-error-bg); border-color: var(--status-error-border); color: var(--status-error-text)" role="alert">
        <p class="font-semibold">Do not retry automatically or use erase-all.</p>
        <ol class="mt-1.5 list-decimal space-y-1 pl-5 text-[10px]">
          <li>Keep USB connected and return the terminal to ESP32-S3 ROM download mode.</li>
          <li>Confirm the same physical model and revision again.</li>
          <li>Rerun this exact four-segment preserve-config package, or use the documented CLI recovery path.</li>
        </ol>
      </div>
    {/if}

    <div class="mt-3 flex flex-wrap gap-2">
      <button
        type="button"
        onclick={preparePackage}
        disabled={!canPreparePackage}
        class="inline-flex min-h-9 items-center justify-center rounded-lg bg-accent-600 px-3 text-xs font-medium text-white hover:bg-accent-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {packageState === 'fetching' ? 'Verifying package…' : preparedPlan ? 'Verify package again' : 'Verify installation package'}
      </button>
      <button
        type="button"
        onclick={clearPreparedPackage}
        disabled={!preparedPlan || deviceConnected}
        class="inline-flex min-h-9 items-center justify-center rounded-lg border px-3 text-xs font-medium disabled:opacity-50"
        style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-secondary)"
      >Clear package</button>
      <button
        type="button"
        disabled={!PRODUCTION_TRANSPORT_AVAILABLE || !preparedPlan}
        class="inline-flex min-h-9 items-center justify-center rounded-lg border px-3 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-50"
        style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-secondary)"
        title="Real device transport remains locked until E1001/E1002 hardware-in-the-loop qualification is complete."
      >Connect &amp; install</button>
      <button
        type="button"
        onclick={disconnectDevice}
        disabled={!deviceConnected || disconnecting}
        class="inline-flex min-h-9 items-center justify-center rounded-lg border px-3 text-xs font-medium disabled:opacity-50"
        style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-secondary)"
      >{disconnecting ? 'Disconnecting…' : 'Disconnect device'}</button>
    </div>
    <p class="mt-2 text-[10px]" style="color: var(--text-tertiary)">
      Package verification may download signed firmware bytes. It never requests a serial port. Device transport is not present in this build.
    </p>
  </div>

  <div class="mt-4 rounded-lg border px-3 py-3 text-xs" style="background: var(--bg-primary); border-color: var(--border-color)">
    <p class="font-semibold" style="color: var(--text-secondary)">Why flashing is locked</p>
    <ul class="mt-1.5 space-y-1 list-disc pl-4" style="color: var(--text-tertiary)">
      {#each lock.blockers as blocker}
        <li>{blocker}</li>
      {/each}
    </ul>
    <p class="mt-2 text-[10px] font-medium" style="color: var(--text-secondary)">
      This screen can verify signed artifact bytes, but it never requests a serial port and cannot write or erase a terminal.
    </p>
  </div>
</section>
