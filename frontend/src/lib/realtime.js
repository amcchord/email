/**
 * Real-time event stream using Server-Sent Events.
 *
 * Connects to /api/events/stream and exposes a Svelte store that
 * pages can react to for automatic data refreshes.
 */

import { writable } from 'svelte/store';
import { captureAuthEpoch, isAuthEpochCurrent } from './authSession.js';

export const lastEvent = writable(null);

let eventSource = null;
let reconnectTimer = null;
let reconnectDelay = 1000;
let realtimeSession = null;

const MAX_RECONNECT_DELAY = 30000;
const SSE_URL = '/api/events/stream';

function realtimeSessionIsCurrent(session) {
  return realtimeSession === session
    && session?.userId !== null
    && isAuthEpochCurrent(session);
}

function handleEvent(eventType, session) {
  return function (e) {
    if (!realtimeSessionIsCurrent(session)) return;
    let data = {};
    try {
      data = JSON.parse(e.data);
    } catch {
      // ignore parse errors
    }
    lastEvent.set({ type: eventType, ...data });
  };
}

function connect(session) {
  if (!realtimeSessionIsCurrent(session) || eventSource) {
    return;
  }

  eventSource = new EventSource(SSE_URL, { withCredentials: true });

  eventSource.addEventListener('new_emails', handleEvent('new_emails', session));
  eventSource.addEventListener('emails_updated', handleEvent('emails_updated', session));
  eventSource.addEventListener('mail_action_updated', handleEvent('mail_action_updated', session));
  eventSource.addEventListener('sync_complete', handleEvent('sync_complete', session));

  eventSource.onopen = function () {
    if (!realtimeSessionIsCurrent(session)) return;
    reconnectDelay = 1000;
  };

  eventSource.onerror = function () {
    cleanup();
    if (realtimeSessionIsCurrent(session)) scheduleReconnect(session);
  };
}

function cleanup() {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
}

function scheduleReconnect(session) {
  if (!realtimeSessionIsCurrent(session) || reconnectTimer) {
    return;
  }
  reconnectTimer = setTimeout(function () {
    reconnectTimer = null;
    connect(session);
  }, reconnectDelay);
  reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
}

export function startRealtime() {
  stopRealtime();
  const session = captureAuthEpoch();
  if (session.userId === null || !isAuthEpochCurrent(session)) return;
  realtimeSession = session;
  connect(session);
}

export function stopRealtime() {
  realtimeSession = null;
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  cleanup();
  reconnectDelay = 1000;
  lastEvent.set(null);
}
