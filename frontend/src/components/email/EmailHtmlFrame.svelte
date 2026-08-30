<script>
  import { onMount, untrack } from 'svelte';
  import { theme } from '../../lib/theme.js';
  import { sanitizeEmailHtml } from '../../lib/sanitize.js';
  import { emailContentSecurityPolicy } from '../../lib/remoteContent.js';
  import Icon from '../common/Icon.svelte';

  let {
    html = '',
    contentKey = '',
    title = 'Email content',
    padding = '0',
    minHeight = '100px',
  } = $props();

  let iframeEl = $state(null);
  let remoteContentApproval = $state(null);
  let announcement = $state('');
  let previousContentKey = $state('');
  let previousHtml = $state('');
  let hasObservedContent = $state(false);
  let systemPrefersDark = $state(false);
  let allowRemoteContent = $derived(
    remoteContentApproval?.contentKey === contentKey
      && remoteContentApproval?.html === html,
  );
  let prepared = $derived(sanitizeEmailHtml(html, { allowRemoteContent }));
  let effectiveDark = $derived(
    $theme === 'system' ? systemPrefersDark : $theme === 'dark',
  );

  onMount(() => {
    const systemScheme = window.matchMedia('(prefers-color-scheme: dark)');
    const updateSystemScheme = () => { systemPrefersDark = systemScheme.matches; };
    updateSystemScheme();
    systemScheme.addEventListener('change', updateSystemScheme);
    return () => systemScheme.removeEventListener('change', updateSystemScheme);
  });

  $effect(() => {
    const nextContentKey = contentKey;
    const nextHtml = html;
    if (hasObservedContent && (nextContentKey !== previousContentKey || nextHtml !== previousHtml)) {
      remoteContentApproval = null;
      announcement = '';
    }
    previousContentKey = nextContentKey;
    previousHtml = nextHtml;
    hasObservedContent = true;
  });

  function applyThemeToDocument(doc, isDark) {
    doc.documentElement.style.colorScheme = isDark ? 'dark' : 'light';
    doc.documentElement.style.setProperty('--email-text', isDark ? '#e4e4e7' : '#1a1a1a');
    doc.documentElement.style.setProperty('--email-bg', isDark ? '#18181b' : '#ffffff');
    doc.documentElement.style.setProperty('--email-link', isDark ? '#f59e0b' : '#b45309');
    doc.documentElement.style.setProperty('--email-quote', isDark ? '#3f3f46' : '#d4d4d8');
    doc.documentElement.style.setProperty('--email-placeholder-bg', isDark ? '#27272a' : '#f4f4f5');
    doc.documentElement.style.setProperty('--email-placeholder-border', isDark ? '#52525b' : '#d4d4d8');
    doc.documentElement.style.setProperty('--email-placeholder-text', isDark ? '#a1a1aa' : '#52525b');
  }

  $effect(() => {
    if (!iframeEl || !html) return;

    const documentHtml = prepared.html;
    const csp = emailContentSecurityPolicy(allowRemoteContent);
    const doc = iframeEl.contentDocument;
    if (!doc) return;

    doc.open();
    doc.write(`<!DOCTYPE html><html><head>
      <meta http-equiv="Content-Security-Policy" content="${csp}">
      <meta name="referrer" content="no-referrer">
      <meta http-equiv="x-dns-prefetch-control" content="off">
      <style>
        :root {
          color-scheme: light;
          --email-text: #1a1a1a; --email-bg: #ffffff;
          --email-link: #b45309; --email-quote: #d4d4d8;
          --email-placeholder-bg: #f4f4f5;
          --email-placeholder-border: #d4d4d8;
          --email-placeholder-text: #52525b;
        }
        body {
          margin: 0; padding: ${padding};
          font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
          font-size: 14px; line-height: 1.6;
          color: var(--email-text);
          background: var(--email-bg);
          overflow-wrap: anywhere;
          word-break: break-word;
        }
        img, video { max-width: 100%; height: auto; }
        ${allowRemoteContent ? '' : 'video, audio { display: none; }'}
        a { color: var(--email-link); }
        blockquote {
          border-left: 3px solid var(--email-quote);
          padding-left: 12px; margin-left: 0; opacity: 0.8;
        }
        .remote-image-placeholder {
          display: inline-flex; align-items: center; min-height: 32px;
          max-width: 100%; box-sizing: border-box; padding: 5px 8px;
          border: 1px dashed var(--email-placeholder-border); border-radius: 6px;
          background: var(--email-placeholder-bg); color: var(--email-placeholder-text);
          font-size: 12px; line-height: 1.35;
        }
        table { max-width: 100%; }
        pre { overflow-x: auto; }
      </style>
    </head><body>${documentHtml}</body></html>`);
    doc.close();
    applyThemeToDocument(doc, untrack(() => effectiveDark));

    let resizeObserver;
    const timers = [];
    const resize = () => {
      if (!iframeEl || !doc.body) return;
      iframeEl.style.height = `${Math.max(doc.body.scrollHeight, Number.parseInt(minHeight, 10) || 0)}px`;
    };
    const scheduleResize = delay => timers.push(window.setTimeout(resize, delay));

    doc.querySelectorAll('img, video, audio, link').forEach(resource => {
      resource.addEventListener('load', resize, { once: true });
      resource.addEventListener('error', resize, { once: true });
    });
    const handleLinkClick = event => {
      const anchor = event.target?.closest?.('a[href], area[href]');
      if (!anchor) return;
      event.preventDefault();
      try {
        const target = new URL(anchor.getAttribute('href'), window.location.href);
        if (!['http:', 'https:', 'mailto:', 'tel:'].includes(target.protocol)) return;
        const opened = window.open(target.href, '_blank', 'noopener,noreferrer');
        if (opened) opened.opener = null;
      } catch {
        // Malformed sender links stay inert.
      }
    };
    doc.addEventListener('click', handleLinkClick);
    if (typeof ResizeObserver !== 'undefined' && doc.body) {
      resizeObserver = new ResizeObserver(resize);
      resizeObserver.observe(doc.body);
    }
    scheduleResize(0);
    scheduleResize(50);
    scheduleResize(300);
    scheduleResize(1000);

    return () => {
      resizeObserver?.disconnect();
      doc.removeEventListener('click', handleLinkClick);
      timers.forEach(timer => window.clearTimeout(timer));
    };
  });

  $effect(() => {
    const isDark = effectiveDark;
    const doc = iframeEl?.contentDocument;
    if (doc?.documentElement) applyThemeToDocument(doc, isDark);
  });

  function loadRemoteContentOnce() {
    remoteContentApproval = { contentKey, html };
    announcement = 'Direct loading enabled for this message only.';
  }

  function blockRemoteContentAgain() {
    remoteContentApproval = null;
    announcement = 'Remote content is hidden again. Requests already made cannot be undone.';
  }
</script>

{#if prepared.remoteResourceCount > 0}
  <section
    class="mb-3 flex flex-col gap-3 rounded-xl border px-3 py-3 sm:flex-row sm:items-center sm:justify-between"
    style={allowRemoteContent
      ? 'border-color: var(--border-color); background: var(--bg-tertiary); color: var(--text-secondary)'
      : 'border-color: var(--status-warning-border); background: var(--status-warning-bg); color: var(--status-warning-text)'}
    aria-label="Email privacy notice"
  >
    <div class="flex min-w-0 items-start gap-2.5">
      <span class="mt-0.5 shrink-0" aria-hidden="true"><Icon name="shield" size={17} /></span>
      <div class="min-w-0">
        <div class="text-sm font-semibold">
          {allowRemoteContent
            ? 'Direct loading enabled'
            : prepared.directLoadableResourceCount > 0
              ? 'Remote content blocked'
              : 'External content removed'}
        </div>
        <p class="mt-0.5 text-xs leading-relaxed">
          {#if allowRemoteContent}
            Sender-hosted images and media are allowed for this message only. Image hosts may learn your IP address, device details, and approximate view time. External styles stay blocked.
          {:else if prepared.directLoadableResourceCount > 0}
            This message can load sender-hosted images or media. Loading directly may reveal your IP address, device details, and approximate view time.
          {:else}
            External styles and tracking resources were removed for your privacy.
          {/if}
        </p>
      </div>
    </div>
    {#if prepared.directLoadableResourceCount > 0}
      <button
        type="button"
        class="inline-flex min-h-11 shrink-0 items-center justify-center rounded-lg border px-3 text-sm font-semibold transition-fast focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        style="border-color: var(--status-warning-border); background: var(--bg-primary); color: var(--text-primary)"
        aria-label={allowRemoteContent
          ? 'Hide remote content for this message'
          : 'Load remote content directly for this message once'}
        onclick={allowRemoteContent ? blockRemoteContentAgain : loadRemoteContentOnce}
      >
        {allowRemoteContent ? 'Hide remote content' : 'Load directly once'}
      </button>
    {/if}
  </section>
{/if}

{#if announcement}
  <span class="sr-only" role="status" aria-live="polite" aria-atomic="true">{announcement}</span>
{/if}

{#key allowRemoteContent}
  <iframe
    bind:this={iframeEl}
    {title}
    sandbox="allow-same-origin"
    referrerpolicy="no-referrer"
    class="w-full border-0"
    style:min-height={minHeight}
  ></iframe>
{/key}
