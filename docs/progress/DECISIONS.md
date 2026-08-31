# Decisions

Durable decisions are numbered and never silently removed. If a choice changes,
add a new entry that explicitly supersedes the old one.

## D-001 — Git-first staging workflow

- Date: 2026-08-26
- Status: accepted
- Decision: Use this local checkout for development and `origin/main` as the
  code source of truth. Use `/opt/mail` only as the production deployment
  target.
- Reason: Keeps review, testing, history, and recovery available while avoiding
  configuration drift from direct server edits.
- Consequence: Emergency live changes must be reconciled back into Git
  immediately.

## D-002 — Production mutations require explicit scope

- Date: 2026-08-26
- Status: accepted
- Decision: Read-only production inspection may support normal work. Deploys,
  restarts, migrations, configuration edits, and data changes require an
  explicit request in the current task.
- Reason: The host is actively processing private mail and root SSH access has a
  large blast radius.
- Consequence: Completing a local change does not imply deploying it.

## D-003 — Progress lives beside the code

- Date: 2026-08-26
- Status: accepted
- Decision: Keep current state, session evidence, durable decisions, and the
  operations runbook in version-controlled Markdown.
- Reason: Future work should resume from repository state rather than private
  chat history.
- Consequence: Material sessions update `CURRENT.md` and `JOURNAL.md`; durable
  choices update this file.

## D-004 — Never mirror production secrets into staging

- Date: 2026-08-26
- Status: accepted
- Decision: Do not copy `/opt/mail/.env`, databases, mailbox content,
  attachments, OAuth tokens, or private logs into the staging checkout.
- Reason: The local workspace is a code and documentation home base, not a
  production data replica.
- Consequence: Local integration work uses fakes or separately provisioned
  non-production credentials.

## D-005 — Treat known working relationships as routing data

- Date: 2026-08-29
- Status: accepted
- Decision: Encode Andrea Durbin as Austin's default scheduling owner and Angie
  Mecham as a trusted close colleague in a single workflow-context module used
  by prompts, presentation, and mail queues.
- Reason: Free-form LLM inference is not reliable enough for stable delegation
  and trusted-sender behavior, especially when Andrea is included on Cc.
- Consequence: Routine low/normal-priority scheduling already routed to Andrea
  does not become Austin's action item or follow-up; high/urgent messages still
  surface, direct questions from Andrea remain Austin's responsibility, and
  future relationship changes should be made in the centralized workflow
  context rather than scattered prompt text.

## D-006 — Synchronization checkpoints represent complete work

- Date: 2026-08-30
- Status: accepted
- Decision: Serialize Gmail sync per account and advance a history or page
  checkpoint only after every item in its unit is resolved. Full sync owns a
  versioned baseline through scan and history replay; incremental and full
  completion use compare-and-swap as the final ownership guard.
- Reason: Partial batch results, swallowed message failures, or overlapping
  workers can otherwise move a checkpoint beyond mail that was never stored.
- Consequence: Missing batch results and poison messages fail the unit and pin
  its checkpoint for retry. Full sync refreshes existing messages and replays
  changes since its captured baseline before publishing completion. Future
  sync changes must preserve these invariants and add real-database
  interleaving coverage when they alter ownership or transaction boundaries.

## D-007 — Accepted mail actions are durable, ordered work

- Date: 2026-08-30
- Status: accepted
- Decision: Record one ordered outbox item per target email in the same
  transaction as its optimistic local projection. Gmail execution and sync use
  one shared account advisory lock; Redis may accelerate work but PostgreSQL is
  the recovery source of truth.
- Reason: Inline best-effort Gmail calls can partially succeed, be lost after a
  process failure, execute opposite actions out of order, and let sync erase
  user intent while still reporting success.
- Consequence: API acceptance is distinct from Gmail confirmation. Clients use
  request status for partial results, exact staged Undo is permitted only
  before execution, retries preserve per-email order, expired leases are
  reclaimable, and sync must overlay the newest active action state. Redis
  publication is bounded best effort, lost create responses are reconciled by
  owned idempotency-key lookup, and one-attempt Gmail mutations use a finite
  transport deadline before durable retry policy takes over.

## D-008 — Command discovery reflects executable state

- Date: 2026-08-30
- Status: accepted
- Decision: Build command discovery from the active shortcut catalog plus the
  currently registered page/component handlers. Surface live unavailable
  reasons, make command/help dialogs own focus and keyboard input, and exclude
  irreversible Send from the palette until send has a durable client-keyed
  idempotency contract.
- Reason: A palette that advertises no-op, stale, unavailable, or ambiguous
  irreversible actions is less trustworthy than direct shortcuts and can
  duplicate real-world side effects after lost responses.
- Consequence: Page handlers register synchronously with owned cleanup and may
  provide `isEnabled` and `disabledReason`; disabled commands remain
  discoverable but Enter-inert; async completion is scoped to its originating
  palette session and captured entity; and new irreversible palette commands
  require deterministic lost-response coverage before exposure.

## D-009 — Email search is composable inside an immutable ownership boundary

- Date: 2026-08-30
- Status: accepted
- Decision: Parse structured search into AND clauses and OR groups, compile all
  user values as bound parameters, and apply the resulting predicate only
  inside a separately enforced set of accounts owned by the current user.
  Browser search covers regular mail by default, preserves explicit account
  scope, suspends Focused/smart filters, and lets a positive `in:` clause own
  mailbox scope without broadening other OR branches into Spam or Trash.
- Reason: Modern-client search needs quotes, exclusions, fields, dates, and
  mailbox composition, but malformed syntax, foreign account IDs, interpolated
  JSONB values, or ambiguous filter inheritance must never broaden private-mail
  access or misrepresent result scope.
- Consequence: Unknown/foreign outer accounts fail closed; `account:` and
  `label:` only narrow owned mail; date boundaries use an explicit IANA zone;
  parser errors return stable 422 details; plain search retains complete
  literal fallbacks when full-text vectors are stale; and clearing browser
  search restores the unchanged mailbox and filter stores.

## D-010 — Canonical attachment caching is bounded and ID-derived

- Date: 2026-08-30
- Status: accepted
- Decision: Cache browser-downloaded received attachments only at canonical
  positive-ID-derived paths under a per-user namespace. Enforce a 512 MiB hard
  limit with a 384 MiB low-water target, 30-day idle retention, 24-hour orphan
  grace, and one-hour temporary-file grace using fixed sharded file locks,
  no-follow directory-descriptor operations, and duplicate-safe daily
  maintenance.
- Reason: Persisted `storage_path` values, unbounded filenames, path-based
  cleanup, and process-local coordination cannot prove cross-user isolation,
  quota compliance, or in-flight safety under concurrent workers and
  cancellation.
- Consequence: The browser download handler derives identity from owned
  database IDs, never trusts or mutates `Attachment.storage_path`, counts fresh
  temporary bytes before writes, and skips caching whenever a stable capacity
  proof or lease is unavailable while still returning verified downloaded
  bytes. Cleanup uses database ownership only when its snapshot succeeds and
  reports aggregates rather than cache paths. The separately owned legacy Chat
  attachment path is explicitly excluded until a coordinated migration brings
  it into this namespace and policy.

## D-011 — Attachment previews are typed derivatives, not trust proofs

- Date: 2026-08-30
- Status: accepted
- Decision: Expose received-attachment previews only through the same owned
  membership and canonical byte-loading boundary as downloads. Derive a
  bounded renderer kind from bytes, normalize raster/text output, require the
  client kind and content type to agree, and treat every preview as untrusted.
  PDF preview performs only basic checks and opens in a separate browser-native
  viewer; it is never described as structurally safe or malware-scanned.
- Reason: Sender filenames and MIME metadata are attacker-controlled, preview
  derivatives can be truncated or transformed, and raw PDF feature scans are
  bypassable. Reusing a derivative for Download can silently corrupt user data,
  while unbounded classification can exhaust process memory or CPU.
- Consequence: Preview and Download remain separate requests; Download always
  returns canonical original bytes. Active/archive/mismatched metadata and
  runtime type failures require confirmation, images/text use inert renderers,
  PDF bytes remain untrusted, and a process admission lease spans retrieval
  through classification. The AI-owned legacy Chat attachment path is outside
  this contract until separately coordinated.

## D-012 — Feature routes load behind a stale-safe shell boundary

- Date: 2026-08-30
- Status: accepted
- Decision: Keep authentication, global navigation, search, toasts, and route
  recovery in the eager shell while loading every feature screen through a
  literal allowlisted registry. Deduplicate concurrent imports, cache only the
  current successful request, discard superseded route results, and use real
  browser history with canonical per-route query parameters.
- Reason: A single 1.17 MB entry delays every mailbox visit, while ad hoc
  dynamic imports can expose stale screens, inert navigation, unrecoverable
  cached module failures, lost focus, and timing-dependent cross-screen intent.
- Consequence: New feature routes must register a stable key/label/import,
  expose accessible loading and error behavior, and pass cold, failed, stale,
  Back/Forward, focus, and narrow-screen QA. Shell controls may prefetch intent
  but must remain useful while chunks load. Route changes focus the named main
  region only when the previous focus was removed; Chromium module-load errors
  recover by preserving the canonical URL and reloading the document.

## D-013 — Select AI model and effort by workload

- Date: 2026-08-29
- Status: accepted
- Decision: Keep provider, model capability, compatible effort levels, and
  per-workload defaults in one registry. Use GPT-5.6 Terra/medium for planning,
  Luna/low for parallel and bulk work, Sol/high for final verification,
  Terra/medium for custom replies, and Claude Sonnet 5/medium for unsubscribe.
- Reason: Planning, parallel retrieval, final synthesis, bulk triage, and
  browser automation have different quality, latency, cost, and protocol needs.
- Consequence: New model families must declare their provider, effort support,
  and workload compatibility in the registry. Unsubscribe remains Claude-only
  until its Computer Use loop has an explicitly implemented provider adapter;
  retired or incompatible stored preferences fall back to the full default
  model/effort pair.

## D-014 — Load the rich editor only after writing intent

- Date: 2026-08-30
- Status: accepted
- Decision: Keep an immediately usable, accessible basic editor in the writing
  surface and import Tiptap only after Compose, Reply, or Forward is actually
  opened. Cache successful imports, share concurrent requests, evict failures,
  and keep the basic editor usable when enhancement cannot load.
- Reason: Reading mail should not transfer or execute the 117 kB gzip editor
  runtime, while writing must remain responsive on cold, slow, failed, and
  narrow-screen paths.
- Consequence: Read routes must not reference the RichEditor chunk directly;
  editor recovery preserves the current draft instead of reloading the page;
  and generated browser QA must cover asset closure, slow enhancement,
  recoverable failure, draft continuity, focus, and mobile controls.

## D-015 — Rendered email and AI content is display-only

- Date: 2026-08-30
- Status: accepted
- Decision: Sanitize sender-controlled email HTML and AI-generated Markdown as
  display surfaces. Explicitly reject scripts, frames, objects, embeds, forms,
  form controls, templates, base/meta elements, `srcdoc`, event attributes, and
  executable URLs while preserving ordinary layout, inline style, tables,
  images, Unicode, and safe links required for readable mail.
- Reason: A sanitizer dependency is a security boundary, not a formatting
  helper. Active or clobbering document structures provide no necessary mail
  client function and must not become allowed through dependency-default drift.
- Consequence: New rendered-content features must use the centralized policies
  and pass generated hostile/benign browser fixtures. Remote image, CSS, and
  link tracking remain a separate product policy requiring visible controls;
  this display-only decision does not claim to block all network tracking.

## D-016 — Remote message content is blocked until a scoped user decision

- Date: 2026-08-30
- Status: accepted
- Decision: Block every sender-controlled auto-loading resource by default in
  all message readers and in quoted Compose content. A message may expose a
  message-scoped, in-memory direct-load action only with explicit disclosure
  that it can reveal IP address, device details, and view timing. Its display
  state is reversible, but requests already made are not. External CSS,
  fonts, tracking pings, active content, and external SVG references remain
  blocked even after that action.
- Reason: A sandbox isolates script and style effects but does not stop network
  requests. Persistent sender trust or claims of private loading would be
  misleading without an owned resource manifest, hardened proxy, bounded
  cache, redirect/DNS/private-network validation, and truthful timing model.
- Consequence: Inbox, standalone/subscription, and Flow must use the shared
  email-frame boundary and its restrictive CSP; Forward/Compose must use the
  separate style-free sanitizer. Future preferences stay fail-closed on error,
  Spam never inherits a trust exception, and persistent exact-sender/global
  modes may be added only through the owned proxy. CID images require an owned
  inline-resource mapping rather than a direct exception.

## D-017 — OAuth callbacks restore explicit PKCE state and fail into the app

- Date: 2026-08-30
- Status: accepted
- Decision: Build every Google authorization-code flow with an explicit PKCE
  verifier. Carry account-flow verifiers encrypted inside signed, expiring
  state bound to a short-lived HttpOnly browser nonce; carry login verifiers in
  a separate encrypted HttpOnly cookie. Bind reauthorization to one owned
  account, validate the returned identity, actual required scopes, allowlist,
  and effective refresh token before clearing health, and express every
  expected callback result as a sanitized local HTTP 303 redirect.
- Reason: Process-local flow objects do not survive browser redirects, access
  cookies can expire during consent, login hints are advisory, and raw provider
  errors/blank callback tabs turn recoverable authorization outcomes into
  security and usability failures.
- Consequence: New OAuth entry points must use the shared explicit-verifier
  helper, one-time browser binding, bounded return targets, generated no-network
  regressions, and centralized result copy. Callback URLs and logs must never
  reflect authorization codes, tokens, provider descriptions, raw state, or
  account identities.

## D-018 — Reply envelopes require authoritative account provenance

- Date: 2026-08-30
- Status: accepted
- Decision: Build Reply and Reply All from an authoritative message detail or
  account-scoped thread member. The visible From/To/Cc context and the eventual
  send/compose payload must share one derived envelope. Missing, inactive,
  unknown, mismatched, ambiguous, or stale account/thread identity fails
  closed; there is no single-account or first-account fallback.
- Reason: In a multi-account client, guessing the sending account or rebuilding
  recipients separately can silently send from the wrong identity, omit
  Reply-To/Cc participants, duplicate owned addresses, or disclose a message to
  unintended recipients.
- Consequence: Detail/thread APIs carry account identity and References state;
  reply thread reads are account-scoped; all owned accounts and aliases are
  removed from recipients; Bcc is never inherited; failed thread reads disable
  editing, full compose, and send until authoritative data is restored.

## D-019 — Calendar truth is range-, account-, and generation-scoped

- Date: 2026-08-30
- Status: accepted
- Decision: Treat the visible Calendar dataset as the result of one immutable
  view/range/account/timezone request generation. Treat account discovery,
  cached event reads, successful full-sync coverage, and active Google
  ingestion as separate authorities. Certify an empty range only when every
  visible account has Calendar scope, healthy status, and a successful
  full-sync window that covers the exact displayed range.
- Reason: Event GET success alone cannot distinguish a truly empty calendar
  from a stale, disconnected, out-of-window, partially loaded, or superseded
  cache. Client clocks and historical activity also cannot prove that every
  requested sync target finished.
- Consequence: Superseded account/range reads and old-session polling results
  cannot commit UI state; local-date API selection uses DST-correct half-open
  boundaries; Reload remains a cache read; Sync captures one target set and
  requires server-observed progress for all targets; and uncertain/out-of-
  window empty states must use saved-data language with a recovery path.

## D-020 — At a Glance separates content catalogs from delivery adapters

- Date: 2026-08-30
- Status: accepted
- Decision: Define views, designs, and display profiles in one catalog, and
  require explicit device and browser renderer registrations for every catalog
  content type. Preserve current visual designs through canonical raster
  adapters while allowing future native-HTML adapters behind the same view
  contract.
- Reason: Independent hard-coded lists and renderer fallbacks make new designs
  easy to expose without a working output path. Browser delivery should not
  fork the product model or silently diverge from e-ink output.
- Consequence: A new content type must add catalog metadata and both required
  renderer registrations before startup succeeds. Current browser pages are
  exact-aspect HTML shells around canonical PNG frames; a native reflow is an
  explicit adapter change, not an accidental rewrite of the existing art.

## D-021 — Browser displays and firmware updates use separate trust scopes

- Date: 2026-08-30
- Status: accepted
- Decision: Give each browser display a high-entropy, revocable credential
  bound server-side to one view/design/profile. Keep firmware routing separate,
  and require future firmware installation and OTA to consume immutable
  per-model artifacts with hashes, signatures, exact variant/layout gates,
  CA-validated transport, A/B rollback, and per-device authentication.
- Reason: Reusing the firmware route secret lets one leaked display link expose
  every private view, while unauthenticated single-slot updates cannot fail
  safely or prove artifact/model identity.
- Consequence: Rotating a display invalidates only that URL. Firmware-code
  rotation does not disturb browser displays. Browser flashing and OTA remain
  blocked until their release, recovery, enrollment, power, and rollout gates
  are implemented and hardware-qualified.

## D-022 — Authenticated browser state is identity-generation scoped

- Date: 2026-08-30
- Status: accepted
- Decision: Advance one central authentication generation before publishing a
  changed user, synchronously clear all user-derived stores, and require every
  request, stream, timer, poller, and delayed continuation to prove that its
  captured generation is still current before it can write UI state. Drain any
  in-flight refresh before the ordered logout clears cookies, and do not expose
  login again until that barrier completes. Scope browser drafts and last-sender
  choices by authenticated user and writing intent. Enforce Todo-to-email
  ownership in both the router and PostgreSQL.
- Reason: A single-document A-to-B transition can otherwise expose A's
  messages, drafts, Todos, action results, or notifications in B's UI. A late
  refresh response can also overwrite B's browser cookies before JavaScript can
  reject its body. Todo IDs supplied by a client are untrusted cross-account
  references.
- Consequence: New authenticated features must register their user-derived
  state with the session reset, cancel or ignore stale async work, and use the
  shared API/session guard. Legacy unscoped drafts are purged, never migrated.
  Foreign, missing, and analysis-missing email IDs share a uniform Todo 404;
  historical cross-owner AI-derived Todos are purged, while user-authored
  manual titles are preserved only after detaching unsafe email/draft links.

## D-023 — Outbound email is a durable at-most-once operation

- Date: 2026-08-30
- Status: accepted
- Decision: Accept each browser send into PostgreSQL under one user-scoped
  client UUID and immutable canonical payload, wait through a server-owned
  ten-second Undo window, durably mark a provider attempt before calling Gmail,
  and assign one stable RFC Message-ID. A pre-attempt failure may retry under a
  lease; any ambiguous or interrupted post-attempt outcome becomes lookup-only
  reconciliation and is never automatically resent. Reply metadata is accepted
  only with an exact owned source message/account/thread/header proof.
- Reason: An HTTP response is not provider delivery truth. Retrying after a
  lost Gmail response can duplicate external email, while guessing reply
  provenance can send from the wrong account or attach a response to a foreign
  thread.
- Consequence: Interactive Compose, reader, and Flow sends use the shared
  durable controller, clear editors on durable ownership rather than claiming
  success, and announce sent only from server state. PostgreSQL is recovery
  authority; Redis only accelerates draining. Sent and cancelled operations
  scrub recipients, bodies, and attachment bytes; non-retryable failures scrub
  immediately, and any authorized pre-provider retry expires and scrubs after
  one hour. Ambiguous sends tell the user not to resend; unsafe failures cannot
  be retried. Undo/failure recovery
  opens a distinct auth-scoped Compose intent, or queues it behind an explicit
  Review draft action when another composer is active. The global failure UI
  does not offer one-click Retry beside an editable recovered copy. Public API
  tokens cannot access these mutation routes.

## D-024 — Firmware approval is signed, generation-pinned, and independently gated

- Date: 2026-08-30
- Status: accepted
- Decision: Serve browser firmware only from an operator-staged,
  content-addressed local bundle referenced by a detached-signature-verified
  catalog with one approved release and a monotonically increasing generation.
  Require the configured public-key trust set, a positive externally pinned
  minimum generation, exact manifest/partition/hash/hardware qualification,
  explicit server enablement, independent browser signature verification,
  secure serial provisioning, and hardware recovery evidence before any write
  path can become eligible.
- Reason: A signed manifest alone does not express operator approval, prevent a
  replayed older release, prove a model's flash boundaries, or protect against
  accidentally shipping an incomplete browser flasher. Fetching mutable
  release state from GitHub at request time also widens the availability and
  trust boundary.
- Consequence: Production defaults remain locked with no trusted key, catalog,
  positive generation floor, or enablement flag. Catalog inspection may ship
  before installation because its client contains no serial request, binary
  download, erase, or write code. Catalog generations are never reused; E1004
  remains ineligible; private firmware signing keys stay offline; future
  enrollment uses a separate online signing key and physical-cable trust is not
  described as hardware attestation.

## D-025 — Drafts are versioned sessions with dual recovery authority

- Date: 2026-08-30
- Status: accepted
- Decision: Give every Compose writing intent one user-scoped client UUID and
  immutable, mutation-keyed revisions. Commit the complete snapshot and
  attachment bytes to auth-scoped IndexedDB and PostgreSQL, then synchronize
  one stable provider draft identity with at-most-once initial creation and
  lookup-only ambiguity recovery. Keep a send-owned browser snapshot until
  terminal delivery truth; delete it on `sent`, or convert it to a fresh
  Compose identity after `failed` or `cancelled` recovery is durable.
- Reason: A Gmail response, browser tab, Redis enqueue, or worker lease is not
  durable writing-session truth. Blind create retry can duplicate provider
  drafts, immediate local deletion can lose late Undo/failure content, and
  content retention after an expired discard window unnecessarily preserves
  sensitive bodies and attachments.
- Consequence: Every edit advances revision and mutation identity; conflicts
  require an explicit local/server choice; reply provenance and account
  ownership fail closed; server discard scrubs content immediately after the
  authoritative Undo deadline while a content-free tombstone finishes provider
  reconciliation. Public tokens cannot mutate or read draft detail, and a
  schema downgrade is an explicit data-loss operation.

## D-026 — Terminal enrollment activates from device proof, not browser success

- Date: 2026-08-30
- Status: accepted
- Decision: Treat RET1 as confidential, server-authorized provisioning under
  physical-cable observation, not hardware attestation. Approve enrollment only
  when a signed schema-2 firmware claim, positive catalog generation, protected
  independent online P-256 key, exact HTTPS origin, and explicit E1001/E1002
  release/model HIL allowlist agree. Persist only credential/config hashes and
  activate a candidate only on its first matching scoped HTTPS check-in. Keep
  the same owner's shared route during first-enrollment interruption, retain
  only the immediately previous generation for a 24-hour rollback grace, and
  make all credential generations owner-revocable.
- Reason: A browser result can be lost or forged, a MAC and open ESP32 ROM
  downloader do not prove hardware identity, replacing the active credential
  before connectivity is observed can strand a device, and an unrevocable URL
  secret turns one leak into indefinite access.
- Consequence: The browser completion event is advisory; enrolled and revoked
  devices cannot fall back to a shared code; revocation requires qualified
  physical re-enrollment; path secrets are suppressed at both Caddy and ASGI
  logging boundaries; all state transitions use device-first PostgreSQL locks,
  absent-row ownership uses an advisory lock plus partial unique index, and the
  production transport remains absent until physical HIL passes. The online
  enrollment key is never the offline firmware release key.

## D-027 — At a Glance is a first-class application destination

- Date: 2026-08-30
- Status: accepted
- Decision: Give At a Glance its own authenticated application route and
  primary navigation entry, comparable to Flow, Email, Calendar, and Todos.
  Keep Settings as the management surface for device credentials, browser
  display links, firmware policy, and destructive actions; the first-class page
  is the everyday view/design/display experience.
- Reason: Promoting e-ink and browser displays to a product feature requires a
  discoverable daily destination. Renaming a Settings section leaves the
  feature structurally hidden and does not satisfy that product contract.
- Consequence: The route must use the shared catalog and adapters from D-020,
  preserve session-generation isolation, work on desktop and narrow screens,
  and integrate with lazy routes and primary navigation. It will land after the
  coordinated Durable Replies release clears shared shell files; the secure
  enrollment migration does not opportunistically modify those files.

## D-028 — One source message owns one durable reply session

- Date: 2026-08-30
- Status: accepted
- Decision: Identify a reply writing session by the authenticated user, exact
  owned sending account, and exact source email. Reader, Flow, and full Compose
  use the same stable reply intent and durable draft controller. Enforce at
  most one active server reply for that source, serialize competing first
  saves, and let a loser discover and adopt only an editable exact-source
  winner. Never adopt a sending, discard-pending, discarded, conflicted, or
  ambiguous winner.
- Reason: Surface-specific draft keys can fork one reply into multiple Gmail
  drafts, while choosing by thread, sender, subject, or provider draft is too
  weak to prove ownership or the intended reply. Cross-device recovery also
  needs a server lookup that cannot disclose whether another user's source or
  draft exists.
- Consequence: The browser writes every edit to owner-scoped IndexedDB before
  remote debounce, discovers a missing local reply through the exact
  account/source endpoint, and blocks navigation when local durability, send,
  or discard truth is unresolved. Reply and Reply All may rebase only the
  verified recipient envelope while preserving content. Recent Drafts is a
  metadata-only Continue Writing surface; opening a row still re-enters the
  exact durable session and compares any newer server revision.

## D-029 — Scheduled delivery is one durable outbound operation

- Date: 2026-08-30
- Status: accepted
- Decision: Represent an immediate or future delivery as the same immutable,
  user/account-owned outbound operation. Store the requested instant in UTC,
  retain the IANA zone only as presentation context, require an exact linked
  durable draft for future delivery, and let PostgreSQL due-time ownership
  decide every cancel/send race. Redis is only an exact deferred wake; cron
  remains the recovery authority.
- Reason: A browser timer, long-lived Undo toast, provider draft schedule, or
  repeated create request cannot guarantee delivery across reload, device
  changes, worker restarts, daylight-saving transitions, or a lost response.
  Creating a replacement operation for Send now or retry would also weaken the
  established idempotency and ambiguity boundary.
- Consequence: Scheduled operations share the existing Message-ID preflight,
  provider-attempt marker, bounded retry, and lookup-only reconciliation.
  Cancel is idempotent, scrubs payload content, and restores the linked draft;
  Send now advances the same operation. Post-send Flow actions use a
  deterministic durable mail-action key before terminal send truth, so reload
  cannot drop Archive after send. The UI displays explicit zone/offset choices,
  restores a metadata-only pending list across sessions, and reduces polling
  while the due time is distant.

## D-030 — Terminal firmware writes require independent end-to-end gates

- Date: 2026-08-30
- Status: accepted
- Decision: Ship trusted firmware parsing, browser cryptographic preflight,
  battery prediction, and OTA policy/status independently from any device-write
  transport. Browser install requires an exact source-pinned release key,
  signed generation-pinned catalog, exact model/layout evidence, secure local
  provisioning, and physical recovery qualification. Device OTA additionally
  requires an exact signed content-addressed descriptor linked to its parent
  bundle, explicit HIL qualification, device authentication, direct power
  safety, a durable idempotent event ledger, and boot validation/rollback. No
  single flag may enable either write path.
- Reason: A valid signature does not prove the connected model, recoverability,
  power safety, operator approval, or durable update state. Browser-observed
  Serial identity is self-reported, and battery-voltage trends cannot prove
  external power. Coupling a visible feature or one enablement flag to a flash
  operation would turn a UI or configuration mistake into a device-bricking
  boundary.
- Consequence: Candidate.4 and the application policy modules may ship while
  every transport remains locked. Battery forecasts are advisory only; E1004
  remains single-slot and ineligible; the browser production trust map is empty;
  and future Serial/OTA work must preserve every independent gate plus exact
  interruption, rollback, and ROM-recovery evidence.

## D-031 — Snooze is a durable conversation lifecycle

- Date: 2026-08-30
- Status: accepted
- Decision: Represent one active Snooze by the exact authenticated user,
  Google account, and Gmail thread. Persist its time, condition, current
  conversation membership, original Inbox membership, mail-action baselines,
  attempts, leases, and terminal state in PostgreSQL. Use the existing ordered
  mail-action outbox for archive and Inbox return; Redis is only wake-up
  acceleration and cron remains the recovery authority.
- Reason: Browser timers and one-message projections lose reminders across
  reloads and split a conversation into contradictory rows. Pre-staging a
  future Inbox return would make optimistic mail-action overlay surface it
  immediately, while staging outside the conversation-row lock can let an
  automated wake override a later manual mailbox move.
- Consequence: Current eligible Inbox siblings archive together and one active
  reminder exists per account/thread. Due/Return-now assigns ordered unarchive
  work while every current conversation row is locked, so later manual
  placement wins. Cancel restores original placement; wake returns to Inbox;
  protected or newer-manual members are filtered individually. Conditional
  return waits for a fresh sync checkpoint before concluding nobody replied,
  terminal provider failures release uniqueness, and lost browser responses
  reconcile the same client-keyed operation instead of creating another.

## D-032 — Existing Gmail labels are account-scoped conversation actions

- Date: 2026-08-30
- Status: accepted
- Decision: Represent Label and Move as durable mail-action deltas against one
  positive local `label_type=user` catalog identity from the exact owned Gmail
  account. Expand explicit anchors to current synchronized conversation
  members. Define Move narrowly as applying the destination label and removing
  Inbox, and expose it only from the literal Inbox view.
- Reason: Gmail label IDs are provider/account-local, a conversation can contain
  multiple stored messages, and an accepted action must survive catalog refresh,
  lost responses, retry, Undo, and process restart. Calling the same operation
  “Move” from a custom label, All Mail, Spam, or Trash would falsely imply that
  every source label or protected placement is removed.
- Consequence: Idempotency is based on the original email IDs, action, and local
  label ID before mutable resolution; every item persists exact provider deltas;
  mixed-account, system, stale, and foreign labels fail closed; successful full
  catalog sync prunes only after complete validation. Existing-label actions
  ship independently from future durable create/rename/delete label lifecycle,
  and split/focused Inbox work must reuse this account/conversation boundary.

## D-033 — The Inbox unit is an owned-account conversation

- Date: 2026-08-30
- Status: accepted
- Decision: Project Inbox, ordinary mailboxes, and search as one row per exact
  `(account_id, gmail_thread_id)` after all filters, grouping, counts, and
  pagination are resolved in PostgreSQL. Treat a blank thread ID as a typed
  one-message identity. Use the newest matching member as the presentation
  anchor, derive aggregate state from every synchronized member, and expand an
  additive durable conversation action under server locks.
- Reason: Message-level pagination can display contradictory duplicates, hide a
  sibling outside the current page, misstate totals, and let a visible-page
  action pretend to cover a conversation. Gmail thread IDs are account-local,
  while blank IDs and cross-account collisions cannot safely share a reader or
  mutation boundary.
- Consequence: First-party thread reads always include account scope; a legacy
  unscoped ambiguous read fails with 409. Ordinary Inbox Snoozes are excluded in
  the authoritative query. Conversation actions retain message-scope backward
  compatibility but include scope in new idempotency identity and remain capped
  after expansion. Full thread reading is chronological; focused/split Inbox is
  a later placement policy over this row primitive, not a second source of mail
  truth.

## D-034 — OTA authority is an immutable offer plus append-only device truth

- Date: 2026-08-30
- Status: accepted
- Decision: Create one idempotent, owner-requested OTA attempt for an exact
  owned terminal, active credential generation, verified content-addressed
  descriptor and parent bundle, confirmed hardware revision, coherent running
  build/slot/boot identity, fresh measured power reserve, and deterministic
  rollout cohort. Persist every accepted device transition as an append-only
  event and project the latest state in the same PostgreSQL transaction.
- Reason: A schedule poll, Redis job, firmware version string, or successful
  download cannot prove which device, credential, artifact, slot, boot, or
  lifecycle transition actually occurred. Retrying after a lost response must
  neither mint a second offer nor advance the device twice, and a global enable
  flag must not silently turn an unqualified release into a fleet rollout.
- Consequence: Only the current active credential can receive the exact
  credential-scoped offer and artifacts. First event acceptance is `201`, exact
  replay is `200`, conflicting identity/sequence/payload/runtime evidence fails
  closed, and sequence gaps remain marked as non-promotion-quality evidence.
  OTA stays independently locked by default behind signed release evidence,
  exact HIL allowlisting, explicit device revision, fresh direct-or-conservative
  power truth, nonzero rollout, and server enablement. Generic firmware remains
  transport-disabled and unkeyed; physical E1001/E1002 interruption, rollback,
  and recovery evidence is still required before any production offer.

## D-035 — Split Inbox is a projection over one authoritative conversation

- Date: 2026-08-30
- Status: accepted
- Decision: Classify the authoritative newest mailbox-matching anchor exactly
  once, after owned-account conversation identity is established and before
  count or pagination. Use only persisted deterministic signals with stable
  precedence: high priority, unanswered needs-reply, trusted contact, delegated
  scheduling, subscription, low priority, unclassified, then direct/FYI.
- Reason: Filtering individual messages before grouping can put one Gmail
  conversation into both Focused and Other with contradictory anchors and
  totals. Invoking or backfilling AI during reads would make placement unstable,
  expensive, and capable of hiding newly synchronized mail while classification
  lags.
- Consequence: Focused and Other are disjoint views whose totals sum to the
  ordinary Inbox. Missing analysis stays visibly Focused; later-sent-reply
  correlation is scoped to the exact account/thread; account filters remain
  safe; every placement has an explainable reason. Split changes presentation
  only: Gmail placement, labels, durable conversation actions, Snooze, Undo,
  retry, and idempotency retain their existing ownership boundary. No migration
  or AI-provider call is part of the feature.

## D-036 — Catalog designs require exact registered implementations

- Date: 2026-08-30
- Status: accepted
- Decision: Treat every catalog-declared `(content_type, design)` as an exact
  contract with explicit immutable Pillow renderer and palette registrations,
  plus exact device and browser content renderers. Validate equality across
  these registries at import time. Unknown content, design, or palette values
  fail closed instead of selecting a visually plausible default.
- Reason: A catalog option can reach first-class selectors, scoped browser
  displays, and physical terminals automatically. Silently mapping a missing
  future design to Editorial would make an incomplete feature appear valid and
  could let browser/device outputs disagree while tests still see an image.
- Consequence: Existing Home Editorial/Swiss and Day Ahead Editorial pixels are
  snapshot-pinned and unchanged. Adding a design now requires one explicit
  registry entry, its palette family, compatible catalog declaration, and exact
  renderer coverage; startup/test validation rejects partial registration.
  Persisted invalid selections use the existing logged safety fallback rather
  than impersonating a different named design.

## D-037 — Browser transport presence does not imply write eligibility

- Date: 2026-08-30
- Status: accepted
- Decision: Ship the reviewed, exact-version Web Serial/esptool adapter as an
  inert capability behind the existing independent release-signature,
  generation-pinned catalog, secure-enrollment, printed-revision, model/layout,
  and physical HIL gates. Only an enabled Connect action entered by an explicit
  user click may request a port. Hold one origin-wide exclusive Web Lock across
  ROM write/readback, reset, and same-port RET1 verification, and never expose a
  whole-chip erase path.
- Reason: Keeping transport code absent prevented physical testing of the real
  browser path, but merely including it must not let a UI or configuration flag
  bypass trust, recoverability, model identity, or provisioning. Browser port
  selection is physical authorization, not firmware authenticity or hardware
  attestation.
- Consequence: Production can deploy and inspect the exact transport while the
  Connect action remains unreachable with an empty key/catalog/HIL state.
  Promotion consumes immutable candidate bytes only after complete exact-revision
  E1001 and E1002 evidence and signs offline; E1004 and OTA eligibility stay
  false. Physical interruption, DTR/RTS, ROM recovery, RET1 provisioning, and
  first authenticated check-in remain mandatory before any enablement.

## D-038 — Send & Archive is one durable post-delivery operation

- Date: 2026-08-30
- Status: accepted
- Decision: Full Compose and inline replies may request Send & Archive only
  from an exact admission-validated source message. The server owns one
  immutable outbound intent and stages one deterministic conversation-scoped
  archive action only after provider delivery is confirmed.
- Reason: A client-side send followed by archive can hide mail that failed to
  send, lose the archive across reload, duplicate work after an ambiguous
  response, or archive only one message while promising the conversation.
- Consequence: New messages fail closed to ordinary Send; Undo, cancellation,
  and delivery failure leave the conversation in place; provider-confirmed
  reconciliation retries the same archive identity; and a source removed by
  later sync turns the archive into a terminal no-op instead of trapping the
  delivered message in reconciliation.

## D-039 — Browser install and enrollment share one physical session; activation remains device-authenticated

- Date: 2026-08-30
- Status: accepted
- Decision: After all independent server, signed-catalog, release/model,
  printed-revision, enrollment, and HIL gates pass, one explicit user gesture
  selects one Web Serial port and holds one origin-wide Web Lock across exact
  preserve-config flash/readback, reset, RET1 encrypted configuration/result,
  and activation polling. Wi-Fi and the raw device credential remain
  browser-to-device; the API receives only hashes. Firmware, not browser
  structure parsing, performs authoritative ES256 ticket verification.
- Reason: Reopening a chooser between flash and provisioning loses physical
  continuity and makes identity/recovery ambiguous, while treating a serial
  result as activation would let self-reported cable evidence replace proof
  that the installed credential can authenticate over the intended HTTPS path.
- Consequence: Pre-write cancellation is owner/same-origin and supersedes only
  the exact attempt/candidate. A later old-generation handshake can retry with
  fresh hashes, and one unique lost-result lineage can reconcile from an
  observed target generation, but an uncertain encrypted write is never
  replayed automatically. Only the first matching scoped HTTPS check-in
  activates the candidate. Production exposes no Wi-Fi fields and disables
  Connect until every independent gate is deliberately satisfied.

## D-040 — Personal Snippets are private revisioned templates that materialize on insertion

- Date: 2026-08-30
- Status: accepted
- Decision: Store Personal Snippets as user-owned records with a stable
  client-generated create UUID, a unique normalized shortcut, and full
  revision-checked replacement. Sanitize rich HTML at each editor insertion
  boundary and materialize the selected content into the active draft instead
  of retaining a live reference to the template.
- Reason: Reusable writing must survive devices and lost responses without
  disclosing content across users, duplicating records, silently overwriting a
  concurrent edit, or letting later template changes rewrite an already
  composed message. Treating stored rich content as trusted would also widen
  the draft rendering boundary unnecessarily.
- Consequence: Exact create and update replays are safe, stale revisions fail
  visibly, missing and foreign identifiers remain non-disclosing, and deletion
  affects only future selection. Compose, reader, and Flow all insert one
  sanitized snapshot with one Undo step. Inline semicolon expansion, variables,
  sharing, analytics, and per-account signatures remain separate milestones.

## D-041 — Release validation is focused during iteration and consolidated once after freeze

- Date: 2026-08-30
- Status: accepted
- Decision: Run affected focused tests while code is changing, one bounded
  P0/P1 review when the candidate is coherent, and one consolidated release
  gate after code freeze. Specialized migration, generated-fixture, and browser
  evidence run once when applicable. Documentation-only closeout does not
  restart broad testing; P2 polish is batched unless it blocks the primary
  workflow, accessibility, ownership, integrity, or security.
- Reason: Repeating every suite and browser journey after each small finding
  consumes hours without proportionally improving release confidence, delays
  delivery, and encourages the team to treat cosmetic polish like a data-loss
  or cross-user security risk.
- Consequence: A final-gate blocker receives its focused regression check and
  one consolidated rerun after correction. Production preflight, validated
  backups, migration checks, health, logs, and rollback boundaries remain
  mandatory. The repository-wide operating rule is recorded in `AGENTS.md`.

## D-042 — Recipient suggestions are account-scoped projections; pending text is not a recipient

- Date: 2026-08-30
- Status: accepted
- Decision: Derive Compose suggestions from one index-bounded recent metadata
  corpus for the selected owned account, exclude every address owned by the
  signed-in user, and return only normalized mailbox metadata. Persist and send
  only canonical committed chips. Keep unfinished input local and visibly block
  sender changes, draft save, navigation, and every Send path until it is
  committed or removed.
- Reason: A naive address-book lookup can disclose another account's contacts
  or turn every keystroke into an unbounded mailbox scan. Treating partial text
  as durable can corrupt quoted display names; omitting it from a send while it
  remains visible can silently deliver to the wrong set of people.
- Consequence: Autocomplete needs no Contacts scope, provider call, schema
  change, or message-content response. Quoted commas, paste, keyboard
  selection, duplicates across To/Cc/Bcc, account switches, stale responses,
  and manual entry share one parser and fail closed. Inline snippet expansion
  and a first-class contacts directory remain separate milestones.

## D-043 — Inline snippet expansion replaces only a live verified literal

- Date: 2026-08-31
- Status: accepted
- Decision: Treat `;shortcut` as ordinary draft text until the user explicitly
  selects a result in the same authenticated editor activation. At selection,
  re-read and verify the exact trigger range, sanitize the chosen snapshot at
  the editor boundary, and replace it in one undoable transaction. Never use a
  captured asynchronous range as mutation authority.
- Reason: Automatic or stale expansion can overwrite text after caret movement,
  leak one user's private template into another session, trigger Send shortcuts,
  or leave a change that cannot be undone. A compatibility fallback that edits
  text without browser/editor Undo would make the same visible feature carry a
  materially weaker safety contract.
- Consequence: Triggering is limited to block start or whitespace and is
  suppressed during composition, selection, links, and code. Loading, empty,
  error, Escape, movement, identity change, and stale response paths preserve
  the literal. Rich and plain surfaces share keyboard containment and one-step
  Undo; an unsupported compatibility editor keeps the existing explicit picker.

## D-044 — Automatic follow-up is a delivery-confirmed, reply-aware reminder

- Date: 2026-08-31
- Status: accepted
- Decision: Resolve an explicit or per-account default follow-up policy exactly
  once at immutable outbound admission, persist a content-free companion intent
  in the same transaction, and schedule one `if_no_reply` automatic Snooze only
  after provider-confirmed delivery maps to one exact synchronized Sent row.
  Never remove a synchronized Inbox conversation for an automatic reminder;
  serialize every Snooze creator, mutator, and worker by the same conversation
  advisory lock, and let manual reminders or newer manual placement win.
- Reason: Scheduling from an HTTP acceptance, planned delivery time, or
  unconfirmed provider attempt can create a reminder for mail that was undone,
  cancelled, failed, retried, or never sent. Tracking pixels and read receipts
  widen privacy boundaries without proving that a recipient will reply. A
  partially committed Snooze/mail-action operation can also release ordering
  authority before the visible reminder state is final.
- Consequence: Default is off; account policy revisions and per-send overrides
  round-trip through durable drafts. Delivery timestamp, business-day/DST
  calculation, reply detection, and retries are server-owned and recoverable
  from PostgreSQL without message content. Explicit self-only or Bcc-only
  enablement fails admission, identifier disagreement fails closed, and schema
  rollback becomes data-lossy once e8 reminder truth exists.

## D-045 — Signatures are immutable per-draft sidecars, not authored body content

- Date: 2026-08-31
- Status: accepted
- Decision: Store one revisioned rich/plain signature policy per exact owned
  Google account. Freeze one sanitized, content-hashed snapshot when a new
  durable writing intent is established; linked sends copy that snapshot
  exactly. Keep authored body, signature, and structured quoted history as
  separate fields and assemble the transient provider body exactly once in that
  order. Remove and Restore change only the frozen snapshot's applied state.
- Reason: Copying live settings into editable draft HTML makes signatures
  duplicate on reload, drift after settings edits, become indistinguishable
  from user-authored text, and reorder incorrectly around forwarded history.
  Resolving policy again during retries or scheduled delivery can also change
  an already accepted message.
- Consequence: Existing legacy drafts remain unsigned; policy changes affect
  future intents only. Sender and account ownership fail closed, sanitization
  is versioned, rendered size is checked before Gmail, recent draft lists do
  not expose content, and an unavailable policy blocks Send until explicit
  Retry or Continue unsigned. Downgrading f9 drops user-created signature
  content and is data-lossy once rows exist.

## D-046 — Contact profiles are bounded correspondence projections, not an address book

- Date: 2026-08-31
- Status: accepted
- Decision: Derive each Contact profile at read time from one exact owned
  account's newest 4,000 eligible synchronized metadata rows. Identify a
  correspondent with an opaque user/account/address HMAC, exclude Bcc-only and
  every owned address, and return only normalized relationship counts,
  timestamps, corpus coverage, and exact recent thread pointers. Keep query
  and profile POST-only, private, no-store, and session-authenticated.
- Reason: A first-class relationship view is useful before adding Google
  Contacts access or a writable schema, but a global or content-bearing
  projection could disclose another account's correspondents, place private
  search terms in URLs, or imply complete address-book truth from partial mail
  history.
- Consequence: The UI labels every metric as observed, discloses truncation,
  and keeps same-address correspondents separate across accounts. Compose and
  Inbox handoffs retain exact account authority and session-only identities.
  Durable aliases, notes, organizations, merge rules, provider contacts, and
  all-history counters require a separately reviewed owned schema and sync
  contract rather than widening this projection in place.

## D-047 — Saved Views persist private definitions, never result authority

- Date: 2026-08-31
- Status: accepted
- Decision: Persist at most twelve revisioned, user-owned Saved Views containing
  only a normalized name, validated structured-search query, optional exact
  owned account, order, and idempotency metadata. Treat the conversation/search
  endpoint as the only result authority; never cache result rows, message IDs,
  counts, or provider state in a view. Keep the client collection session-only
  and keep private query text out of navigation URLs and browser storage.
- Reason: Durable named searches close the Custom Split workflow gap without
  duplicating Inbox truth or introducing Gmail filters, AI classification, or a
  second pagination model. Cached membership would become stale under sync and
  mail actions, while a missing account silently widened to all accounts could
  disclose unrelated mail.
- Consequence: Every mutation is owner-serialized and revision-checked; create
  and replacement retries are content-checked; reorder carries the exact
  expected collection; and deletion refreshes compacted positions/revisions.
  Missing or foreign account scope fails as 404 and account deletion removes
  scoped views. Future provider rules, notifications, badges, shared views, or
  cached counts require a separate model and review rather than widening this
  definition contract.

## D-048 — Attachment discovery is metadata-only until an explicit byte action

- Date: 2026-08-31
- Status: accepted
- Decision: Project the Attachments workspace from synchronized local metadata
  for one exact active owned account, with a strict response allowlist and
  deterministic signed-cursor pagination. Exclude Draft, Spam, Trash, and
  inline parts. Listing, searching, filtering, keyboard selection, and parent
  navigation must never fetch provider bytes, populate the attachment cache,
  render thumbnails, or expose provider/storage identifiers. Reuse the existing
  exact email-and-attachment Preview and Download routes only after an explicit
  user action.
- Reason: Mailbox-wide file discovery is valuable, but filenames, MIME claims,
  and source-message metadata remain private and attacker-controlled. Eager
  previewing would turn a read-only list into hidden Gmail reads and cache
  writes, while an unscoped or client-filtered query could cross account or
  session boundaries. The existing attachment foreign key also lacked the
  index required for a durable all-history projection.
- Consequence: The feature adds only an `attachments.email_id` index and no new
  file content or provider permission. Search stays POST-only and private,
  responses are no-store, filenames are sanitized, late account/session results
  fail closed, and real-mail production QA remains metadata-only. Thumbnails,
  OCR, AI summaries, bulk ZIP, compose reuse, provider-wide reindexing, and
  writable file organization require separately reviewed contracts.
