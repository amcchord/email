import {
  RET1_LIMITS,
  Ret1ProtocolError,
  parseRet1Line,
  validateHelloAck,
  validateStatus,
} from './terminalEnrollmentProtocol.js';

const RET1_PREFIX = new TextEncoder().encode('@RET1 ');
const ERROR_CODE_PATTERN = /^[a-z0-9_]{1,64}$/u;
const SESSION_PATTERN = /^[A-Za-z0-9_-]{22}$/u;

export class TerminalEnrollmentTransportError extends Error {
  constructor(code, message) {
    super(message);
    this.name = 'TerminalEnrollmentTransportError';
    this.code = code;
  }
}

function fail(code, message) {
  throw new TerminalEnrollmentTransportError(code, message);
}

function abortError() {
  const error = new Error('Terminal enrollment serial read was cancelled.');
  error.name = 'AbortError';
  return error;
}

function bytes(value) {
  if (value instanceof Uint8Array) return value;
  if (value instanceof ArrayBuffer) return new Uint8Array(value);
  if (ArrayBuffer.isView(value)) {
    return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  }
  fail('transport_invalid', 'Terminal enrollment transport returned non-byte data.');
}

function beginsWith(value, prefix) {
  return value.length >= prefix.length && prefix.every((item, index) => value[index] === item);
}

function exactKeys(value, keys) {
  return value !== null
    && typeof value === 'object'
    && !Array.isArray(value)
    && Object.keys(value).length === keys.length
    && keys.every(key => Object.hasOwn(value, key));
}

function validateDeviceError(message, expectedSessionId) {
  const withSession = Object.hasOwn(message, 'session_id');
  const keys = withSession ? ['v', 'type', 'code', 'session_id'] : ['v', 'type', 'code'];
  if (!exactKeys(message, keys)
    || message.v !== 1
    || message.type !== 'error'
    || typeof message.code !== 'string'
    || !ERROR_CODE_PATTERN.test(message.code)
    || (withSession && (typeof message.session_id !== 'string' || !SESSION_PATTERN.test(message.session_id)))
    || (withSession && expectedSessionId && message.session_id !== expectedSessionId)) {
    fail('malformed_frame', 'Terminal returned a malformed RET1 error frame.');
  }
  fail('device_rejected', `Terminal rejected the RET1 request (${message.code}).`);
}

function validateExpectedMessage(message, expectedType, expectedSessionId) {
  if (message.type === 'error') validateDeviceError(message, expectedSessionId);
  if (message.type === 'status') {
    try {
      validateStatus(message);
    } catch (error) {
      if (error instanceof Ret1ProtocolError) {
        fail('malformed_frame', 'Terminal returned a malformed RET1 status frame.');
      }
      throw error;
    }
    return null;
  }
  if (message.type !== expectedType) {
    fail('unexpected_frame', 'Terminal returned an out-of-sequence RET1 frame.');
  }
  try {
    if (expectedType === 'hello_ack') return validateHelloAck(message).message;
    if (expectedType === 'result') {
      if (!exactKeys(message, ['v', 'type', 'session_id', 'seq', 'ciphertext', 'tag'])
        || message.v !== 1
        || message.type !== 'result'
        || message.seq !== 2
        || typeof message.session_id !== 'string'
        || message.session_id !== expectedSessionId
        || typeof message.ciphertext !== 'string'
        || typeof message.tag !== 'string') {
        fail('malformed_frame', 'Terminal returned a malformed RET1 result envelope.');
      }
      return message;
    }
  } catch (error) {
    if (error instanceof Ret1ProtocolError) {
      fail('malformed_frame', `Terminal returned a malformed RET1 ${expectedType} frame.`);
    }
    throw error;
  }
  fail('transport_invalid', 'Unsupported RET1 enrollment response type.');
}

class Ret1EnrollmentReader {
  constructor({ expectedType, expectedSessionId = '' }) {
    if (!['hello_ack', 'result'].includes(expectedType)
      || (expectedType === 'result' && !SESSION_PATTERN.test(expectedSessionId))) {
      fail('transport_invalid', 'RET1 response reader contract is invalid.');
    }
    this.expectedType = expectedType;
    this.expectedSessionId = expectedSessionId;
    this.line = [];
    this.discardingDiagnostic = false;
    this.frameCount = 0;
    this.message = null;
  }

  #consumeLine(rawLine) {
    let line = Uint8Array.from(rawLine);
    if (line[line.length - 1] === 0x0d) line = line.subarray(0, line.length - 1);
    if (!beginsWith(line, RET1_PREFIX)) return;
    if (line.length > RET1_LIMITS.maxLineBytes) {
      fail('frame_too_large', 'RET1 enrollment frame exceeds its byte limit.');
    }
    if (++this.frameCount > 8) {
      fail('frame_limit', 'Too many RET1 frames were observed for one browser request.');
    }
    let parsed;
    try {
      parsed = parseRet1Line(line);
    } catch (error) {
      if (error instanceof Ret1ProtocolError) {
        fail('malformed_frame', 'Terminal returned a malformed RET1 frame.');
      }
      throw error;
    }
    const accepted = validateExpectedMessage(parsed, this.expectedType, this.expectedSessionId);
    if (accepted) {
      if (this.message) fail('contradictory_frame', 'Terminal returned duplicate RET1 response frames.');
      this.message = accepted;
    }
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
          fail('frame_too_large', 'RET1 enrollment frame exceeds its byte limit.');
        }
        this.line = [];
        this.discardingDiagnostic = true;
      }
    }
    return this.message;
  }

  finish() {
    if (!this.discardingDiagnostic && this.line.length > 0) {
      if (beginsWith(Uint8Array.from(this.line), RET1_PREFIX)) {
        fail('malformed_frame', 'Terminal ended an incomplete RET1 frame.');
      }
      this.line = [];
    }
    if (!this.message) fail('response_timeout', `No RET1 ${this.expectedType} response was observed.`);
    return this.message;
  }
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
      () => finish(reject)(new TerminalEnrollmentTransportError(
        'response_timeout',
        'RET1 enrollment response timed out.',
      )),
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
      new Promise(resolve => { timer = setTimeout(resolve, 100); }),
    ]);
  } catch {
    // The persistent Web Serial pump owns the port. A response consumer ending
    // must not cancel that shared reader or release the enclosing Web Lock.
  } finally {
    clearTimeout(timer);
  }
}

export async function readTerminalEnrollmentResponse({
  chunks,
  expectedType,
  expectedSessionId = '',
  signal,
  timeoutMs = 8000,
}) {
  if (!chunks?.[Symbol.asyncIterator]
    || !Number.isSafeInteger(timeoutMs)
    || timeoutMs <= 0
    || timeoutMs > 60_000) {
    fail('transport_invalid', 'RET1 enrollment byte stream contract is invalid.');
  }
  const reader = new Ret1EnrollmentReader({ expectedType, expectedSessionId });
  const iterator = chunks[Symbol.asyncIterator]();
  const expiresAt = Date.now() + timeoutMs;
  try {
    while (true) {
      const remaining = expiresAt - Date.now();
      if (remaining <= 0) return reader.finish();
      const next = await nextWithDeadline(iterator, Math.max(1, remaining), signal);
      if (next.done) return reader.finish();
      if (reader.push(next.value)) return reader.finish();
    }
  } finally {
    await closeIterator(iterator);
  }
}
