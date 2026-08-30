# Frontend Security Refresh — 2026-08-30

Status: verified release candidate; production deployment pending.

## Purpose

Clear the 11 compatible npm production advisories left after the consolidated
product-polish release, prove the updated rendering stack against generated
hostile content, and improve the adjacent Chat mobile and PDF-export UX. This
cycle is isolated from the concurrent AI-provider work and does not inspect or
mutate real mail.

## Dependency Changes

The lockfile-only compatible refresh takes the production audit from 11
findings (4 moderate, 6 high, 1 critical) to zero. Key resolved versions:

| Package | Before | After |
| --- | ---: | ---: |
| DOMPurify | 3.3.1 | 3.4.14 |
| jsPDF | 4.1.0 | 4.2.1 |
| Svelte | 5.50.1 | 5.57.0 |
| Vite | 6.4.1 | 6.4.3 |
| Rollup | 4.57.1 | 4.63.1 |
| acorn | 8.15.0 | 8.18.0 |
| devalue | 5.6.2 | 5.9.2 |
| markdown-it | 14.1.0 | 14.3.1 |
| linkify-it | 5.0.0 | 5.0.2 |
| nanoid | 3.3.11 | 3.3.18 |
| picomatch | 4.0.3 | 4.0.7 |
| postcss | 8.5.6 | 8.5.26 |

The refresh uses `npm audit fix --package-lock-only` without `--force`; the
declared dependency ranges and application API contracts remain unchanged.

## Product and Security Changes

- Treat rendered email and AI content as display-only. Both sanitizer policies
  explicitly reject scripts, frames, embeds, objects, forms, form controls,
  templates, base/meta elements, and `srcdoc`, in addition to DOMPurify's URL
  and event-attribute protections. Safe email tables, inline styles, Unicode,
  and ordinary HTTPS links remain intact.
- Keep one configured Tiptap Link and Underline extension by disabling the
  copies now included in StarterKit. This removes the updated editor's duplicate
  extension warning without losing the app's link styling or behavior.
- Make Chat usable at narrow widths: the conversation list starts closed on
  mobile, opens as a dismissible overlay, closes after conversation selection,
  and no longer consumes most of a 375 px screen. The menu and both download
  controls now meet the 44 px touch-target floor and the download row wraps.
- Make PDF export exception-safe by removing its offscreen rendering container
  and resetting progress state in `finally`.
- Replace fixed raster page slicing with section-aware pagination. Heading gaps
  are preferred, top-level block boundaries are the next fallback, and a
  whitespace scan is used when structure is unavailable. Cross-origin-tainted
  canvases retain the legacy fixed-height fallback rather than failing export.
- Extend the localhost-only, mutation-rejecting browser harness with generated
  hostile email HTML, hostile Chat Markdown, a long multi-page/non-ASCII Chat
  answer, exact-width mobile wrappers, Chat read auditing, and a dedicated
  content-security audit. Every address remains under `.example.test`.

## Multi-Agent Review

- Dependency implementation updated only the lockfile and proved the initial
  zero-audit build.
- Dependency reachability review identified DOMPurify, Svelte, jsPDF, and the
  Linux Node floor as the release-critical surfaces; advisory-only APIs not
  used by the app were recorded but not treated as sufficient evidence.
- Generated user testing found the Tiptap duplicate-extension warning and the
  missing hostile-render/PDF fixtures. Attachment, slow-route, failed-route,
  slow-editor, and failed-editor desktop/mobile regressions otherwise passed
  with empty mutation and unknown-route audits.

## Verification Evidence

- `make check`: 303 backend tests passed; four opt-in PostgreSQL integration
  tests skipped as expected; 108 frontend tests passed; the 500-module
  production build completed.
- Clean Linux x86_64 Node `v20.20.2`: locked install passed, production audit
  reported zero vulnerabilities, all 108 frontend tests passed, and
  `vite build --manifest` completed. This specifically proves the documented
  Node 20 floor despite Rollup's newer optional packages.
- Generated in-app browser, desktop and exact 375x812:
  - email and Chat kept safe links, table/layout content, inline styles,
    headings, lists, blockquotes, code, and Unicode;
  - forbidden active elements, event attributes, and `javascript:` URLs were
    absent; no probe executed;
  - both exact-width pages had `scrollWidth === clientWidth === 375`;
  - Chat content was 337 px wide, its sidebar closed after selection, and its
    download controls were 44 px high;
  - the enhanced editor mounted once as one contenteditable ProseMirror
    surface; and
  - final security audits contained zero mutation attempts and zero unknown
    routes.
- Generated Chat PDF: sanitized filename, `%PDF-` signature, 1,041,576 bytes,
  PDF 1.3, four US-letter pages. All pages were rendered with Poppler and
  visually inspected; headings, tables, Unicode, lists, blockquotes, footer,
  margins, and page transitions were legible with no clipped or split text.
- `node --check scripts/qa/generated_search_server.mjs`,
  `npm audit --omit=dev`, and `git diff --check` passed.

## Production Plan and Rollback

This is a frontend-only release: no Python dependency, API, schema, migration,
worker, Caddy, systemd, or production data change is required. After an exact
Git fast-forward, production needs only `npm ci` and `npm run build`; no service
restart is planned because Caddy serves the static build directly.

Rollback is a Git fast-forward/revert to the prior production baseline
`413d763`, followed by the same locked frontend install/build. No database
rollback is involved.

## Known Follow-ups

- Email HTML still deliberately permits images, inline style, and stylesheet
  links for compatibility. Preventing remote image/CSS tracking requires a
  separate product policy with visible remote-content controls; the sanitizer
  refresh is not presented as that policy.
- Chat PDF remains a raster export rather than selectable/accessible document
  text. Pagination and visual quality are now reliable, but a future semantic
  PDF generator could improve accessibility and file size.
- Browser QA continues to use generated fixtures only. Production message
  rendering is not opened because opening unread real mail can mark it read.
