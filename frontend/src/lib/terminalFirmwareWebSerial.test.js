import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { loadTerminalFirmwareInstallArtifacts } from './terminalFirmwareInstallPlan.js';
import { runTerminalFirmwareInstallWorkflow } from './terminalFirmwareInstallWorkflow.js';
import {
  createTerminalFirmwareWebSerialTransports,
  TERMINAL_FIRMWARE_WEB_SERIAL_VERSION,
} from './terminalFirmwareWebSerial.js';
import {
  createFixtureFetch,
  createTerminalFirmwareInstallFixture,
  statusFrame,
} from './fixtures/terminalFirmwareInstallTestFixtures.js';

class FakeReadable {
  constructor(chunks) {
    this.chunks = chunks.map(chunk => Uint8Array.from(chunk));
    this.locked = false;
    this.cancelled = false;
  }

  getReader() {
    if (this.locked) throw new Error('reader already locked');
    this.locked = true;
    const stream = this;
    return {
      async read() {
        if (stream.cancelled) return { done: true, value: undefined };
        if (stream.chunks.length > 0) return { done: false, value: stream.chunks.shift() };
        return { done: true, value: undefined };
      },
      async cancel() {
        stream.cancelled = true;
      },
      releaseLock() {
        stream.locked = false;
      },
    };
  }
}

class FakeWritable {
  constructor(writes) {
    this.writes = writes;
    this.locked = false;
  }

  getWriter() {
    if (this.locked) throw new Error('writer already locked');
    this.locked = true;
    const stream = this;
    return {
      async write(value) {
        stream.writes.push(Uint8Array.from(value));
      },
      releaseLock() {
        stream.locked = false;
      },
    };
  }
}

class FakePort {
  constructor(status) {
    this.status = status;
    this.opened = false;
    this.readable = null;
    this.writable = null;
    this.openOptions = [];
    this.closeCalls = 0;
    this.signalCalls = [];
    this.writes = [];
    this.flash = new Map();
    this.loaderCalls = [];
    this.corruptReadback = false;
  }

  getInfo() {
    return { usbVendorId: 0x1a86, usbProductId: 0x7523 };
  }

  async open(options) {
    if (this.opened) throw new Error('port already open');
    this.opened = true;
    this.openOptions.push(options);
    this.readable = new FakeReadable([statusFrame(this.status)]);
    this.writable = new FakeWritable(this.writes);
  }

  async close() {
    if (!this.opened) throw new Error('port already closed');
    if (this.readable?.locked || this.writable?.locked) throw new Error('port stream still locked');
    this.opened = false;
    this.readable = null;
    this.writable = null;
    this.closeCalls += 1;
  }

  async setSignals(value) {
    this.signalCalls.push(value);
  }
}

class FakeEspressifTransport {
  constructor(device, tracing, slipReader) {
    this.device = device;
    this.device.loaderCalls.push({ operation: 'transport', tracing, slipReader });
    this.lostCallback = null;
  }

  setDeviceLostCallback(callback) {
    this.lostCallback = callback;
  }

  async disconnect() {
    await this.device.close();
  }
}

class FakeEspLoader {
  constructor(options) {
    this.options = options;
    this.transport = options.transport;
    this.port = options.transport.device;
    this.chip = {
      CHIP_NAME: 'ESP32-S3',
      readMac: async () => 'AA:BB:CC:DD:EE:FF',
    };
  }

  async main(mode) {
    this.port.loaderCalls.push({ operation: 'main', mode, baudrate: this.options.baudrate });
    await this.port.open({ baudRate: this.options.baudrate });
    return 'ESP32-S3';
  }

  async detectFlashSize() {
    this.port.loaderCalls.push({ operation: 'detect-flash-size' });
    return '32MB';
  }

  flashSizeBytes(value) {
    return value === '32MB' ? 32 * 1024 * 1024 : -1;
  }

  async writeFlash(options) {
    this.port.loaderCalls.push({ operation: 'write', options });
    for (let index = 0; index < options.fileArray.length; index += 1) {
      const file = options.fileArray[index];
      this.port.flash.set(file.address, Uint8Array.from(file.data));
      options.reportProgress?.(index, 0, file.data.length);
      options.reportProgress?.(index, file.data.length, file.data.length);
    }
  }

  async readFlash(offset, size) {
    this.port.loaderCalls.push({ operation: 'read', offset, size });
    const observed = Uint8Array.from(this.port.flash.get(offset)?.subarray(0, size) || []);
    if (this.port.corruptReadback && observed.length > 0) observed[0] ^= 1;
    return observed;
  }

  async after(mode) {
    this.port.loaderCalls.push({ operation: 'after', mode });
  }
}

function fakeRuntime(port, events, { lockAvailable = true } = {}) {
  const listeners = new Map();
  return {
    isSecureContext: true,
    navigator: {
      serial: {
        async requestPort() {
          events.push('request-port');
          return port;
        },
        addEventListener(type, callback) {
          listeners.set(type, callback);
        },
        removeEventListener(type, callback) {
          if (listeners.get(type) === callback) listeners.delete(type);
        },
      },
      locks: {
        async request(name, options, callback) {
          events.push('request-lock');
          assert.equal(name, TERMINAL_FIRMWARE_WEB_SERIAL_VERSION.lockName);
          assert.deepEqual(options, { mode: 'exclusive', ifAvailable: true });
          const result = await callback(lockAvailable ? { name } : null);
          events.push('release-lock');
          return result;
        },
      },
    },
  };
}

async function preparedFixture() {
  const fixture = await createTerminalFirmwareInstallFixture();
  const preparedPlan = await loadTerminalFirmwareInstallArtifacts(fixture.plan, {
    fetchImpl: createFixtureFetch(fixture),
  });
  return { fixture, preparedPlan };
}

test('official adapter selects under user activation, holds one Web Lock, flashes without erase-all, reads back, resets, and reads RET1', async () => {
  const { fixture, preparedPlan } = await preparedFixture();
  const port = new FakePort(fixture.status);
  const events = [];
  const transports = await createTerminalFirmwareWebSerialTransports({
    runtime: fakeRuntime(port, events),
    esptool: { ESPLoader: FakeEspLoader, Transport: FakeEspressifTransport },
  });
  assert.deepEqual(events, ['request-port', 'request-lock']);

  const progress = [];
  const result = await runTerminalFirmwareInstallWorkflow({
    preparedPlan,
    ...transports,
    statusSettleMs: 0,
    onProgress: value => progress.push(value),
  });

  assert.equal(result.ok, true);
  assert.equal(result.probe.chip, 'ESP32-S3');
  assert.equal(result.probe.flashBytes, 32 * 1024 * 1024);
  assert.equal(result.probe.factoryMac, fixture.factoryMac);
  assert.equal(result.status.firmware_build_id, fixture.release.git_sha);
  assert.deepEqual(events, ['request-port', 'request-lock', 'release-lock']);
  assert.equal(port.closeCalls, 2, 'ROM and application serial modes close independently');
  assert.deepEqual(port.openOptions.map(item => item.baudRate), [115200, 115200]);
  assert.equal(new TextDecoder().decode(port.writes[0]), '@RET1 {"v":2,"type":"status_request"}\n');
  assert.ok(progress.some(item => item.bytesTransferred > 0));

  const write = port.loaderCalls.find(item => item.operation === 'write').options;
  assert.equal(write.eraseAll, false);
  assert.equal(write.flashMode, 'keep');
  assert.equal(write.flashFreq, 'keep');
  assert.equal(write.flashSize, 'keep');
  assert.equal(write.compress, true);
  assert.deepEqual(write.fileArray.map(item => item.address), [0, 0x8000, 0xe000, 0x10000]);
  assert.equal(port.loaderCalls.filter(item => item.operation === 'read').length, 4);
  assert.deepEqual(port.loaderCalls.find(item => item.operation === 'after'), {
    operation: 'after',
    mode: 'hard_reset',
  });
});

test('byte-for-byte readback mismatch remains recovery-required after writing', async () => {
  const { fixture, preparedPlan } = await preparedFixture();
  const port = new FakePort(fixture.status);
  port.corruptReadback = true;
  const events = [];
  const transports = await createTerminalFirmwareWebSerialTransports({
    runtime: fakeRuntime(port, events),
    esptool: { ESPLoader: FakeEspLoader, Transport: FakeEspressifTransport },
  });
  const result = await runTerminalFirmwareInstallWorkflow({ preparedPlan, ...transports });

  assert.equal(result.ok, false);
  assert.equal(result.state, 'recovery_required');
  assert.equal(result.error.code, 'flash_verify_failed');
  assert.deepEqual(events, ['request-port', 'request-lock', 'release-lock']);
  assert.equal(port.loaderCalls.some(item => item.operation === 'after'), false);
});

test('unsupported contexts fail before port selection and a busy lock fails before opening the chosen port', async () => {
  let serialCalls = 0;
  await assert.rejects(
    createTerminalFirmwareWebSerialTransports({
      runtime: {
        isSecureContext: false,
        navigator: {
          serial: { requestPort() { serialCalls += 1; } },
          locks: { request() {} },
        },
      },
    }),
    error => error.code === 'permission_denied',
  );
  assert.equal(serialCalls, 0);

  const fixture = await createTerminalFirmwareInstallFixture();
  const port = new FakePort(fixture.status);
  const events = [];
  await assert.rejects(
    createTerminalFirmwareWebSerialTransports({
      runtime: fakeRuntime(port, events, { lockAvailable: false }),
      esptool: { ESPLoader: FakeEspLoader, Transport: FakeEspressifTransport },
    }),
    error => error.code === 'device_busy',
  );
  assert.deepEqual(events, ['request-port', 'request-lock', 'release-lock']);
  assert.equal(port.opened, false);
  assert.equal(port.loaderCalls.length, 0);
});

test('the reviewed Espressif package identity is explicit and exactly pinned in npm metadata', async () => {
  assert.deepEqual(TERMINAL_FIRMWARE_WEB_SERIAL_VERSION, {
    package: 'esptool-js',
    version: '0.6.1',
    lockName: 'mailapp-terminal-firmware-web-serial-v1',
  });
  const packageJson = JSON.parse(await readFile(new URL('../../package.json', import.meta.url), 'utf8'));
  const packageLock = JSON.parse(await readFile(new URL('../../package-lock.json', import.meta.url), 'utf8'));
  assert.equal(packageJson.dependencies['esptool-js'], '0.6.1');
  assert.equal(packageLock.packages[''].dependencies['esptool-js'], '0.6.1');
  assert.deepEqual(
    {
      version: packageLock.packages['node_modules/esptool-js'].version,
      resolved: packageLock.packages['node_modules/esptool-js'].resolved,
      integrity: packageLock.packages['node_modules/esptool-js'].integrity,
    },
    {
      version: '0.6.1',
      resolved: 'https://registry.npmjs.org/esptool-js/-/esptool-js-0.6.1.tgz',
      integrity: 'sha512-WNgQTfaEIgHyEiT56pI5v7Tq6Pzjc2XaibLxAtWY4v3zE2Ofk5ImkJY5foEUr0JrdkfHWf6rNizAewN4/kSpHw==',
    },
  );
});
