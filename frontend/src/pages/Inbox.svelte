<script>
  import { onDestroy, onMount, tick, untrack } from 'svelte';
  import { get } from 'svelte/store';
  import { api } from '../lib/api.js';
  import {
    emails, emailsLoading, emailsTotal, currentPageNum,
    currentMailbox, selectedEmailId, selectedAccountId,
    searchQuery, showToast, pageSize, viewMode, smartFilter,
    hideIgnored, sidebarCollapsed, createAuthenticatedSessionGuard,
    accounts, contactConversationIntent, labels as labelsStore,
  } from '../lib/stores.js';
  import { registerActions } from '../lib/shortcutStore.js';
  import { lastEvent } from '../lib/realtime.js';
  import {
    canActOnInboxEmails,
    createDatasetActionReconciler,
    createInitialDirectOpenGuard,
    createLatestRequestGuard,
    normalizeInboxDatasetSnapshot,
  } from '../lib/inboxDataset.js';
  import {
    actionPastTense,
    applyEmailAction,
    canUndoAction,
    captureInboxAction,
    createMailActionSubmissionQueue,
    idempotencyKey,
    isMailActionNetworkError,
    optimisticInboxAction,
    remainingUndoMs,
    rollbackEmailAction,
    rollbackThreadAction,
    restoreInboxAction,
  } from '../lib/mailActionUX.js';
  import {
    expandVisibleLabelTargets,
    isLabelAction,
    mergeLabelCatalog,
  } from '../lib/labelWorkflows.js';
  import {
    actionScopeForEmails,
    isConversationSummary,
    nextConversationFocus,
    normalizeConversationList,
  } from '../lib/conversationInbox.js';
  import {
    adjustInboxSectionTotals,
    combineInboxSections,
    isSplitInboxActive,
    mergeInboxSectionPages,
    nextInboxRowFocus,
    nextInboxSectionFocus,
    normalizeInboxSectionResult,
  } from '../lib/focusedInbox.js';
  import EmailList from '../components/email/EmailList.svelte';
  import EmailTable from '../components/email/EmailTable.svelte';
  import EmailView from '../components/email/EmailView.svelte';
  import ConversationView from '../components/email/ConversationView.svelte';
  import LabelPicker from '../components/email/LabelPicker.svelte';
  import MailActionStatus from '../components/email/MailActionStatus.svelte';
  import WorkingDrafts from '../components/email/WorkingDrafts.svelte';
  import EmailSearchSummary from '../components/email/EmailSearchSummary.svelte';
  import Icon from '../components/common/Icon.svelte';
  import SnoozePicker from '../components/common/SnoozePicker.svelte';
  import {
    buildSnoozeRequest,
    cancelAccepted,
    createSnoozeWithReconciliation,
    normalizeSnoozedList,
    partitionSnoozeConversation,
    reconcileActiveSnoozeEmails,
    rescheduleMatches,
    returnNowAccepted,
    runSnoozeMutationWithReconciliation,
    snoozeMatchesEmail,
  } from '../lib/snooze.js';
  import { focusEmailRow, focusEmailRowOrFallback } from '../lib/emailRowFocus.js';
  import { formatSnoozeWake } from '../lib/remindLater.js';
  import {
    contactConversationAnchorForAccount,
    normalizeContactConversationNavigationIntent,
  } from '../lib/contactProfiles.js';

  let selectedEmail = $state(null);
  let selectedThread = $state(null);
  let focusedEmailId = $state(null);
  let emailLoading = $state(false);
  let loadingMore = $state(false);
  let mounted = $state(false);
  let sessionGuard = null;
  let hasMore = $state(false);
  let datasetAuthoritative = $state(false);
  let datasetUpdating = $state(false);
  let datasetError = $state(false);
  let datasetErrorMessage = $state('');
  let actionReconciliationRequired = $state(false);
  let selectionEpoch = $state(0);
  let narrowViewport = $state(window.matchMedia('(max-width: 767px)').matches);
  let useTableLayout = $derived($viewMode === 'table' && !narrowViewport);
  let uncertainActions = $state(new Map());
  let checkingUncertainActions = $state(false);
  let showingPreviousResults = $derived(
    datasetError && !datasetAuthoritative && Boolean(committedDatasetKey) && $emails.length > 0
  );
  let resultsMailbox = $derived(
    $smartFilter?.type === 'snoozed' ? 'SNOOZED' : ($searchQuery ? 'ALL' : $currentMailbox)
  );
  let moveAvailable = $derived(
    !$searchQuery && !$smartFilter && $currentMailbox === 'INBOX'
  );
  let selectedListConversation = $derived(
    $emails.find(email => Number(email.id) === Number($selectedEmailId)) || null
  );
  let selectedReaderUsesThread = $derived(
    Array.isArray(selectedThread?.emails) && selectedThread.emails.length > 0
  );
  let selectedReaderConversation = $derived(
    isConversationSummary(selectedListConversation)
      ? selectedListConversation
      : (selectedReaderUsesThread && selectedEmail
        ? {
            ...selectedEmail,
            id: Number(selectedEmail.id),
            account_id: Number(selectedEmail.account_id),
            anchor_email_id: Number(selectedEmail.id),
            conversation_key: `${Number(selectedEmail.account_id)}:${String(selectedThread?.thread_id || `message:${selectedEmail.id}`)}`,
            member_count: selectedThread.emails.length,
            matched_count: 1,
            unread_count: selectedThread.emails.filter(message => !message.is_read).length,
            conversation_scope: false,
          }
        : null)
  );

  const listRequests = createLatestRequestGuard();
  const emailRequests = createLatestRequestGuard();
  const initialDirectOpen = createInitialDirectOpenGuard();
  const actionSubmissions = createMailActionSubmissionQueue();
  const acceptedActionReconciler = createDatasetActionReconciler({
    isCurrent: datasetKey => inboxSessionIsCurrent()
      && (Boolean(get(searchQuery)) || actionReconciliationRequired)
      && currentDatasetSnapshot().key === datasetKey,
    refresh: () => refreshDataset(),
  });
  let requestedDatasetKey = null;
  let committedDatasetKey = null;
  let latestUndo = null;
  let uncertainActionTimer = null;
  let actionReconciliationVersion = 0;
  let committedDatasetSnapshot = null;
  let emailViewTransitionGuard = null;
  let snoozeTarget = $state(null);
  let snoozeBusyIds = $state(new Set());
  let labelPicker = $state(null);
  let focusSectionTotals = $state(null);
  let pendingActionRestoreFocus = null;

  function registerEmailViewTransitionGuard(guard) {
    emailViewTransitionGuard = typeof guard === 'function' ? guard : null;
  }

  async function canLeaveSelectedEmail() {
    if (!emailViewTransitionGuard) return true;
    return (await emailViewTransitionGuard()) !== false;
  }

  function selectedActionEnabled() {
    return inboxSessionIsCurrent()
      && datasetAuthoritative
      && Boolean(actionTargetId());
  }

  function actionTargetId() {
    return get(selectedEmailId) || focusedEmailId;
  }

  function selectedActionUnavailable() {
    return datasetUpdating
      ? 'Wait for the current inbox results'
      : 'Select an email first';
  }

  function restoreCommittedDatasetControls() {
    const snapshot = committedDatasetSnapshot;
    if (!snapshot) return;
    requestedDatasetKey = snapshot.key;
    currentMailbox.set(snapshot.mailbox);
    selectedAccountId.set(snapshot.accountId);
    searchQuery.set(snapshot.search);
    smartFilter.set(snapshot.smartFilter);
    hideIgnored.set(snapshot.hideIgnored);
    pageSize.set(snapshot.pageSize);
    currentPageNum.set(snapshot.page);
  }

  // Resizable panel splits (persisted)
  let columnListWidth = $state(parseInt(localStorage.getItem('columnListWidth') || '380', 10));
  let tableTopPct = $state(parseInt(localStorage.getItem('tableTopPct') || '45', 10));
  let panelDragging = $state(false);
  let containerEl = $state(null);

  onMount(() => {
    sessionGuard = createAuthenticatedSessionGuard();
    mounted = sessionGuard.isCurrent();
    const narrowViewportQuery = window.matchMedia('(max-width: 767px)');
    const updateNarrowViewport = () => {
      narrowViewport = narrowViewportQuery.matches;
    };
    updateNarrowViewport();
    narrowViewportQuery.addEventListener('change', updateNarrowViewport);

    // Register keyboard shortcut actions for the inbox
    const cleanupShortcuts = registerActions({
      'inbox.next': {
        run: () => navigateEmails(1),
        isEnabled: () => datasetAuthoritative && get(emails).length > 0,
        disabledReason: 'No email results are available',
      },
      'inbox.prev': {
        run: () => navigateEmails(-1),
        isEnabled: () => datasetAuthoritative && get(emails).length > 0,
        disabledReason: 'No email results are available',
      },
      'inbox.archive': {
        run: () => handleAction('archive', [actionTargetId()]),
        isEnabled: selectedActionEnabled,
        disabledReason: selectedActionUnavailable,
      },
      'inbox.trash': {
        run: () => handleAction('trash', [actionTargetId()]),
        isEnabled: selectedActionEnabled,
        disabledReason: selectedActionUnavailable,
      },
      'inbox.star': {
        run: () => {
          const emailId = actionTargetId();
          const target = get(emails).find(email => email.id === emailId) || selectedEmail;
          return handleAction(target?.is_starred ? 'unstar' : 'star', [emailId]);
        },
        isEnabled: selectedActionEnabled,
        disabledReason: selectedActionUnavailable,
      },
      'inbox.read': {
        run: () => handleAction('mark_read', [actionTargetId()]),
        isEnabled: selectedActionEnabled,
        disabledReason: selectedActionUnavailable,
      },
      'inbox.unread': {
        run: () => handleAction('mark_unread', [actionTargetId()]),
        isEnabled: selectedActionEnabled,
        disabledReason: selectedActionUnavailable,
      },
      'inbox.spam': {
        run: () => handleAction('spam', [actionTargetId()]),
        isEnabled: selectedActionEnabled,
        disabledReason: selectedActionUnavailable,
      },
      'inbox.snooze': {
        run: () => openSnoozePicker(actionTargetId()),
        isEnabled: selectedActionEnabled,
        disabledReason: selectedActionUnavailable,
      },
      'inbox.label': {
        run: () => openLabelPicker('apply', [actionTargetId()]),
        isEnabled: selectedActionEnabled,
        disabledReason: selectedActionUnavailable,
      },
      'inbox.viewMode': () => {
        const current = get(viewMode);
        const next = current === 'table' ? 'column' : 'table';
        viewMode.set(next);
        localStorage.setItem('viewMode', next);
      },
      'inbox.sidebar': () => {
        sidebarCollapsed.update(v => !v);
      },
      'inbox.focused': {
        run: () => hideIgnored.update(value => !value),
        isEnabled: () => moveAvailable,
        disabledReason: 'Split Inbox is available in the standard Inbox',
      },
      'inbox.nextSection': {
        run: () => navigateInboxSection(1),
        isEnabled: () => Boolean(focusSectionTotals && get(emails).length > 0),
        disabledReason: 'Split Inbox is not active',
      },
      'inbox.prevSection': {
        run: () => navigateInboxSection(-1),
        isEnabled: () => Boolean(focusSectionTotals && get(emails).length > 0),
        disabledReason: 'Split Inbox is not active',
      },
      'inbox.undo': {
        run: runLatestUndo,
        isEnabled: () => Boolean(latestUndo && latestUndo.expiresAt > Date.now()),
        disabledReason: 'There is no email action available to undo',
      },
      'inbox.open': {
        run: () => openFocusedEmail(),
        isEnabled: () => datasetAuthoritative && Boolean(actionTargetId()),
        disabledReason: 'Focus a conversation first',
      },
      'inbox.close': {
        run: () => closeSelectedEmail(),
        isEnabled: () => Boolean(get(selectedEmailId)),
        disabledReason: 'No conversation is open',
      },
    });

    return () => {
      cleanupShortcuts();
      narrowViewportQuery.removeEventListener('change', updateNarrowViewport);
    };
  });

  $effect(() => {
    if (!moveAvailable) return undefined;
    return registerActions({
      'inbox.move': {
        run: () => openLabelPicker('move', [actionTargetId()]),
        isEnabled: selectedActionEnabled,
        disabledReason: selectedActionUnavailable,
      },
    });
  });

  onDestroy(() => {
    // Requests are guarded per component instance. Invalidate them before this
    // instance disappears so a late response cannot write into the shared
    // inbox stores after a newly mounted Inbox has committed newer results.
    mounted = false;
    sessionGuard?.dispose();
    sessionGuard = null;
    listRequests.invalidate();
    emailRequests.invalidate();
    acceptedActionReconciler.dispose();
    selectionEpoch += 1;
    latestUndo = null;
    if (uncertainActionTimer !== null) window.clearInterval(uncertainActionTimer);
    uncertainActionTimer = null;
    for (const pending of uncertainActions.values()) pending.releaseQueue();
    uncertainActions = new Map();
    datasetAuthoritative = false;
    labelPicker = null;
    datasetUpdating = false;
    emailViewTransitionGuard = null;
    snoozeTarget = null;
    snoozeBusyIds = new Set();
    selectedEmailId.set(null);
    selectedEmail = null;
    selectedThread = null;
    focusedEmailId = null;
    pendingActionRestoreFocus = null;
    emailLoading = false;
    loadingMore = false;
    focusSectionTotals = null;
    emailsLoading.set(false);
  });

  async function navigateEmails(direction) {
    if (!inboxSessionIsCurrent() || !datasetAuthoritative) return;
    const list = get(emails);
    if (!list || list.length === 0) return;
    const currentId = focusedEmailId || get(selectedEmailId);
    const currentIdx = list.findIndex(e => e.id === currentId);
    let nextIdx;
    if (currentIdx === -1) {
      nextIdx = direction > 0 ? 0 : list.length - 1;
    } else {
      nextIdx = currentIdx + direction;
    }
    if (nextIdx >= 0 && nextIdx < list.length) {
      const nextId = list[nextIdx].id;
      focusedEmailId = nextId;
      if (get(selectedEmailId)) {
        await handleSelect(nextId);
      } else {
        queueMicrotask(() => focusEmailRow(document.querySelector('.inbox-page'), nextId));
      }
    }
  }

  async function navigateInboxSection(direction) {
    if (!inboxSessionIsCurrent() || !datasetAuthoritative || !focusSectionTotals) return;
    const nextId = nextInboxSectionFocus(
      get(emails),
      focusedEmailId || get(selectedEmailId),
      direction,
    );
    if (nextId == null) return;
    focusedEmailId = nextId;
    if (get(selectedEmailId)) {
      await handleSelect(nextId);
    } else {
      queueMicrotask(() => focusEmailRow(document.querySelector('.inbox-page'), nextId));
    }
  }

  $effect(() => {
    const snapshot = normalizeInboxDatasetSnapshot({
      mailbox: $currentMailbox,
      accountId: $selectedAccountId,
      search: $searchQuery,
      smartFilter: $smartFilter,
      hideIgnored: $hideIgnored,
      pageSize: $pageSize,
      page: 1,
    });

    if (!inboxSessionIsCurrent()) return;
    if (snapshot.key === requestedDatasetKey) return;
    requestedDatasetKey = snapshot.key;
    currentPageNum.set(1);
    untrack(() => { loadEmails(false, snapshot); });
  });

  $effect(() => {
    const eid = $selectedEmailId;
    const canLoad = datasetAuthoritative;
    emailRequests.invalidate();
    if (eid && canLoad) {
      untrack(() => { loadEmail(eid); });
    } else {
      selectedEmail = null;
      selectedThread = null;
      emailLoading = false;
    }
  });

  $effect(() => {
    const evt = $lastEvent;
    if (!evt || !inboxSessionIsCurrent()) return;
    if (evt.type === 'new_emails' || evt.type === 'emails_updated' || evt.type === 'snooze_updated') {
      untrack(() => { refreshDataset(); });
    }
  });

  function currentDatasetSnapshot(page = get(currentPageNum)) {
    return normalizeInboxDatasetSnapshot({
      mailbox: get(currentMailbox),
      accountId: get(selectedAccountId),
      search: get(searchQuery),
      smartFilter: get(smartFilter),
      hideIgnored: get(hideIgnored),
      pageSize: get(pageSize),
      page,
    });
  }

  function browserTimezone() {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    } catch {
      return 'UTC';
    }
  }

  function invalidateInboxSelection() {
    selectionEpoch += 1;
    selectedEmailId.set(null);
    selectedEmail = null;
    selectedThread = null;
    focusedEmailId = null;
    emailRequests.invalidate();
    emailLoading = false;
  }

  function inboxSessionIsCurrent() {
    return mounted && Boolean(sessionGuard?.isCurrent());
  }

  function listRequestIsCurrent(requestId) {
    return inboxSessionIsCurrent() && listRequests.isCurrent(requestId);
  }

  function pendingContactAnchorEmailId(accountId) {
    try {
      return contactConversationAnchorForAccount(get(contactConversationIntent), accountId);
    } catch {
      contactConversationIntent.set(null);
      return null;
    }
  }

  function refreshDataset() {
    if (!inboxSessionIsCurrent()) return Promise.resolve(false);
    currentPageNum.set(1);
    return loadEmails(false, currentDatasetSnapshot(1));
  }

  async function loadEmails(append, snapshot = currentDatasetSnapshot()) {
    if (!inboxSessionIsCurrent()) return false;
    if (
      !append
      && committedDatasetSnapshot
      && snapshot.key !== committedDatasetSnapshot.key
      && !(await canLeaveSelectedEmail())
    ) {
      restoreCommittedDatasetControls();
      return false;
    }
    const actionReconciliationVersionAtStart = actionReconciliationVersion;
    const requestId = listRequests.begin();
    if (append) {
      loadingMore = true;
    } else {
      // A source screen may set selectedEmailId before this lazy component
      // mounts. Hold that one-time navigation intent across the normal
      // selection reset, then restore it only after trusted results commit.
      initialDirectOpen.capture(get(selectedEmailId));
      datasetAuthoritative = false;
      datasetUpdating = true;
      datasetError = false;
      datasetErrorMessage = '';
      emailsLoading.set(true);
      loadingMore = false;
      invalidateInboxSelection();
    }

    try {
      const sf = snapshot.smartFilter;
      let result;
      let resultUsesConversations = false;

      if (sf && sf.type === 'needs_reply_ignored') {
        const paginationParams = { page: snapshot.page, page_size: snapshot.pageSize };
        result = await api.getNeedsReplyIgnored(paginationParams);
      } else if (sf && sf.type === 'needs_reply_snoozed') {
        const paginationParams = { page: snapshot.page, page_size: snapshot.pageSize };
        result = await api.getNeedsReplySnoozed(paginationParams);
      } else if (sf && sf.type === 'snoozed') {
        const payload = await api.listSnoozes({
          state: 'active',
          limit: snapshot.pageSize,
          offset: (snapshot.page - 1) * snapshot.pageSize,
        });
        result = normalizeSnoozedList(payload);
      } else {
        const params = {
          mailbox: snapshot.mailbox,
          page: snapshot.page,
          page_size: snapshot.pageSize,
        };
        const acctId = snapshot.accountId;
        if (acctId) params.account_id = acctId;
        const sq = snapshot.search;
        if (sq) {
          params.search = sq;
          params.tz = browserTimezone();
        }
        if (sf) {
          if (sf.type === 'needs_reply') {
            params.needs_reply = true;
          } else if (sf.type === 'ai_category') {
            params.ai_category = sf.value;
          } else if (sf.type === 'ai_email_type') {
            params.ai_email_type = sf.value;
          }
        }
        const useConversations = Boolean(snapshot.search)
          || (!sf && snapshot.mailbox !== 'DRAFTS');
        resultUsesConversations = useConversations;
        if (isSplitInboxActive(snapshot)) {
          const sectionPageSize = Math.max(1, Math.ceil(snapshot.pageSize / 2));
          const sectionParams = { ...params, page_size: sectionPageSize };
          const splitPayload = await api.listConversationSplit(sectionParams);
          const focused = normalizeInboxSectionResult(
            normalizeConversationList(splitPayload?.focused),
            'focused',
          );
          const other = normalizeInboxSectionResult(
            normalizeConversationList(splitPayload?.other),
            'other',
          );
          result = combineInboxSections(focused, other);
          if (Number(splitPayload?.total) !== result.total) {
            throw new Error('Split Inbox totals did not match the coherent response');
          }
          resultUsesConversations = true;
        } else {
          result = useConversations
            ? normalizeConversationList(await api.listConversations(params))
            : await api.listEmails(params);
        }
      }

      const activeSnoozesExcludedByServer = !sf
        && !snapshot.search
        && snapshot.mailbox === 'INBOX'
        && resultUsesConversations;
      const reconcileActiveSnoozes = sf?.type !== 'snoozed' && !activeSnoozesExcludedByServer;
      if (reconcileActiveSnoozes) {
        const active = await api.listSnoozes({ state: 'active', limit: 200, offset: 0 });
        const activeItems = active.items || [];
        const retain = !sf && (Boolean(snapshot.search) || snapshot.mailbox !== 'INBOX');
        const reconciled = reconcileActiveSnoozeEmails(result.emails, activeItems, { retain });
        result = { ...result, emails: reconciled.emails };
        if (!retain) {
          result.total = Math.max(0, Number(result.total || 0) - reconciled.matchedCount);
        }
      }

      if (!listRequestIsCurrent(requestId)) return false;

      if (append) {
        emails.update(existing => {
          if (result.sectionTotals) {
            return mergeInboxSectionPages(existing, result.emails);
          }
          const existingIds = new Set(existing.map(email => email.id));
          return [
            ...existing,
            ...result.emails.filter(email => !existingIds.has(email.id)),
          ];
        });
      } else {
        emails.set(result.emails);
        committedDatasetKey = snapshot.key;
        committedDatasetSnapshot = snapshot;
        if (actionReconciliationVersionAtStart === actionReconciliationVersion) {
          actionReconciliationRequired = false;
        }
        datasetAuthoritative = !actionReconciliationRequired;
        datasetError = false;
        datasetErrorMessage = '';
        const initialDirectOpenEmailId = initialDirectOpen.commit(datasetAuthoritative);
        // Contacts owns a one-shot, exact-account reader intent. Restore its
        // anchor only after this Inbox dataset is authoritative so a cold lazy
        // mount cannot erase the selection before the detail request begins.
        const contactDirectOpenEmailId = pendingContactAnchorEmailId(snapshot.accountId);
        const directOpenEmailId = contactDirectOpenEmailId ?? initialDirectOpenEmailId;
        if (directOpenEmailId !== null) {
          focusedEmailId = directOpenEmailId;
          selectedEmailId.set(directOpenEmailId);
        }
        if (pendingActionRestoreFocus) {
          const pending = pendingActionRestoreFocus;
          pendingActionRestoreFocus = null;
          if (pending.datasetKey === snapshot.key) {
            const restored = result.emails.find(email =>
              (pending.conversationKey
                && email.conversation_key === pending.conversationKey)
              || Number(email.id) === Number(pending.emailId));
            const focusStillOwned = [
              pending.expectedFocusedId,
              pending.emailId,
              null,
            ].some(value => Number(value) === Number(focusedEmailId)
              || (value === null && focusedEmailId === null));
            if (restored && focusStillOwned) {
              focusedEmailId = restored.id;
              if (pending.restoreSelection) selectedEmailId.set(restored.id);
              await tick();
              if (listRequestIsCurrent(requestId)
                && focusedEmailId === restored.id) {
                focusInboxSelection();
              }
            }
          }
        }
      }
      focusSectionTotals = result.sectionTotals || null;
      emailsTotal.set(result.total);
      hasMore = typeof result.hasMore === 'boolean'
        ? result.hasMore
        : (snapshot.page * snapshot.pageSize) < result.total;
      return true;
    } catch (err) {
      if (!listRequestIsCurrent(requestId)) return false;
      if (err.message !== 'Unauthorized' && !snapshot.search) showToast(err.message, 'error');
      if (!append) {
        datasetError = true;
        datasetErrorMessage = err.message || 'Search request failed';
        if (committedDatasetKey === snapshot.key) {
          datasetAuthoritative = !actionReconciliationRequired;
        }
      }
      return false;
    } finally {
      if (listRequestIsCurrent(requestId)) {
        if (!append) {
          emailsLoading.set(false);
          datasetUpdating = false;
        }
        loadingMore = false;
      }
    }
  }

  async function handleRestoreFromIgnored(emailId) {
    if (!canActOnEmails([emailId])) return;
    if (get(selectedEmailId) === emailId && !(await canLeaveSelectedEmail())) return;
    const actionEpoch = selectionEpoch;
    try {
      await api.unignoreNeedsReply(emailId);
      if (!inboxSessionIsCurrent() || actionEpoch !== selectionEpoch) return;
      showToast('Restored to needs reply', 'success');
      emails.update(list => list.filter(e => e.id !== emailId));
      emailsTotal.update(t => Math.max(0, t - 1));
      if (get(selectedEmailId) === emailId) {
        selectedEmailId.set(null);
        selectedEmail = null;
      }
    } catch (err) {
      if (inboxSessionIsCurrent() && actionEpoch === selectionEpoch) showToast(err.message, 'error');
    }
  }

  async function handleRestoreFromSnoozed(emailId) {
    if (!canActOnEmails([emailId])) return;
    if (get(selectedEmailId) === emailId && !(await canLeaveSelectedEmail())) return;
    const actionEpoch = selectionEpoch;
    try {
      await api.unsnoozeNeedsReply(emailId);
      if (!inboxSessionIsCurrent() || actionEpoch !== selectionEpoch) return;
      showToast('Unsnooze — restored to needs reply', 'success');
      emails.update(list => list.filter(e => e.id !== emailId));
      emailsTotal.update(t => Math.max(0, t - 1));
      if (get(selectedEmailId) === emailId) {
        selectedEmailId.set(null);
        selectedEmail = null;
      }
    } catch (err) {
      if (inboxSessionIsCurrent() && actionEpoch === selectionEpoch) showToast(err.message, 'error');
    }
  }

  async function handleLoadMore() {
    if (!datasetAuthoritative || datasetUpdating || loadingMore || !hasMore) return;
    const previousPage = get(currentPageNum);
    const nextPage = previousPage + 1;
    currentPageNum.set(nextPage);
    const loaded = await loadEmails(true, currentDatasetSnapshot(nextPage));
    if (!loaded && inboxSessionIsCurrent() && get(currentPageNum) === nextPage) {
      currentPageNum.set(previousPage);
    }
  }

  async function loadEmail(id) {
    const requestId = emailRequests.begin();
    emailLoading = true;
    selectedEmail = null;
    selectedThread = null;
    let exactContactIntent = null;
    try {
      const pendingContactIntent = get(contactConversationIntent);
      if (pendingContactIntent !== null) {
        exactContactIntent = normalizeContactConversationNavigationIntent(pendingContactIntent);
        if (exactContactIntent.anchor_email_id !== Number(id)) exactContactIntent = null;
      }
      if (
        exactContactIntent
        && Number(get(selectedAccountId)) !== exactContactIntent.account_id
      ) {
        throw new Error('The contact conversation account no longer matches the active account.');
      }

      const summary = get(emails).find(email => email.id === id);
      const conversation = isConversationSummary(summary);
      const threadId = String(summary?.gmail_thread_id || '').trim();
      const result = exactContactIntent?.thread_id
        ? await api.getThread(exactContactIntent.thread_id, 'asc', exactContactIntent.account_id)
        : (exactContactIntent
          ? await api.getEmail(id)
          : (conversation && threadId
            ? await api.getThread(threadId, 'asc', summary.account_id)
            : await api.getEmail(id)));
      if (!isCurrentEmailRequest(requestId, id)) return;

      if (exactContactIntent?.thread_id) {
        const messages = Array.isArray(result?.emails) ? result.emails : [];
        if (
          messages.length === 0
          || messages.some(message => Number(message?.account_id) !== exactContactIntent.account_id)
        ) {
          throw new Error('The contact conversation response did not match its account.');
        }
        const anchor = messages.find(message => Number(message.id) === exactContactIntent.anchor_email_id);
        if (!anchor) throw new Error('The contact conversation did not contain its exact anchor message.');
        selectedThread = result;
        selectedEmail = anchor;
      } else if (exactContactIntent) {
        if (Number(result?.account_id) !== exactContactIntent.account_id || Number(result?.id) !== exactContactIntent.anchor_email_id) {
          throw new Error('The contact message response did not match its account and anchor.');
        }
        selectedThread = null;
        selectedEmail = result;
      } else {
        selectedThread = conversation
          ? (threadId ? result : { thread_id: '', emails: [result] })
          : null;
        const detail = conversation
          ? (selectedThread.emails || []).find(message => Number(message.id) === Number(summary.anchor_email_id))
            || selectedThread.emails?.[selectedThread.emails.length - 1]
            || null
          : result;
        selectedEmail = summary?.snooze_id && detail
          ? {
              ...detail,
              snooze_id: summary.snooze_id,
              snooze_wake_at: summary.snooze_wake_at,
              snooze_time_zone: summary.snooze_time_zone,
              snooze_condition: summary.snooze_condition,
              snooze_origin: summary.snooze_origin,
              snooze_state: summary.snooze_state,
            }
          : detail;
      }
      if (exactContactIntent ? !selectedEmail?.is_read : (conversation ? Number(summary.unread_count) > 0 : !selectedEmail?.is_read)) {
        // Rendering the message must never wait for a mailbox mutation. The
        // durable action path owns retries and exposes any terminal failure.
        void handleAction('mark_read', [id], { announce: false, offerUndo: false });
      }
    } catch (err) {
      if (isCurrentEmailRequest(requestId, id)) showToast(err.message, 'error');
    } finally {
      if (exactContactIntent) {
        const pending = get(contactConversationIntent);
        if (
          Number(pending?.account_id) === exactContactIntent.account_id
          && Number(pending?.anchor_email_id) === exactContactIntent.anchor_email_id
          && (pending?.thread_id ?? null) === exactContactIntent.thread_id
        ) contactConversationIntent.set(null);
      }
      if (inboxSessionIsCurrent() && emailRequests.isCurrent(requestId)) emailLoading = false;
    }
  }

  function isCurrentEmailRequest(requestId, emailId) {
    return inboxSessionIsCurrent()
      && emailRequests.isCurrent(requestId)
      && datasetAuthoritative
      && get(selectedEmailId) === emailId;
  }

  async function handleSelect(emailId) {
    if (!inboxSessionIsCurrent() || !datasetAuthoritative) return;
    if (!get(emails).some(email => email.id === emailId)) return;
    if (get(selectedEmailId) !== emailId && !(await canLeaveSelectedEmail())) return;
    focusedEmailId = emailId;
    selectedEmailId.set(emailId);
  }

  async function openFocusedEmail() {
    const emailId = actionTargetId();
    if (!emailId) return;
    await handleSelect(emailId);
  }

  function handleRowFocus(emailId) {
    if (get(emails).some(email => Number(email.id) === Number(emailId))) {
      focusedEmailId = emailId;
    }
  }

  async function closeSelectedEmail() {
    if (!(await canLeaveSelectedEmail())) return;
    const returnId = focusedEmailId || get(selectedEmailId);
    selectedEmailId.set(null);
    selectedEmail = null;
    selectedThread = null;
    queueMicrotask(() => {
      if (!focusEmailRow(document.querySelector('.inbox-page'), returnId)) {
        document.querySelector('[data-inbox-focus-fallback]')?.focus?.();
      }
    });
  }

  function canActOnEmails(emailIds, notify = true) {
    const canAct = canActOnInboxEmails({
      authoritative: inboxSessionIsCurrent() && datasetAuthoritative,
      emailIds,
      visibleEmailIds: get(emails).map(email => email.id),
      selectedEmailId: get(selectedEmailId),
      selectedDetailId: selectedEmail?.id ?? null,
    });

    if (!canAct && notify) {
      showToast('Wait for the current inbox results before applying actions', 'info');
    }
    return canAct;
  }

  function actionContextIsCurrent(actionEpoch, datasetKey) {
    return inboxSessionIsCurrent()
      && actionEpoch === selectionEpoch
      && datasetAuthoritative
      && currentDatasetSnapshot().key === datasetKey;
  }

  function restoreOptimisticAction({
    action,
    snapshot,
    optimistic,
    detailBefore,
    threadBefore,
    removedCount,
    gmailLabelId,
    focusedBefore,
    sectionTotalsBefore,
    hasMoreBefore,
  }) {
    emails.update(current => restoreInboxAction(
      current,
      snapshot,
      action,
      optimistic.removed,
      { gmailLabelId },
    ));
    if (removedCount > 0) emailsTotal.update(total => total + removedCount);
    focusSectionTotals = sectionTotalsBefore;
    hasMore = hasMoreBefore;
    if (get(selectedEmailId) === optimistic.selectedId) {
      selectedEmailId.set(snapshot.selectedId);
    }
    if (detailBefore && selectedEmail?.id === detailBefore.id) {
      selectedEmail = rollbackEmailAction(selectedEmail, detailBefore, action, { gmailLabelId });
    }
    if (threadBefore && get(selectedEmailId) === snapshot.selectedId) {
      selectedThread = rollbackThreadAction(
        selectedThread,
        threadBefore,
        action,
        { gmailLabelId },
      );
    }
    focusedEmailId = focusedBefore;
    void tick().then(() => {
      if (inboxSessionIsCurrent() && focusedEmailId === focusedBefore) {
        focusInboxSelection();
      }
    });
  }

  async function submitMailAction(emailIds, action, requestKey, labelId = null, scope = null) {
    try {
      return await api.emailActions(emailIds, action, requestKey, labelId, scope);
    } catch (err) {
      // A lost response is ambiguous. Replaying once with the same key is safe
      // and lets the server return the original accepted operation.
      if (!isMailActionNetworkError(err)) throw err;
      try {
        return await api.emailActions(emailIds, action, requestKey, labelId, scope);
      } catch (retryError) {
        if (!isMailActionNetworkError(retryError)) throw retryError;
        try {
          return await api.getMailActionByIdempotency(requestKey);
        } catch (lookupError) {
          const unknownError = new Error('The email action was sent, but its status is not confirmed yet');
          unknownError.code = 'mail_action_outcome_unknown';
          unknownError.lookupError = lookupError;
          throw unknownError;
        }
      }
    }
  }

  function actionDisplayCount(context, operation = null) {
    if (context.scope === 'conversations') return context.snapshot.items.length;
    const acceptedCount = Number(operation?.accepted_count);
    return isLabelAction(context.action) && Number.isFinite(acceptedCount)
      ? acceptedCount
      : context.emailIds.length;
  }

  function acceptMailAction(context, operation, announce, offerUndo) {
    // Definitive actions always reconcile their still-current structured
    // search. This is intentionally independent of selectionEpoch: an earlier
    // refresh can invalidate presentation state while a queued action accepts.
    requireActionReconciliation(context.datasetKey, context.optimistic.removed);
    if (!actionContextIsCurrent(context.actionEpoch, context.datasetKey)) return;
    if (!announce) return;

    const displayCount = actionDisplayCount(context, operation);
    const undoMs = offerUndo && canUndoAction(operation) ? remainingUndoMs(operation.undo_until) : 0;
    if (undoMs > 0) {
      const undoContext = { ...context, operation };
      let undoPromise = null;
      const runUndo = () => {
        if (!undoPromise) {
          undoPromise = undoAcceptedAction(undoContext).finally(() => {
            undoPromise = null;
          });
        }
        return undoPromise;
      };
      latestUndo = {
        requestId: operation.request_id,
        expiresAt: Date.parse(operation.undo_until),
        run: runUndo,
      };
      showToast(actionPastTense(context.action, displayCount, context.labelName, context.scope === 'conversations' ? 'conversation' : 'email'), 'success', undoMs, {
        actionLabel: 'Undo',
        onAction: latestUndo.run,
        dismissLabel: 'Dismiss action confirmation',
      });
    } else {
      showToast(actionPastTense(context.action, displayCount, context.labelName, context.scope === 'conversations' ? 'conversation' : 'email'), 'success');
    }
  }

  function requireActionReconciliation(datasetKey, force = false) {
    if (
      !inboxSessionIsCurrent()
      || (!force && !get(searchQuery))
      || currentDatasetSnapshot().key !== datasetKey
    ) return;
    actionReconciliationRequired = true;
    actionReconciliationVersion += 1;
    void acceptedActionReconciler.request(datasetKey);
  }

  function scheduleUncertainActionChecks() {
    if (uncertainActionTimer !== null || uncertainActions.size === 0) return;
    uncertainActionTimer = window.setInterval(() => {
      void reconcileUncertainActions();
    }, 3_000);
  }

  function stopUncertainActionChecksIfIdle() {
    if (uncertainActions.size > 0 || uncertainActionTimer === null) return;
    window.clearInterval(uncertainActionTimer);
    uncertainActionTimer = null;
  }

  async function reconcileUncertainActions() {
    if (!inboxSessionIsCurrent() || checkingUncertainActions || uncertainActions.size === 0) return;
    checkingUncertainActions = true;
    try {
      for (const [requestKey, pending] of [...uncertainActions]) {
        try {
          // Re-submit the same logical operation until POST itself returns a
          // definitive result. A GET 404 cannot prove that an earlier lost
          // POST is not still queued behind a database lock.
          const operation = await api.emailActions(
            pending.context.emailIds,
            pending.context.action,
            requestKey,
            pending.context.labelId,
            pending.context.scope,
          );
          if (!inboxSessionIsCurrent()) return;
          const next = new Map(uncertainActions);
          if (next.get(requestKey) === pending) {
            next.delete(requestKey);
            uncertainActions = next;
            pending.releaseQueue();
          }
          acceptMailAction(pending.context, operation, pending.announce, pending.offerUndo);
        } catch {
          // Keep the optimistic projection explicitly pending. Reusing the
          // same idempotency key cannot duplicate an accepted operation.
        }
      }
      stopUncertainActionChecksIfIdle();
    } finally {
      checkingUncertainActions = false;
    }
  }

  async function undoAcceptedAction(context) {
    try {
      const operation = await api.undoMailAction(context.operation.request_id);
      if (!inboxSessionIsCurrent()) return operation;
      if (context.optimistic.removed) {
        const restoredItem = context.snapshot.items.find(item =>
          Number(item.email.id) === Number(context.focusedBefore))
          || context.snapshot.items.find(item =>
            Number(item.email.id) === Number(context.snapshot.selectedId));
        if (restoredItem) {
          pendingActionRestoreFocus = {
            datasetKey: context.datasetKey,
            conversationKey: restoredItem.email.conversation_key || null,
            emailId: restoredItem.email.id,
            expectedFocusedId: focusedEmailId,
            restoreSelection: context.snapshot.selectedId != null
              && context.emailIds.includes(context.snapshot.selectedId),
          };
        }
      }
      if (actionContextIsCurrent(context.actionEpoch, context.datasetKey)) {
        restoreOptimisticAction(context);
      }
      requireActionReconciliation(context.datasetKey, context.optimistic.removed);
      if (latestUndo?.requestId === context.operation.request_id) latestUndo = null;
      showToast(`${actionPastTense(context.action, actionDisplayCount(context, context.operation), context.labelName, context.scope === 'conversations' ? 'conversation' : 'email')} — undone`, 'success');
      return operation;
    } catch (err) {
      if (inboxSessionIsCurrent()) {
        showToast(err.message || 'This action can no longer be undone', 'error');
      }
      throw err;
    }
  }

  function runLatestUndo() {
    if (!inboxSessionIsCurrent() || !latestUndo) return;
    if (latestUndo.expiresAt <= Date.now()) {
      latestUndo = null;
      showToast('The undo window has closed', 'info');
      return;
    }
    return latestUndo.run();
  }

  async function handleAction(action, emailIds, {
    announce = true,
    offerUndo = true,
    labelId = null,
    gmailLabelId = null,
    labelName = '',
  } = {}) {
    const requestedIds = [...new Set(emailIds)];
    if (!canActOnEmails(requestedIds)) return false;
    if (isLabelAction(action) && (!Number.isInteger(Number(labelId)) || Number(labelId) <= 0 || !gmailLabelId)) {
      showToast('Choose a valid label before applying this action', 'error');
      return false;
    }
    const uniqueIds = isLabelAction(action)
      ? expandVisibleLabelTargets(requestedIds, get(emails))
      : requestedIds;
    const scope = actionScopeForEmails(uniqueIds, get(emails));
    const actionEpoch = selectionEpoch;
    const datasetSnapshot = currentDatasetSnapshot();
    const datasetKey = datasetSnapshot.key;
    const detailBefore = selectedEmail;
    const threadBefore = selectedThread;
    const focusedBefore = focusedEmailId;
    const emailsBefore = get(emails);
    const sectionTotalsBefore = focusSectionTotals
      ? { ...focusSectionTotals }
      : null;
    const hasMoreBefore = hasMore;
    const snapshot = captureInboxAction(emailsBefore, get(selectedEmailId), uniqueIds);
    const optimistic = optimisticInboxAction({
      emails: emailsBefore,
      selectedId: get(selectedEmailId),
      emailIds: uniqueIds,
      action,
      mailbox: datasetSnapshot.mailbox,
      gmailLabelId,
    });
    if (optimistic.removed && !(await canLeaveSelectedEmail())) return false;
    const removedCount = optimistic.removed ? snapshot.items.length : 0;

    emails.set(optimistic.emails);
    if (removedCount > 0) emailsTotal.update(total => Math.max(0, total - removedCount));
    if (removedCount > 0 && focusSectionTotals) {
      focusSectionTotals = adjustInboxSectionTotals(
        focusSectionTotals,
        snapshot.items,
        -1,
      );
    }
    if (optimistic.removed) {
      // Offset pagination cannot safely accept a response computed before a
      // row-removing action. Discard any append and restart from page one once
      // the durable operation is confirmed.
      listRequests.invalidate();
      loadingMore = false;
      currentPageNum.set(1);
      hasMore = get(emails).length < get(emailsTotal);
    }
    const splitNextFocus = optimistic.removed && focusSectionTotals
      ? nextInboxRowFocus(emailsBefore, focusedBefore, uniqueIds)
      : null;
    const selectedWasRemoved = optimistic.removed
      && snapshot.selectedId != null
      && uniqueIds.includes(snapshot.selectedId);
    selectedEmailId.set(selectedWasRemoved && focusSectionTotals
      ? splitNextFocus
      : optimistic.selectedId);
    if (optimistic.removed) {
      focusedEmailId = focusSectionTotals
        ? splitNextFocus
        : nextConversationFocus(emailsBefore, focusedBefore, uniqueIds);
      if (!focusSectionTotals && optimistic.selectedId != null) {
        focusedEmailId = optimistic.selectedId;
      }
    }
    if (optimistic.removed && (
      (snapshot.selectedId != null && uniqueIds.includes(snapshot.selectedId))
      || uniqueIds.includes(focusedBefore)
    )) {
      queueMicrotask(focusInboxSelection);
    }
    const selectedConversationTargeted = scope === 'conversations'
      && snapshot.selectedId != null
      && uniqueIds.includes(snapshot.selectedId);
    if (optimistic.removed && snapshot.selectedId !== optimistic.selectedId) {
      selectedEmail = null;
      selectedThread = null;
    } else if (!optimistic.removed && selectedConversationTargeted) {
      selectedEmail = selectedEmail
        ? applyEmailAction(selectedEmail, action, { gmailLabelId })
        : null;
      selectedThread = selectedThread
        ? {
            ...selectedThread,
            emails: (selectedThread.emails || []).map(message => applyEmailAction(message, action, { gmailLabelId })),
          }
        : null;
    } else if (!optimistic.removed && selectedEmail && uniqueIds.includes(selectedEmail.id)) {
      selectedEmail = applyEmailAction(selectedEmail, action, { gmailLabelId });
    }

    const context = {
      action,
      actionEpoch,
      datasetKey,
      detailBefore,
      threadBefore,
      focusedBefore,
      emailIds: uniqueIds,
      gmailLabelId,
      labelId: labelId ? Number(labelId) : null,
      labelName,
      optimistic,
      removedCount,
      snapshot,
      scope,
      sectionTotalsBefore,
      hasMoreBefore,
    };
    const requestKey = idempotencyKey();
    let releaseQueue = null;

    try {
      const operation = await actionSubmissions.enqueue(
        uniqueIds,
        async queueControl => {
          try {
            return await submitMailAction(uniqueIds, action, requestKey, context.labelId, context.scope);
          } catch (err) {
            if (err.code === 'mail_action_outcome_unknown') {
              // Keep this original queue entry unsettled for followers even
              // when a newer same-email action was queued before uncertainty
              // was discovered.
              releaseQueue = queueControl.hold();
            }
            throw err;
          }
        },
      );
      if (!inboxSessionIsCurrent()) return false;
      acceptMailAction(context, operation, announce, offerUndo);
      return true;
    } catch (err) {
      if (err.code === 'mail_action_outcome_unknown') {
        if (!inboxSessionIsCurrent()) return false;
        const next = new Map(uncertainActions);
        next.set(requestKey, {
          announce,
          context,
          offerUndo,
          releaseQueue,
        });
        uncertainActions = next;
        scheduleUncertainActionChecks();
        showToast('Email action sent — confirming with the server', 'info');
        return true;
      }
      if (actionContextIsCurrent(actionEpoch, datasetKey)) {
        restoreOptimisticAction(context);
        showToast(err.message, 'error');
      } else if (inboxSessionIsCurrent() && currentDatasetSnapshot().key === datasetKey) {
        // A preceding accepted action may already have invalidated this
        // presentation epoch. Do not reinsert an old snapshot, but do make the
        // definitive failure visible and require a trailing server refresh.
        requireActionReconciliation(datasetKey);
        showToast(err.message, 'error');
      }
      return false;
    }
  }

  function emailForLabel(target) {
    if (target && typeof target === 'object') return target;
    const id = Number(target);
    return (selectedEmail?.id === id ? selectedEmail : null)
      || get(emails).find(email => email.id === id)
      || null;
  }

  function openLabelPicker(mode, targets, onComplete = null) {
    if (mode === 'move' && !moveAvailable) {
      showToast('Move to label is available from Inbox', 'info');
      return false;
    }
    const targetList = Array.isArray(targets) ? targets : [targets];
    const targetEmails = targetList.map(emailForLabel).filter(Boolean);
    if (!targetEmails.length || !canActOnEmails(targetEmails.map(email => email.id))) return false;
    labelPicker = {
      mode: mode === 'move' ? 'move' : 'apply',
      emails: targetEmails,
      onComplete: typeof onComplete === 'function' ? onComplete : null,
    };
    return true;
  }

  function updateLabelCatalog(fetched, accountId) {
    labelsStore.update(current => mergeLabelCatalog(current, fetched, accountId));
  }

  async function handleLabelSubmit(labelAction) {
    const target = labelPicker;
    if (!target) return false;
    const accepted = await handleAction(
      labelAction.action,
      target.emails.map(email => email.id),
      labelAction,
    );
    if (accepted) target.onComplete?.(true);
    return accepted;
  }

  function focusInboxSelection() {
    if (!inboxSessionIsCurrent()) return;
    const inboxRoot = document.querySelector('.inbox-page');
    focusEmailRowOrFallback(inboxRoot, focusedEmailId || get(selectedEmailId), inboxRoot);
  }

  function emailForSnooze(target) {
    if (target && typeof target === 'object') return target;
    const id = Number(target);
    return (selectedEmail?.id === id ? selectedEmail : null)
      || get(emails).find(email => email.id === id)
      || null;
  }

  async function openSnoozePicker(target) {
    const candidate = emailForSnooze(target);
    if (!candidate || snoozeBusyIds.has(candidate.id)) return;
    if (candidate.snooze_outcome_unknown) {
      showToast('Checking whether that reminder was accepted…', 'info');
      await refreshDataset();
      return;
    }
    if (candidate.is_draft || candidate.is_trash || candidate.is_spam) {
      showToast('Restore or send this email before snoozing it', 'info');
      return;
    }
    if (get(selectedEmailId) === candidate.id && !(await canLeaveSelectedEmail())) return;
    snoozeTarget = candidate;
  }

  function markSnoozeBusy(emailId, busy) {
    const next = new Set(snoozeBusyIds);
    if (busy) next.add(emailId); else next.delete(emailId);
    snoozeBusyIds = next;
  }

  function removeEmailOptimistically(target) {
    const list = get(emails);
    const sectionTotalsBefore = focusSectionTotals
      ? { ...focusSectionTotals }
      : null;
    const emailId = Number(target?.id ?? target);
    const identity = {
      email_id: emailId,
      account_id: target?.account_id,
      gmail_thread_id: target?.gmail_thread_id,
    };
    const conversation = partitionSnoozeConversation(list, identity);
    const index = list.findIndex(email => email.id === emailId);
    const item = index >= 0 ? list[index] : null;
    const firstRemovedIndex = conversation.matched[0]?.index ?? index;
    const nextFocusId = firstRemovedIndex >= 0
      ? (conversation.remaining[firstRemovedIndex]?.id
        ?? conversation.remaining[firstRemovedIndex - 1]?.id
        ?? null)
      : null;
    if (conversation.matched.length > 0) {
      emails.set(conversation.remaining);
      emailsTotal.update(total => Math.max(0, total - conversation.matched.length));
      if (focusSectionTotals) {
        focusSectionTotals = adjustInboxSectionTotals(
          focusSectionTotals,
          conversation.matched.map(entry => entry.email),
          -1,
        );
      }
    }
    const removedIds = new Set(conversation.matched.map(entry => entry.email.id));
    const selectedId = get(selectedEmailId);
    const wasSelected = removedIds.has(selectedId);
    const detail = wasSelected ? selectedEmail : null;
    if (wasSelected) {
      selectedEmailId.set(nextFocusId);
      selectedEmail = null;
    }
    queueMicrotask(() => {
      if (!inboxSessionIsCurrent()) return;
      const inboxRoot = document.querySelector('.inbox-page');
      if (!focusEmailRow(inboxRoot, nextFocusId)) {
        document.querySelector('[data-inbox-focus-fallback]')?.focus?.();
      }
    });
    return {
      affectedItems: conversation.matched.map(entry => entry.email),
      detail,
      identity,
      index,
      item,
      matched: conversation.matched,
      nextFocusId,
      removed: conversation.matched.length > 0,
      selectedId,
      sectionTotalsBefore,
      wasSelected,
    };
  }

  function keepSnoozedEmailInCurrentDataset() {
    if (get(searchQuery)) return true;
    const filter = get(smartFilter);
    if (filter && filter.type !== 'snoozed') return false;
    return !filter && get(currentMailbox) !== 'INBOX';
  }

  function captureRetainedSnooze(target, schedule, idempotencyKey) {
    const list = get(emails);
    const identity = {
      email_id: target.id,
      account_id: target.account_id,
      gmail_thread_id: target.gmail_thread_id,
    };
    const index = list.findIndex(email => email.id === target.id);
    const item = index >= 0 ? list[index] : null;
    const detail = selectedEmail && snoozeMatchesEmail(identity, selectedEmail) ? selectedEmail : null;
    const affectedItems = list.filter(email => snoozeMatchesEmail(identity, email));
    const projection = email => snoozeMatchesEmail(identity, email)
      ? {
          ...email,
          snooze_wake_at: schedule.wakeAt,
          snooze_time_zone: schedule.timeZone,
          snooze_condition: schedule.condition,
          snooze_state: 'pending_archive',
          snooze_idempotency_key: idempotencyKey,
          snooze_outcome_unknown: false,
        }
      : email;
    emails.set(list.map(projection));
    if (detail) selectedEmail = projection(detail);
    return {
      affectedItems,
      detail,
      identity,
      index,
      item,
      nextFocusId: null,
      removed: false,
      wasSelected: Boolean(detail),
    };
  }

  function projectAcceptedSnooze(reminder) {
    const projection = email => snoozeMatchesEmail(reminder, email)
      ? {
          ...email,
          snooze_id: reminder.id,
          snooze_wake_at: reminder.wake_at,
          snooze_time_zone: reminder.time_zone,
          snooze_condition: reminder.condition,
          snooze_state: reminder.state,
          snooze_idempotency_key: null,
          snooze_outcome_unknown: false,
        }
      : email;
    emails.update(list => list.map(projection));
    if (selectedEmail && snoozeMatchesEmail(reminder, selectedEmail)) {
      selectedEmail = projection(selectedEmail);
    }
  }

  function restoreOptimisticSnooze(snapshot) {
    if (!snapshot?.item) return;
    if (!snapshot.removed) {
      const originals = new Map(snapshot.affectedItems.map(email => [email.id, email]));
      emails.update(list => list.map(email => originals.get(email.id) || email));
      if (snapshot.detail && selectedEmail && originals.has(selectedEmail.id)) {
        selectedEmail = snapshot.detail;
      }
      return;
    }
    const presentIds = new Set(get(emails).map(email => email.id));
    const missing = snapshot.matched.filter(entry => !presentIds.has(entry.email.id));
    emails.update(list => {
      const next = [...list];
      for (const entry of missing) {
        next.splice(Math.min(entry.index, next.length), 0, entry.email);
      }
      return next;
    });
    emailsTotal.update(total => total + missing.length);
    focusSectionTotals = snapshot.sectionTotalsBefore || null;
    if (snapshot.wasSelected) {
      selectedEmailId.set(snapshot.selectedId);
      selectedEmail = snapshot.detail;
    }
    queueMicrotask(() => {
      if (inboxSessionIsCurrent()) {
        focusEmailRow(document.querySelector('.inbox-page'), snapshot.selectedId ?? snapshot.item.id);
      }
    });
  }

  async function handleSnoozeSubmit(schedule) {
    const target = snoozeTarget;
    snoozeTarget = null;
    if (!target || !inboxSessionIsCurrent()) return;
    const datasetKey = currentDatasetSnapshot().key;
    markSnoozeBusy(target.id, true);

    if (target.snooze_id) {
      const previousWake = target.snooze_wake_at;
      emails.update(list => list.map(email => email.id === target.id
        ? { ...email, snooze_wake_at: schedule.wakeAt, snooze_time_zone: schedule.timeZone }
        : email));
      if (selectedEmail?.id === target.id) {
        selectedEmail = { ...selectedEmail, snooze_wake_at: schedule.wakeAt, snooze_time_zone: schedule.timeZone };
      }
      try {
        await runSnoozeMutationWithReconciliation({
          mutate: () => api.rescheduleSnooze(target.snooze_id, {
            wake_at: schedule.wakeAt,
            time_zone: schedule.timeZone,
          }),
          lookup: () => api.getSnooze(target.snooze_id),
          accepted: record => rescheduleMatches(record, schedule.wakeAt, schedule.timeZone),
        });
        if (inboxSessionIsCurrent()) {
          showToast(`Reminder moved to ${formatSnoozeWake(schedule.wakeAt, schedule.timeZone)}`, 'success');
        }
      } catch (error) {
        if (error.code === 'snooze_mutation_outcome_unknown' && inboxSessionIsCurrent()) {
          showToast('Reminder change sent — refresh Snoozed to confirm', 'info');
          return;
        }
        if (inboxSessionIsCurrent() && currentDatasetSnapshot().key === datasetKey) {
          emails.update(list => list.map(email => email.id === target.id
            ? { ...email, snooze_wake_at: previousWake }
            : email));
          if (selectedEmail?.id === target.id) selectedEmail = { ...selectedEmail, snooze_wake_at: previousWake };
          showToast(error.message || 'The reminder could not be changed', 'error');
        }
      } finally {
        if (inboxSessionIsCurrent()) markSnoozeBusy(target.id, false);
      }
      return;
    }

    const createPayload = buildSnoozeRequest(target.id, schedule);
    const snapshot = keepSnoozedEmailInCurrentDataset()
      ? captureRetainedSnooze(target, schedule, createPayload.idempotency_key)
      : removeEmailOptimistically(target);
    try {
      const reminder = await createSnoozeWithReconciliation(
        api,
        createPayload,
      );
      if (!inboxSessionIsCurrent()) return;
      if (!snapshot.removed) projectAcceptedSnooze(reminder);
      showToast(
        `Snoozed until ${formatSnoozeWake(reminder.wake_at || schedule.wakeAt, reminder.time_zone || schedule.timeZone)}`,
        'success',
        10_000,
        {
          actionLabel: 'Undo',
          dismissLabel: 'Dismiss snooze confirmation',
          onAction: async () => {
            await runSnoozeMutationWithReconciliation({
              mutate: () => api.cancelSnooze(reminder.id),
              lookup: () => api.getSnooze(reminder.id),
              accepted: cancelAccepted,
            });
            if (!inboxSessionIsCurrent()) return;
            if (currentDatasetSnapshot().key === datasetKey) {
              if (snapshot.removed) restoreOptimisticSnooze(snapshot);
              else restoreOptimisticSnooze(snapshot);
            }
            showToast('Snooze undone — original placement restored', 'success');
          },
        },
      );
    } catch (error) {
      if (error.code === 'snooze_outcome_unknown' && inboxSessionIsCurrent()) {
        if (!snapshot.removed) {
          const markUnknown = email => snoozeMatchesEmail(snapshot.identity, email)
            ? { ...email, snooze_outcome_unknown: true, snooze_state: 'unknown' }
            : email;
          emails.update(list => list.map(markUnknown));
          if (selectedEmail && snoozeMatchesEmail(snapshot.identity, selectedEmail)) {
            selectedEmail = markUnknown(selectedEmail);
          }
        }
        showToast('Snooze sent — open Snoozed or refresh to confirm', 'info');
        return;
      }
      if (inboxSessionIsCurrent() && currentDatasetSnapshot().key === datasetKey) {
        restoreOptimisticSnooze(snapshot);
        showToast(error.message || 'The email could not be snoozed', 'error');
      }
    } finally {
      if (inboxSessionIsCurrent()) markSnoozeBusy(target.id, false);
    }
  }

  async function returnSnoozedNow(target = selectedEmail) {
    if (!target?.snooze_id || snoozeBusyIds.has(target.id)) return;
    const datasetKey = currentDatasetSnapshot().key;
    markSnoozeBusy(target.id, true);
    const snapshot = removeEmailOptimistically(target);
    try {
      await runSnoozeMutationWithReconciliation({
        mutate: () => api.returnSnoozeNow(target.snooze_id),
        lookup: () => api.getSnooze(target.snooze_id),
        accepted: returnNowAccepted,
      });
      if (inboxSessionIsCurrent()) showToast('Returned to inbox', 'success');
    } catch (error) {
      if (error.code === 'snooze_mutation_outcome_unknown' && inboxSessionIsCurrent()) {
        showToast('Return sent — refreshing Snoozed will confirm it', 'info');
        return;
      }
      if (inboxSessionIsCurrent() && currentDatasetSnapshot().key === datasetKey) {
        restoreOptimisticSnooze(snapshot);
        showToast(error.message || 'The email could not be returned', 'error');
      }
    } finally {
      if (inboxSessionIsCurrent()) markSnoozeBusy(target.id, false);
    }
  }

  async function cancelSnoozed(target = selectedEmail) {
    if (!target?.snooze_id || snoozeBusyIds.has(target.id)) return;
    const datasetKey = currentDatasetSnapshot().key;
    markSnoozeBusy(target.id, true);
    const snapshot = removeEmailOptimistically(target);
    try {
      await runSnoozeMutationWithReconciliation({
        mutate: () => api.cancelSnooze(target.snooze_id),
        lookup: () => api.getSnooze(target.snooze_id),
        accepted: cancelAccepted,
      });
      if (inboxSessionIsCurrent()) showToast('Reminder cancelled — original placement restored', 'success');
    } catch (error) {
      if (error.code === 'snooze_mutation_outcome_unknown' && inboxSessionIsCurrent()) {
        showToast('Cancellation sent — refreshing Snoozed will confirm it', 'info');
        return;
      }
      if (inboxSessionIsCurrent() && currentDatasetSnapshot().key === datasetKey) {
        restoreOptimisticSnooze(snapshot);
        showToast(error.message || 'The reminder could not be cancelled', 'error');
      }
    } finally {
      if (inboxSessionIsCurrent()) markSnoozeBusy(target.id, false);
    }
  }

  // --- Horizontal resize (column view: list | preview) ---
  function startHResize(e) {
    e.preventDefault();
    panelDragging = true;
    const startX = e.clientX;
    const startW = columnListWidth;

    function onMove(ev) {
      const delta = ev.clientX - startX;
      columnListWidth = Math.max(280, Math.min(startW + delta, 800));
    }
    function onUp() {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      panelDragging = false;
      localStorage.setItem('columnListWidth', String(columnListWidth));
    }
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }

  // --- Vertical resize (table view: table / preview) ---
  function startVResize(e) {
    e.preventDefault();
    panelDragging = true;
    const startY = e.clientY;
    const startPct = tableTopPct;

    function onMove(ev) {
      if (!containerEl) return;
      const rect = containerEl.getBoundingClientRect();
      const totalH = rect.height;
      const delta = ev.clientY - startY;
      const deltaPct = (delta / totalH) * 100;
      tableTopPct = Math.max(20, Math.min(startPct + deltaPct, 80));
    }
    function onUp() {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      panelDragging = false;
      localStorage.setItem('tableTopPct', String(Math.round(tableTopPct)));
    }
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }
</script>

<div class="inbox-page h-full flex flex-col" class:select-none={panelDragging} aria-busy={datasetUpdating} tabindex="-1" data-inbox-focus-fallback>
  {#if $searchQuery}
    <EmailSearchSummary
      query={$searchQuery}
      total={$emailsTotal}
      updating={datasetUpdating}
      failed={datasetError}
      showingPrevious={showingPreviousResults}
      onQueryChange={(query) => searchQuery.set(query)}
    />
  {/if}
  {#if !$searchQuery && $smartFilter?.type === 'snoozed'}
    <div class="flex min-h-12 flex-wrap items-center gap-2 border-b px-4 py-2" style="background: var(--bg-tertiary); border-color: var(--border-color)">
      <Icon name="clock" size={15} />
      <div class="min-w-0">
        <p class="text-xs font-semibold" style="color: var(--text-primary)">Snoozed</p>
        <p class="text-[11px]" style="color: var(--text-tertiary)">
          {selectedEmail?.snooze_origin === 'automatic_follow_up'
            ? 'Automatic follow-up · returns only if nobody replies'
            : 'Messages return to the inbox at their reminder time'}
        </p>
      </div>
      {#if selectedEmail?.snooze_id}
        <div class="ml-auto flex flex-wrap gap-1">
          <button
            type="button"
            class="min-h-10 rounded-lg border px-3 text-xs font-semibold disabled:opacity-50"
            style="border-color: var(--border-color); color: var(--text-secondary)"
            disabled={snoozeBusyIds.has(selectedEmail.id)}
            onclick={() => openSnoozePicker(selectedEmail)}
          >Change time</button>
          <button
            type="button"
            class="min-h-10 rounded-lg bg-accent-600 px-3 text-xs font-semibold text-white disabled:opacity-50"
            disabled={snoozeBusyIds.has(selectedEmail.id)}
            onclick={() => returnSnoozedNow(selectedEmail)}
          >Return now</button>
          <button
            type="button"
            class="min-h-10 rounded-lg px-3 text-xs font-semibold text-red-600 disabled:opacity-50"
            disabled={snoozeBusyIds.has(selectedEmail.id)}
            onclick={() => cancelSnoozed(selectedEmail)}
          >Cancel reminder</button>
        </div>
      {/if}
    </div>
  {/if}
  {#if !$searchQuery && ($smartFilter?.type === 'needs_reply_ignored' || $smartFilter?.type === 'needs_reply_snoozed')}
    <div class="flex items-center gap-2 px-4 py-2 border-b" style="background: var(--bg-tertiary); border-color: var(--border-color)">
      <Icon name={$smartFilter.type === 'needs_reply_ignored' ? 'eye-off' : 'clock'} size={14} />
      <span class="text-xs font-medium" style="color: var(--text-secondary)">
        {$smartFilter.type === 'needs_reply_ignored' ? 'Ignored needs-reply emails' : 'Snoozed needs-reply emails'}
      </span>
      {#if $selectedEmailId}
        <button
          onclick={() => {
            if ($smartFilter.type === 'needs_reply_ignored') {
              handleRestoreFromIgnored($selectedEmailId);
            } else {
              handleRestoreFromSnoozed($selectedEmailId);
            }
          }}
          class="ml-auto flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium transition-fast border"
          disabled={!datasetAuthoritative}
          style="border-color: var(--border-color); color: var(--text-secondary)"
        >
          <Icon name="rotate-ccw" size={12} />
          {$smartFilter.type === 'needs_reply_ignored' ? 'Unignore' : 'Unsnooze'}
        </button>
      {/if}
    </div>
  {/if}
  {#if datasetUpdating}
    <div
      class="flex items-center gap-2 px-4 py-2 border-b shrink-0"
      style="background: var(--bg-tertiary); border-color: var(--border-color); color: var(--text-secondary)"
    >
      <div class="w-3.5 h-3.5 border-2 rounded-full animate-spin shrink-0" style="border-color: var(--border-color); border-top-color: var(--color-accent-500)"></div>
      <span class="text-xs font-medium">{$searchQuery ? 'Searching mail…' : 'Updating inbox…'}</span>
      <span class="text-xs hidden sm:inline" style="color: var(--text-tertiary)">Actions will be available when these results finish loading.</span>
    </div>
  {:else if datasetError}
    <div
      class="flex items-center gap-2 px-4 py-2 border-b shrink-0"
      style="background: var(--bg-tertiary); border-color: var(--border-color); color: var(--text-secondary)"
      role="alert"
    >
      <Icon name="alert-circle" size={14} />
      <span class="text-xs font-medium">
        {#if $searchQuery}
          {showingPreviousResults ? 'Search failed. Showing previous results.' : 'Search results could not be updated.'}
        {:else}
          {datasetAuthoritative ? 'Could not refresh. Showing previous results.' : 'Inbox results could not be updated.'}
        {/if}
      </span>
      {#if datasetErrorMessage && datasetErrorMessage !== 'Request failed'}
        <span class="text-xs hidden md:inline truncate" style="color: var(--text-tertiary)">{datasetErrorMessage}</span>
      {/if}
      <button
        onclick={refreshDataset}
        class="ml-auto px-2.5 py-1 rounded-md border text-xs font-medium"
        style="border-color: var(--border-color); color: var(--color-accent-600)"
      >
        Try again
      </button>
    </div>
  {/if}
  <MailActionStatus
    onReconcile={refreshDataset}
    pendingConfirmationCount={uncertainActions.size}
    checkingPending={checkingUncertainActions}
    onCheckPending={reconcileUncertainActions}
  />
  {#if !$searchQuery && $currentMailbox === 'DRAFTS'}
    <WorkingDrafts />
  {/if}
  <div class="inbox-split flex-1 min-h-0 flex" class:results-stale={datasetUpdating || showingPreviousResults}>
  {#if useTableLayout}
    <!-- Table view: vertical split (table on top, preview below) -->
    <div class="flex flex-col w-full h-full overflow-hidden" bind:this={containerEl}>
      <div class="email-list-pane overflow-hidden" class:mobile-hidden={Boolean($selectedEmailId)} style="flex: {$selectedEmailId ? '0 0 ' + tableTopPct + '%' : '1 1 auto'}; min-height: 150px">
        <EmailTable
          emails={$emails}
          loading={$emailsLoading}
          {loadingMore}
          {hasMore}
          total={$emailsTotal}
          selectedId={focusedEmailId || $selectedEmailId}
          mailbox={resultsMailbox}
          searchActive={!!$searchQuery}
          loadFailed={datasetError && !datasetAuthoritative && $emails.length === 0}
          actionsDisabled={!datasetAuthoritative}
          sectionTotals={focusSectionTotals}
          {selectionEpoch}
          onSelect={handleSelect}
          onFocus={handleRowFocus}
          onAction={handleAction}
          onLabel={openLabelPicker}
          allowMove={moveAvailable}
          onSnooze={openSnoozePicker}
          onLoadMore={handleLoadMore}
        />
      </div>
      {#if $selectedEmailId}
        <!-- Vertical drag handle -->
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div
          class="email-resize-handle shrink-0 flex items-center justify-center cursor-row-resize group"
          style="height: 7px; background: var(--bg-secondary); border-top: 1px solid var(--border-color); border-bottom: 1px solid var(--border-color)"
          onmousedown={startVResize}
        >
          <div class="w-10 h-1 rounded-full transition-colors group-hover:bg-accent-500" style="background: var(--border-color)"></div>
        </div>
        <div class="email-preview-pane flex-1 min-h-0 overflow-hidden">
          {#if selectedReaderUsesThread}
            <ConversationView
              conversation={selectedReaderConversation}
              thread={selectedThread}
              loading={emailLoading}
              onAction={handleAction}
              onLabel={openLabelPicker}
              allowMove={moveAvailable}
              onSnooze={openSnoozePicker}
              onClose={closeSelectedEmail}
              onGuardChange={registerEmailViewTransitionGuard}
            />
          {:else}
            <EmailView
              email={selectedEmail}
              loading={emailLoading}
              onAction={handleAction}
              onLabel={openLabelPicker}
              allowMove={moveAvailable}
              onSnooze={openSnoozePicker}
              onClose={closeSelectedEmail}
              onGuardChange={registerEmailViewTransitionGuard}
            />
          {/if}
        </div>
      {/if}
    </div>
  {:else}
    <!-- Column view: horizontal split (list on left, preview on right) -->
    <div
      class="email-list-pane flex flex-col overflow-hidden shrink-0"
      class:mobile-hidden={Boolean($selectedEmailId)}
      style="border-right: 1px solid var(--border-color); width: {$selectedEmailId ? columnListWidth + 'px' : '100%'}; min-width: {$selectedEmailId ? '280px' : 'auto'}"
    >
      <EmailList
        emails={$emails}
        loading={$emailsLoading}
        {loadingMore}
        {hasMore}
        total={$emailsTotal}
        selectedId={focusedEmailId || $selectedEmailId}
        mailbox={resultsMailbox}
        searchActive={!!$searchQuery}
        loadFailed={datasetError && !datasetAuthoritative && $emails.length === 0}
        actionsDisabled={!datasetAuthoritative}
        sectionTotals={focusSectionTotals}
        {selectionEpoch}
        onSelect={handleSelect}
        onFocus={handleRowFocus}
        onAction={handleAction}
        onLabel={openLabelPicker}
        allowMove={moveAvailable}
        onSnooze={openSnoozePicker}
        onLoadMore={handleLoadMore}
      />
    </div>
    {#if $selectedEmailId}
      <!-- Horizontal drag handle -->
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div
        class="email-resize-handle shrink-0 flex items-center justify-center cursor-col-resize group"
        style="width: 7px; background: var(--bg-secondary); border-left: 1px solid var(--border-color); border-right: 1px solid var(--border-color)"
        onmousedown={startHResize}
      >
        <div class="h-10 w-1 rounded-full transition-colors group-hover:bg-accent-500" style="background: var(--border-color)"></div>
      </div>
      <div class="email-preview-pane flex-1 min-w-0 overflow-hidden">
        {#if selectedReaderUsesThread}
          <ConversationView
            conversation={selectedReaderConversation}
            thread={selectedThread}
            loading={emailLoading}
            onAction={handleAction}
            onLabel={openLabelPicker}
            allowMove={moveAvailable}
            onSnooze={openSnoozePicker}
            onClose={closeSelectedEmail}
            onGuardChange={registerEmailViewTransitionGuard}
          />
        {:else}
          <EmailView
            email={selectedEmail}
            loading={emailLoading}
            onAction={handleAction}
            onLabel={openLabelPicker}
            allowMove={moveAvailable}
            onSnooze={openSnoozePicker}
            onClose={closeSelectedEmail}
            onGuardChange={registerEmailViewTransitionGuard}
          />
        {/if}
      </div>
    {/if}
  {/if}
  </div>
  <SnoozePicker
    open={Boolean(snoozeTarget)}
    email={snoozeTarget}
    mode={snoozeTarget?.snooze_id ? 'reschedule' : 'create'}
    onclose={() => { snoozeTarget = null; }}
    onsubmit={handleSnoozeSubmit}
  />
  <LabelPicker
    open={Boolean(labelPicker)}
    mode={labelPicker?.mode || 'apply'}
    emails={labelPicker?.emails || []}
    accounts={$accounts}
    catalog={$labelsStore}
    onclose={() => { labelPicker = null; }}
    oncatalog={updateLabelCatalog}
    onsubmit={handleLabelSubmit}
    onfocusfallback={focusInboxSelection}
  />
</div>

<style>
  .inbox-split.results-stale {
    opacity: 0.58;
    filter: saturate(0.7);
    transition: opacity 120ms ease;
  }
  @media (max-width: 767px) {
    .email-list-pane {
      width: 100% !important;
      min-width: 0 !important;
      min-height: 0 !important;
      border-right: 0 !important;
      flex: 1 1 auto !important;
    }
    .email-preview-pane {
      width: 100%;
      flex: 1 1 auto;
    }
    .email-resize-handle,
    .mobile-hidden {
      display: none !important;
    }
  }
</style>
