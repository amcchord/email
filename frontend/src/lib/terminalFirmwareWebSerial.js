import { TerminalFirmwareInstallError } from './terminalFirmwareInstallPlan.js';
import {
  encodeRet1Frame,
  parseRet1Line,
  Ret1ProtocolError,
} from './terminalEnrollmentProtocol.js';

const ROM_BAUD_RATE = 115200;
const APPLICATION_BAUD_RATE = 115200;
const APPLICATION_BOOT_DELAY_MS = 750;
const LOCK_NAME = 'mailapp-terminal-firmware-web-serial-v1';
const EXPECTED_CHIP = 'ESP32-S3';
const MAX_QUEUED_APPLICATION_BYTES = 16 * 1024;
const STATUS_REQUEST = new TextEncoder().encode('@RET1 {"v":2,"type":"status_request"}\n');
const PRESERVE_CONFIG_LAYOUT = Object.freeze([
  Object.freeze({ role: 'bootloader', offset: 0x0000 }),
  Object.freeze({ role: 'partition_table', offset: 0x8000 }),
  Object.freeze({ role: 'ota_data_initial', offset: 0xe000 }),
  Object.freeze({ role: 'application', offset: 0x10000 }),
]);

function fail(code, message) {
  throw new TerminalFirmwareInstallError(code, message);
}

function transportError(code, message) {
  return new TerminalFirmwareInstallError(code, message);
}

function abortError() {
  const error = new Error('Terminal serial operation was cancelled.');
  error.name = 'AbortError';
  return error;
}

function throwIfAborted(signal) {
  if (signal?.aborted) throw abortError();
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function delay(milliseconds, signal) {
  throwIfAborted(signal);
  return new Promise((resolve, reject) => {
    const timer = setTimeout(finish(resolve), milliseconds);
    const onAbort = () => finish(reject)(abortError());
    function finish(callback) {
      return value => {
        clearTimeout(timer);
        signal?.removeEventListener?.('abort', onAbort);
        callback(value);
      };
    }
    signal?.addEventListener?.('abort', onAbort, { once: true });
  });
}

function bytes(value, message) {
  if (value instanceof Uint8Array) return value;
  if (value instanceof ArrayBuffer) return new Uint8Array(value);
  if (ArrayBuffer.isView(value)) {
    return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  }
  fail('transport_invalid', message);
}

function equalBytes(left, right) {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) {
    difference |= left[index] ^ right[index];
  }
  return difference === 0;
}

function normalizeFactoryMac(value) {
  return typeof value === 'string' ? value.trim().toLowerCase() : '';
}

function requirePort(port) {
  if (!port
    || typeof port.open !== 'function'
    || typeof port.close !== 'function'
    || typeof port.getInfo !== 'function'
    || typeof port.setSignals !== 'function') {
    fail('transport_invalid', 'The selected Web Serial port does not implement the required terminal transport.');
  }
  return port;
}

function browserPrimitives(runtime) {
  const browserWindow = runtime?.window || runtime;
  const browserNavigator = browserWindow?.navigator || runtime?.navigator;
  if (browserWindow?.isSecureContext !== true) {
    fail('permission_denied', 'Browser firmware installation requires a secure HTTPS context.');
  }
  if (typeof browserNavigator?.serial?.requestPort !== 'function') {
    fail('permission_denied', 'This browser does not support Web Serial port selection.');
  }
  if (typeof browserNavigator?.locks?.request !== 'function') {
    fail('permission_denied', 'This browser cannot reserve the terminal with Web Locks.');
  }
  return {
    serial: browserNavigator.serial,
    locks: browserNavigator.locks,
  };
}

async function acquireExclusiveLock(locks) {
  const ready = deferred();
  const release = deferred();
  let request;
  try {
    request = Promise.resolve(locks.request(
      LOCK_NAME,
      { mode: 'exclusive', ifAvailable: true },
      async lock => {
        ready.resolve(Boolean(lock));
        if (lock) await release.promise;
      },
    ));
  } catch (error) {
    ready.reject(error);
    request = Promise.reject(error);
  }

  let acquired;
  try {
    acquired = await ready.promise;
  } catch {
    request.catch(() => {});
    fail('device_busy', 'The browser could not reserve an exclusive terminal firmware session.');
  }
  if (!acquired) {
    await request.catch(() => {});
    fail('device_busy', 'Another tab is already using the browser terminal firmware session.');
  }

  let released = false;
  return async () => {
    if (released) return;
    released = true;
    release.resolve();
    await request.catch(() => {});
  };
}

function normalizePortSelectionError(error) {
  if (error instanceof TerminalFirmwareInstallError) return error;
  if (error?.name === 'NotFoundError' || error?.name === 'AbortError') {
    return new TerminalFirmwareInstallError(
      'permission_denied',
      'No terminal serial port was selected. No firmware bytes were written.',
    );
  }
  return new TerminalFirmwareInstallError(
    'permission_denied',
    'The browser did not grant access to a terminal serial port.',
  );
}

class SharedSerialSession {
  constructor({ port, serial, releaseLock, onDisconnect }) {
    this.port = port;
    this.serial = serial;
    this.releaseLock = releaseLock;
    this.onDisconnect = onDisconnect;
    this.closePromise = null;
    this.romCloser = null;
    this.applicationCloser = null;
    this.applicationLost = null;
    this.lost = false;
    this.disconnectListener = event => {
      if (event?.target === this.port || event?.port === this.port) this.markLost();
    };
    this.serial?.addEventListener?.('disconnect', this.disconnectListener);
  }

  register({ romCloser, applicationCloser, applicationLost }) {
    this.romCloser = romCloser;
    this.applicationCloser = applicationCloser;
    this.applicationLost = applicationLost;
  }

  markLost() {
    if (this.lost) return;
    this.lost = true;
    try {
      this.applicationLost?.();
    } catch {
      // The application queue is best-effort notification of authoritative
      // device loss. throwIfLost() independently protects every operation.
    }
    try {
      this.onDisconnect();
    } catch {
      // Device-loss observers are outside the transport trust boundary.
    }
  }

  throwIfLost() {
    if (this.lost) fail('device_disconnected', 'The selected terminal disconnected from Web Serial.');
  }

  close() {
    if (this.closePromise) return this.closePromise;
    this.closePromise = (async () => {
      try {
        await this.applicationCloser?.();
      } finally {
        try {
          await this.romCloser?.();
        } finally {
          this.serial?.removeEventListener?.('disconnect', this.disconnectListener);
          await this.releaseLock();
        }
      }
    })();
    return this.closePromise;
  }
}

class BoundedApplicationQueue {
  constructor(maximumBytes) {
    this.maximumBytes = maximumBytes;
    this.chunks = [];
    this.queuedBytes = 0;
    this.consumer = null;
    this.failure = null;
    this.closed = false;
  }

  push(value) {
    if (this.closed || this.failure) return;
    const chunk = Uint8Array.from(bytes(value, 'The terminal returned invalid application serial bytes.'));
    if (chunk.byteLength > this.maximumBytes) {
      this.fail(transportError(
        'transport_invalid',
        'The terminal exceeded the bounded application serial receive queue.',
      ));
      return;
    }
    const waiter = this.consumer?.waiter;
    if (waiter) {
      this.consumer.waiter = null;
      waiter.resolve({ done: false, value: chunk });
      return;
    }
    if (this.queuedBytes + chunk.byteLength > this.maximumBytes) {
      this.fail(transportError(
        'transport_invalid',
        'The terminal exceeded the bounded application serial receive queue.',
      ));
      return;
    }
    this.chunks.push(chunk);
    this.queuedBytes += chunk.byteLength;
  }

  fail(error) {
    if (this.closed || this.failure) return;
    this.failure = error instanceof Error
      ? error
      : transportError('transport_invalid', 'The terminal application serial reader failed closed.');
    this.chunks = [];
    this.queuedBytes = 0;
    const waiter = this.consumer?.waiter;
    if (waiter) {
      this.consumer.waiter = null;
      this.consumer.release?.();
      waiter.reject(this.failure);
    }
  }

  close() {
    if (this.closed) return;
    this.closed = true;
    const waiter = this.consumer?.waiter;
    if (waiter) {
      this.consumer.waiter = null;
      this.consumer.release?.();
      waiter.resolve({ done: true, value: undefined });
    }
  }

  subscribe(signal) {
    if (this.consumer) {
      fail('transport_invalid', 'Only one RET1 application serial consumer may be active.');
    }
    const consumer = { active: true, waiter: null, onAbort: null };
    this.consumer = consumer;

    const release = () => {
      if (!consumer.active) return;
      consumer.active = false;
      signal?.removeEventListener?.('abort', consumer.onAbort);
      if (this.consumer === consumer) this.consumer = null;
    };
    consumer.release = release;
    consumer.onAbort = () => {
      const waiter = consumer.waiter;
      consumer.waiter = null;
      release();
      waiter?.reject(abortError());
    };
    signal?.addEventListener?.('abort', consumer.onAbort, { once: true });

    const queue = this;
    return {
      [Symbol.asyncIterator]() {
        return this;
      },
      next() {
        if (!consumer.active) return Promise.resolve({ done: true, value: undefined });
        if (signal?.aborted) {
          consumer.onAbort();
          return Promise.reject(abortError());
        }
        if (queue.chunks.length > 0) {
          const value = queue.chunks.shift();
          queue.queuedBytes -= value.byteLength;
          return Promise.resolve({ done: false, value });
        }
        if (queue.failure) {
          const error = queue.failure;
          release();
          return Promise.reject(error);
        }
        if (queue.closed) {
          release();
          return Promise.resolve({ done: true, value: undefined });
        }
        if (consumer.waiter) {
          return Promise.reject(transportError(
            'transport_invalid',
            'Concurrent reads from one RET1 serial consumer are not allowed.',
          ));
        }
        const waiter = deferred();
        consumer.waiter = waiter;
        return waiter.promise;
      },
      return() {
        const waiter = consumer.waiter;
        consumer.waiter = null;
        release();
        waiter?.resolve({ done: true, value: undefined });
        return Promise.resolve({ done: true, value: undefined });
      },
    };
  }
}

class EspressifRomTransport {
  constructor({ shared, EsploaderClass, TransportClass }) {
    this.shared = shared;
    this.EsploaderClass = EsploaderClass;
    this.TransportClass = TransportClass;
    this.transport = null;
    this.loader = null;
    this.portOpen = false;
    this.probeResult = null;
  }

  async probe({ signal } = {}) {
    throwIfAborted(signal);
    this.shared.throwIfLost();
    if (this.probeResult) return this.probeResult;
    if (this.transport || this.loader) {
      fail('transport_invalid', 'The terminal ROM probe cannot be restarted in the same browser session.');
    }

    this.transport = new this.TransportClass(this.shared.port, false, true);
    this.transport.setDeviceLostCallback?.(() => this.shared.markLost());
    this.loader = new this.EsploaderClass({
      transport: this.transport,
      baudrate: ROM_BAUD_RATE,
      debugLogging: false,
      enableTracing: false,
      terminal: {
        clean() {},
        write() {},
        writeLine() {},
      },
    });

    try {
      await this.loader.main('default_reset');
      this.portOpen = true;
      throwIfAborted(signal);
      this.shared.throwIfLost();
      const chip = this.loader.chip?.CHIP_NAME;
      if (chip !== EXPECTED_CHIP) {
        return Object.freeze({ chip: chip || '', flashBytes: 0, factoryMac: '' });
      }
      const flashSize = await this.loader.detectFlashSize();
      const flashBytes = this.loader.flashSizeBytes(flashSize);
      const factoryMac = normalizeFactoryMac(await this.loader.chip.readMac(this.loader));
      throwIfAborted(signal);
      this.shared.throwIfLost();
      this.probeResult = Object.freeze({ chip, flashBytes, factoryMac });
      return this.probeResult;
    } catch (error) {
      // main() opens the port before it can fail, so cleanup must consider it
      // open even when chip synchronization or stub upload did not finish.
      this.portOpen = true;
      throw error;
    }
  }

  async writeSegments(segments, { signal, eraseAll, onProgress = () => {} } = {}) {
    throwIfAborted(signal);
    this.shared.throwIfLost();
    if (!this.probeResult
      || !this.loader
      || eraseAll !== false
      || !Array.isArray(segments)
      || segments.length !== PRESERVE_CONFIG_LAYOUT.length) {
      fail('transport_invalid', 'The terminal ROM writer received an invalid preserve-config operation.');
    }
    const normalized = segments.map((segment, index) => {
      const expected = PRESERVE_CONFIG_LAYOUT[index];
      if (!segment
        || segment.role !== expected.role
        || segment.offset !== expected.offset) {
        fail('transport_invalid', 'The terminal ROM writer received an invalid firmware segment.');
      }
      const segmentBytes = bytes(segment.bytes, 'A firmware segment is not a byte buffer.');
      if (segmentBytes.length === 0) fail('transport_invalid', 'A firmware segment is empty.');
      return Object.freeze({
        role: segment.role,
        offset: segment.offset,
        bytes: segmentBytes,
        index,
      });
    });

    await this.loader.writeFlash({
      fileArray: normalized.map(segment => ({ data: segment.bytes, address: segment.offset })),
      flashMode: 'keep',
      flashFreq: 'keep',
      flashSize: 'keep',
      eraseAll: false,
      compress: true,
      reportProgress(fileIndex, transferred, total) {
        const segment = normalized[fileIndex];
        if (!segment) return;
        try {
          onProgress(Object.freeze({
            role: segment.role,
            fileIndex,
            bytesTransferred: transferred,
            transferTotalBytes: total,
          }));
        } catch {
          // UI progress cannot interrupt a flash operation.
        }
      },
    });
    throwIfAborted(signal);
    this.shared.throwIfLost();
    return true;
  }

  async verifySegments(segments, { signal } = {}) {
    throwIfAborted(signal);
    this.shared.throwIfLost();
    if (!this.probeResult || !this.loader || !Array.isArray(segments) || segments.length === 0) {
      fail('transport_invalid', 'The terminal ROM readback operation is invalid.');
    }
    for (const segment of segments) {
      const expected = bytes(segment?.bytes, 'A firmware readback segment is not a byte buffer.');
      const observed = bytes(
        await this.loader.readFlash(segment.offset, expected.length),
        'The terminal ROM returned invalid flash readback bytes.',
      );
      if (!equalBytes(observed, expected)) return false;
      throwIfAborted(signal);
      this.shared.throwIfLost();
    }
    return true;
  }

  async resetToApplication({ signal } = {}) {
    throwIfAborted(signal);
    this.shared.throwIfLost();
    if (!this.probeResult || !this.loader || !this.transport || !this.portOpen) {
      fail('transport_invalid', 'The terminal cannot reset before a successful ROM probe.');
    }
    await this.loader.after('hard_reset');
    await this.#disconnectRomPort();
    await delay(APPLICATION_BOOT_DELAY_MS, signal);
    this.shared.throwIfLost();
    return true;
  }

  async #disconnectRomPort() {
    if (!this.transport || !this.portOpen) return;
    try {
      await this.transport.disconnect();
    } finally {
      this.portOpen = false;
    }
  }

  async closeLocal() {
    try {
      await this.#disconnectRomPort();
    } catch {
      // The application adapter will also close the raw port when applicable.
    }
    this.transport = null;
    this.loader = null;
  }

  close() {
    return this.shared.close();
  }
}

class WebSerialApplicationTransport {
  constructor({ shared }) {
    this.shared = shared;
    this.portOpen = false;
    this.reader = null;
    this.readerPump = null;
    this.queue = new BoundedApplicationQueue(MAX_QUEUED_APPLICATION_BYTES);
    this.closing = false;
    this.writeActive = false;
  }

  async sendStatusRequest({ baudRate, bytes: requestBytes, signal } = {}) {
    throwIfAborted(signal);
    this.shared.throwIfLost();
    const payload = bytes(requestBytes, 'The RET1 status request is not a byte buffer.');
    if (baudRate !== APPLICATION_BAUD_RATE || !equalBytes(payload, STATUS_REQUEST) || this.portOpen) {
      fail('transport_invalid', 'The RET1 application serial request is invalid.');
    }
    await this.shared.port.open({
      baudRate: APPLICATION_BAUD_RATE,
      dataBits: 8,
      stopBits: 1,
      parity: 'none',
      flowControl: 'none',
      bufferSize: 4096,
    });
    this.portOpen = true;
    this.#startReaderPump();
    throwIfAborted(signal);
    this.shared.throwIfLost();
    await this.#write(payload, signal);
    throwIfAborted(signal);
    return true;
  }

  readChunks({ baudRate, signal } = {}) {
    if (baudRate !== APPLICATION_BAUD_RATE || !this.portOpen) {
      fail('transport_invalid', 'The RET1 application serial reader is invalid.');
    }
    throwIfAborted(signal);
    this.shared.throwIfLost();
    return this.queue.subscribe(signal);
  }

  async sendRet1Frame({ bytes: frameBytes, signal } = {}) {
    throwIfAborted(signal);
    this.shared.throwIfLost();
    const payload = bytes(frameBytes, 'The RET1 application frame is not a byte buffer.');
    if (!this.portOpen || payload.byteLength === 0 || payload[payload.byteLength - 1] !== 0x0a) {
      fail('transport_invalid', 'The RET1 application frame is invalid.');
    }
    let parsed;
    try {
      parsed = parseRet1Line(payload);
    } catch (error) {
      if (error instanceof Ret1ProtocolError) {
        fail('transport_invalid', 'The RET1 application frame is invalid.');
      }
      throw error;
    }
    if (!equalBytes(encodeRet1Frame(parsed), payload)) {
      fail('transport_invalid', 'The RET1 application frame is not canonical.');
    }
    await this.#write(payload, signal);
    return true;
  }

  markLost() {
    this.queue.fail(transportError(
      'device_disconnected',
      'The selected terminal disconnected from Web Serial.',
    ));
  }

  #startReaderPump() {
    if (!this.shared.port.readable) {
      fail('device_disconnected', 'The terminal serial input stream is unavailable.');
    }
    this.reader = this.shared.port.readable.getReader();
    this.readerPump = (async () => {
      try {
        while (true) {
          const { value, done } = await this.reader.read();
          if (done) {
            if (this.closing) this.queue.close();
            else this.queue.fail(transportError(
              'device_disconnected',
              'The terminal application serial input stream ended unexpectedly.',
            ));
            return;
          }
          this.shared.throwIfLost();
          if (value?.byteLength) this.queue.push(value);
          if (this.queue.failure) {
            await this.reader.cancel().catch(() => {});
            return;
          }
        }
      } catch (error) {
        if (!this.closing) {
          this.queue.fail(
            error instanceof TerminalFirmwareInstallError
              ? error
              : transportError('device_disconnected', 'The terminal application serial reader failed.'),
          );
        }
      } finally {
        try {
          this.reader?.releaseLock();
        } finally {
          this.reader = null;
        }
      }
    })();
  }

  async #write(payload, signal) {
    throwIfAborted(signal);
    this.shared.throwIfLost();
    if (this.writeActive) fail('transport_invalid', 'Concurrent RET1 application serial writes are not allowed.');
    if (!this.shared.port.writable) fail('device_disconnected', 'The terminal serial output stream is unavailable.');
    this.writeActive = true;
    let writer;
    try {
      writer = this.shared.port.writable.getWriter();
      await writer.write(payload);
      throwIfAborted(signal);
      this.shared.throwIfLost();
    } finally {
      writer?.releaseLock();
      this.writeActive = false;
    }
  }

  async closeLocal() {
    this.closing = true;
    this.queue.close();
    if (this.reader) {
      await this.reader.cancel().catch(() => {});
    }
    await this.readerPump?.catch(() => {});
    this.readerPump = null;
    if (this.portOpen) {
      try {
        await this.shared.port.close();
      } finally {
        this.portOpen = false;
      }
    }
  }

  close() {
    return this.shared.close();
  }
}

/**
 * Select one physical serial port from a user click, then reserve the origin's
 * single terminal flashing lane until both ROM and application transports are
 * closed. The returned adapters implement terminalFirmwareInstallWorkflow's
 * injected contract; they never fetch artifacts or bypass its signed-plan,
 * model, revision, preserve-config, readback, or RET1 status gates.
 */
export async function createTerminalFirmwareWebSerialTransports({
  runtime = globalThis,
  onDisconnect = () => {},
  esptool = null,
} = {}) {
  const { serial, locks } = browserPrimitives(runtime);

  // requestPort() is deliberately the first asynchronous browser operation so
  // the chooser remains bound to the caller's user activation.
  let port;
  try {
    port = requirePort(await serial.requestPort());
  } catch (error) {
    throw normalizePortSelectionError(error);
  }

  const releaseLock = await acquireExclusiveLock(locks);
  try {
    // Loading after requestPort preserves the chooser's user-activation
    // boundary while keeping unsupported/non-selected sessions free of the
    // relatively large flashing dependency.
    let implementation = esptool;
    if (!implementation) {
      try {
        implementation = await import('esptool-js');
      } catch {
        fail('transport_invalid', 'The reviewed Espressif browser transport dependency could not be loaded.');
      }
    }
    if (typeof implementation?.ESPLoader !== 'function' || typeof implementation?.Transport !== 'function') {
      fail('transport_invalid', 'The reviewed Espressif browser transport dependency is unavailable.');
    }
    const shared = new SharedSerialSession({ port, serial, releaseLock, onDisconnect });
    const romTransport = new EspressifRomTransport({
      shared,
      EsploaderClass: implementation.ESPLoader,
      TransportClass: implementation.Transport,
    });
    const applicationTransport = new WebSerialApplicationTransport({ shared });
    shared.register({
      romCloser: () => romTransport.closeLocal(),
      applicationCloser: () => applicationTransport.closeLocal(),
      applicationLost: () => applicationTransport.markLost(),
    });
    const session = Object.freeze({ close: () => shared.close() });
    return Object.freeze({ session, romTransport, applicationTransport });
  } catch (error) {
    await releaseLock();
    throw error;
  }
}

export const TERMINAL_FIRMWARE_WEB_SERIAL_VERSION = Object.freeze({
  package: 'esptool-js',
  version: '0.6.1',
  lockName: LOCK_NAME,
});

export const TERMINAL_FIRMWARE_WEB_SERIAL_LIMITS = Object.freeze({
  maxQueuedApplicationBytes: MAX_QUEUED_APPLICATION_BYTES,
});
