#!/usr/bin/env node

// Deterministic local-only API and request beacon for remote-content browser QA.
// It never reads Gmail, credentials, production configuration, or mailbox data.

import { createServer } from 'node:http';

const port = Number.parseInt(process.env.QA_API_PORT || '8000', 10);
const colorScheme = process.env.QA_COLOR_SCHEME === 'dark' ? 'dark' : 'light';
// Keep fixture resources on a different hostname than the Vite app so the
// direct-load test proves same-host authenticated URLs remain blocked.
const beaconBase = `http://localhost:${port}/__qa/remote`;
const pixel = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
  'base64',
);

const remoteBody = `
  <link rel="stylesheet" href="${beaconBase}/link-stylesheet.css">
  <style>
    @import url("${beaconBase}/css-import.css");
    @font-face { font-family: Generated; src: url("${beaconBase}/font.woff2"); }
    .generated-remote { background-image: url("${beaconBase}/css-background.png"); padding: 12px; }
  </style>
  <h2>Generated privacy matrix</h2>
  <p>This message is synthetic and exercises sender-controlled resource types.</p>
  <div class="generated-remote" style="background-image:url('${beaconBase}/inline-style.png')">
    CSS background fixture
  </div>
  <table background="${beaconBase}/table-background.png">
    <tr><td background="${beaconBase}/cell-background.png">Legacy background fixture</td></tr>
  </table>
  <img src="${beaconBase}/img-src.png"
       srcset="${beaconBase}/img-1x.png 1x, ${beaconBase}/img-2x.png 2x"
       alt="Generated remote landscape" width="320" height="80">
  <img src="/api/generated-relative-image.png" alt="Generated relative app resource">
  <img src="http://127.0.0.1:5173/api/generated-same-host-image.png" alt="Generated absolute app resource">
  <picture>
    <source srcset="${beaconBase}/picture.webp" type="image/webp">
    <img src="${beaconBase}/picture-fallback.png" alt="Generated picture fallback">
  </picture>
  <video src="${beaconBase}/video.mp4" poster="${beaconBase}/poster.png" preload="metadata">
    <source src="${beaconBase}/video-source.webm">
    <track src="${beaconBase}/captions.vtt">
  </video>
  <svg width="40" height="40" aria-label="Generated SVG resource fixture">
    <defs>
      <pattern id="generated-pattern" href="${beaconBase}/svg-pattern.svg#pattern"></pattern>
      <linearGradient id="generated-linear" xlink:href="${beaconBase}/svg-linear.svg#gradient"></linearGradient>
      <radialGradient id="generated-radial" href="${beaconBase}/svg-radial.svg#gradient"></radialGradient>
      <path id="generated-local-path" d="M0 20 H40"></path>
    </defs>
    <image href="${beaconBase}/svg-image.png" width="40" height="40"></image>
    <use href="${beaconBase}/icons.svg#generated"></use>
    <filter id="generated-filter"><feImage href="${beaconBase}/svg-filter.png"></feImage></filter>
    <text><textPath href="${beaconBase}/svg-text-path.svg#path">Remote path</textPath></text>
    <text><tref xlink:href="${beaconBase}/svg-tref.svg#text"></tref></text>
    <animateMotion><mpath href="${beaconBase}/svg-motion.svg#path"></mpath></animateMotion>
    <glyphRef href="${beaconBase}/svg-glyph.svg#glyph"></glyphRef>
  </svg>
  <a href="https://landing.example.test/" ping="${beaconBase}/anchor-ping">Generated link</a>
  <map name="generated-map"><area shape="rect" coords="0,0,10,10" href="https://map.example.test/"></map>
  <iframe src="${beaconBase}/nested-frame.html"></iframe>
  <script>document.body.dataset.executed = 'true'</script>
`;

const safeBody = `
  <h2>Generated embedded-content message</h2>
  <p>This raster image is embedded and should not display a privacy banner.</p>
  <img
    src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    alt="Generated embedded pixel"
    width="48"
    height="48">
  <p style="color:#047857; font-weight:600">Ordinary inline styling remains available.</p>
`;

const permanentlyBlockedOnlyBody = `
  <style>@import url("${beaconBase}/blocked-only-import.css");</style>
  <h2>Generated permanent-block fixture</h2>
  <p style="background-image:url('${beaconBase}/blocked-only-style.png')">
    This message has no image or media that direct loading can restore.
  </p>
  <a href="https://landing.example.test/" ping="${beaconBase}/blocked-only-ping">Generated link</a>
`;

const secondRemoteBody = `
  <h2>Generated second remote message</h2>
  <p>This fixture verifies that permission never survives message changes.</p>
  <img src="${beaconBase}/second-message.png" alt="Generated second remote image" width="240" height="64">
`;

function generatedEmail(id, bodyHtml, {
  fromName = 'Generated QA Fixture',
  fromAddress = 'fixture@example.test',
  subject = 'Generated mail rendering audit',
} = {}) {
  return {
    id,
    account_id: 1,
    account_email: 'qa.generated@example.test',
    gmail_message_id: `generated-remote-${id}`,
    gmail_thread_id: `generated-remote-thread-${id}`,
    message_id_header: `<generated-remote-${id}@example.test>`,
    from_name: fromName,
    from_address: fromAddress,
    reply_to: fromAddress,
    to_addresses: [{ name: 'QA User', address: 'qa.generated@example.test' }],
    cc_addresses: [],
    subject,
    snippet: 'Synthetic browser QA only.',
    body_text: 'Synthetic browser QA only.',
    body_html: bodyHtml,
    date: '2026-08-30T15:00:00Z',
    labels: ['INBOX'],
    is_read: true,
    is_starred: false,
    is_trash: false,
    is_spam: false,
    attachments: [],
    ai_action_items: [],
    is_subscription: false,
  };
}

const emails = new Map([
  [320, generatedEmail(320, remoteBody, {
    fromName: 'Remote Content Matrix',
    fromAddress: 'matrix@tracking.example.test',
    subject: 'Generated remote-content privacy audit',
  })],
  [324, generatedEmail(324, safeBody, {
    fromName: 'Embedded Content Fixture',
    fromAddress: 'embedded@example.test',
    subject: 'Generated embedded-content audit',
  })],
  [325, generatedEmail(325, permanentlyBlockedOnlyBody, {
    fromName: 'Permanent Block Fixture',
    fromAddress: 'blocked-only@tracking.example.test',
    subject: 'Generated permanent-block audit',
  })],
  [326, generatedEmail(326, secondRemoteBody, {
    fromName: 'Second Remote Fixture',
    fromAddress: 'second@tracking.example.test',
    subject: 'Generated permission-reset audit',
  })],
]);
const resourceAttempts = [];
const mutationAttempts = [];
const unknownRoutes = [];

function writeJson(response, payload, status = 200) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(body),
    'Cache-Control': 'no-store',
  });
  response.end(body);
}

function handleRemoteResource(request, response, url) {
  resourceAttempts.push({
    sequence: resourceAttempts.length + 1,
    method: request.method,
    pathname: url.pathname,
    referer: request.headers.referer || null,
    destination: request.headers['sec-fetch-dest'] || null,
  });

  if (url.pathname.endsWith('.css')) {
    const css = `.generated-remote { border: 2px solid #dc2626; background-image: url("${beaconBase}/nested-css.png"); }`;
    response.writeHead(200, { 'Content-Type': 'text/css', 'Cache-Control': 'no-store' });
    return response.end(css);
  }
  if (url.pathname.endsWith('.vtt')) {
    response.writeHead(200, { 'Content-Type': 'text/vtt', 'Cache-Control': 'no-store' });
    return response.end('WEBVTT\n\n');
  }
  if (url.pathname.endsWith('.woff2')) {
    response.writeHead(200, { 'Content-Type': 'font/woff2', 'Cache-Control': 'no-store' });
    return response.end(Buffer.alloc(8));
  }
  if (/\.(?:mp3|mp4|ogg|webm)$/.test(url.pathname)) {
    response.writeHead(200, { 'Content-Type': 'application/octet-stream', 'Cache-Control': 'no-store' });
    return response.end(Buffer.alloc(8));
  }
  response.writeHead(200, {
    'Content-Type': 'image/png',
    'Content-Length': pixel.length,
    'Cache-Control': 'no-store',
  });
  return response.end(pixel);
}

function handleRequest(request, response) {
  const url = new URL(request.url, `http://${request.headers.host}`);
  const { pathname } = url;

  if (request.method === 'GET' && pathname === '/api/auth/me') {
    return writeJson(response, { id: 1, username: 'qa-user', is_admin: false });
  }
  if (request.method === 'GET' && pathname === '/__qa/mobile-wrapper') {
    // The in-app capture backend rasterizes narrow child frames at half scale.
    // The iframe itself remains an exact 375x812 CSS viewport; this wrapper
    // compensates only the saved evidence bitmap so one CSS pixel is visible
    // as one output pixel.
    const body = `<!doctype html><html><head><meta charset="utf-8"><style>
      html, body { margin: 0; width: 750px; height: 1624px; overflow: hidden; background: #f8fafc; }
      iframe {
        display: block; width: 375px; height: 812px; border: 0;
        transform: scale(2); transform-origin: top left;
      }
    </style></head><body><iframe title="Exact 375 pixel generated mail QA" src="http://127.0.0.1:5173/?view=email&id=320"></iframe></body></html>`;
    response.writeHead(200, {
      'Content-Type': 'text/html; charset=utf-8',
      'Content-Length': Buffer.byteLength(body),
      'Cache-Control': 'no-store',
    });
    return response.end(body);
  }
  if (request.method === 'GET' && pathname === '/api/auth/ui-preferences') {
    return writeJson(response, { thread_order: 'asc', theme: 'default', color_scheme: colorScheme });
  }
  if (request.method === 'GET' && pathname === '/api/auth/keyboard-shortcuts') {
    return writeJson(response, { shortcuts: {} });
  }
  if (request.method === 'GET' && pathname === '/api/accounts/') {
    return writeJson(response, [{
      id: 1,
      email: 'qa.generated@example.test',
      display_name: 'Generated QA',
      has_calendar_scope: true,
      sync_status: { status: 'idle' },
      calendar_sync_status: { status: 'idle' },
    }]);
  }
  if (request.method === 'GET' && pathname === '/api/build-version') {
    return writeJson(response, { version: 'generated-remote-content-qa' });
  }
  if (request.method === 'GET' && pathname === '/api/events/stream') {
    response.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
    });
    response.write(': generated remote-content QA stream\n\n');
    request.on('close', () => response.end());
    return;
  }
  if (request.method === 'GET' && pathname === '/api/emails/labels/all') {
    return writeJson(response, []);
  }
  if (request.method === 'GET' && pathname === '/api/emails/actions/recent') {
    return writeJson(response, []);
  }
  if (request.method === 'GET' && pathname === '/api/emails/') {
    const generated = [...emails.values()];
    return writeJson(response, {
      emails: generated,
      total: generated.length,
      page: 1,
      page_size: 50,
    });
  }
  if (request.method === 'GET' && pathname === '/api/calendar/upcoming') {
    return writeJson(response, { events: [] });
  }
  if (request.method === 'GET' && pathname === '/api/todos/') {
    return writeJson(response, { todos: [] });
  }
  if (request.method === 'GET' && pathname === '/api/ai/needs-reply') {
    return writeJson(response, {
      emails: [
        {
          ...emails.get(320),
          category: 'urgent',
          summary: 'Generated remote-content fixture for Flow QA.',
          reply_options: [],
        },
        {
          ...emails.get(326),
          category: 'normal',
          summary: 'Generated second-message fixture for permission reset QA.',
          reply_options: [],
        },
      ],
      total: 2,
    });
  }
  if (request.method === 'GET' && pathname === '/api/ai/trends') {
    return writeJson(response, { summary: '', needs_attention: [] });
  }
  if (request.method === 'GET' && pathname === '/api/ai/awaiting-response') {
    return writeJson(response, { emails: [], total: 0 });
  }
  if (request.method === 'GET' && pathname === '/api/ai/digests') {
    return writeJson(response, { digests: [], total: 0 });
  }
  if (request.method === 'GET' && pathname === '/api/chat/conversations') {
    return writeJson(response, []);
  }
  const threadMatch = pathname.match(/^\/api\/emails\/thread\/(generated-remote-thread-\d+)$/);
  if (request.method === 'GET' && threadMatch) {
    const email = [...emails.values()].find(candidate => candidate.gmail_thread_id === threadMatch[1]);
    if (!email) return writeJson(response, { detail: 'Not found' }, 404);
    return writeJson(response, {
      thread_id: email.gmail_thread_id,
      subject: email.subject,
      emails: [email],
    });
  }
  const emailMatch = pathname.match(/^\/api\/emails\/(\d+)$/);
  if (request.method === 'GET' && emailMatch) {
    const email = emails.get(Number(emailMatch[1]));
    return writeJson(response, email || { detail: 'Not found' }, email ? 200 : 404);
  }
  if (request.method === 'GET' && pathname === '/__qa/audit') {
    return writeJson(response, { resourceAttempts, mutationAttempts, unknownRoutes });
  }
  if (request.method === 'POST' && pathname === '/__qa/reset-audit') {
    resourceAttempts.length = 0;
    mutationAttempts.length = 0;
    unknownRoutes.length = 0;
    return writeJson(response, { reset: true });
  }
  if (request.method === 'POST' && pathname.startsWith('/api/')) {
    mutationAttempts.push({ method: request.method, pathname });
    return writeJson(response, { detail: 'Generated QA rejects mailbox mutations' }, 409);
  }
  if (request.method === 'GET' && pathname.startsWith('/__qa/remote/')) {
    return handleRemoteResource(request, response, url);
  }

  unknownRoutes.push({ method: request.method, pathname });
  return writeJson(response, { detail: 'Unknown generated QA route' }, 404);
}

const server = createServer(handleRequest);
server.listen(port, '127.0.0.1', () => {
  process.stdout.write(`Generated remote-content QA server listening on http://127.0.0.1:${port}\n`);
});

function shutdown() {
  server.close(() => process.exit(0));
}

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
