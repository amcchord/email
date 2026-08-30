import assert from 'node:assert/strict';
import test from 'node:test';

import {
  attachmentPreviewHint,
  attachmentSafetyNotice,
  attachmentTypeLabel,
  isCurrentAttachmentPreviewRequest,
  materializeAttachmentPreview,
  releaseAttachmentPreview,
} from './attachmentPreview.js';

test('preview hints require compatible inert renderer families', () => {
  assert.equal(attachmentPreviewHint({ filename: 'notes.txt', content_type: 'text/plain' }), 'text');
  assert.equal(attachmentPreviewHint({ filename: 'photo.png', content_type: 'image/png' }), 'image');
  assert.equal(attachmentPreviewHint({ filename: 'brief.pdf', content_type: 'application/pdf' }), 'pdf');
  assert.equal(attachmentPreviewHint({ filename: 'photo.exe', content_type: 'image/png' }), null);
  assert.equal(attachmentPreviewHint({ filename: 'photo.png', content_type: 'application/pdf' }), null);
  assert.equal(attachmentPreviewHint({ filename: 'archive.zip', content_type: 'application/zip' }), null);
  assert.equal(attachmentPreviewHint({ filename: 'unknown.bin', content_type: 'application/octet-stream' }), null);
});

test('attachment safety cues are truthful and require confirmation for active files', () => {
  const executable = attachmentSafetyNotice({ filename: 'invoice.js', content_type: 'text/javascript' });
  assert.equal(executable.label, 'Potentially unsafe file');
  assert.equal(executable.requiresConfirmation, true);

  const disguisedHtml = attachmentSafetyNotice({ filename: 'invoice.txt', content_type: 'text/html' });
  assert.equal(disguisedHtml.label, 'Potentially unsafe file');
  assert.equal(disguisedHtml.requiresConfirmation, true);

  const archive = attachmentSafetyNotice({ filename: 'documents.zip', content_type: 'application/zip' });
  assert.equal(archive.label, 'Compressed archive');
  assert.equal(archive.requiresConfirmation, true);

  const mismatch = attachmentSafetyNotice({ filename: 'photo.png', content_type: 'application/pdf' });
  assert.equal(mismatch.label, 'File type mismatch');
  assert.equal(mismatch.requiresConfirmation, true);

  const unknown = attachmentSafetyNotice({ filename: 'payload.bin', content_type: 'application/octet-stream' });
  assert.equal(unknown.label, 'Preview unavailable');
  assert.equal(unknown.requiresConfirmation, false);
  assert.equal(attachmentSafetyNotice({ filename: 'notes.txt', content_type: 'text/plain' }), null);
});

test('attachment type labels use stable human descriptions', () => {
  assert.equal(attachmentTypeLabel({ filename: 'report.pdf', content_type: 'application/pdf' }), 'PDF document');
  assert.equal(attachmentTypeLabel({ filename: 'photo.webp', content_type: 'image/webp' }), 'Image');
  assert.equal(attachmentTypeLabel({ filename: 'bundle.7z', content_type: '' }), 'Compressed archive');
  assert.equal(attachmentTypeLabel({ filename: 'model.xyz', content_type: '' }), 'XYZ file');
});

test('verified image previews own and release one object URL', async () => {
  const calls = [];
  const blob = new Blob(['generated image bytes'], { type: 'image/png' });
  const urlObject = {
    createObjectURL: value => {
      assert.equal(value, blob);
      calls.push('create');
      return 'blob:generated-preview';
    },
    revokeObjectURL: value => calls.push(['revoke', value]),
  };
  const preview = await materializeAttachmentPreview({
    blob,
    kind: 'image',
    contentType: 'image/png',
    truncated: false,
  }, { urlObject });

  assert.equal(preview.objectUrl, 'blob:generated-preview');
  releaseAttachmentPreview(preview, { urlObject });
  assert.deepEqual(calls, ['create', ['revoke', 'blob:generated-preview']]);
});

test('verified text previews decode without creating an object URL', async () => {
  const blob = new Blob(['<script>generated inert text</script>'], { type: 'text/plain' });
  const preview = await materializeAttachmentPreview({
    blob,
    kind: 'text',
    contentType: 'text/plain; charset=utf-8',
    truncated: true,
  }, {
    urlObject: { createObjectURL: () => assert.fail('text must not create an object URL') },
  });

  assert.equal(preview.kind, 'text');
  assert.equal(preview.text, '<script>generated inert text</script>');
  assert.equal(preview.truncated, true);
  assert.equal(preview.objectUrl, null);
});

test('accepted PDFs defer untrusted rendering to the browser viewer without a blob URL', async () => {
  const blob = new Blob(['%PDF-1.7\n%%EOF'], { type: 'application/pdf' });
  const preview = await materializeAttachmentPreview({
    blob,
    kind: 'pdf',
    contentType: 'application/pdf',
  }, {
    urlObject: { createObjectURL: () => assert.fail('PDFs must not create an app-origin blob URL') },
  });

  assert.equal(preview.kind, 'pdf');
  assert.equal(preview.objectUrl, null);
  assert.equal(preview.blob, blob);
});

test('missing, mismatched, empty, and oversized preview responses fail closed', async () => {
  const textBlob = new Blob(['generated'], { type: 'text/plain' });
  await assert.rejects(
    materializeAttachmentPreview({ blob: textBlob, kind: 'image', contentType: 'text/plain' }),
    error => error.status === 415,
  );
  await assert.rejects(
    materializeAttachmentPreview(
      { blob: textBlob, kind: 'text', contentType: 'text/plain' },
      { expectedKind: 'image' },
    ),
    error => error.status === 415,
  );
  await assert.rejects(
    materializeAttachmentPreview({ blob: new Blob([], { type: 'text/plain' }), kind: 'text', contentType: 'text/plain' }),
    error => error.status === 413,
  );
  await assert.rejects(
    materializeAttachmentPreview({
      blob: new Blob(['x'.repeat(1024 * 1024 + 1)], { type: 'text/plain' }),
      kind: 'text',
      contentType: 'text/plain',
    }),
    error => error.status === 413,
  );
});

test('preview requests stay current only for the same email, attachment, and generation', () => {
  const request = {
    requestedEmailId: 313,
    requestedAttachmentId: 8411,
    requestedGeneration: 7,
    currentEmailId: 313,
    currentAttachmentId: 8411,
    currentGeneration: 7,
  };
  assert.equal(isCurrentAttachmentPreviewRequest(request), true);
  assert.equal(isCurrentAttachmentPreviewRequest({ ...request, currentEmailId: 314 }), false);
  assert.equal(isCurrentAttachmentPreviewRequest({ ...request, currentAttachmentId: 8412 }), false);
  assert.equal(isCurrentAttachmentPreviewRequest({ ...request, currentGeneration: 8 }), false);
});
