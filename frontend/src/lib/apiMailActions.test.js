import assert from 'node:assert/strict';
import test from 'node:test';
import { api } from './api.js';

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

test('mail action creation sends the durable idempotency contract', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  let call = null;
  globalThis.fetch = async (url, options) => {
    call = { url, options };
    return jsonResponse({ request_id: 'request-1', state: 'staged' }, 202);
  };

  const result = await api.emailActions([11, 12], 'archive', 'client-key');

  assert.equal(call.url, '/api/emails/actions');
  assert.equal(call.options.method, 'POST');
  assert.deepEqual(JSON.parse(call.options.body), {
    email_ids: [11, 12],
    action: 'archive',
    idempotency_key: 'client-key',
  });
  assert.equal(result.state, 'staged');
});

test('mail action lifecycle helpers use request-scoped routes', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, method: options.method });
    return jsonResponse([]);
  };

  await api.getMailAction('request-2');
  await api.getMailActionByIdempotency('client-key');
  await api.listRecentMailActions(7);
  await api.undoMailAction('request-2');
  await api.retryMailAction('request-2');

  assert.deepEqual(calls, [
    { url: '/api/emails/actions/request-2', method: 'GET' },
    { url: '/api/emails/actions/by-idempotency/client-key', method: 'GET' },
    { url: '/api/emails/actions/recent?limit=7', method: 'GET' },
    { url: '/api/emails/actions/request-2/undo', method: 'POST' },
    { url: '/api/emails/actions/request-2/retry', method: 'POST' },
  ]);
});

test('API errors retain the HTTP status needed for authoritative reconciliation', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async () => jsonResponse({ detail: 'Mail action not found' }, 404);

  await assert.rejects(
    api.getMailActionByIdempotency('missing-key'),
    error => error.message === 'Mail action not found' && error.status === 404,
  );
});

test('attachment downloads forward cancellation signals to fetch', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  let call = null;
  globalThis.fetch = async (url, options) => {
    call = { url, options };
    return new Response('generated attachment', {
      status: 200,
      headers: { 'Content-Type': 'text/plain' },
    });
  };
  const controller = new AbortController();

  const result = await api.downloadAttachment(41, 83, { signal: controller.signal });

  assert.equal(call.url, '/api/emails/41/attachments/83/download');
  assert.equal(call.options.signal, controller.signal);
  assert.equal(await result.text(), 'generated attachment');
});

test('attachment authorization failures retain terminal HTTP status', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async () => jsonResponse({ detail: 'Unauthorized' }, 401);

  await assert.rejects(
    api.downloadAttachment(41, 83),
    error => error.message === 'Unauthorized' && error.status === 401,
  );
});

test('attachment previews preserve the typed renderer response contract', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return new Response('generated preview text', {
      status: 200,
      headers: {
        'Content-Type': 'text/plain; charset=utf-8',
        'X-Attachment-Preview-Kind': 'text',
        'X-Attachment-Preview-Truncated': 'true',
      },
    });
  };
  const controller = new AbortController();
  const result = await api.previewAttachment(41, 83, { signal: controller.signal });

  assert.equal(calls[0].url, '/api/emails/41/attachments/83/preview');
  assert.equal(calls[0].options.signal, controller.signal);
  assert.equal(result.kind, 'text');
  assert.equal(result.truncated, true);
  assert.equal(result.contentType, 'text/plain; charset=utf-8');
  assert.equal(await result.blob.text(), 'generated preview text');
  assert.equal(
    api.attachmentPreviewUrl(41, 83),
    '/api/emails/41/attachments/83/preview',
  );
});
