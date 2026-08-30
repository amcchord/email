import assert from 'node:assert/strict';
import test from 'node:test';

import { getTerminalFirmwareReleaseEvidence } from './terminalFirmwareApi.js';

const RELEASE_ID = 'a'.repeat(64);

function response(raw, { ok = true, declaredLength = raw.length } = {}) {
  const bytes = Uint8Array.from(raw);
  return {
    ok,
    headers: { get: name => name === 'content-length' ? String(declaredLength) : null },
    arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
  };
}

test('fetches only canonical exact-byte manifest and signature evidence', async () => {
  const calls = [];
  const manifest = new TextEncoder().encode('{"schema_version":2}\n');
  const signature = new Uint8Array(64).fill(7);
  const fetchImpl = async (url, options) => {
    calls.push([url, options]);
    return url.endsWith('manifest.json') ? response(manifest) : response(signature);
  };

  const evidence = await getTerminalFirmwareReleaseEvidence(RELEASE_ID, { fetchImpl });

  assert.deepEqual(evidence.manifestBytes, manifest);
  assert.deepEqual(evidence.signatureBytes, signature);
  assert.deepEqual(calls.map(([url]) => url), [
    `/api/terminal/firmware/releases/${RELEASE_ID}/manifest.json`,
    `/api/terminal/firmware/releases/${RELEASE_ID}/manifest.sig`,
  ]);
  assert.ok(calls.every(([, options]) => options.method === 'GET' && options.credentials === 'include'));
});

test('fails closed on invalid release IDs, response status, or byte bounds', async () => {
  await assert.rejects(
    getTerminalFirmwareReleaseEvidence('../artifact', { fetchImpl: async () => response([1]) }),
    /release ID/i,
  );
  await assert.rejects(
    getTerminalFirmwareReleaseEvidence(RELEASE_ID, {
      fetchImpl: async url => url.endsWith('manifest.json')
        ? response([1], { ok: false })
        : response(new Uint8Array(64)),
    }),
    /manifest is unavailable/i,
  );
  await assert.rejects(
    getTerminalFirmwareReleaseEvidence(RELEASE_ID, {
      fetchImpl: async url => url.endsWith('manifest.json')
        ? response([1], { declaredLength: 512 * 1024 + 1 })
        : response(new Uint8Array(64)),
    }),
    /unsafe byte length/i,
  );
  await assert.rejects(
    getTerminalFirmwareReleaseEvidence(RELEASE_ID, {
      fetchImpl: async url => url.endsWith('manifest.json')
        ? response([1])
        : response(new Uint8Array(63)),
    }),
    /signature is not 64 bytes/i,
  );
});
