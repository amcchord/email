#!/usr/bin/env node

// Deterministic, read-only browser-QA server for core mail-client flows.
// It binds only to localhost, serves immutable .example.test fixtures and the
// built frontend, makes no outbound requests, and rejects every mutation.

import { createReadStream } from 'node:fs';
import { readFile, readdir, stat } from 'node:fs/promises';
import { createServer } from 'node:http';
import { dirname, extname, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const host = '127.0.0.1';
const port = Number.parseInt(process.env.QA_PORT || '4178', 10);
const fixtureNow = new Date('2026-08-30T14:00:00Z');
const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const frontendDist = resolve(scriptDirectory, '../../frontend/dist');
const frontendManifest = resolve(frontendDist, '.vite/manifest.json');
const forcedRouteCase = ['slow', 'fail-once'].includes(process.env.QA_ROUTE_CASE)
  ? process.env.QA_ROUTE_CASE
  : null;
const forcedRouteTarget = process.env.QA_ROUTE_TARGET || null;
const forcedRouteRun = process.env.QA_ROUTE_RUN || null;
const editorFixtureEnabled = process.env.QA_EDITOR_FIXTURE === '1';
const replyEnvelopeFixtureEnabled = process.env.QA_REPLY_ENVELOPE_FIXTURE === '1';
const forcedEditorCase = ['slow', 'fail-once'].includes(process.env.QA_EDITOR_CASE)
  ? process.env.QA_EDITOR_CASE
  : null;
const forcedEditorRun = process.env.QA_EDITOR_RUN || null;

const compoundQuery = 'from:renee+launch@example.test subject:"Quarterly & Planning" has:attachment -is:read in:inbox';
const removalQuery = 'from:renee+launch@example.test subject:"Quarterly & Planning" -is:read in:inbox';

const scenarioQueries = Object.freeze({
  compound: compoundQuery,
  removal: removalQuery,
  zero_results: 'no-match',
  slow_overlap: 'slow:request',
  fast_overlap: 'fast:request',
  validation_error: 'backend-error',
  service_error: 'service-down',
});

function deepFreeze(value) {
  if (!value || typeof value !== 'object' || Object.isFrozen(value)) return value;
  for (const nestedValue of Object.values(value)) deepFreeze(nestedValue);
  return Object.freeze(value);
}

const generatedPreviewText = Buffer.from(
  'Generated attachment preview\n\nThis text is escaped and uses no real mailbox data.\n',
);
const generatedPreviewPng = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAoAAAAFoCAIAAABIUN0GAAAFn0lEQVR42u3cMU5CQRSGUXy5FVpSU1pQswc2QWNix3rsiDRuwj1QU1BSW6K1tY0xQeXN/OeswLlj8uW+Md68P99OAID/NRgBAAgwAAgwACDAACDAAIAAA4AAAwACDAACDAAIMAAIMAAIMAAgwAAgwACAAAOAAAMAAgwAAgwACDAACDAACDAAIMAAIMAAgAADgAADAAIMAAIMAAgwAAgwAAgwACDAACDAAIAAA4AAAwACDAACDAAIMAAIMAAIMADw96rpn376cHaFAMk+dncCLLoAXDMKbcW4pBeAnmLcSoZLegGQYQGWXgAiMjyoLwAJL8QCrL4AqMkoP0FLLwDdf44e1BcAq3B6gNUXgJDK+FeUAJAdYOsvADmtGUwEAA0ODbD6ApDWHW/AABAZYOsvAIH1sQEDQF6Arb8AZDbIBgwAYQG2/gIQuwTbgAFAgAFAgAGA3gLsARiASfAzsA0YAAQYAAQYABBgABBgAECAAUCAAQABBgABBgAEGAAEGAAEGAAQYAAQYABAgAFAgAEAAQYAAQYABBgABBgABBgAEGAAEGAAQIABQIABAAEGgLGqtAPfP765dYBxOm5nNmAAQIABQIABAAEGAAEGAAQYAAQYABBgABBgABBgAECAAUCAAQABBgABBgAEGAAEGAAQYAAQYAAQYABAgAFAgAEAAQYAAQYABBgABBgA+KLSDnzcztw6ADZgABBgAECAAUCAAQABBgABBgAEGAAEGAAQYAAQYAAQYABAgAFAgAEAAQYAAQYABBgABBgAEGAAEGAAEGAAQIABQIABAAEGAAEGAAQYAAQYABBgABBgAIhWaQd+enl168B4bNYrQ7ABAwACDAACDAAIMAAIMAAgwAAgwACAAAOAAAOAAAMAAgwAAgwACDAACDAAIMAAIMAAgAADgAADgAADAAIMAL2rtANv1iu3DoANGAAEGAAQYAAQYABAgAFAgAEAAQYAAQYABBgABBgABBgAEGAAEGAAQIABQIABAAEGAAEGAAQYAAQYAAQYABBgABBgAECAAaB9lXbg/eHk1gG+t1zMDcEGDAACDAAIMAAIMAAgwAAgwACAAAOAAAOAAAMAAgwAAgwACDAACDAAIMAAIMAAgAADgAADgAADAAIMAA2uX8A1Ukh8R/ZwwpAAAAAElFTkSuQmCC',
  'base64',
);

function buildGeneratedPdf() {
  const stream = 'BT /F1 18 Tf 72 720 Td (Generated attachment preview) Tj ET';
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`,
  ];
  let document = '%PDF-1.4\n';
  const offsets = [0];
  objects.forEach((object, index) => {
    offsets.push(Buffer.byteLength(document));
    document += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xrefOffset = Buffer.byteLength(document);
  document += `xref\n0 ${objects.length + 1}\n`;
  document += '0000000000 65535 f \n';
  document += offsets.slice(1).map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('');
  document += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`;
  return Buffer.from(document);
}

const generatedPreviewPdf = buildGeneratedPdf();

function generatedEmail(overrides) {
  const accountId = overrides.account_id || 1;
  const accountEmail = accountId === 1
    ? 'search.primary@example.test'
    : 'search.secondary@example.test';
  const id = overrides.id;
  const snippet = Object.hasOwn(overrides, 'snippet')
    ? overrides.snippet
    : 'Generated locally for structured-search browser QA.';
  const bodyText = Object.hasOwn(overrides, 'body_text')
    ? overrides.body_text
    : `${snippet || 'This fixture intentionally has no snippet.'}\n\nNo real mailbox data is used.`;
  const bodyHtml = Object.hasOwn(overrides, 'body_html')
    ? overrides.body_html
    : `<p>${snippet || 'This fixture intentionally has no snippet.'}</p><p>No real mailbox data is used.</p>`;

  return {
    id,
    account_id: accountId,
    account_email: Object.hasOwn(overrides, 'account_email')
      ? overrides.account_email
      : accountEmail,
    gmail_message_id: `generated-search-message-${id}`,
    gmail_thread_id: `generated-search-thread-${id}`,
    message_id_header: `<generated-search-${id}@example.test>`,
    from_name: Object.hasOwn(overrides, 'from_name')
      ? overrides.from_name
      : 'Generated Sender',
    from_address: overrides.from_address || `sender-${id}@example.test`,
    reply_to: Object.hasOwn(overrides, 'reply_to')
      ? overrides.reply_to
      : (overrides.from_address || `sender-${id}@example.test`),
    to_addresses: Object.hasOwn(overrides, 'to_addresses')
      ? overrides.to_addresses
      : [{ name: 'Search QA', address: accountEmail }],
    cc_addresses: Object.hasOwn(overrides, 'cc_addresses') ? overrides.cc_addresses : [],
    bcc_addresses: Object.hasOwn(overrides, 'bcc_addresses') ? overrides.bcc_addresses : [],
    subject: Object.hasOwn(overrides, 'subject') ? overrides.subject : `Generated message ${id}`,
    snippet,
    body_text: bodyText,
    body_html: bodyHtml,
    date: overrides.date || '2026-08-30T12:00:00Z',
    labels: overrides.labels || ['INBOX'],
    is_read: overrides.is_read ?? true,
    is_starred: overrides.is_starred ?? false,
    is_trash: overrides.is_trash ?? false,
    is_spam: overrides.is_spam ?? false,
    is_sent: overrides.is_sent ?? false,
    is_draft: overrides.is_draft ?? false,
    has_attachments: overrides.has_attachments ?? false,
    attachments: overrides.attachments || [],
    ai_action_items: [],
    is_subscription: false,
  };
}

const generatedEmails = deepFreeze([
  generatedEmail({
    id: 316,
    from_name: 'Generated Security Lab',
    from_address: 'security-lab@example.test',
    subject: 'HTML sanitizer boundary QA',
    snippet: 'Generated benign layouts and hostile markup for the email iframe boundary.',
    date: '2026-08-30T13:58:00Z',
    labels: ['INBOX'],
    is_read: true,
    body_text: 'Generated sanitizer fixture. No real mailbox data is used.',
    body_html: `
      <style id="generated-safe-email-style">
        .generated-safe-email-marker { color: rgb(17, 94, 89); font-weight: 700; }
        .generated-safe-email-table { border-collapse: collapse; width: 100%; }
        .generated-safe-email-table td { border: 1px solid #cbd5e1; padding: 8px; }
      </style>
      <div id="generated-safe-email-marker" class="generated-safe-email-marker" style="color: rgb(17, 94, 89); font-weight: 700; padding: 8px" onclick="globalThis.__generatedEmailClick = 1">
        Benign formatted email content survives.
      </div>
      <table id="generated-safe-email-table" class="generated-safe-email-table" cellpadding="2" cellspacing="0" style="border-collapse: collapse; width: 100%">
        <tr><td style="border: 1px solid #cbd5e1; padding: 8px">Generated table layout</td><td style="border: 1px solid #cbd5e1; padding: 8px">Renée · 日本語 · ✅</td></tr>
      </table>
      <p>
        <a id="generated-safe-email-link" href="https://safe.example.test/generated-email" target="_blank">Safe generated link</a>
        <a id="generated-unsafe-email-link" href="javascript:globalThis.__generatedEmailHref = 1">Unsafe generated link</a>
      </p>
      <img id="generated-email-event-probe" alt="Generated local pixel" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==" onerror="globalThis.__generatedEmailError = 1">
      <script>globalThis.__generatedEmailScript = 1</script>
      <iframe srcdoc="&lt;script&gt;parent.__generatedEmailFrame = 1&lt;/script&gt;"></iframe>
      <object data="data:text/html,generated"></object>
      <embed src="data:text/html,generated">
      <svg width="0" height="0" aria-hidden="true" onload="globalThis.__generatedEmailSvg = 1"></svg>
      <form id="generated-email-clobber-probe"><input name="__proto__" value="generated"></form>
      <template id="generated-email-template-probe"><img src="x" onerror="globalThis.__generatedEmailTemplate = 1"></template>
    `,
  }),
  generatedEmail({
    id: 313,
    from_name: 'Generated Preview Lab',
    from_address: 'preview-lab@example.test',
    subject: 'Attachment preview gallery',
    snippet: 'Generated text, image, PDF, caution, mismatch, error, and cancellation fixtures.',
    date: '2026-08-30T13:45:00Z',
    labels: ['INBOX'],
    is_read: true,
    has_attachments: true,
    attachments: [
      { id: 8411, filename: 'generated-preview-notes.txt', content_type: 'text/plain', size_bytes: generatedPreviewText.length },
      { id: 8412, filename: 'generated-preview-image.png', content_type: 'image/png', size_bytes: generatedPreviewPng.length },
      { id: 8413, filename: 'generated-preview-document.pdf', content_type: 'application/pdf', size_bytes: generatedPreviewPdf.length },
      { id: 8414, filename: 'generated-preview-archive.zip', content_type: 'application/zip', size_bytes: 4096 },
      { id: 8415, filename: 'generated-preview-script.js', content_type: 'text/javascript', size_bytes: 512 },
      { id: 8416, filename: 'generated-mismatch.png', content_type: 'application/pdf', size_bytes: 1024 },
      { id: 8417, filename: 'generated-corrupt-image.png', content_type: 'image/png', size_bytes: 64 },
      { id: 8418, filename: 'generated-delayed-preview.txt', content_type: 'text/plain', size_bytes: 96 },
      { id: 8419, filename: 'generated-retry-preview.txt', content_type: 'text/plain', size_bytes: 88 },
    ],
  }),
  generatedEmail({
    id: 301,
    from_name: 'Renée Launch',
    from_address: 'renee+launch@example.test',
    subject: 'Quarterly & Planning',
    snippet: 'Exact phrase fixture with the generated launch packet attached.',
    date: '2026-03-08T01:30:00-05:00',
    labels: ['INBOX', 'UNREAD', 'STARRED', 'Label_QA_SHARED'],
    is_read: false,
    is_starred: true,
    has_attachments: true,
    attachments: [{
      id: 8301,
      filename: 'quarterly-planning-generated.txt',
      content_type: 'text/plain',
      size_bytes: 43,
    }],
    to_addresses: [{ name: 'Primary Search QA', address: 'search.primary@example.test' }],
    cc_addresses: [{ name: 'Generated Observer', address: 'observer@example.test' }],
  }),
  generatedEmail({
    id: 302,
    from_name: 'Renée Launch',
    from_address: 'renee+launch@example.test',
    subject: 'Quarterly notes and Planning',
    snippet: 'Quarterly and Planning both occur, but the exact subject phrase does not.',
    date: '2026-03-08T03:30:00-04:00',
    labels: ['INBOX', 'UNREAD', 'STARRED'],
    is_read: false,
    is_starred: true,
    has_attachments: true,
    attachments: [{
      id: 8302,
      filename: 'near-miss-generated.txt',
      content_type: 'text/plain',
      size_bytes: 37,
    }],
  }),
  generatedEmail({
    id: 303,
    from_name: 'Renée Launch',
    from_address: 'renee+launch@example.test',
    subject: 'Quarterly & Planning',
    snippet: 'Read peer for the exact generated search fixture.',
    date: '2026-08-29T16:20:00Z',
    labels: ['INBOX', 'STARRED'],
    is_read: true,
    is_starred: true,
    has_attachments: true,
    attachments: [
      {
        id: 8303,
        filename: 'delayed-read-peer-generated.txt',
        content_type: 'text/plain',
        size_bytes: 68,
      },
      {
        id: 8304,
        filename: 'retryable-generated.txt',
        content_type: 'text/plain',
        size_bytes: 64,
      },
      {
        id: 8305,
        filename: 'too-large-generated.zip',
        content_type: 'application/zip',
        size_bytes: 34 * 1024 * 1024,
      },
      {
        id: 8306,
        filename: 'unavailable-generated.txt',
        content_type: 'text/plain',
        size_bytes: 1,
      },
      {
        id: 8307,
        filename: `../Résumé-${'非常に長い'.repeat(18)}-\u0000-final.txt`,
        content_type: 'text/plain',
        size_bytes: 2048,
      },
    ],
  }),
  generatedEmail({
    id: 304,
    from_name: 'Renée Launch',
    from_address: 'renee+launch@example.test',
    subject: 'Quarterly & Planning',
    snippet: 'Unread peer ticket:1234 deliberately missing an attachment.',
    date: '2026-08-29T16:10:00Z',
    labels: ['INBOX', 'UNREAD', 'STARRED'],
    is_read: false,
    is_starred: true,
    has_attachments: false,
  }),
  generatedEmail({
    id: 305,
    from_name: 'Primary Search QA',
    from_address: 'search.primary@example.test',
    subject: 'Sent fixture with legacy recipients',
    snippet: 'Recipient arrays use the legacy string shape.',
    date: '2026-08-28T18:00:00Z',
    labels: ['SENT'],
    is_sent: true,
    to_addresses: ['legacy.recipient@example.test'],
    cc_addresses: ['legacy.copy@example.test'],
  }),
  generatedEmail({
    id: 306,
    from_name: 'Primary Search QA',
    from_address: 'search.primary@example.test',
    subject: 'Draft fixture with JSON recipients',
    snippet: 'Recipient arrays use the object JSON shape.',
    date: '2026-08-28T17:30:00Z',
    labels: ['DRAFT'],
    is_draft: true,
    to_addresses: [{ name: 'Draft Recipient', address: 'draft.recipient@example.test' }],
  }),
  generatedEmail({
    id: 307,
    from_name: 'Generated Support',
    from_address: 'support@example.test',
    subject: 'Archived case ticket:1234',
    snippet: 'Generated archived custom-label fixture for ticket:1234.',
    body_text: 'The literal token ticket:1234 is preserved in this generated fixture.',
    date: '2026-08-27T14:00:00Z',
    labels: ['Label_QA_SHARED'],
  }),
  generatedEmail({
    id: 308,
    from_name: 'Generated Trash',
    from_address: 'trash@example.test',
    subject: 'Trash-only generated fixture',
    date: '2026-08-26T14:00:00Z',
    labels: ['TRASH'],
    is_trash: true,
  }),
  generatedEmail({
    id: 309,
    from_name: 'Generated Spam',
    from_address: 'spam@example.test',
    subject: 'Spam-only generated fixture',
    date: '2026-08-25T14:00:00Z',
    labels: ['SPAM'],
    is_spam: true,
  }),
  generatedEmail({
    id: 310,
    from_name: null,
    from_address: 'null-fields@example.test',
    reply_to: null,
    subject: null,
    snippet: null,
    body_text: null,
    body_html: null,
    date: '2026-08-24T12:00:00Z',
    labels: ['INBOX', 'Label_QA_SHARED'],
    to_addresses: null,
    cc_addresses: null,
    bcc_addresses: null,
  }),
  generatedEmail({
    id: 311,
    account_id: 2,
    from_name: 'Secondary Equal Time',
    from_address: 'equal-time@example.test',
    subject: 'Equal timestamp, second account',
    snippet: 'Shares an exact timestamp and custom label with another-account mail.',
    date: '2026-08-24T12:00:00Z',
    labels: ['INBOX', 'Label_QA_SHARED'],
    to_addresses: ['search.secondary@example.test'],
  }),
  generatedEmail({
    id: 312,
    account_id: 2,
    from_name: 'Renée Launch',
    from_address: 'renee+launch@example.test',
    subject: 'Quarterly & Planning',
    snippet: 'Read generated peer proves account isolation for matching visible fields.',
    date: '2026-08-23T15:00:00Z',
    labels: ['INBOX', 'STARRED', 'Label_QA_SHARED'],
    is_read: true,
    is_starred: true,
    has_attachments: true,
    attachments: [{
      id: 8312,
      filename: 'secondary-account-generated.txt',
      content_type: 'text/plain',
      size_bytes: 45,
    }],
  }),
  ...(replyEnvelopeFixtureEnabled ? [
    generatedEmail({
      id: 317,
      account_id: 2,
      from_name: 'Generated Envelope Sender',
      from_address: 'envelope.sender@example.test',
      reply_to: 'envelope.reply@example.test',
      subject: 'Generated reply-all envelope target',
      snippet: 'Owned by the second generated account while the decoy account is listed first.',
      date: '2026-08-30T13:59:00Z',
      labels: ['INBOX'],
      is_read: true,
      to_addresses: [
        { name: 'Generated Secondary Owner', address: 'search.secondary@example.test' },
        { name: 'Generated Teammate', address: 'teammate@example.test' },
        { name: 'Duplicate Reply Target', address: 'envelope.reply@example.test' },
      ],
      cc_addresses: [
        { name: 'Generated Observer', address: 'observer@example.test' },
        { name: 'Generated Primary Decoy', address: 'search.primary@example.test' },
        { name: 'Duplicate Observer', address: 'observer@example.test' },
      ],
    }),
    generatedEmail({
      id: 318,
      account_id: 999,
      account_email: 'missing.source@example.test',
      from_name: 'Generated Missing Source',
      from_address: 'missing.sender@example.test',
      reply_to: 'missing.reply@example.test',
      subject: 'Generated reply source unavailable',
      snippet: 'No generated account owns this immutable message source.',
      date: '2026-08-30T13:58:30Z',
      labels: ['INBOX'],
      is_read: true,
      to_addresses: [{ name: 'Unavailable Source', address: 'missing.source@example.test' }],
      cc_addresses: [{ name: 'Generated Missing Observer', address: 'missing.observer@example.test' }],
    }),
  ] : []),
]);

function generatedEditorEmail(overrides) {
  return {
    ...generatedEmail(overrides),
    needs_reply: overrides.needs_reply ?? true,
    summary: overrides.summary || '',
    category: overrides.category || null,
    action_items: overrides.action_items || [],
    ai_action_items: overrides.action_items || [],
    reply_options: overrides.reply_options || null,
    suggested_reply: overrides.suggested_reply || null,
  };
}

const generatedEditorNeedsReply = deepFreeze([
  generatedEditorEmail({
    id: 314,
    from_name: 'Generated Editor QA',
    from_address: 'editor-qa@example.test',
    reply_to: 'editor-reply@example.test',
    subject: 'Generated cold editor reply',
    snippet: 'Open this immutable generated thread to exercise the lazy reply editor.',
    date: '2026-08-30T13:55:00Z',
    labels: ['INBOX', 'UNREAD'],
    is_read: false,
    needs_reply: true,
    category: 'urgent',
    summary: 'A generated-only message for cold Flow reply editor loading.',
    action_items: ['Reply using only the generated QA fixture.'],
    suggested_reply: 'Thanks for the generated note. I can confirm this QA-only reply.',
    reply_options: [
      {
        label: 'Confirm fixture',
        body: 'Thanks for the generated note. I can confirm this QA-only reply.',
        intent: 'accept',
      },
      {
        label: 'Defer fixture',
        body: 'Thanks for the generated note. I will revisit this QA-only fixture tomorrow.',
        intent: 'defer',
      },
    ],
  }),
  generatedEditorEmail({
    id: 315,
    from_name: 'Generated Editor Race QA',
    from_address: 'editor-race@example.test',
    reply_to: 'editor-race-reply@example.test',
    subject: 'Generated concurrent editor reply',
    snippet: 'A second immutable message for open, close, and A-to-B editor races.',
    date: '2026-08-30T13:50:00Z',
    labels: ['INBOX', 'UNREAD'],
    is_read: false,
    needs_reply: true,
    category: 'awaiting_reply',
    summary: 'A second generated-only thread keeps concurrent editor tests deterministic.',
    action_items: ['Switch between the two generated QA threads without sending.'],
    suggested_reply: 'This is the second generated QA reply fixture.',
    reply_options: [{
      label: 'Acknowledge fixture',
      body: 'This is the second generated QA reply fixture.',
      intent: 'custom',
    }],
  }),
]);

const generatedReplyEnvelopeNeedsReply = deepFreeze(
  replyEnvelopeFixtureEnabled
    ? [317, 318].map(id => generatedEditorEmail({
      ...generatedEmails.find(email => email.id === id),
      needs_reply: true,
      category: id === 317 ? 'urgent' : 'awaiting_reply',
      summary: id === 317
        ? 'Generated reply-all target owned by the second account.'
        : 'Generated source-account failure must keep reply actions disabled.',
      suggested_reply: null,
      reply_options: null,
    }))
    : [],
);

const generatedThreadEmails = [
  ...generatedEditorNeedsReply,
  ...generatedReplyEnvelopeNeedsReply,
];

const generatedEditorEmailsById = new Map(
  generatedThreadEmails.map(email => [email.id, email]),
);
const generatedEditorThreads = deepFreeze(Object.fromEntries(
  generatedThreadEmails.map(email => [
    email.gmail_thread_id,
    {
      thread_id: email.gmail_thread_id,
      subject: email.subject,
      emails: [email],
    },
  ]),
));

const generatedTodos = deepFreeze([{
  id: 9101,
  title: 'Review the generated attachment preview message',
  status: 'pending',
  source: 'generated_route_qa',
  email_id: 313,
  created_at: '2026-08-30T13:50:00Z',
  ai_draft_status: null,
}]);

const generatedChatId = 'generated-security-chat';
const generatedChatLongSections = Array.from({ length: 18 }, (_, index) => `
## Generated section ${index + 1}

This deterministic paragraph makes the PDF span multiple pages without using mailbox data. Renée reviews 日本語 text and accessibility marker ✅ ${index + 1}.

- Generated list item A${index + 1}
- Generated list item B${index + 1}

> Generated blockquote ${index + 1} remains readable.
`).join('\n');
const generatedChatMarkdown = `# Generated dependency security

Renée · 日本語 · ✅ — every value on this page is generated locally.

| Boundary | Expected result |
| --- | --- |
| Benign Markdown | Preserved |
| Active content | Removed |

[Safe generated link](https://safe.example.test/generated-chat)

<a id="generated-unsafe-chat-link" href="javascript:globalThis.__generatedChatHref = 1" onclick="globalThis.__generatedChatClick = 1">Unsafe generated link</a>
<div id="generated-hostile-chat-marker" onclick="globalThis.__generatedChatMarker = 1">Hostile attributes are stripped from this retained marker.</div>
<script>globalThis.__generatedChatScript = 1</script>
<iframe srcdoc="<script>parent.__generatedChatFrame = 1</script>"></iframe>
<object data="data:text/html,generated"></object>
<embed src="data:text/html,generated">
<svg width="0" height="0" aria-hidden="true" onload="globalThis.__generatedChatSvg = 1"></svg>
<form id="generated-chat-clobber-probe"><input name="__proto__" value="generated"></form>
<template id="generated-chat-template-probe"><img src="x" onerror="globalThis.__generatedChatTemplate = 1"></template>

\`\`\`text
generated code block — no secrets or mailbox data
\`\`\`

${generatedChatLongSections}`;
const generatedChatConversation = deepFreeze({
  id: generatedChatId,
  title: 'Generated dependency security',
  created_at: '2026-08-30T13:59:00Z',
  updated_at: '2026-08-30T13:59:00Z',
  messages: [
    {
      id: 'generated-chat-user-message',
      role: 'user',
      content: 'Render the generated dependency security fixture.',
      plan: null,
      task_results: null,
      tokens_used: 0,
      created_at: '2026-08-30T13:58:30Z',
    },
    {
      id: 'generated-chat-assistant-message',
      role: 'assistant',
      content: generatedChatMarkdown,
      plan: null,
      task_results: null,
      tokens_used: 0,
      created_at: '2026-08-30T13:59:00Z',
    },
  ],
});
const generatedChatSummary = deepFreeze({
  id: generatedChatConversation.id,
  title: generatedChatConversation.title,
  created_at: generatedChatConversation.created_at,
  updated_at: generatedChatConversation.updated_at,
});

const emailsById = new Map(generatedEmails.map(email => [email.id, email]));

const scenarios = deepFreeze({
  // Baseline order is newest first; the equal-timestamp pair remains stable.
  '': {
    result_ids: [
      ...(replyEnvelopeFixtureEnabled ? [317, 318] : []),
      316, 313, 303, 304, 305, 306, 307, 308, 309, 310, 311, 312, 302, 301,
    ],
  },
  [compoundQuery]: { result_ids: [301] },
  [removalQuery]: { result_ids: [301, 304] },
  'no-match': { result_ids: [] },
  'slow:request': { result_ids: [310], delay_ms: 650 },
  'fast:request': { result_ids: [311], delay_ms: 15 },
  'in:sent': { result_ids: [305], overrides_mailbox: true },
  'in:trash': { result_ids: [308], overrides_mailbox: true },
  'in:spam': { result_ids: [309], overrides_mailbox: true },
  'in:trash OR in:spam': { result_ids: [309, 308], overrides_mailbox: true },
  'in:anywhere': { result_ids: [309, 308, 305, 301], overrides_mailbox: true },
  'backend-error': {
    result_ids: [],
    status: 422,
    detail: 'Generated search validation error for backend-error',
  },
  'service-down': {
    result_ids: [],
    status: 503,
    detail: 'Generated search service unavailable for service-down',
  },
  'ticket:1234': { result_ids: [304, 307] },
  'subject:"Quarterly & Planning"': { result_ids: [301, 303, 304, 312] },
});

const generatedAccounts = deepFreeze([
  {
    id: 1,
    email: 'search.primary@example.test',
    display_name: 'Generated Search Primary',
    description: 'Generated Search Primary',
    short_label: 'Primary',
    is_active: true,
    has_calendar_scope: true,
    sync_status: { status: 'idle', last_incremental_sync: fixtureNow.toISOString() },
    calendar_sync_status: { status: 'idle' },
  },
  {
    id: 2,
    email: 'search.secondary@example.test',
    display_name: 'Generated Search Secondary',
    description: 'Generated Search Secondary',
    short_label: 'Secondary',
    is_active: true,
    has_calendar_scope: true,
    sync_status: { status: 'idle', last_incremental_sync: fixtureNow.toISOString() },
    calendar_sync_status: { status: 'idle' },
  },
]);

const generatedLabels = deepFreeze([
  {
    id: 1,
    account_id: 1,
    gmail_label_id: 'Label_QA_SHARED',
    name: 'Generated Shared Search',
    label_type: 'user',
  },
  {
    id: 2,
    account_id: 2,
    gmail_label_id: 'Label_QA_SHARED',
    name: 'Generated Shared Search',
    label_type: 'user',
  },
]);

const audit = {
  queries: [],
  action_status_reads: [],
  attachment_reads: [],
  attachment_preview_reads: [],
  chat_reads: [],
  reply_envelope_reads: [],
  mutation_attempts: [],
  unknown_routes: [],
};
const routeAssetReads = [];
const routeAssetAttempts = new Map();
let routeAssetsPromise = null;
const editorAssetReads = [];
const editorAssetAttempts = new Map();
let editorAssetsPromise = null;
const attachmentAttempts = new Map();
const attachmentPreviewAttempts = new Map();
let receivedSequence = 0;
let respondedSequence = 0;

function beginAudit(request, url, extra = {}) {
  receivedSequence += 1;
  return {
    received_sequence: receivedSequence,
    responded_sequence: null,
    method: request.method,
    original_url: request.url || '',
    pathname: url.pathname,
    status: null,
    ...extra,
  };
}

function completeAudit(entry, status, resultIds = []) {
  respondedSequence += 1;
  entry.responded_sequence = respondedSequence;
  entry.status = status;
  entry.result_ids = [...resultIds];
}

function writeJson(response, payload, status = 200, extraHeaders = {}) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
    'Cache-Control': 'no-store',
    ...extraHeaders,
  });
  response.end(body);
}

function writeHtml(response, body, status = 200) {
  response.writeHead(status, {
    'Content-Type': 'text/html; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
    'Cache-Control': 'no-store',
  });
  response.end(body);
}

function replyEnvelopeAuditPayload() {
  return {
    fixture: 'generated-reply-envelope',
    fixture_enabled: replyEnvelopeFixtureEnabled,
    fixture_domains: ['example.test'],
    account_order: generatedAccounts.map(account => ({ id: account.id, email: account.email })),
    decoy_account: { id: 1, email: 'search.primary@example.test' },
    source_account: { id: 2, email: 'search.secondary@example.test' },
    target_message_id: 317,
    missing_source_message_id: 318,
    expected_reply: {
      from: 'search.secondary@example.test',
      to: ['envelope.reply@example.test'],
      cc: [],
    },
    expected_reply_all: {
      from: 'search.secondary@example.test',
      to: ['envelope.reply@example.test', 'teammate@example.test'],
      cc: ['observer@example.test'],
    },
    reads: audit.reply_envelope_reads,
    mutation_attempts: audit.mutation_attempts,
    accepted_mutation_count: audit.mutation_attempts.filter(entry => (
      Number.isInteger(entry.status) && entry.status >= 200 && entry.status < 300
    )).length,
    unknown_routes: audit.unknown_routes,
  };
}

function replyEnvelopeAuditFrame(response) {
  const escapedAudit = JSON.stringify(replyEnvelopeAuditPayload(), null, 2)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;');
  return writeHtml(response, `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Generated reply-envelope audit</title></head>
<body><main><h1>Generated reply-envelope audit</h1><pre>${escapedAudit}</pre></main></body></html>`);
}

function mobileOAuthQaFrame(response, url) {
  const oauthCase = url.searchParams.get('case') === 'error' ? 'error' : 'success';
  const frameQuery = oauthCase === 'error'
    ? 'page=admin&tab=profile&oauth_error=account_mismatch'
    : 'page=calendar&oauth=reauthorized';
  const expectedMessage = oauthCase === 'error'
    ? 'The selected Google account does not match the account being reconnected.'
    : 'Google account reconnected successfully';
  const body = `<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Generated mobile OAuth callback QA</title>
  <style>
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; background: #111827; }
    body { display: grid; min-height: 100vh; place-items: start center; padding: 12px; }
    iframe { width: 375px; height: 812px; max-width: 100%; border: 0; border-radius: 14px; background: white; box-shadow: 0 22px 70px rgb(0 0 0 / .4); }
  </style>
</head>
<body data-qa-ready="false">
  <iframe id="mobile-oauth-app" src="/?${frameQuery}" title="Generated OAuth callback at 375 by 812 pixels"></iframe>
  <script>
    const frame = document.getElementById('mobile-oauth-app');
    const expectedMessage = ${JSON.stringify(expectedMessage)};
    const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
    frame.addEventListener('load', async () => {
      const doc = frame.contentDocument;
      for (let attempt = 0; attempt < 100; attempt += 1) {
        const notification = doc.querySelector('[aria-label="Notifications"]');
        if (notification?.textContent?.includes(expectedMessage)) {
          document.body.dataset.qaMetrics = JSON.stringify({
            innerWidth: frame.contentWindow.innerWidth,
            innerHeight: frame.contentWindow.innerHeight,
            clientWidth: doc.documentElement.clientWidth,
            scrollWidth: doc.documentElement.scrollWidth,
            path: frame.contentWindow.location.pathname,
            query: frame.contentWindow.location.search,
            notification: notification.textContent.trim(),
          });
          document.body.dataset.qaReady = 'true';
          break;
        }
        await delay(25);
      }
    });
  </script>
</body>
</html>`;
  return writeHtml(response, body);
}

function mobileRouteQaFrame(response, url) {
  const routeCase = ['slow', 'fail-once'].includes(url.searchParams.get('case'))
    ? url.searchParams.get('case')
    : 'slow';
  const frameHeight = url.searchParams.get('short') === '1' ? 390 : 812;
  const run = url.searchParams.get('run') || `generated-mobile-${routeCase}`;
  const frameQuery = new URLSearchParams({
    page: 'inbox',
    qa_route_case: routeCase,
    qa_route_target: 'calendar',
    qa_route_run: run,
  });
  const expectedState = routeCase === 'slow' ? 'loading' : 'error';
  const body = `<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Generated mobile lazy-route QA</title>
  <style>
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; background: #111827; }
    body { display: grid; min-height: 100vh; place-items: start center; padding: 12px; }
    iframe { width: 375px; height: ${frameHeight}px; max-width: 100%; border: 0; border-radius: 14px; background: white; box-shadow: 0 22px 70px rgb(0 0 0 / .4); }
  </style>
</head>
<body data-qa-ready="false">
  <iframe id="mobile-route-app" src="/?${frameQuery.toString()}" title="Generated lazy-route mail at 375 by ${frameHeight} pixels"></iframe>
  <script>
    const frame = document.getElementById('mobile-route-app');
    const routeCase = ${JSON.stringify(routeCase)};
    const expectedState = ${JSON.stringify(expectedState)};
    const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
    frame.addEventListener('load', async () => {
      const doc = frame.contentDocument;
      let calendarTab = null;
      for (let attempt = 0; attempt < 120; attempt += 1) {
        calendarTab = doc.querySelector('[aria-label="Calendar tab"]');
        const inboxReady = doc.querySelector('main[aria-label="Email content"]')
          && !doc.querySelector('[data-route-key="inbox"][data-route-state="loading"]');
        if (calendarTab && inboxReady) {
          calendarTab.click();
          break;
        }
        await delay(25);
      }
      for (let attempt = 0; attempt < 120; attempt += 1) {
        const routeState = doc.querySelector('[data-route-key="calendar"][data-route-state="' + expectedState + '"]');
        if (routeState) {
          await delay(routeCase === 'slow' ? 220 : 80);
          const controls = [...routeState.querySelectorAll('button, a[href]')];
          const topbarControls = [...doc.querySelectorAll('.primary-nav > button:not(.fixed)')];
          document.body.dataset.qaMetrics = JSON.stringify({
            innerWidth: frame.contentWindow.innerWidth,
            innerHeight: frame.contentWindow.innerHeight,
            clientWidth: doc.documentElement.clientWidth,
            scrollWidth: doc.documentElement.scrollWidth,
            routeState: routeState.dataset.routeState,
            routeKey: routeState.dataset.routeKey,
            statusText: routeState.querySelector('[role="status"]')?.textContent?.trim() || null,
            alertText: routeState.getAttribute('role') === 'alert' ? routeState.textContent?.trim() : null,
            minRouteControlHeight: controls.length
              ? Math.min(...controls.map(element => element.getBoundingClientRect().height))
              : null,
            minTopbarControlHeight: topbarControls.length
              ? Math.min(...topbarControls.map(element => element.getBoundingClientRect().height))
              : null,
            calendarCurrent: calendarTab.getAttribute('aria-current'),
          });
          document.body.dataset.qaReady = 'true';
          break;
        }
        await delay(25);
      }
    });
  </script>
</body>
</html>`;
  return writeHtml(response, body);
}

function mobileEditorQaFrame(response, url) {
  const surface = url.searchParams.get('surface') === 'flow-reply' ? 'flow-reply' : 'compose';
  const editorCase = ['slow', 'fail-once'].includes(url.searchParams.get('case'))
    ? url.searchParams.get('case')
    : 'slow';
  const frameHeight = url.searchParams.get('short') === '1' ? 390 : 812;
  const run = url.searchParams.get('run') || `generated-mobile-${surface}-${editorCase}`;
  const frameQuery = new URLSearchParams({
    page: surface === 'flow-reply' ? 'flow' : 'inbox',
    qa_editor_surface: surface,
    qa_editor_case: editorCase,
    qa_editor_run: run,
  });
  const expectedState = editorCase === 'slow' ? 'loading' : 'error';
  const body = `<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Generated mobile lazy-editor QA</title>
  <style>
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; background: #111827; }
    body { display: grid; min-height: 100vh; place-items: start center; padding: 12px; }
    iframe { width: 375px; height: ${frameHeight}px; max-width: 100%; border: 0; border-radius: 14px; background: white; box-shadow: 0 22px 70px rgb(0 0 0 / .4); }
  </style>
</head>
<body data-qa-ready="false">
  <iframe id="mobile-editor-app" src="/?${frameQuery.toString()}" title="Generated ${surface} lazy-editor mail at 375 by ${frameHeight} pixels"></iframe>
  <script>
    const frame = document.getElementById('mobile-editor-app');
    const surface = ${JSON.stringify(surface)};
    const editorCase = ${JSON.stringify(editorCase)};
    const expectedState = ${JSON.stringify(expectedState)};
    const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
    frame.addEventListener('load', async () => {
      const doc = frame.contentDocument;
      let opener = null;
      for (let attempt = 0; attempt < 160; attempt += 1) {
        opener = surface === 'flow-reply'
          ? doc.querySelector('[aria-label^="Open Generated cold editor reply"]')
          : doc.querySelector('[data-shortcut="nav.compose"]');
        if (opener) {
          opener.click();
          break;
        }
        await delay(25);
      }

      for (let attempt = 0; attempt < 160; attempt += 1) {
        const editorState = doc.querySelector('[data-editor-state="' + expectedState + '"]');
        if (editorState) {
          await delay(editorCase === 'slow' ? 220 : 80);
          const controls = [...editorState.querySelectorAll('button, a[href]')];
          const fallback = editorState.querySelector('textarea, [contenteditable="true"]');
          const active = doc.activeElement;
          const stateRect = editorState.getBoundingClientRect();
          document.body.dataset.qaMetrics = JSON.stringify({
            innerWidth: frame.contentWindow.innerWidth,
            innerHeight: frame.contentWindow.innerHeight,
            clientWidth: doc.documentElement.clientWidth,
            scrollWidth: doc.documentElement.scrollWidth,
            clientHeight: doc.documentElement.clientHeight,
            scrollHeight: doc.documentElement.scrollHeight,
            editorState: editorState.dataset.editorState,
            editorSurface: editorState.dataset.editorSurface || surface,
            stateRect: {
              left: stateRect.left,
              right: stateRect.right,
              top: stateRect.top,
              bottom: stateRect.bottom,
              width: stateRect.width,
              height: stateRect.height,
            },
            statusText: editorState.querySelector('[role="status"]')?.textContent?.trim() || null,
            alertText: (editorState.matches('[role="alert"]')
              ? editorState
              : editorState.querySelector('[role="alert"]'))?.textContent?.trim() || null,
            minEditorControlHeight: controls.length
              ? Math.min(...controls.map(element => element.getBoundingClientRect().height))
              : null,
            fallbackPresent: Boolean(fallback),
            fallbackLabel: fallback?.getAttribute('aria-label') || fallback?.getAttribute('placeholder') || null,
            activeElement: active ? {
              tag: active.tagName,
              label: active.getAttribute('aria-label') || active.getAttribute('placeholder') || null,
              shortcut: active.getAttribute('data-shortcut') || null,
            } : null,
            openerFound: Boolean(opener),
          });
          document.body.dataset.qaReady = 'true';
          break;
        }
        await delay(25);
      }
    });
  </script>
</body>
</html>`;
  return writeHtml(response, body);
}

function mobileQaFrame(response, url) {
  const scenario = url.searchParams.get('scenario') === 'compound' ? 'compound' : 'suggestions';
  const query = scenario === 'compound' ? compoundQuery : '';
  const body = `<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Generated mobile search QA</title>
  <style>
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; background: #111827; }
    body { display: grid; min-height: 100vh; place-items: start center; padding: 12px; }
    iframe { width: 375px; height: 812px; max-width: 100%; border: 0; border-radius: 14px; background: white; box-shadow: 0 22px 70px rgb(0 0 0 / .4); }
  </style>
</head>
<body data-qa-ready="false">
  <iframe id="mobile-app" src="/" title="Generated mail at 375 by 812 pixels"></iframe>
  <script>
    const scenario = ${JSON.stringify(scenario)};
    const query = ${JSON.stringify(query)};
    const frame = document.getElementById('mobile-app');
    const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
    const publishMetrics = (doc, input) => {
      const frameWindow = frame.contentWindow;
      const popover = doc.querySelector('.suggestion-popover');
      const interactive = [...doc.querySelectorAll('.clear-search, [role="option"], .search-chip, .summary-actions button')];
      const popoverRect = popover?.getBoundingClientRect();
      document.body.dataset.qaMetrics = JSON.stringify({
        innerWidth: frameWindow.innerWidth,
        innerHeight: frameWindow.innerHeight,
        clientWidth: doc.documentElement.clientWidth,
        scrollWidth: doc.documentElement.scrollWidth,
        inputHeight: input.getBoundingClientRect().height,
        inputFontSize: frameWindow.getComputedStyle(input).fontSize,
        ariaExpanded: input.getAttribute('aria-expanded'),
        minInteractiveHeight: interactive.length
          ? Math.min(...interactive.map(element => element.getBoundingClientRect().height))
          : null,
        popover: popoverRect ? {
          left: popoverRect.left,
          right: popoverRect.right,
          top: popoverRect.top,
          height: popoverRect.height,
        } : null,
        chipCount: doc.querySelectorAll('.search-chip').length,
        resultCountText: doc.querySelector('.summary-copy strong')?.textContent?.trim() || null,
      });
    };
    frame.addEventListener('load', async () => {
      const doc = frame.contentDocument;
      for (let attempt = 0; attempt < 80; attempt += 1) {
        const emailTab = doc.querySelector('[aria-label="Email tab"]');
        if (emailTab) {
          emailTab.click();
          break;
        }
        await delay(25);
      }
      for (let attempt = 0; attempt < 80; attempt += 1) {
        const input = doc.getElementById('email-search-input');
        if (input) {
          if (scenario === 'compound') {
            const setter = Object.getOwnPropertyDescriptor(
              frame.contentWindow.HTMLInputElement.prototype,
              'value',
            ).set;
            setter.call(input, query);
            input.dispatchEvent(new frame.contentWindow.Event('input', { bubbles: true }));
            input.dispatchEvent(new frame.contentWindow.KeyboardEvent('keydown', {
              key: 'Enter',
              code: 'Enter',
              bubbles: true,
            }));
            await delay(220);
          } else {
            input.focus();
            await delay(80);
          }
          publishMetrics(doc, input);
          document.body.dataset.qaReady = 'true';
          break;
        }
        await delay(25);
      }
    });
  </script>
</body>
</html>`;
  return writeHtml(response, body);
}

function mobileAttachmentQaFrame(response) {
  const body = `<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Generated mobile attachment QA</title>
  <style>
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; background: #111827; }
    body { display: grid; min-height: 100vh; place-items: start center; padding: 12px; }
    iframe { width: 375px; height: 812px; max-width: 100%; border: 0; border-radius: 14px; background: white; box-shadow: 0 22px 70px rgb(0 0 0 / .4); }
  </style>
</head>
<body data-qa-ready="false">
  <iframe id="mobile-app" src="/" title="Generated attachment mail at 375 by 812 pixels"></iframe>
  <script>
    const frame = document.getElementById('mobile-app');
    const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
    frame.addEventListener('load', async () => {
      const doc = frame.contentDocument;
      for (let attempt = 0; attempt < 80; attempt += 1) {
        const emailTab = doc.querySelector('[aria-label="Email tab"]');
        if (emailTab) {
          emailTab.click();
          break;
        }
        await delay(25);
      }
      for (let attempt = 0; attempt < 80; attempt += 1) {
        const emailButton = [...doc.querySelectorAll('button')].find(element =>
          element.getAttribute('aria-label') === 'Open email: Quarterly & Planning'
        );
        if (emailButton) {
          emailButton.click();
          break;
        }
        await delay(25);
      }
      for (let attempt = 0; attempt < 80; attempt += 1) {
        const terminalButton = [...doc.querySelectorAll('button')].find(element =>
          element.getAttribute('aria-label')?.includes('final.txt')
        );
        if (terminalButton) {
          terminalButton.click();
          await delay(180);
          const interactive = [...doc.querySelectorAll('button')];
          const attachmentButtons = interactive.filter(element =>
            element.getAttribute('aria-label')?.startsWith('Download ')
          );
          const alert = doc.querySelector('[role="alert"]');
          document.body.dataset.qaMetrics = JSON.stringify({
            innerWidth: frame.contentWindow.innerWidth,
            innerHeight: frame.contentWindow.innerHeight,
            clientWidth: doc.documentElement.clientWidth,
            scrollWidth: doc.documentElement.scrollWidth,
            attachmentCount: attachmentButtons.length,
            minAttachmentHeight: attachmentButtons.length
              ? Math.min(...attachmentButtons.map(element => element.getBoundingClientRect().height))
              : null,
            widestAttachmentRight: attachmentButtons.length
              ? Math.max(...attachmentButtons.map(element => element.getBoundingClientRect().right))
              : null,
            alertRight: alert?.getBoundingClientRect().right || null,
            alertText: alert?.textContent?.trim() || null,
            terminalRetryCount: [...doc.querySelectorAll('button')].filter(element =>
              element.getAttribute('aria-label')?.includes('Retry download')
              && element.getAttribute('aria-label')?.includes('final.txt')
            ).length,
          });
          document.body.dataset.qaReady = 'true';
          break;
        }
        await delay(25);
      }
    });
  </script>
</body>
</html>`;
  return writeHtml(response, body);
}

function mobileAttachmentPreviewQaFrame(
  response,
  {
    frameHeight = 812,
    actionPrefix = 'Preview generated-preview-image.png',
  } = {},
) {
  const body = `<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Generated mobile attachment preview QA</title>
  <style>
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; background: #111827; }
    body { display: grid; min-height: 100vh; place-items: start center; padding: 12px; }
    iframe { width: 375px; height: ${frameHeight}px; max-width: 100%; border: 0; border-radius: 14px; background: white; box-shadow: 0 22px 70px rgb(0 0 0 / .4); }
  </style>
</head>
<body data-qa-ready="false">
  <iframe id="mobile-preview-app" src="/" title="Generated attachment preview at 375 by ${frameHeight} pixels"></iframe>
  <script>
    const frame = document.getElementById('mobile-preview-app');
    const actionPrefix = ${JSON.stringify(actionPrefix)};
    const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
    frame.addEventListener('load', async () => {
      const doc = frame.contentDocument;
      for (let attempt = 0; attempt < 80; attempt += 1) {
        const emailTab = doc.querySelector('[aria-label="Email tab"]');
        if (emailTab) {
          emailTab.click();
          break;
        }
        await delay(25);
      }
      for (let attempt = 0; attempt < 80; attempt += 1) {
        const emailButton = doc.querySelector('[aria-label="Open email: Attachment preview gallery"]');
        if (emailButton) {
          emailButton.click();
          break;
        }
        await delay(25);
      }
      for (let attempt = 0; attempt < 80; attempt += 1) {
        const previewButton = [...doc.querySelectorAll('button')].find(element =>
          element.getAttribute('aria-label')?.startsWith(actionPrefix)
        );
        if (previewButton) {
          previewButton.click();
          await delay(220);
          const dialog = doc.querySelector('[data-attachment-preview] [role="dialog"]');
          const image = dialog?.querySelector('img');
          const previewBody = dialog?.querySelector('.attachment-preview-body');
          const confirmButton = [...(dialog?.querySelectorAll('button') || [])].find(element =>
            element.textContent?.includes('Download anyway')
          );
          const controls = [...(dialog?.querySelectorAll('button, a[href]') || [])];
          const dialogRect = dialog?.getBoundingClientRect();
          const imageRect = image?.getBoundingClientRect();
          document.body.dataset.qaMetrics = JSON.stringify({
            innerWidth: frame.contentWindow.innerWidth,
            innerHeight: frame.contentWindow.innerHeight,
            clientWidth: doc.documentElement.clientWidth,
            scrollWidth: doc.documentElement.scrollWidth,
            dialog: dialogRect ? {
              left: dialogRect.left,
              right: dialogRect.right,
              top: dialogRect.top,
              bottom: dialogRect.bottom,
            } : null,
            image: imageRect ? {
              left: imageRect.left,
              right: imageRect.right,
              top: imageRect.top,
              bottom: imageRect.bottom,
            } : null,
            minControlHeight: controls.length
              ? Math.min(...controls.map(element => element.getBoundingClientRect().height))
              : null,
            controlCount: controls.length,
            appInert: doc.getElementById('app')?.hasAttribute('inert') || false,
            title: dialog?.querySelector('h2')?.textContent?.trim() || null,
            bodyClientHeight: previewBody?.clientHeight || null,
            bodyScrollHeight: previewBody?.scrollHeight || null,
            confirmButton: confirmButton ? {
              top: confirmButton.getBoundingClientRect().top,
              bottom: confirmButton.getBoundingClientRect().bottom,
              visible: confirmButton.getBoundingClientRect().top < frame.contentWindow.innerHeight
                && confirmButton.getBoundingClientRect().bottom > 0,
            } : null,
          });
          document.body.dataset.qaReady = 'true';
          break;
        }
        await delay(25);
      }
    });
  </script>
</body>
</html>`;
  return writeHtml(response, body);
}

function mobileEmailSanitizerQaFrame(response) {
  const body = `<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Generated mobile email sanitizer QA</title>
  <style>
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; background: #111827; }
    body { display: grid; min-height: 100vh; place-items: start center; padding: 12px; }
    iframe { width: 375px; height: 812px; max-width: 100%; border: 0; border-radius: 14px; background: white; box-shadow: 0 22px 70px rgb(0 0 0 / .4); }
  </style>
</head>
<body data-qa-ready="false">
  <iframe id="mobile-email-sanitizer-app" src="/?page=inbox" title="Generated sanitizer email at 375 by 812 pixels"></iframe>
  <script>
    const frame = document.getElementById('mobile-email-sanitizer-app');
    const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
    frame.addEventListener('load', async () => {
      const doc = frame.contentDocument;
      for (let attempt = 0; attempt < 120; attempt += 1) {
        const emailTab = doc.querySelector('[aria-label="Email tab"]');
        if (emailTab) {
          emailTab.click();
          break;
        }
        await delay(25);
      }
      for (let attempt = 0; attempt < 120; attempt += 1) {
        const emailButton = doc.querySelector('[aria-label="Open email: HTML sanitizer boundary QA"]');
        if (emailButton) {
          emailButton.click();
          break;
        }
        await delay(25);
      }
      for (let attempt = 0; attempt < 120; attempt += 1) {
        const emailFrame = doc.querySelector('iframe[title="Email content"]');
        const emailDoc = emailFrame?.contentDocument;
        const marker = emailDoc?.getElementById('generated-safe-email-marker');
        if (marker) {
          const forbidden = emailDoc.querySelectorAll('script, iframe, object, embed, form, input, button, textarea, select, option, template, base, meta');
          const eventAttributes = [...emailDoc.querySelectorAll('*')].flatMap(element =>
            [...element.attributes].filter(attribute => attribute.name.toLowerCase().startsWith('on'))
          );
          const unsafeLink = emailDoc.getElementById('generated-unsafe-email-link');
          const safeLink = emailDoc.getElementById('generated-safe-email-link');
          document.body.dataset.qaMetrics = JSON.stringify({
            innerWidth: frame.contentWindow.innerWidth,
            innerHeight: frame.contentWindow.innerHeight,
            clientWidth: doc.documentElement.clientWidth,
            scrollWidth: doc.documentElement.scrollWidth,
            markerText: marker.textContent.trim(),
            markerFontWeight: emailFrame.contentWindow.getComputedStyle(marker).fontWeight,
            tableCount: emailDoc.querySelectorAll('#generated-safe-email-table').length,
            styleCount: emailDoc.querySelectorAll('#generated-safe-email-style').length,
            forbiddenCount: forbidden.length,
            eventAttributeCount: eventAttributes.length,
            unsafeHref: unsafeLink?.getAttribute('href') || null,
            safeHref: safeLink?.getAttribute('href') || null,
            probesExecuted: [
              '__generatedEmailClick', '__generatedEmailHref', '__generatedEmailError',
              '__generatedEmailScript', '__generatedEmailFrame', '__generatedEmailSvg',
              '__generatedEmailTemplate',
            ].filter(name => Object.hasOwn(emailFrame.contentWindow, name)),
          });
          document.body.dataset.qaReady = 'true';
          break;
        }
        await delay(25);
      }
    });
  </script>
</body>
</html>`;
  return writeHtml(response, body);
}

function mobileChatQaFrame(response) {
  const body = `<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Generated mobile Chat security QA</title>
  <style>
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; background: #111827; }
    body { display: grid; min-height: 100vh; place-items: start center; padding: 12px; }
    iframe { width: 375px; height: 812px; max-width: 100%; border: 0; border-radius: 14px; background: white; box-shadow: 0 22px 70px rgb(0 0 0 / .4); }
  </style>
</head>
<body data-qa-ready="false">
  <iframe id="mobile-chat-app" src="/?page=chat" title="Generated Chat at 375 by 812 pixels"></iframe>
  <script>
    const frame = document.getElementById('mobile-chat-app');
    const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
    frame.addEventListener('load', async () => {
      const doc = frame.contentDocument;
      for (let attempt = 0; attempt < 120; attempt += 1) {
        const sidebarToggle = doc.querySelector('[aria-label="Show conversation sidebar"]');
        if (sidebarToggle) {
          sidebarToggle.click();
          break;
        }
        await delay(25);
      }
      for (let attempt = 0; attempt < 120; attempt += 1) {
        const conversation = [...doc.querySelectorAll('[role="button"]')].find(element =>
          element.textContent?.includes('Generated dependency security')
        );
        if (conversation) {
          conversation.click();
          break;
        }
        await delay(25);
      }
      for (let attempt = 0; attempt < 160; attempt += 1) {
        const markdown = doc.querySelector('.chat-markdown');
        if (markdown) {
          const forbidden = markdown.querySelectorAll('script, iframe, object, embed, form, input, button, textarea, select, option, template, base, meta');
          const eventAttributes = [...markdown.querySelectorAll('*')].flatMap(element =>
            [...element.attributes].filter(attribute => attribute.name.toLowerCase().startsWith('on'))
          );
          const unsafeLink = markdown.querySelector('#generated-unsafe-chat-link');
          const safeLink = [...markdown.querySelectorAll('a')].find(element =>
            element.textContent?.includes('Safe generated link')
          );
          const downloadControls = [...doc.querySelectorAll('[title="Download as Markdown"], [title="Download as PDF"]')];
          document.body.dataset.qaMetrics = JSON.stringify({
            innerWidth: frame.contentWindow.innerWidth,
            innerHeight: frame.contentWindow.innerHeight,
            clientWidth: doc.documentElement.clientWidth,
            scrollWidth: doc.documentElement.scrollWidth,
            markdownWidth: markdown.getBoundingClientRect().width,
            headingCount: markdown.querySelectorAll('h1, h2').length,
            tableCount: markdown.querySelectorAll('table').length,
            blockquoteCount: markdown.querySelectorAll('blockquote').length,
            codeCount: markdown.querySelectorAll('pre code').length,
            forbiddenCount: forbidden.length,
            eventAttributeCount: eventAttributes.length,
            unsafeHref: unsafeLink?.getAttribute('href') || null,
            safeHref: safeLink?.getAttribute('href') || null,
            nonAsciiPresent: markdown.textContent.includes('Renée · 日本語 · ✅'),
            minDownloadHeight: downloadControls.length
              ? Math.min(...downloadControls.map(element => element.getBoundingClientRect().height))
              : null,
            sidebarClosed: !doc.querySelector('[aria-label="Close conversation sidebar"]'),
            probesExecuted: [
              '__generatedChatHref', '__generatedChatClick', '__generatedChatMarker',
              '__generatedChatScript', '__generatedChatFrame', '__generatedChatSvg',
              '__generatedChatTemplate',
            ].filter(name => Object.hasOwn(frame.contentWindow, name)),
          });
          document.body.dataset.qaReady = 'true';
          break;
        }
        await delay(25);
      }
    });
  </script>
</body>
</html>`;
  return writeHtml(response, body);
}

function positiveInteger(value, fallback) {
  const parsed = Number.parseInt(value || '', 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function visibleInMailbox(email, mailbox) {
  const normalized = mailbox.toUpperCase();
  if (normalized === 'ALL') return !email.is_trash && !email.is_spam;
  if (normalized === 'STARRED') return email.is_starred && !email.is_trash && !email.is_spam;
  if (normalized === 'TRASH') return email.is_trash;
  if (normalized === 'SPAM') return email.is_spam;
  if (normalized === 'SENT') return email.is_sent && !email.is_trash;
  if (normalized === 'DRAFTS' || normalized === 'DRAFT') return email.is_draft;
  if (normalized === 'INBOX') {
    return email.labels.includes('INBOX') && !email.is_trash && !email.is_spam;
  }
  return email.labels.some(label => label.toUpperCase() === normalized)
    && !email.is_trash
    && !email.is_spam;
}

function wait(delayMs) {
  if (!delayMs) return Promise.resolve();
  return new Promise(resolveWait => setTimeout(resolveWait, delayMs));
}

async function listEmails(request, response, url) {
  const decodedSearch = url.searchParams.get('search') ?? '';
  const mailbox = url.searchParams.get('mailbox') || 'INBOX';
  const accountValue = url.searchParams.get('account_id');
  const accountId = accountValue === null ? null : Number.parseInt(accountValue, 10);
  const page = positiveInteger(url.searchParams.get('page'), 1);
  const pageSize = Math.min(positiveInteger(url.searchParams.get('page_size'), 50), 200);
  const entry = beginAudit(request, url, {
    decoded_search: decodedSearch,
    mailbox,
    account: accountValue,
    account_id: Number.isFinite(accountId) ? accountId : null,
    page,
    page_size: pageSize,
    result_ids: [],
  });
  audit.queries.push(entry);

  const scenario = Object.hasOwn(scenarios, decodedSearch) ? scenarios[decodedSearch] : null;
  if (!scenario) {
    completeAudit(entry, 422);
    return writeJson(
      response,
      { detail: 'No generated search QA scenario for decoded search' },
      422,
    );
  }

  await wait(scenario.delay_ms);

  const status = scenario.status || 200;
  if (status !== 200) {
    completeAudit(entry, status);
    return writeJson(response, { detail: scenario.detail }, status);
  }

  const filtered = scenario.result_ids
    .map(id => emailsById.get(id))
    .filter(Boolean)
    .filter(email => scenario.overrides_mailbox || visibleInMailbox(email, mailbox))
    .filter(email => accountId === null || email.account_id === accountId);
  const offset = (page - 1) * pageSize;
  const pageEmails = filtered.slice(offset, offset + pageSize);
  const resultIds = pageEmails.map(email => email.id);

  completeAudit(entry, 200, resultIds);
  return writeJson(response, {
    emails: pageEmails,
    total: filtered.length,
    page,
    page_size: pageSize,
  });
}

const mimeTypes = Object.freeze({
  '.css': 'text/css; charset=utf-8',
  '.gif': 'image/gif',
  '.html': 'text/html; charset=utf-8',
  '.ico': 'image/x-icon',
  '.jpeg': 'image/jpeg',
  '.jpg': 'image/jpeg',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.txt': 'text/plain; charset=utf-8',
  '.webp': 'image/webp',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
});

async function existingFile(pathname) {
  try {
    const fileStat = await stat(pathname);
    return fileStat.isFile() ? fileStat : null;
  } catch {
    return null;
  }
}

const routeSourceByPage = Object.freeze({
  flow: 'src/pages/Flow.svelte',
  inbox: 'src/pages/Inbox.svelte',
  calendar: 'src/pages/Calendar.svelte',
  compose: 'src/pages/Compose.svelte',
  stats: 'src/pages/Stats.svelte',
  'ai-insights': 'src/pages/AIInsights.svelte',
  todos: 'src/pages/Todos.svelte',
  chat: 'src/pages/Chat.svelte',
  subscriptions: 'src/pages/Subscriptions.svelte',
  admin: 'src/pages/Admin.svelte',
});

function assetPath(file) {
  if (!file) return null;
  return file.startsWith('/') ? file : `/${file}`;
}

function sortedAssetClosure(mode, rootPaths, assetsByPath) {
  const assets = [...assetsByPath.values()].sort((left, right) => (
    left.path.localeCompare(right.path)
  ));
  return {
    mode,
    root_paths: [...new Set(rootPaths)].sort(),
    paths: assets.map(asset => asset.path),
    assets,
  };
}

function editorAssetsFromManifest(manifest) {
  const rootKeys = Object.entries(manifest)
    .filter(([key, record]) => (
      key.startsWith('src/components/email/RichEditor.svelte')
      || record?.name === 'RichEditor'
    ))
    .map(([key]) => key);
  const rootKeySet = new Set(rootKeys);
  const rootPaths = [];
  const visited = new Set();
  const assetsByPath = new Map();

  function addAsset(path, kind, source) {
    if (!path) return;
    const existing = assetsByPath.get(path);
    if (!existing || kind === 'root') assetsByPath.set(path, { path, kind, source });
  }

  function visit(key, kind) {
    if (visited.has(key)) return;
    const record = manifest[key];
    if (!record || (record.isEntry && !rootKeySet.has(key))) return;
    visited.add(key);

    const filePath = assetPath(record.file);
    if (filePath) {
      addAsset(filePath, kind, key);
      if (kind === 'root') rootPaths.push(filePath);
    }
    for (const cssFile of record.css || []) {
      addAsset(assetPath(cssFile), 'css', key);
    }
    for (const importedKey of record.imports || []) {
      const importedRecord = manifest[importedKey];
      if (importedRecord?.isEntry) continue;
      visit(importedKey, 'dependency');
    }
  }

  for (const rootKey of rootKeys) visit(rootKey, 'root');
  return sortedAssetClosure('manifest', rootPaths, assetsByPath);
}

function staticImportSpecifiers(contents) {
  const specifiers = new Set();
  const fromPattern = /\b(?:import|export)\s*[^\"'();]*?\bfrom\s*[\"']([^\"']+)[\"']/g;
  const sideEffectPattern = /\bimport\s*[\"']([^\"']+)[\"']/g;
  for (const pattern of [fromPattern, sideEffectPattern]) {
    for (const match of contents.matchAll(pattern)) specifiers.add(match[1]);
  }
  return [...specifiers];
}

async function editorAssetsFromAssetScan() {
  const [assetNames, indexContents] = await Promise.all([
    readdir(resolve(frontendDist, 'assets')),
    readFile(resolve(frontendDist, 'index.html'), 'utf8'),
  ]);
  const knownAssetPaths = new Set(assetNames.map(name => `/assets/${name}`));
  const eagerPaths = new Set(
    [...indexContents.matchAll(/\b(?:src|href)=[\"']([^\"']+)[\"']/g)]
      .map(match => {
        try {
          return new URL(match[1], 'http://generated.invalid/').pathname;
        } catch {
          return null;
        }
      })
      .filter(path => path?.startsWith('/assets/')),
  );
  const rootPaths = assetNames
    .filter(name => /^RichEditor-.+\.js$/.test(name))
    .map(name => `/assets/${name}`)
    .sort();
  const rootCssPaths = assetNames
    .filter(name => /^RichEditor-.+\.css$/.test(name))
    .map(name => `/assets/${name}`)
    .sort();
  const assetsByPath = new Map();
  for (const path of rootPaths) {
    assetsByPath.set(path, { path, kind: 'root', source: 'asset-scan' });
  }
  for (const path of rootCssPaths) {
    assetsByPath.set(path, { path, kind: 'css', source: 'asset-scan' });
  }

  const pending = [...rootPaths];
  const scanned = new Set();
  while (pending.length > 0) {
    const currentPath = pending.shift();
    if (scanned.has(currentPath)) continue;
    scanned.add(currentPath);
    const contents = await readFile(resolve(frontendDist, currentPath.replace(/^\/+/, '')), 'utf8');
    for (const specifier of staticImportSpecifiers(contents)) {
      let dependencyPath;
      try {
        dependencyPath = new URL(specifier, `http://generated.invalid${currentPath}`).pathname;
      } catch {
        continue;
      }
      if (
        !dependencyPath.startsWith('/assets/')
        || !knownAssetPaths.has(dependencyPath)
        || eagerPaths.has(dependencyPath)
      ) continue;
      if (!assetsByPath.has(dependencyPath)) {
        assetsByPath.set(dependencyPath, {
          path: dependencyPath,
          kind: dependencyPath.endsWith('.css') ? 'css' : 'dependency',
          source: currentPath,
        });
      }
      if (dependencyPath.endsWith('.js') && !scanned.has(dependencyPath)) {
        pending.push(dependencyPath);
      }
    }
  }

  return sortedAssetClosure('asset-scan', rootPaths, assetsByPath);
}

async function loadEditorAssets() {
  if (!editorAssetsPromise) {
    editorAssetsPromise = readFile(frontendManifest, 'utf8')
      .then(async contents => {
        const closure = editorAssetsFromManifest(JSON.parse(contents));
        return closure.root_paths.length > 0 ? closure : editorAssetsFromAssetScan();
      })
      .catch(error => {
        if (error?.code !== 'ENOENT') throw error;
        return editorAssetsFromAssetScan();
      });
  }
  return editorAssetsPromise;
}

async function loadRouteAssets() {
  if (!routeAssetsPromise) {
    routeAssetsPromise = readFile(frontendManifest, 'utf8')
      .then(contents => {
        const manifest = JSON.parse(contents);
        return Object.fromEntries(Object.entries(routeSourceByPage).map(([page, source]) => {
          const asset = manifest[source]?.file;
          return [page, asset ? `/${asset}` : null];
        }));
      })
      .catch(async error => {
        if (error?.code !== 'ENOENT') throw error;
        const assetNames = await readdir(resolve(frontendDist, 'assets'));
        return Object.fromEntries(Object.entries(routeSourceByPage).map(([page, source]) => {
          const componentName = source.split('/').at(-1).replace(/\.svelte$/, '');
          const asset = assetNames.find(name => name.startsWith(`${componentName}-`) && name.endsWith('.js'));
          return [page, asset ? `/assets/${asset}` : null];
        }));
      });
  }
  return routeAssetsPromise;
}

async function applyEditorAssetScenario(request, response, url) {
  const editorAssets = await loadEditorAssets();
  const requestedAsset = editorAssets.assets.find(asset => asset.path === url.pathname);
  if (!requestedAsset) return false;

  const canForceScenario = (
    editorFixtureEnabled
    && forcedEditorCase
    && forcedEditorRun
    && /^[a-zA-Z0-9._-]{1,100}$/.test(forcedEditorRun)
    && requestedAsset.kind === 'root'
  );
  const editorCase = canForceScenario ? forcedEditorCase : 'normal';
  const run = canForceScenario ? forcedEditorRun : null;
  const attemptKey = `${run || 'normal'}:${url.pathname}`;
  const attempt = (editorAssetAttempts.get(attemptKey) || 0) + 1;
  editorAssetAttempts.set(attemptKey, attempt);
  const startedAt = Date.now();
  const entry = {
    sequence: editorAssetReads.length + 1,
    asset_kind: requestedAsset.kind,
    case: editorCase,
    run,
    path: url.pathname,
    attempt,
    status: null,
    duration_ms: null,
    aborted: false,
  };
  editorAssetReads.push(entry);
  request.once('aborted', () => { entry.aborted = true; });

  if (editorCase === 'slow') await wait(1200);
  if (request.aborted || response.destroyed) {
    entry.status = 499;
    entry.duration_ms = Date.now() - startedAt;
    return true;
  }
  if (editorCase === 'fail-once' && attempt === 1) {
    entry.status = 503;
    entry.duration_ms = Date.now() - startedAt;
    const body = 'Generated transient lazy-editor failure';
    response.writeHead(503, {
      'Content-Type': 'text/plain; charset=utf-8',
      'Content-Length': Buffer.byteLength(body),
      'Cache-Control': 'no-store',
    });
    response.end(body);
    return true;
  }

  entry.status = 200;
  entry.duration_ms = Date.now() - startedAt;
  return false;
}

async function routeAssetScenario(request, url) {
  const routeAssets = await loadRouteAssets();
  if (
    forcedRouteCase
    && routeSourceByPage[forcedRouteTarget]
    && forcedRouteRun
    && /^[a-zA-Z0-9._-]{1,100}$/.test(forcedRouteRun)
    && url.pathname === routeAssets[forcedRouteTarget]
  ) {
    return {
      routeCase: forcedRouteCase,
      route: forcedRouteTarget,
      run: forcedRouteRun,
    };
  }

  const referrer = request.headers.referer;
  if (!referrer) return null;

  let referrerUrl;
  try {
    referrerUrl = new URL(referrer);
  } catch {
    return null;
  }

  const routeCase = referrerUrl.searchParams.get('qa_route_case');
  const route = referrerUrl.searchParams.get('qa_route_target');
  const run = referrerUrl.searchParams.get('qa_route_run');
  if (!['slow', 'fail-once'].includes(routeCase) || !routeSourceByPage[route] || !run) return null;
  if (!/^[a-zA-Z0-9._-]{1,100}$/.test(run)) return null;

  if (url.pathname !== routeAssets[route]) return null;
  return { routeCase, route, run };
}

async function applyRouteAssetScenario(request, response, url) {
  const routeAssets = await loadRouteAssets();
  const requestedRoute = Object.entries(routeAssets).find(([, path]) => path === url.pathname)?.[0];
  if (!requestedRoute) return false;
  const scenario = await routeAssetScenario(request, url) || {
    routeCase: 'normal',
    route: requestedRoute,
    run: null,
  };

  const attemptKey = `${scenario.run || 'normal'}:${scenario.route}:${url.pathname}`;
  const attempt = (routeAssetAttempts.get(attemptKey) || 0) + 1;
  routeAssetAttempts.set(attemptKey, attempt);
  const startedAt = Date.now();
  const entry = {
    sequence: routeAssetReads.length + 1,
    route: scenario.route,
    case: scenario.routeCase,
    run: scenario.run,
    path: url.pathname,
    attempt,
    status: null,
    duration_ms: null,
    aborted: false,
  };
  routeAssetReads.push(entry);
  request.once('aborted', () => { entry.aborted = true; });

  if (scenario.routeCase === 'slow') await wait(1200);
  if (scenario.routeCase === 'fail-once' && attempt === 1) {
    entry.status = 503;
    entry.duration_ms = Date.now() - startedAt;
    const body = 'Generated transient lazy-route failure';
    response.writeHead(503, {
      'Content-Type': 'text/plain; charset=utf-8',
      'Content-Length': Buffer.byteLength(body),
      'Cache-Control': 'no-store',
    });
    response.end(body);
    return true;
  }

  entry.status = 200;
  entry.duration_ms = Date.now() - startedAt;
  return false;
}

async function serveFrontend(request, response, url) {
  let decodedPath;
  try {
    decodedPath = decodeURIComponent(url.pathname);
  } catch {
    const entry = beginAudit(request, url);
    audit.unknown_routes.push(entry);
    completeAudit(entry, 400);
    writeJson(response, { detail: 'Malformed generated QA URL' }, 400);
    return;
  }

  const relativePath = decodedPath === '/' ? 'index.html' : decodedPath.replace(/^\/+/, '');
  let candidate = resolve(frontendDist, relativePath);
  const insideDist = candidate === frontendDist || candidate.startsWith(`${frontendDist}${sep}`);
  if (!insideDist) {
    const entry = beginAudit(request, url);
    audit.unknown_routes.push(entry);
    completeAudit(entry, 404);
    writeJson(response, { detail: 'Generated QA static path not found' }, 404);
    return;
  }

  let fileStat = await existingFile(candidate);
  if (!fileStat && !extname(relativePath)) {
    candidate = resolve(frontendDist, 'index.html');
    fileStat = await existingFile(candidate);
  }
  if (!fileStat) {
    const entry = beginAudit(request, url);
    audit.unknown_routes.push(entry);
    completeAudit(entry, 404);
    writeJson(response, { detail: 'Generated QA static file not found' }, 404);
    return;
  }

  if (await applyEditorAssetScenario(request, response, url)) return;
  if (await applyRouteAssetScenario(request, response, url)) return;

  response.writeHead(200, {
    'Content-Type': mimeTypes[extname(candidate).toLowerCase()] || 'application/octet-stream',
    'Content-Length': fileStat.size,
    'Cache-Control': 'no-store',
  });
  const stream = createReadStream(candidate);
  stream.on('error', () => {
    if (!response.headersSent) writeJson(response, { detail: 'Could not read generated QA static file' }, 500);
    else response.destroy();
  });
  stream.pipe(response);
}

const eventStreams = new Set();

async function handleGet(request, response, url) {
  const { pathname } = url;

  if (pathname === '/favicon.ico') {
    response.writeHead(204, { 'Cache-Control': 'no-store' });
    response.end();
    return;
  }
  if (pathname === '/__qa/mobile') return mobileQaFrame(response, url);
  if (pathname === '/__qa/attachment-mobile') return mobileAttachmentQaFrame(response);
  if (pathname === '/__qa/attachment-preview-mobile') {
    const shortViewport = url.searchParams.get('short') === '1';
    return mobileAttachmentPreviewQaFrame(response, shortViewport
      ? {
        frameHeight: 390,
        actionPrefix: 'Download generated-preview-script.js',
      }
      : undefined);
  }
  if (pathname === '/__qa/route-mobile') return mobileRouteQaFrame(response, url);
  if (pathname === '/__qa/editor-mobile') return mobileEditorQaFrame(response, url);
  if (pathname === '/__qa/email-sanitizer-mobile') return mobileEmailSanitizerQaFrame(response);
  if (pathname === '/__qa/chat-mobile') return mobileChatQaFrame(response);
  if (pathname === '/__qa/oauth-mobile') return mobileOAuthQaFrame(response, url);
  if (pathname === '/__qa/reply-envelope-audit') return replyEnvelopeAuditFrame(response);
  if (pathname === '/api/test/editor-audit') {
    return writeJson(response, {
      fixture: 'generated-lazy-editor',
      fixture_enabled: editorFixtureEnabled,
      fixture_domains: ['example.test'],
      fixture_message_ids: generatedEditorNeedsReply.map(email => email.id),
      forced_case: forcedEditorCase,
      forced_run: forcedEditorRun,
      editor_assets: await loadEditorAssets(),
      asset_reads: editorAssetReads,
      mutation_attempts: audit.mutation_attempts,
      unknown_routes: audit.unknown_routes,
    });
  }
  if (pathname === '/api/test/route-audit') {
    return writeJson(response, {
      fixture: 'generated-lazy-routes',
      route_assets: await loadRouteAssets(),
      asset_reads: routeAssetReads,
      mutation_attempts: audit.mutation_attempts,
      unknown_routes: audit.unknown_routes,
    });
  }
  if (pathname === '/api/test/security-audit') {
    return writeJson(response, {
      fixture: 'generated-content-security',
      fixture_domains: ['example.test'],
      fixture_message_id: 316,
      fixture_conversation_id: generatedChatId,
      chat_reads: audit.chat_reads,
      mutation_attempts: audit.mutation_attempts,
      unknown_routes: audit.unknown_routes,
    });
  }
  if (pathname === '/api/test/reply-envelope-audit') {
    return writeJson(response, replyEnvelopeAuditPayload());
  }
  if (pathname === '/api/test/audit') {
    return writeJson(response, {
      fixture: 'generated-structured-search',
      fixture_domains: ['example.test'],
      fixture_account_ids: generatedAccounts.map(account => account.id),
      fixture_message_ids: [
        ...generatedEmails.map(email => email.id),
        ...(editorFixtureEnabled ? generatedEditorNeedsReply.map(email => email.id) : []),
      ],
      scenarios: scenarioQueries,
      queries: audit.queries,
      action_status_reads: audit.action_status_reads,
      attachment_reads: audit.attachment_reads,
      attachment_preview_reads: audit.attachment_preview_reads,
      chat_reads: audit.chat_reads,
      mutation_attempts: audit.mutation_attempts,
      unknown_routes: audit.unknown_routes,
    });
  }
  if (pathname === '/api/auth/me') {
    return writeJson(response, { id: 1, username: 'generated-search-qa', is_admin: false });
  }
  if (pathname === '/api/auth/ui-preferences') {
    return writeJson(response, { thread_order: 'newest_first', theme: 'amber', color_scheme: 'light' });
  }
  if (pathname === '/api/auth/keyboard-shortcuts') {
    return writeJson(response, { shortcuts: {} });
  }
  if (pathname === '/api/auth/ai-preferences') {
    return writeJson(response, {
      chat_plan_model: 'generated-model',
      chat_execute_model: 'generated-model',
      chat_verify_model: 'generated-model',
      agentic_model: 'generated-model',
      custom_prompt_model: 'generated-model',
      unsubscribe_model: 'generated-model',
      allowed_models: ['generated-model'],
      labels: { 'generated-model': 'Generated QA model' },
    });
  }
  if (pathname === '/api/auth/about-me') return writeJson(response, { about_me: '' });
  if (pathname === '/api/auth/api-tokens') return writeJson(response, []);
  if (pathname === '/api/accounts/') return writeJson(response, generatedAccounts);
  if (pathname === '/api/admin/feature-flags') {
    return writeJson(response, { desktop_app_enabled: false });
  }
  if (pathname === '/api/terminal/settings') {
    return writeJson(response, {
      code: 'generated-route-qa',
      schedule_url_template: '/terminal/generated-route-qa/schedule.json',
      image_url_template: '/terminal/generated-route-qa/image.bmp',
      home_assistant_url: '',
      home_assistant_token_set: false,
      timezone: 'America/New_York',
      variants: [{
        key: 'generated-800x480',
        query: 'variant=generated-800x480',
        image_format: 'PNG',
        width: 800,
        height: 480,
        next_checkin_sec: 900,
      }],
      content_types: [],
      designs: [],
      refresh_interval_presets: [],
    });
  }
  if (pathname === '/api/terminal/devices') return writeJson(response, []);
  if (pathname === '/api/build-version') {
    return writeJson(response, { version: 'generated-structured-search-qa' });
  }
  if (pathname === '/api/events/stream') {
    response.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
    });
    response.write(': generated structured-search QA stream\n\n');
    eventStreams.add(response);
    request.on('close', () => {
      eventStreams.delete(response);
      response.end();
    });
    return;
  }
  if (pathname === '/api/emails/labels/all') {
    const accountId = Number.parseInt(url.searchParams.get('account_id') || '', 10);
    const labels = Number.isFinite(accountId)
      ? generatedLabels.filter(label => label.account_id === accountId)
      : generatedLabels;
    return writeJson(response, labels);
  }
  if (pathname === '/api/emails/' || pathname === '/api/emails') {
    return listEmails(request, response, url);
  }
  if (pathname === '/api/emails/actions/recent') {
    const entry = beginAudit(request, url);
    audit.action_status_reads.push(entry);
    completeAudit(entry, 200);
    return writeJson(response, []);
  }
  if (pathname === '/api/calendar/sync-status') {
    return writeJson(response, { status: 'idle', accounts: [] });
  }
  if (pathname === '/api/calendar/events') {
    return writeJson(response, { events: [], total: 0 });
  }
  if (pathname === '/api/calendar/upcoming') return writeJson(response, { events: [] });
  if (pathname === '/api/todos/') return writeJson(response, { todos: generatedTodos });
  if (pathname === '/api/ai/needs-reply') {
    const emails = replyEnvelopeFixtureEnabled
      ? generatedReplyEnvelopeNeedsReply
      : (editorFixtureEnabled ? generatedEditorNeedsReply : []);
    return writeJson(response, { emails, total: emails.length });
  }
  if (pathname === '/api/ai/trends') {
    return writeJson(response, { summary: '', needs_attention: [] });
  }
  if (pathname === '/api/ai/stats') {
    return writeJson(response, {
      total_emails: 0,
      total_analyzed: 0,
      models: {},
      unanalyzed: { '30d': 0, '90d': 0, '1y': 0, all: 0 },
    });
  }
  if (pathname === '/api/ai/processing/status') {
    return writeJson(response, { active: false, just_finished: false });
  }
  if (pathname === '/api/ai/awaiting-response') {
    return writeJson(response, { emails: [], total: 0 });
  }
  if (pathname === '/api/ai/digests') {
    const digests = replyEnvelopeFixtureEnabled ? [{
      id: 9317,
      thread_id: 'generated-search-thread-317',
      account_id: 2,
      conversation_type: 'discussion',
      summary: 'Generated active-thread account provenance fixture.',
      resolved_outcome: null,
      is_resolved: false,
      key_topics: ['generated QA'],
      message_count: 1,
      participants: ['Generated Envelope Sender'],
      subject: 'Generated active thread provenance',
      latest_date: '2026-08-30T13:59:00Z',
      updated_at: '2026-08-30T14:00:00Z',
    }] : [];
    return writeJson(response, { digests, total: digests.length });
  }
  if (pathname === '/api/chat/conversations') {
    const entry = beginAudit(request, url, { kind: 'conversation-list' });
    audit.chat_reads.push(entry);
    completeAudit(entry, 200, [generatedChatId]);
    return writeJson(response, [generatedChatSummary]);
  }

  if (pathname === `/api/chat/conversations/${generatedChatId}`) {
    const entry = beginAudit(request, url, {
      kind: 'conversation-detail',
      conversation_id: generatedChatId,
    });
    audit.chat_reads.push(entry);
    completeAudit(entry, 200, [generatedChatId]);
    return writeJson(response, generatedChatConversation);
  }

  const threadMatch = pathname.match(/^\/api\/emails\/thread\/([^/]+)$/);
  if (threadMatch) {
    let threadId;
    try {
      threadId = decodeURIComponent(threadMatch[1]);
    } catch {
      return writeJson(response, { detail: 'Malformed generated thread ID' }, 400);
    }
    const thread = (editorFixtureEnabled || replyEnvelopeFixtureEnabled)
      ? generatedEditorThreads[threadId]
      : null;
    if (replyEnvelopeFixtureEnabled && thread?.emails?.some(email => [317, 318].includes(email.id))) {
      const entry = beginAudit(request, url, {
        kind: 'thread',
        thread_id: threadId,
      });
      audit.reply_envelope_reads.push(entry);
      completeAudit(entry, 200, thread.emails.map(email => email.id));
    }
    return writeJson(response, thread || { detail: 'Generated thread not found' }, thread ? 200 : 404);
  }

  const emailMatch = pathname.match(/^\/api\/emails\/(\d+)$/);
  if (emailMatch) {
    const emailId = Number(emailMatch[1]);
    const email = emailsById.get(emailId)
      || ((editorFixtureEnabled || replyEnvelopeFixtureEnabled)
        ? generatedEditorEmailsById.get(emailId)
        : null);
    if (replyEnvelopeFixtureEnabled && email && [317, 318].includes(emailId)) {
      const entry = beginAudit(request, url, {
        kind: 'email',
        email_id: emailId,
      });
      audit.reply_envelope_reads.push(entry);
      completeAudit(entry, 200, [emailId]);
    }
    return writeJson(response, email || { detail: 'Generated email not found' }, email ? 200 : 404);
  }

  const attachmentPreviewMatch = pathname.match(/^\/api\/emails\/(\d+)\/attachments\/(\d+)\/preview$/);
  if (attachmentPreviewMatch) {
    const emailId = Number(attachmentPreviewMatch[1]);
    const attachmentId = Number(attachmentPreviewMatch[2]);
    const email = emailsById.get(emailId);
    const attachment = email?.attachments?.find(item => item.id === attachmentId);
    const attempt = (attachmentPreviewAttempts.get(attachmentId) || 0) + 1;
    attachmentPreviewAttempts.set(attachmentId, attempt);
    const entry = beginAudit(request, url, {
      email_id: emailId,
      attachment_id: attachmentId,
      attempt,
      aborted: false,
      request_closed: false,
      response_finished: false,
      response_closed: false,
      closed_before_finish: false,
    });
    audit.attachment_preview_reads.push(entry);
    request.once('aborted', () => { entry.aborted = true; });
    request.once('close', () => { entry.request_closed = true; });
    response.once('finish', () => { entry.response_finished = true; });
    response.once('close', () => {
      entry.response_closed = true;
      entry.closed_before_finish = !entry.response_finished;
    });

    if (!attachment) {
      completeAudit(entry, 404);
      return writeJson(response, { detail: 'Generated attachment not found' }, 404);
    }
    if ([8303, 8418].includes(attachmentId)) await wait(650);
    if (request.aborted || response.destroyed) {
      completeAudit(entry, 499);
      return;
    }
    if ([8304, 8419].includes(attachmentId) && attempt % 2 === 1) {
      completeAudit(entry, 503);
      return writeJson(response, { detail: 'Generated transient preview failure' }, 503);
    }
    if (attachmentId === 8305) {
      completeAudit(entry, 413);
      return writeJson(response, { detail: 'This attachment is too large to preview' }, 413);
    }
    if (attachmentId === 8306) {
      completeAudit(entry, 409);
      return writeJson(response, { detail: 'Attachment content is unavailable' }, 409);
    }
    if (attachmentId === 8307) {
      completeAudit(entry, 422);
      return writeJson(response, { detail: 'Generated terminal preview validation detail' }, 422);
    }
    if ([8414, 8415, 8416, 8417].includes(attachmentId)) {
      completeAudit(entry, 415);
      return writeJson(response, { detail: 'Preview is not available for this attachment' }, 415);
    }

    let body = generatedPreviewText;
    let kind = 'text';
    let contentType = 'text/plain; charset=utf-8';
    if (attachmentId === 8412) {
      body = generatedPreviewPng;
      kind = 'image';
      contentType = 'image/png';
    } else if (attachmentId === 8413) {
      body = generatedPreviewPdf;
      kind = 'pdf';
      contentType = 'application/pdf';
    }
    completeAudit(entry, 200);
    response.writeHead(200, {
      'Content-Type': contentType,
      'Content-Length': body.length,
      'Content-Disposition': `inline; filename="${attachment.filename}"`,
      'X-Attachment-Preview-Kind': kind,
      'X-Attachment-Preview-Truncated': 'false',
      'Cache-Control': 'private, no-store',
      'X-Content-Type-Options': 'nosniff',
      'Cross-Origin-Resource-Policy': 'same-origin',
      'Content-Security-Policy': "sandbox; default-src 'none'; script-src 'none'; object-src 'none'",
    });
    response.end(body);
    return;
  }

  const attachmentMatch = pathname.match(/^\/api\/emails\/(\d+)\/attachments\/(\d+)\/download$/);
  if (attachmentMatch) {
    const emailId = Number(attachmentMatch[1]);
    const attachmentId = Number(attachmentMatch[2]);
    const email = emailsById.get(emailId);
    const attachment = email?.attachments?.find(item => item.id === attachmentId);
    const attempt = (attachmentAttempts.get(attachmentId) || 0) + 1;
    attachmentAttempts.set(attachmentId, attempt);
    const entry = beginAudit(request, url, {
      email_id: emailId,
      attachment_id: attachmentId,
      attempt,
      aborted: false,
      request_closed: false,
      response_finished: false,
      response_closed: false,
      closed_before_finish: false,
    });
    audit.attachment_reads.push(entry);
    request.once('aborted', () => { entry.aborted = true; });
    request.once('close', () => { entry.request_closed = true; });
    response.once('finish', () => { entry.response_finished = true; });
    response.once('close', () => {
      entry.response_closed = true;
      entry.closed_before_finish = !entry.response_finished;
    });

    if (!attachment) {
      completeAudit(entry, 404);
      return writeJson(response, { detail: 'Generated attachment not found' }, 404);
    }
    if (attachmentId === 8303) await wait(650);
    if ([8411, 8412, 8413].includes(attachmentId)) await wait(5000);
    if (attachmentId === 8415) await wait(400);
    if (request.aborted || response.destroyed) {
      completeAudit(entry, 499);
      return;
    }
    if (attachmentId === 8304 && attempt % 2 === 1) {
      completeAudit(entry, 503);
      return writeJson(
        response,
        { detail: 'Generated transient attachment service failure' },
        503,
      );
    }
    if (attachmentId === 8305) {
      completeAudit(entry, 413);
      return writeJson(response, { detail: 'Attachment is too large to download' }, 413);
    }
    if (attachmentId === 8306) {
      completeAudit(entry, 409);
      return writeJson(response, { detail: 'Attachment content is unavailable' }, 409);
    }
    if (attachmentId === 8307) {
      completeAudit(entry, 422);
      return writeJson(
        response,
        {
          detail: 'Generated terminal attachment validation detail stays readable even when the filename and explanation are intentionally very long on a narrow screen.',
        },
        422,
      );
    }
    const body = Buffer.from(`Generated attachment ${attachment.id} for ${email.message_id_header}\n`);
    completeAudit(entry, 200);
    response.writeHead(200, {
      'Content-Type': attachment.content_type,
      'Content-Length': body.length,
      'Content-Disposition': `attachment; filename="${attachment.filename}"`,
      'Cache-Control': 'no-store',
    });
    response.end(body);
    return;
  }

  if (!pathname.startsWith('/api/')) return serveFrontend(request, response, url);

  const entry = beginAudit(request, url);
  audit.unknown_routes.push(entry);
  completeAudit(entry, 404);
  return writeJson(
    response,
    { detail: `No generated read-only QA route for GET ${pathname}` },
    404,
  );
}

async function handleRequest(request, response) {
  const url = new URL(request.url, `http://${host}:${port}`);
  const { pathname } = url;

  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method)) {
    const entry = beginAudit(request, url);
    audit.mutation_attempts.push(entry);
    completeAudit(entry, 405);
    return writeJson(
      response,
      { detail: 'Generated structured-search QA is read-only' },
      405,
      { Allow: 'GET' },
    );
  }
  if (request.method === 'GET') return handleGet(request, response, url);

  const entry = beginAudit(request, url);
  audit.unknown_routes.push(entry);
  completeAudit(entry, 405);
  return writeJson(
    response,
    { detail: `Unsupported method ${request.method}` },
    405,
    { Allow: 'GET' },
  );
}

const server = createServer((request, response) => {
  Promise.resolve(handleRequest(request, response)).catch(error => {
    if (!response.headersSent) writeJson(response, { detail: error.message }, 500);
    else response.destroy();
  });
});

server.listen(port, host, () => {
  process.stdout.write(`Generated structured-search QA listening on http://${host}:${port}\n`);
});

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    for (const response of eventStreams) response.end();
    eventStreams.clear();
    server.close(() => process.exit(0));
  });
}
