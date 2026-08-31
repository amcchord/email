# Inline Snippet Expansion Release — 2026-08-31

## Outcome

Personal Snippets now work at typing speed. In Compose, reader reply, and Flow,
typing a safe `;shortcut` opens an accessible suggestion menu beside the live
editing position. Arrow keys move through results; Enter, Tab, or an explicit
pointer choice replaces only the literal trigger. Escape closes the menu and
keeps the typed text.

Exact application/runtime commit:
`e7292f0ee9eb5ba469a898faa63f7f8fbab000dc`.

This release is frontend-only. It adds no endpoint, schema revision, provider
scope, dependency, background job, AI path, terminal path, or production data.

## User Experience

- One menu and keyboard contract serve rich Compose, rich Flow replies, and
  plain reader replies.
- Activation is intentionally conservative: block start or whitespace followed
  by a semicolon and the existing ASCII shortcut grammar. It does not activate
  inside a word, link, inline code, code block, active selection, or IME
  composition.
- Results are ranked from the current user's bounded Personal Snippets list and
  load fresh for every activation. Loading, empty, and error states are visible
  and never modify the draft.
- Rich content is sanitized immediately before one Tiptap replacement
  transaction. Reader replies use the stored plain fallback in one native text
  transaction. Both paths provide one-step Undo.
- The menu is a non-modal ARIA listbox with active-descendant state, 44-pixel
  choices, desktop caret anchoring, above/below flipping, and narrow viewport
  clamping.
- The existing `Cmd/Ctrl+;` picker remains available everywhere. If a fallback
  editor cannot provide an undoable transaction, inline expansion stays off in
  that compatibility path instead of silently weakening Undo.

## Integrity And Session Boundaries

- A result is never allowed to mutate the range captured before its asynchronous
  request. Selection re-reads the current editor, trigger token, offsets, and
  authenticated session first.
- Each activation clears prior results. Request generations and session guards
  reject a delayed User A list after User B takes over the document.
- Modifier chords are contained while the menu is open, so `Cmd/Ctrl+Enter` and
  `Cmd/Ctrl+Shift+Enter` cannot become Send or Send & Archive.
- Snippet selection materializes a snapshot. Later edit or deletion of the
  template cannot rewrite a saved draft.
- The generated provider fixture uses only `.example.test`, records content-free
  counters, and makes no external network call.

## Changed Files

- `frontend/src/components/email/InlineSnippetMenu.svelte` — shared accessible
  menu, fresh loading, session/generation rejection, keyboard ownership, and
  viewport placement.
- `frontend/src/lib/inlineSnippetExpansion.js` — pure trigger, replacement, and
  clamping contract; focused tests live beside it.
- `frontend/src/components/email/RichEditor.svelte` — current-block trigger
  discovery, hard-break awareness, exact revalidation, and one rich transaction.
- `frontend/src/components/email/DeferredRichEditor.svelte` — shared menu owner,
  lazy-rich bridge, and undo-safe compatibility policy.
- `frontend/src/components/email/EmailView.svelte` — plain reader trigger,
  containment, exact replacement, and one durable update.
- `frontend/src/pages/Compose.svelte`, `frontend/src/pages/Flow.svelte`, and
  `frontend/src/components/email/SnippetPicker.svelte` — surface enablement and
  discovery copy.
- `scripts/qa/generated_provider_draft_server.mjs` and its self-test — one-shot
  held snippet response and stale-session audit evidence.

No backend router, service, model, worker, Alembic revision, Gmail/calendar
integration, AI file, terminal file, package manifest, or production
configuration changed.

## Review And Verification

Iteration used affected focused tests only. After code freeze:

- Independent P0/P1 review found no P0. It found two P1 issues: hard breaks were
  treated like atomic content, and compatibility fallbacks could mutate outside
  the Undo stack. The implementation now maps only rich hard breaks to newline
  and disables inline expansion where an undoable compatibility transaction is
  unavailable. Focused regression checks passed.
- Independent user testing found no remaining P0/P1 issue.
- Generated desktop browser acceptance passed rich and plain insertion, arrow/
  Enter behavior, Escape preservation, modifier containment, hostile HTML
  sanitization, rich and plain one-step Undo, and expanded-draft reopen.
- Generated 390×844 acceptance showed a clamped, readable menu without covering
  reply controls.
- The held-session scenario recorded exactly two snippet-list requests, one held
  User A response, one stale release after User B took over, and one safe User B
  result. It recorded zero sends, provider sends, unexpected mutations, and
  external calls.
- Browser console contained only Vite debug connection messages and no warning
  or error.
- Single consolidated `make check`: 734 backend passed, 66 expected skips; all
  470 frontend tests passed; production build transformed 601 modules.

## Deployment And Postflight

GitHub `main` and the feature branch received the exact reviewed runtime commit.
Production fast-forwarded from Recipient Autocomplete closeout `07e9ef6` to
`e7292f0`, ran the locked frontend install, and built the same 601 modules.

No service restart, database backup, migration, Caddy reload, provider request,
real email action, real calendar action, or terminal action occurred. Postflight
proved:

- production Git exact and clean at the runtime commit;
- all seven checked services active and public health `ok`;
- mailapp PID 2139380, activation time 03:44:51 UTC, and `NRestarts=0` unchanged;
- no warning-or-higher application/worker logs after deployment;
- Alembic still exactly `d7e8f9a0b1c2 (head)`.

## Rollback

If a release-blocking frontend issue appears, revert the runtime commit through
Git, fast-forward production to that reviewed revert, and rebuild the frontend.
No database or provider rollback is required. The explicit snippet picker and
stored Personal Snippets remain the functional fallback.
