import {
  RET1_LIMITS,
  Ret1ProtocolError,
  parseRet1Line,
  validateStatus,
} from './terminalEnrollmentProtocol.js';
import { TerminalFirmwareInstallError } from './terminalFirmwareInstallPlan.js';

const RET1_PREFIX = new TextEncoder().encode('@RET1');
const SUCCESS_STATES = new Set(['config_ready', 'provisioning_required']);
const STATUS_REQUEST_TEXT = '@RET1 {"v":2,"type":"status_request"}\n';

function fail(code, message) {
  throw new TerminalFirmwareInstallError(code, message);
}

function bytes(value) {
  if (value instanceof Uint8Array) return value;
  if (value instanceof ArrayBuffer) return new Uint8Array(value);
  if (ArrayBuffer.isView(value)) {
    return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  }
  fail('status_malformed', 'Terminal status transport returned a non-byte chunk.');
}

function beginsWith(value, prefix) {
  return value.length >= prefix.length && prefix.every((item, index) => value[index] === item);
}

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

export function createTerminalFirmwareStatusRequest() {
  return new TextEncoder().encode(STATUS_REQUEST_TEXT);
}

function expectedIdentity(expected, factoryMac) {
  if (!expected
    || expected.version !== 2
    || !['E1001', 'E1002'].includes(expected.model)
    || typeof expected.firmwareVersion !== 'string'
    || !/^[0-9a-f]{40}$/u.test(expected.firmwareBuildId)
    || expected.partitionLayout !== 'ab-v1'
    || expected.runningPartition !== 'ota_0'
    || typeof factoryMac !== 'string') {
    fail('status_mismatch', 'Expected post-flash identity is incomplete.');
  }
  return expected;
}

/**
 * Apply the strict post-flash success predicate. RET1 remains physical-cable
 * readback and is never promoted to device attestation.
 */
export function verifyTerminalFirmwareRecoveryStatus(status, expected, factoryMac) {
  expectedIdentity(expected, factoryMac);
  let value;
  try {
    value = validateStatus(status);
  } catch (error) {
    if (error instanceof Ret1ProtocolError) {
      fail('status_malformed', 'Terminal returned a malformed RET1 status frame.');
    }
    throw error;
  }
  if (value.v !== expected.version
    || value.model !== expected.model
    || value.firmware_version !== expected.firmwareVersion
    || value.firmware_build_id !== expected.firmwareBuildId
    || value.factory_mac !== factoryMac
    || value.partition_layout !== expected.partitionLayout
    || value.running_partition !== expected.runningPartition
    || value.partition_identity_valid !== true
    || value.boot_state !== 'stable'
    || !SUCCESS_STATES.has(value.state)
    || value.identity_strength !== 'physical_cable_only'
    || value.attestation !== false) {
    fail('status_mismatch', 'Post-flash terminal identity does not match the signed install plan.');
  }
  return Object.freeze({ ...value });
}

export class TerminalFirmwareStatusReader {
  constructor({ expected, factoryMac }) {
    this.expected = expectedIdentity(expected, factoryMac);
    this.factoryMac = factoryMac;
    this.line = [];
    this.discardingDiagnostic = false;
    this.status = null;
    this.statusCanonical = null;
  }

  #consumeLine(rawLine) {
    let line = Uint8Array.from(rawLine);
    if (line[line.length - 1] === 0x0d) line = line.subarray(0, line.length - 1);
    if (!beginsWith(line, RET1_PREFIX)) return;
    if (line.length > RET1_LIMITS.maxLineBytes) {
      fail('status_malformed', 'RET1 status frame exceeds its byte limit.');
    }
    let parsed;
    try {
      parsed = parseRet1Line(line);
    } catch (error) {
      if (error instanceof Ret1ProtocolError) {
        fail('status_malformed', 'Terminal returned a malformed RET1 frame.');
      }
      throw error;
    }
    const verified = verifyTerminalFirmwareRecoveryStatus(parsed, this.expected, this.factoryMac);
    const serialized = canonical(verified);
    if (this.statusCanonical !== null && this.statusCanonical !== serialized) {
      fail('status_mismatch', 'Terminal returned contradictory post-flash status frames.');
    }
    this.status = verified;
    this.statusCanonical = serialized;
  }

  push(chunk) {
    for (const item of bytes(chunk)) {
      if (item === 0x0a) {
        if (!this.discardingDiagnostic) this.#consumeLine(this.line);
        this.line = [];
        this.discardingDiagnostic = false;
        continue;
      }
      if (this.discardingDiagnostic) continue;
      this.line.push(item);
      if (this.line.length > RET1_LIMITS.maxLineBytes) {
        if (beginsWith(Uint8Array.from(this.line), RET1_PREFIX)) {
          fail('status_malformed', 'RET1 status frame exceeds its byte limit.');
        }
        this.line = [];
        this.discardingDiagnostic = true;
      }
    }
    return this.status;
  }

  finish() {
    if (!this.discardingDiagnostic && this.line.length > 0) {
      if (beginsWith(Uint8Array.from(this.line), RET1_PREFIX)) {
        fail('status_malformed', 'Terminal ended an incomplete RET1 status frame.');
      }
      this.line = [];
    }
    if (!this.status) fail('status_timeout', 'No matching RET1 status v2 frame was observed.');
    return this.status;
  }
}

function abortError() {
  const error = new Error('Terminal status read was cancelled.');
  error.name = 'AbortError';
  return error;
}

function nextWithDeadline(iterator, milliseconds, signal) {
  if (signal?.aborted) return Promise.reject(abortError());
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = callback => value => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener?.('abort', onAbort);
      callback(value);
    };
    const onAbort = () => finish(reject)(abortError());
    const timer = setTimeout(
      () => finish(reject)(new TerminalFirmwareInstallError('status_timeout', 'RET1 status read timed out.')),
      milliseconds,
    );
    signal?.addEventListener?.('abort', onAbort, { once: true });
    Promise.resolve(iterator.next()).then(finish(resolve), finish(reject));
  });
}

async function closeIterator(iterator) {
  if (typeof iterator?.return !== 'function') return;
  let timer;
  try {
    await Promise.race([
      Promise.resolve(iterator.return()),
      new Promise(resolve => {
        timer = setTimeout(resolve, 100);
      }),
    ]);
  } catch {
    // The owning application transport is closed by the workflow. Iterator
    // cleanup remains best effort and may not turn a bounded read into a hang.
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Consume a bounded async byte stream. After the first valid status, a short
 * settle window catches the duplicate status emitted by enrollment-capable
 * firmware and rejects any contradiction.
 */
export async function readTerminalFirmwareRecoveryStatus({
  chunks,
  expected,
  factoryMac,
  signal,
  timeoutMs = 5000,
  settleMs = 850,
}) {
  if (!chunks?.[Symbol.asyncIterator]
    || !Number.isSafeInteger(timeoutMs)
    || timeoutMs <= 0
    || !Number.isSafeInteger(settleMs)
    || settleMs < 0
    || settleMs > timeoutMs) {
    fail('status_malformed', 'Terminal status stream contract is invalid.');
  }
  const reader = new TerminalFirmwareStatusReader({ expected, factoryMac });
  const iterator = chunks[Symbol.asyncIterator]();
  const expiresAt = Date.now() + timeoutMs;
  try {
    while (true) {
      const remaining = expiresAt - Date.now();
      if (remaining <= 0) return reader.finish();
      const wait = reader.status && settleMs > 0 ? Math.min(remaining, settleMs) : remaining;
      let next;
      try {
        next = await nextWithDeadline(iterator, Math.max(1, wait), signal);
      } catch (error) {
        if (error instanceof TerminalFirmwareInstallError && error.code === 'status_timeout' && reader.status) {
          return reader.finish();
        }
        throw error;
      }
      if (next.done) return reader.finish();
      reader.push(next.value);
      if (reader.status && settleMs === 0) return reader.finish();
    }
  } finally {
    await closeIterator(iterator);
  }
}
