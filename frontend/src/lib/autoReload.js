/**
 * Auto-reload module: polls /api/build-version and reloads the page
 * when the build version changes (i.e. after scripts/restart.sh runs).
 */

const POLL_INTERVAL_MS = 5000;
const BUILD_VERSION_URL = '/api/build-version';

let knownVersion = null;
let pollTimer = null;

async function fetchBuildVersion() {
  try {
    const resp = await fetch(BUILD_VERSION_URL);
    if (!resp.ok) {
      return null;
    }
    const data = await resp.json();
    return data.version || null;
  } catch {
    // Backend may be temporarily down during restart — silently ignore
    return null;
  }
}

async function checkForUpdate() {
  const currentVersion = await fetchBuildVersion();
  if (currentVersion === null) {
    // Backend unreachable, skip this cycle
    return;
  }
  if (knownVersion === null) {
    // First successful fetch — just record it
    knownVersion = currentVersion;
    return;
  }
  if (currentVersion !== knownVersion) {
    // Version changed — reload the page
    console.log('[autoReload] Build version changed, reloading...');
    stopVersionPolling();
    window.location.reload();
  }
}

export function startVersionPolling() {
  if (pollTimer !== null) {
    return; // Already polling
  }
  // Do an initial fetch to record the current version
  checkForUpdate();
  pollTimer = setInterval(checkForUpdate, POLL_INTERVAL_MS);
}

export function stopVersionPolling() {
  if (pollTimer !== null) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}
