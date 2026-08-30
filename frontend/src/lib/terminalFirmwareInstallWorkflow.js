import {
  TerminalFirmwareInstallError,
  loadTerminalFirmwareInstallArtifacts,
  validateTerminalFirmwareRomIdentity,
  verifyPreparedTerminalFirmwareInstallArtifacts,
} from './terminalFirmwareInstallPlan.js';
import {
  createTerminalFirmwareStatusRequest,
  readTerminalFirmwareRecoveryStatus,
} from './terminalFirmwareRecovery.js';

export const TERMINAL_FIRMWARE_INSTALL_STATES = Object.freeze([
  'preflight',
  'fetching',
  'verifying',
  'awaiting_rom',
  'probing',
  'flashing',
  'verifying_flash',
  'resetting',
  'awaiting_status',
  'verifying_status',
  'succeeded',
  'cancelled_before_write',
  'blocked',
  'recovery_required',
]);

const KNOWN_ERROR_CODES = new Set([
  'permission_denied',
  'unsupported_chip',
  'flash_too_small',
  'model_unconfirmed',
  'hardware_revision_unqualified',
  'release_unverified',
  'plan_invalid',
  'artifact_unavailable',
  'artifact_invalid',
  'artifact_hash_mismatch',
  'auth_session_changed',
  'crypto_unavailable',
  'rom_identity_invalid',
  'write_interrupted',
  'flash_verify_failed',
  'reset_failed',
  'status_timeout',
  'status_malformed',
  'status_mismatch',
  'transport_invalid',
]);

function frozenEvent(state, detail = {}) {
  return Object.freeze({ state, ...detail });
}

function abortError() {
  const error = new Error('Terminal firmware installation was cancelled.');
  error.name = 'AbortError';
  return error;
}

function throwIfAborted(signal) {
  if (signal?.aborted) throw abortError();
}

function transportMethod(transport, method) {
  if (typeof transport?.[method] !== 'function') {
    throw new TerminalFirmwareInstallError(
      'transport_invalid',
      `Injected terminal transport is missing ${method}().`,
    );
  }
}

function normalizeError(error, stage) {
  if (error?.name === 'AbortError') {
    return new TerminalFirmwareInstallError(
      'write_interrupted',
      'Firmware installation was cancelled or disconnected.',
    );
  }
  if (error instanceof TerminalFirmwareInstallError) return error;
  const candidate = typeof error?.code === 'string' && KNOWN_ERROR_CODES.has(error.code)
    ? error.code
    : null;
  const fallbacks = {
    probing: 'permission_denied',
    flashing: 'write_interrupted',
    verifying_flash: 'flash_verify_failed',
    resetting: 'reset_failed',
    awaiting_status: 'status_timeout',
    verifying_status: 'status_mismatch',
  };
  const code = candidate || fallbacks[stage] || 'transport_invalid';
  return new TerminalFirmwareInstallError(code, `Terminal firmware ${stage} failed closed.`);
}

async function safeClose(transport) {
  try {
    await transport?.close?.();
  } catch {
    // Closing is best effort. It must not hide the recovery state produced by
    // an earlier write, verification, reset, or readback result.
  }
}

function notify(callback, event) {
  try {
    callback(event);
  } catch {
    // UI observers are deliberately outside the transport trust boundary. A
    // rendering or telemetry callback must never interrupt an in-flight write
    // or replace the workflow's authoritative recovery state.
  }
}

/**
 * Execute the transport-independent browser install state machine.
 *
 * No concrete Web Serial or esptool adapter is imported here. Both transports
 * are injected, and all artifact bytes are authenticated before probe/write.
 */
export async function runTerminalFirmwareInstallWorkflow({
  plan,
  preparedPlan = null,
  fetchImpl,
  runtime = globalThis.crypto,
  romTransport,
  applicationTransport,
  signal,
  onState = () => {},
  onProgress = () => {},
  statusTimeoutMs = 5000,
  statusSettleMs = 850,
}) {
  const history = [];
  let state = 'preflight';
  let writeMayHaveStarted = false;
  const emit = (next, detail = {}) => {
    state = next;
    const event = frozenEvent(next, detail);
    history.push(event);
    notify(onState, event);
  };
  const finish = (ok, next, { error = null, status = null, probe = null } = {}) => Object.freeze({
    ok,
    state: next,
    error,
    status,
    probe,
    history: Object.freeze([...history]),
    recoveryRequired: next === 'recovery_required',
  });

  emit('preflight');
  try {
    throwIfAborted(signal);
    transportMethod(romTransport, 'probe');
    transportMethod(romTransport, 'writeSegments');
    transportMethod(romTransport, 'verifySegments');
    transportMethod(romTransport, 'resetToApplication');
    transportMethod(applicationTransport, 'sendStatusRequest');
    transportMethod(applicationTransport, 'readChunks');

    let loadedPlan;
    if (preparedPlan) {
      emit('verifying', { segmentCount: preparedPlan.segments?.length || 0 });
      loadedPlan = await verifyPreparedTerminalFirmwareInstallArtifacts(preparedPlan, { runtime, signal });
    } else {
      emit('fetching');
      loadedPlan = await loadTerminalFirmwareInstallArtifacts(plan, { fetchImpl, runtime, signal });
      emit('verifying', { segmentCount: loadedPlan.segments.length });
    }
    throwIfAborted(signal);

    emit('awaiting_rom');
    throwIfAborted(signal);
    emit('probing');
    const probe = validateTerminalFirmwareRomIdentity(await romTransport.probe({ signal }), loadedPlan);
    throwIfAborted(signal);

    emit('flashing', { segmentCount: loadedPlan.segments.length });
    // From this point forward the injected writer may have changed flash even
    // if it disconnects before reporting progress. Every failure therefore
    // requires explicit recovery rather than a silent retry.
    writeMayHaveStarted = true;
    await romTransport.writeSegments(loadedPlan.segments, {
      signal,
      eraseAll: false,
      onProgress(progress) {
        const event = Object.freeze({ stage: 'flashing', ...progress });
        notify(onProgress, event);
      },
    });
    throwIfAborted(signal);

    emit('verifying_flash');
    const verified = await romTransport.verifySegments(loadedPlan.segments, { signal });
    if (verified !== true) {
      throw new TerminalFirmwareInstallError('flash_verify_failed', 'ROM flash readback did not verify.');
    }
    throwIfAborted(signal);

    emit('resetting');
    const reset = await romTransport.resetToApplication({ signal });
    if (reset !== true) {
      throw new TerminalFirmwareInstallError('reset_failed', 'Terminal did not reset into application firmware.');
    }
    throwIfAborted(signal);

    emit('awaiting_status', { baudRate: 115200 });
    const statusRequestSent = await applicationTransport.sendStatusRequest({
      baudRate: 115200,
      bytes: createTerminalFirmwareStatusRequest(),
      signal,
    });
    if (statusRequestSent !== true) {
      throw new TerminalFirmwareInstallError('status_timeout', 'RET1 status request was not accepted by the transport.');
    }
    throwIfAborted(signal);
    const chunks = applicationTransport.readChunks({
      baudRate: 115200,
      timeoutMs: statusTimeoutMs,
      signal,
    });
    const status = await readTerminalFirmwareRecoveryStatus({
      chunks,
      expected: loadedPlan.expectedStatus,
      factoryMac: probe.factoryMac,
      signal,
      timeoutMs: statusTimeoutMs,
      settleMs: statusSettleMs,
    });
    emit('verifying_status');
    emit('succeeded', {
      model: status.model,
      firmwareVersion: status.firmware_version,
      runningPartition: status.running_partition,
    });
    return finish(true, 'succeeded', { status, probe });
  } catch (rawError) {
    const wasAbort = rawError?.name === 'AbortError';
    const error = normalizeError(rawError, state);
    const terminalState = writeMayHaveStarted
      ? 'recovery_required'
      : (wasAbort ? 'cancelled_before_write' : 'blocked');
    emit(terminalState, { code: error.code });
    return finish(false, terminalState, { error });
  } finally {
    await safeClose(applicationTransport);
    await safeClose(romTransport);
  }
}
