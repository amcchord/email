<script>
  import { onDestroy, onMount, tick } from 'svelte';
  import { api } from '../lib/api.js';
  import {
    accounts,
    accountsLoadError,
    composeData,
    contactConversationIntent,
    createAuthenticatedSessionGuard,
    currentMailbox,
    currentPage,
    searchQuery,
    selectedAccountId,
    selectedEmailId,
    showToast,
    smartFilter,
  } from '../lib/stores.js';
  import { registerActions } from '../lib/shortcutStore.js';
  import {
    contactComposeIntent,
    contactConversationNavigationIntent,
    contactDirectionLabel,
    contactDisplayName,
    contactInitials,
    createContactProfilePayload,
    createContactQueryPayload,
    formatContactObservedDate,
    normalizeContactProfileResponse,
    normalizeContactQueryResponse,
  } from '../lib/contactProfiles.js';
  import Icon from '../components/common/Icon.svelte';

  const relationshipOptions = Object.freeze([
    { id: 'all', label: 'All relationships' },
    { id: 'bidirectional', label: 'Two-way' },
    { id: 'inbound_only', label: 'Emailed me' },
    { id: 'outbound_only', label: 'I emailed' },
  ]);

  let sessionGuard = null;
  let contactAccountId = $state(null);
  let query = $state('');
  let relationship = $state('all');
  let page = $state(1);
  let contacts = $state([]);
  let total = $state(0);
  let totalPages = $state(0);
  let coverage = $state(null);
  let listLoading = $state(false);
  let listError = $state('');
  let listGeneration = 0;
  let listRetryVersion = $state(0);

  let selectedContactKey = $state(null);
  let focusedIndex = $state(-1);
  let profile = $state(null);
  let profileLoading = $state(false);
  let profileError = $state('');
  let profileGeneration = 0;
  let profileRetryVersion = $state(0);

  let searchInput = $state(null);
  let profileRegion = $state(null);
  let narrowViewport = $state(window.matchMedia('(max-width: 767px)').matches);

  let activeAccounts = $derived(
    $accounts.filter(account => account?.is_active !== false && Number.isSafeInteger(Number(account?.id)))
  );
  let selectedAccount = $derived(
    activeAccounts.find(account => Number(account.id) === Number(contactAccountId)) || null
  );
  let selectedContact = $derived(
    contacts.find(contact => contact.contact_key === selectedContactKey) || profile?.contact || null
  );
  let showingMobileProfile = $derived(narrowViewport && Boolean(selectedContactKey));

  function accountLabel(account) {
    return account?.short_label || account?.description || account?.email || 'Connected account';
  }

  function resultSummary() {
    if (listLoading && contacts.length === 0) return 'Loading contacts';
    if (listError) return 'Contacts unavailable';
    if (total === 0) return 'No contacts';
    return `${total.toLocaleString()} ${total === 1 ? 'contact' : 'contacts'}`;
  }

  function resetListSelection() {
    selectedContactKey = null;
    focusedIndex = -1;
    profile = null;
    profileError = '';
    profileLoading = false;
    profileGeneration += 1;
  }

  function changeAccount(event) {
    const nextId = Number(event.currentTarget.value);
    if (!Number.isSafeInteger(nextId) || nextId < 1 || nextId === contactAccountId) return;
    contactAccountId = nextId;
    selectedAccountId.set(nextId);
    page = 1;
    resetListSelection();
  }

  function changeRelationship(event) {
    relationship = event.currentTarget.value;
    page = 1;
    resetListSelection();
  }

  function changeQuery(event) {
    query = event.currentTarget.value;
    page = 1;
    resetListSelection();
  }

  function retryList() {
    listRetryVersion += 1;
  }

  function retryProfile() {
    profileRetryVersion += 1;
  }

  function focusRow(index) {
    if (contacts.length === 0) return;
    const bounded = Math.max(0, Math.min(index, contacts.length - 1));
    focusedIndex = bounded;
    requestAnimationFrame(() => {
      document.querySelector(`[data-contact-index="${bounded}"]`)?.focus({ preventScroll: true });
    });
  }

  function moveContact(delta) {
    if (contacts.length === 0) return;
    const start = focusedIndex < 0 ? (delta > 0 ? -1 : 0) : focusedIndex;
    focusRow((start + delta + contacts.length) % contacts.length);
  }

  async function openContact(contact, index = contacts.findIndex(item => item.contact_key === contact?.contact_key)) {
    if (!contact) return;
    selectedContactKey = contact.contact_key;
    if (index >= 0) focusedIndex = index;
    if (narrowViewport) {
      await tick();
      profileRegion?.focus({ preventScroll: true });
    }
  }

  function openFocusedContact() {
    const index = focusedIndex >= 0 ? focusedIndex : 0;
    return openContact(contacts[index], index);
  }

  async function backToContactList() {
    if (!selectedContactKey) return;
    const returnIndex = focusedIndex >= 0 ? focusedIndex : 0;
    selectedContactKey = null;
    profile = null;
    profileError = '';
    profileLoading = false;
    profileGeneration += 1;
    await tick();
    focusRow(returnIndex);
  }

  function emailSelectedContact() {
    const contact = profile?.contact || selectedContact;
    if (!contact || !contactAccountId) return;
    selectedAccountId.set(Number(contactAccountId));
    composeData.set(contactComposeIntent(contactAccountId, contact));
    currentPage.set('compose');
  }

  function openRecentConversation(recent) {
    const intent = contactConversationNavigationIntent(recent);
    selectedAccountId.set(intent.account_id);
    currentMailbox.set('ALL');
    searchQuery.set('');
    smartFilter.set(null);
    contactConversationIntent.set(intent);
    selectedEmailId.set(intent.anchor_email_id);
    currentPage.set('inbox');
  }

  function changePage(nextPage) {
    if (nextPage < 1 || nextPage > totalPages || nextPage === page) return;
    page = nextPage;
    resetListSelection();
    requestAnimationFrame(() => searchInput?.focus({ preventScroll: true }));
  }

  onMount(() => {
    sessionGuard = createAuthenticatedSessionGuard();
    const media = window.matchMedia('(max-width: 767px)');
    const updateViewport = event => { narrowViewport = event.matches; };
    media.addEventListener('change', updateViewport);

    const cleanupActions = registerActions({
      'contacts.next': {
        run: () => moveContact(1),
        isEnabled: () => !showingMobileProfile && contacts.length > 0 && !listLoading,
        disabledReason: 'Wait for a contact list',
      },
      'contacts.prev': {
        run: () => moveContact(-1),
        isEnabled: () => !showingMobileProfile && contacts.length > 0 && !listLoading,
        disabledReason: 'Wait for a contact list',
      },
      'contacts.open': {
        run: openFocusedContact,
        isEnabled: () => !showingMobileProfile && contacts.length > 0 && !listLoading,
        disabledReason: 'Select a contact first',
      },
      'contacts.email': {
        run: emailSelectedContact,
        isEnabled: () => Boolean(profile?.contact || selectedContact),
        disabledReason: 'Open a contact first',
      },
      'contacts.search': () => {
        searchInput?.focus({ preventScroll: true });
        searchInput?.select();
      },
      'contacts.back': {
        run: backToContactList,
        isEnabled: () => showingMobileProfile,
        disabledReason: 'Open a contact first',
      },
    });

    requestAnimationFrame(() => searchInput?.focus({ preventScroll: true }));
    return () => {
      cleanupActions();
      media.removeEventListener('change', updateViewport);
      sessionGuard?.dispose();
      sessionGuard = null;
      listGeneration += 1;
      profileGeneration += 1;
    };
  });

  onDestroy(() => {
    listGeneration += 1;
    profileGeneration += 1;
  });

  $effect(() => {
    const available = activeAccounts;
    if (available.length === 0) {
      contactAccountId = null;
      return;
    }
    if (available.some(account => Number(account.id) === Number(contactAccountId))) return;
    const preferred = available.find(account => Number(account.id) === Number($selectedAccountId)) || available[0];
    contactAccountId = Number(preferred.id);
    selectedAccountId.set(Number(preferred.id));
  });

  $effect(() => {
    const accountId = contactAccountId;
    const requestedQuery = query.trim();
    const requestedRelationship = relationship;
    const requestedPage = page;
    void listRetryVersion;
    if (!accountId || !sessionGuard?.isCurrent()) return undefined;

    const generation = ++listGeneration;
    const controller = new AbortController();
    const delay = requestedQuery ? 220 : 0;
    listLoading = true;
    listError = '';
    const timer = window.setTimeout(async () => {
      try {
        const payload = createContactQueryPayload({
          accountId,
          query: requestedQuery,
          relationship: requestedRelationship,
          page: requestedPage,
          pageSize: 50,
        });
        const response = await api.queryContacts(payload, { signal: controller.signal });
        if (controller.signal.aborted || generation !== listGeneration || !sessionGuard?.isCurrent()) return;
        const normalized = normalizeContactQueryResponse(response, { accountId });
        contacts = [...normalized.contacts];
        total = normalized.total;
        totalPages = normalized.total_pages;
        coverage = normalized.coverage;
        focusedIndex = contacts.length > 0 ? 0 : -1;
        if (selectedContactKey && !contacts.some(contact => contact.contact_key === selectedContactKey)) {
          resetListSelection();
        }
      } catch (error) {
        if (controller.signal.aborted || generation !== listGeneration || !sessionGuard?.isCurrent()) return;
        contacts = [];
        total = 0;
        totalPages = 0;
        coverage = null;
        listError = error?.message || 'Contacts could not be loaded.';
        resetListSelection();
      } finally {
        if (!controller.signal.aborted && generation === listGeneration && sessionGuard?.isCurrent()) {
          listLoading = false;
        }
      }
    }, delay);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  });

  $effect(() => {
    const accountId = contactAccountId;
    const contactKey = selectedContactKey;
    void profileRetryVersion;
    if (!accountId || !contactKey || !sessionGuard?.isCurrent()) {
      profile = null;
      profileLoading = false;
      profileError = '';
      return undefined;
    }

    const generation = ++profileGeneration;
    const controller = new AbortController();
    profileLoading = true;
    profileError = '';
    void (async () => {
      try {
        const payload = createContactProfilePayload({ accountId, contactKey, recentLimit: 8 });
        const response = await api.getContactProfile(payload, { signal: controller.signal });
        if (controller.signal.aborted || generation !== profileGeneration || !sessionGuard?.isCurrent()) return;
        profile = normalizeContactProfileResponse(response, { accountId, contactKey });
      } catch (error) {
        if (controller.signal.aborted || generation !== profileGeneration || !sessionGuard?.isCurrent()) return;
        profile = null;
        profileError = error?.message || 'This contact could not be loaded.';
      } finally {
        if (!controller.signal.aborted && generation === profileGeneration && sessionGuard?.isCurrent()) {
          profileLoading = false;
        }
      }
    })();

    return () => controller.abort();
  });
</script>

<div class="contacts-page h-full min-h-0 flex flex-col" style="background: var(--bg-primary)">
  <header class="contacts-header shrink-0 border-b px-5 py-4" style="border-color: var(--border-color); background: var(--bg-secondary)">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold" style="color: var(--text-primary)">Contacts</h1>
        <p class="mt-1 text-sm" style="color: var(--text-secondary)">
          People observed in one connected account's recent synchronized mail.
        </p>
      </div>
      <span class="min-h-11 inline-flex items-center rounded-full border px-3 text-xs" style="border-color: var(--border-color); color: var(--text-secondary)">
        Metadata only · no Contacts permission
      </span>
    </div>

    <div class="contacts-controls mt-4 grid gap-3">
      <label class="min-w-0 text-xs font-semibold" style="color: var(--text-secondary)">
        Account
        <select
          class="mt-1 min-h-11 w-full rounded-xl border px-3 text-sm"
          style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
          value={contactAccountId ?? ''}
          onchange={changeAccount}
          disabled={activeAccounts.length === 0}
        >
          {#each activeAccounts as account}
            <option value={account.id}>{accountLabel(account)} · {account.email}</option>
          {/each}
        </select>
      </label>
      <label class="min-w-0 text-xs font-semibold" style="color: var(--text-secondary)">
        Search
        <div class="relative mt-1">
          <Icon name="search" size={16} class="pointer-events-none absolute left-3 top-3.5" />
          <input
            bind:this={searchInput}
            class="min-h-11 w-full rounded-xl border py-2 pl-10 pr-3 text-sm"
            style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
            placeholder="Search name or email"
            aria-label="Search contacts"
            value={query}
            oninput={changeQuery}
            disabled={!contactAccountId}
            data-shortcut="contacts.search"
          />
        </div>
      </label>
      <label class="min-w-0 text-xs font-semibold" style="color: var(--text-secondary)">
        Relationship
        <select
          class="mt-1 min-h-11 w-full rounded-xl border px-3 text-sm"
          style="background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary)"
          value={relationship}
          onchange={changeRelationship}
          disabled={!contactAccountId}
        >
          {#each relationshipOptions as option}
            <option value={option.id}>{option.label}</option>
          {/each}
        </select>
      </label>
    </div>
  </header>

  <div class="contacts-workspace min-h-0 flex-1">
    <section
      class="contact-list-pane min-h-0 border-r"
      class:mobile-hidden={showingMobileProfile}
      style="border-color: var(--border-color); background: var(--bg-secondary)"
      aria-label="Contact list"
    >
      <div class="flex min-h-11 items-center justify-between border-b px-4" style="border-color: var(--border-color)">
        <span class="text-xs font-semibold uppercase tracking-wide" style="color: var(--text-tertiary)">{resultSummary()}</span>
        {#if listLoading && contacts.length > 0}
          <span role="status" class="text-xs" style="color: var(--text-secondary)">Updating…</span>
        {/if}
      </div>

      <div class="contact-list-scroll min-h-0 overflow-y-auto">
        {#if !contactAccountId}
          <div class="p-6 text-center">
            <Icon name="users" size={28} class="mx-auto mb-3" />
            <h2 class="font-semibold" style="color: var(--text-primary)">No connected account</h2>
            <p class="mt-1 text-sm" style="color: var(--text-secondary)">
              {$accountsLoadError || 'Connect an email account to discover correspondents.'}
            </p>
          </div>
        {:else if listLoading && contacts.length === 0}
          <div class="space-y-2 p-3" role="status" aria-label="Loading contacts">
            {#each Array(6) as _}
              <div class="min-h-16 animate-pulse rounded-xl" style="background: var(--bg-tertiary)"></div>
            {/each}
          </div>
        {:else if listError}
          <div class="p-6 text-center" role="alert">
            <Icon name="alert-circle" size={28} class="mx-auto mb-3" />
            <h2 class="font-semibold" style="color: var(--text-primary)">Contacts unavailable</h2>
            <p class="mt-1 text-sm" style="color: var(--text-secondary)">{listError}</p>
            <button type="button" class="mt-4 min-h-11 rounded-lg border px-4 text-sm font-semibold" style="border-color: var(--border-color)" onclick={retryList}>Retry</button>
          </div>
        {:else if contacts.length === 0}
          <div class="p-6 text-center">
            <Icon name="user-x" size={28} class="mx-auto mb-3" />
            <h2 class="font-semibold" style="color: var(--text-primary)">No correspondents found</h2>
            <p class="mt-1 text-sm" style="color: var(--text-secondary)">
              {query || relationship !== 'all'
                ? 'Try a different search or relationship filter.'
                : "This account's recent synchronized mail has no eligible correspondents yet."}
            </p>
          </div>
        {:else}
          <div role="listbox" aria-label="Contacts" aria-live="polite" class="p-2">
            {#each contacts as contact, index (contact.contact_key)}
              <button
                type="button"
                role="option"
                aria-selected={selectedContactKey === contact.contact_key}
                data-contact-index={index}
                tabindex={focusedIndex === index ? 0 : -1}
                class="contact-row min-h-16 w-full rounded-xl px-3 py-2 text-left"
                class:contact-row-active={selectedContactKey === contact.contact_key}
                onfocus={() => { focusedIndex = index; }}
                onclick={() => openContact(contact, index)}
              >
                <span class="flex min-w-0 items-center gap-3">
                  <span class="flex size-10 shrink-0 items-center justify-center rounded-full text-xs font-bold" aria-hidden="true" style="background: var(--bg-tertiary); color: var(--text-primary)">{contactInitials(contact)}</span>
                  <span class="min-w-0 flex-1">
                    <span class="block truncate text-sm font-semibold" style="color: var(--text-primary)">{contactDisplayName(contact)}</span>
                    <span class="block truncate text-xs" style="color: var(--text-secondary)">{contact.address}</span>
                    <span class="mt-0.5 block text-[11px]" style="color: var(--text-tertiary)">Last observed {formatContactObservedDate(contact.observed_last_at)}</span>
                  </span>
                </span>
              </button>
            {/each}
          </div>
        {/if}
      </div>

      {#if totalPages > 1}
        <div class="flex min-h-14 items-center justify-between border-t px-3" style="border-color: var(--border-color)">
          <button type="button" class="min-h-11 rounded-lg px-3 text-sm disabled:opacity-40" disabled={page <= 1 || listLoading} onclick={() => changePage(page - 1)}>Previous</button>
          <span class="text-xs" style="color: var(--text-secondary)">Page {page} of {totalPages}</span>
          <button type="button" class="min-h-11 rounded-lg px-3 text-sm disabled:opacity-40" disabled={page >= totalPages || listLoading} onclick={() => changePage(page + 1)}>Next</button>
        </div>
      {/if}
    </section>

    <section
      bind:this={profileRegion}
      class="contact-profile min-h-0 overflow-y-auto"
      class:mobile-hidden={narrowViewport && !selectedContactKey}
      aria-label="Contact profile"
      tabindex="-1"
    >
      {#if selectedContactKey}
        <div class="sticky top-0 z-10 flex min-h-14 items-center gap-2 border-b px-4 md:hidden" style="background: var(--bg-secondary); border-color: var(--border-color)">
          <button type="button" class="min-h-11 inline-flex items-center gap-2 rounded-lg px-2 text-sm font-semibold" onclick={backToContactList} data-shortcut="contacts.back">
            <Icon name="arrow-left" size={18} /> Back to contacts
          </button>
        </div>
      {/if}

      {#if !selectedContactKey}
        <div class="flex h-full min-h-80 items-center justify-center p-8 text-center">
          <div>
            <Icon name="user" size={32} class="mx-auto mb-3" />
            <h2 class="font-semibold" style="color: var(--text-primary)">Select a contact</h2>
            <p class="mt-1 max-w-sm text-sm" style="color: var(--text-secondary)">Review recent relationship metadata or start a message from the exact account.</p>
          </div>
        </div>
      {:else if profileLoading}
        <div class="p-6" role="status" aria-label="Loading contact profile">
          <div class="h-24 animate-pulse rounded-2xl" style="background: var(--bg-tertiary)"></div>
          <div class="mt-4 h-40 animate-pulse rounded-2xl" style="background: var(--bg-tertiary)"></div>
        </div>
      {:else if profileError}
        <div class="flex min-h-80 items-center justify-center p-8 text-center" role="alert">
          <div>
            <Icon name="alert-circle" size={30} class="mx-auto mb-3" />
            <h2 class="font-semibold" style="color: var(--text-primary)">Profile unavailable</h2>
            <p class="mt-1 text-sm" style="color: var(--text-secondary)">{profileError}</p>
            <button type="button" class="mt-4 min-h-11 rounded-lg border px-4 text-sm font-semibold" style="border-color: var(--border-color)" onclick={retryProfile}>Retry</button>
          </div>
        </div>
      {:else if profile}
        <div class="mx-auto w-full max-w-4xl p-5 md:p-7">
          <div class="rounded-2xl border p-5" style="background: var(--bg-secondary); border-color: var(--border-color)">
            <div class="flex flex-wrap items-start gap-4">
              <div class="flex size-14 shrink-0 items-center justify-center rounded-full text-base font-bold" aria-hidden="true" style="background: var(--bg-tertiary); color: var(--text-primary)">{contactInitials(profile.contact)}</div>
              <div class="min-w-0 flex-1">
                <h2 class="truncate text-xl font-semibold" style="color: var(--text-primary)">{contactDisplayName(profile.contact)}</h2>
                <p class="truncate text-sm" style="color: var(--text-secondary)">{profile.contact.address}</p>
                <p class="mt-1 text-xs" style="color: var(--text-tertiary)">{accountLabel(selectedAccount)} · relationship observed in recent mail</p>
              </div>
              <button type="button" class="min-h-11 inline-flex items-center gap-2 rounded-xl bg-accent-600 px-4 text-sm font-semibold text-white hover:bg-accent-700" onclick={emailSelectedContact} data-shortcut="contacts.email">
                <Icon name="edit-3" size={16} /> Email
              </button>
            </div>

            <dl class="contact-metrics mt-5 grid gap-3 border-t pt-4" style="border-color: var(--border-color)">
              <div><dt>Last observed</dt><dd>{formatContactObservedDate(profile.contact.observed_last_at)}</dd></div>
              <div><dt>Last received</dt><dd>{formatContactObservedDate(profile.contact.observed_last_received_at)}</dd></div>
              <div><dt>Last sent</dt><dd>{formatContactObservedDate(profile.contact.observed_last_sent_at)}</dd></div>
              <div><dt>Observed messages</dt><dd>{profile.contact.observed_message_count.toLocaleString()}</dd></div>
            </dl>
          </div>

          <section class="mt-5 rounded-2xl border" style="background: var(--bg-secondary); border-color: var(--border-color)" aria-labelledby="recent-contact-conversations">
            <div class="border-b px-5 py-4" style="border-color: var(--border-color)">
              <h3 id="recent-contact-conversations" class="font-semibold" style="color: var(--text-primary)">Recent conversations</h3>
              <p class="mt-1 text-xs" style="color: var(--text-secondary)">Metadata only. Open an item to load its exact account-owned thread.</p>
            </div>
            {#if profile.recent_conversations.length === 0}
              <p class="p-5 text-sm" style="color: var(--text-secondary)">No recent conversation pointers are available.</p>
            {:else}
              <div class="divide-y" style="border-color: var(--border-color)">
                {#each profile.recent_conversations as recent (`${recent.thread_id ?? ''}:${recent.anchor_email_id}`)}
                  <button type="button" class="min-h-14 w-full px-5 py-3 text-left hover:bg-[var(--bg-hover)]" onclick={() => openRecentConversation(recent)}>
                    <span class="flex items-center justify-between gap-3">
                      <span class="min-w-0">
                        <span class="block text-sm font-semibold" style="color: var(--text-primary)">{contactDirectionLabel(recent.direction)}</span>
                        <span class="block text-xs" style="color: var(--text-secondary)">{formatContactObservedDate(recent.observed_last_at, { includeTime: true })} · {recent.observed_message_count} {recent.observed_message_count === 1 ? 'message' : 'messages'}</span>
                      </span>
                      <Icon name="chevron-right" size={18} class="shrink-0" />
                    </span>
                  </button>
                {/each}
              </div>
            {/if}
          </section>

          {#if coverage}
            <p class="mt-4 rounded-xl border px-4 py-3 text-xs" style="background: var(--bg-secondary); border-color: var(--border-color); color: var(--text-secondary)">
              Based on {coverage.rows_scanned.toLocaleString()} recent synchronized messages from this account{coverage.history_may_be_truncated ? '; older relationships may not appear' : ''}.
            </p>
          {/if}
        </div>
      {/if}
    </section>
  </div>
</div>

<style>
  .contacts-controls {
    grid-template-columns: minmax(13rem, 0.9fr) minmax(15rem, 1.5fr) minmax(11rem, 0.7fr);
  }

  .contacts-workspace {
    display: grid;
    grid-template-columns: minmax(18rem, 23rem) minmax(0, 1fr);
  }

  .contact-list-pane {
    display: grid;
    grid-template-rows: auto minmax(0, 1fr) auto;
  }

  .contact-row:hover,
  .contact-row:focus-visible {
    background: var(--bg-hover);
  }

  .contact-row-active {
    background: color-mix(in srgb, var(--color-accent-500) 13%, transparent);
  }

  .contact-metrics {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }

  .contact-metrics dt {
    color: var(--text-tertiary);
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  .contact-metrics dd {
    margin-top: 0.2rem;
    color: var(--text-primary);
    font-size: 0.875rem;
    font-weight: 600;
  }

  @media (max-width: 900px) {
    .contacts-controls {
      grid-template-columns: 1fr 1fr;
    }

    .contacts-controls > :nth-child(2) {
      grid-column: span 2;
      grid-row: 1;
    }

    .contact-metrics {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }

  @media (max-width: 767px) {
    .contacts-header {
      padding: 0.875rem;
    }

    .contacts-controls {
      grid-template-columns: 1fr;
    }

    .contacts-controls > :nth-child(2) {
      grid-column: auto;
      grid-row: auto;
    }

    .contacts-workspace {
      display: block;
      overflow: hidden;
    }

    .contact-list-pane,
    .contact-profile {
      width: 100%;
      height: 100%;
    }

    .mobile-hidden {
      display: none;
    }
  }
</style>
