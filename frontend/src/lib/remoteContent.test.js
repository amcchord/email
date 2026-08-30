import test from 'node:test';
import assert from 'node:assert/strict';

import {
  attributeMayLoadRemoteContent,
  cssMayLoadRemoteContent,
  emailContentSecurityPolicy,
  isSafeEmbeddedResourceUrl,
  remoteAttributeCanLoadDirectly,
} from './remoteContent.js';

test('embedded resource URLs never require sender-controlled network access', () => {
  for (const value of [
    'data:image/png;base64,AAAA',
    'cid:generated-logo@example.test',
    'about:blank',
  ]) {
    assert.equal(isSafeEmbeddedResourceUrl(value), true, value);
  }

  for (const value of [
    '',
    'https://tracker.example.test/open.gif',
    '//tracker.example.test/open.gif',
    '/api/generated-resource',
    'generated-relative.png',
    'blob:https://mail.example.test/generated',
    'data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=',
    '#generated-symbol',
  ]) {
    assert.equal(isSafeEmbeddedResourceUrl(value), false, value);
  }
});

test('direct loading is limited to visible image and media resources', () => {
  const applicationOrigin = 'https://mail.example.test';
  for (const [tag, attribute, value] of [
    ['img', 'src', 'https://images.example.test/a.png'],
    ['source', 'srcset', 'https://images.example.test/a.webp 1x, //images.example.test/b.webp 2x'],
    ['video', 'poster', '//media.example.test/poster.png'],
    ['audio', 'src', 'https://media.example.test/a.mp3'],
    ['track', 'src', 'https://media.example.test/a.vtt'],
    ['image', 'xlink:href', 'https://images.example.test/a.svg'],
    ['table', 'background', '//images.example.test/bg.png'],
  ]) {
    assert.equal(
      remoteAttributeCanLoadDirectly(tag, attribute, value, applicationOrigin),
      true,
      `${tag}[${attribute}]`,
    );
  }

  for (const [tag, attribute, value] of [
    ['link', 'href', 'https://styles.example.test/a.css'],
    ['a', 'ping', 'https://tracking.example.test/click'],
    ['div', 'style', 'background:url(https://images.example.test/a.png)'],
    ['feimage', 'href', 'https://images.example.test/a.svg'],
    ['use', 'href', 'https://images.example.test/a.svg'],
    ['mglyph', 'src', 'https://images.example.test/a.png'],
    ['pattern', 'href', 'https://images.example.test/a.svg'],
    ['linearGradient', 'xlink:href', 'https://images.example.test/a.svg'],
    ['mpath', 'href', 'https://images.example.test/a.svg'],
    ['textPath', 'href', 'https://images.example.test/a.svg'],
    ['img', 'src', '/api/generated-resource'],
    ['img', 'src', 'https://mail.example.test/api/generated-resource'],
    ['img', 'src', '//mail.example.test/api/generated-resource'],
    ['img', 'src', 'http://mail.example.test:8000/api/generated-resource'],
    ['video', 'poster', 'generated-poster.png'],
    ['source', 'srcset', 'https://images.example.test/a.webp 1x, /api/image 2x'],
    ['img', 'srcset', 'data:image/png;base64,AAAA 1x, https://images.example.test/a.png 2x'],
  ]) {
    assert.equal(
      remoteAttributeCanLoadDirectly(tag, attribute, value, applicationOrigin),
      false,
      `${tag}[${attribute}]`,
    );
  }
});

test('resource-bearing HTML attributes distinguish embedded and remote values', () => {
  assert.equal(attributeMayLoadRemoteContent('img', 'src', 'https://tracker.example.test/pixel'), true);
  assert.equal(attributeMayLoadRemoteContent('source', 'srcset', 'https://tracker.example.test/a 1x'), true);
  assert.equal(attributeMayLoadRemoteContent('img', 'srcset', 'data:image/png;base64,AAAA 1x, /track.png 2x'), true);
  assert.equal(attributeMayLoadRemoteContent('video', 'poster', '/generated-poster.png'), true);
  assert.equal(attributeMayLoadRemoteContent('svg', 'background', '//tracker.example.test/bg'), true);
  assert.equal(attributeMayLoadRemoteContent('a', 'ping', 'https://tracker.example.test/click'), true);
  assert.equal(attributeMayLoadRemoteContent('a', 'attributionsrc', 'https://tracker.example.test/attribute'), true);
  assert.equal(attributeMayLoadRemoteContent('a', 'href', 'https://example.test/read'), false);
  assert.equal(attributeMayLoadRemoteContent('path', 'filter', 'url(https://tracker.example.test/filter.svg#x)'), true);
  assert.equal(attributeMayLoadRemoteContent('mglyph', 'src', '/generated-glyph.png'), true);
  assert.equal(attributeMayLoadRemoteContent('pattern', 'href', 'https://tracker.example.test/pattern.svg'), true);
  assert.equal(attributeMayLoadRemoteContent('linearGradient', 'xlink:href', '/generated-gradient.svg'), true);
  assert.equal(attributeMayLoadRemoteContent('mpath', 'href', '//tracker.example.test/motion.svg'), true);
  assert.equal(attributeMayLoadRemoteContent('textPath', 'href', 'generated-path.svg'), true);
  assert.equal(attributeMayLoadRemoteContent('img', 'src', 'data:image/png;base64,AAAA'), false);
  assert.equal(attributeMayLoadRemoteContent('use', 'href', '#generated-symbol'), false);
  assert.equal(attributeMayLoadRemoteContent('pattern', 'href', '#generated-pattern'), false);
  assert.equal(attributeMayLoadRemoteContent('img', 'src', '#generated-symbol'), true);
  assert.equal(attributeMayLoadRemoteContent('a', 'xlink:href', 'https://example.test/read'), true);
});

test('CSS network references include imports, URLs, image sets, and escaped url tokens', () => {
  assert.equal(cssMayLoadRemoteContent('background: url(https://tracker.example.test/open)'), true);
  assert.equal(cssMayLoadRemoteContent('@import "//tracker.example.test/mail.css";'), true);
  assert.equal(cssMayLoadRemoteContent('background-image: image-set("/one.png" 1x, "/two.png" 2x)'), true);
  assert.equal(cssMayLoadRemoteContent('background: \\75rl(https://tracker.example.test/escaped)'), true);
  assert.doesNotThrow(() => cssMayLoadRemoteContent('content: "\\ffffff"'));
  assert.equal(cssMayLoadRemoteContent('background: url(data:image/png;base64,AAAA)'), false);
  assert.equal(cssMayLoadRemoteContent('filter: url(#generated-filter)'), false);
  assert.equal(cssMayLoadRemoteContent('color: #334155; padding: 12px'), false);
});

test('blocked CSP has no network source while one-message opt-in remains scriptless', () => {
  const blocked = emailContentSecurityPolicy(false);
  assert.doesNotMatch(blocked, /https:|http:/);
  assert.match(blocked, /img-src data: cid: blob:/);
  assert.match(blocked, /connect-src 'none'/);
  assert.match(blocked, /worker-src 'none'/);
  assert.match(blocked, /script-src 'none'/);

  const loaded = emailContentSecurityPolicy(true);
  assert.match(loaded, /img-src data: cid: blob: https: http:/);
  assert.doesNotMatch(loaded, /style-src[^;]*https:/);
  assert.doesNotMatch(loaded, /font-src[^;]*https:/);
  assert.match(loaded, /script-src 'none'/);
  assert.match(loaded, /object-src 'none'/);
});
