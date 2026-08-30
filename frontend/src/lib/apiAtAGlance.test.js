import assert from 'node:assert/strict';
import test from 'node:test';

import { api } from './api.js';


test('At a Glance experience uses a credential-free authenticated read endpoint', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  let call = null;
  globalThis.fetch = async (url, options) => {
    call = { url: String(url), method: options.method, credentials: options.credentials };
    return new Response(JSON.stringify({ combinations: [], devices: [] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };

  const result = await api.getAtAGlanceExperience();

  assert.deepEqual(call, {
    url: '/api/terminal/experience',
    method: 'GET',
    credentials: 'include',
  });
  assert.deepEqual(result, { combinations: [], devices: [] });
});


test('At a Glance preview URL encodes the exact catalog selection', () => {
  const url = api.atAGlancePreviewPngUrl(
    'day ahead',
    'editorial & calm',
    'portrait/9:16',
    123,
  );
  const parsed = new URL(url, 'https://mail.example.test');

  assert.equal(parsed.pathname, '/api/terminal/experience/preview.png');
  assert.equal(parsed.searchParams.get('view'), 'day ahead');
  assert.equal(parsed.searchParams.get('design'), 'editorial & calm');
  assert.equal(parsed.searchParams.get('profile'), 'portrait/9:16');
  assert.equal(parsed.searchParams.get('t'), '123');
});
