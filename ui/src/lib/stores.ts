// Svelte stores for live data.
//
// - `status` + `health` are POLLED (~500ms) so the preview is a true mirror of
//   what the daemon actually rendered (clock ticks, ticker motion, blank...).
// - `appState` is the desired state: fetched once on load, then replaced by the
//   response of every PUT/command (optimistic edits reconcile against the API's
//   canonical, backfilled result).

import { writable } from 'svelte/store';
import { getHealth, getState, getStatus, putState } from './api';
import type { AppState, Health, Status } from './types';

export const status = writable<Status | null>(null);
export const health = writable<Health>({ ok: false, daemon_alive: false });
export const appState = writable<AppState | null>(null);

let timer: ReturnType<typeof setInterval> | null = null;

async function pollOnce(): Promise<void> {
  try {
    status.set(await getStatus());
  } catch {
    /* transient — keep last good value */
  }
  try {
    health.set(await getHealth());
  } catch {
    health.set({ ok: false, daemon_alive: false });
  }
}

export function startPolling(intervalMs = 500): void {
  if (timer) return;
  void pollOnce();
  timer = setInterval(() => void pollOnce(), intervalMs);
}

export function stopPolling(): void {
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
}

/** Load the desired state into the controls. */
export async function loadState(): Promise<void> {
  try {
    appState.set(await getState());
  } catch {
    /* leave null; UI shows a loading state */
  }
}

/** Optimistic patch: PUT the partial and reconcile the store with the result. */
export async function patchState(patch: Partial<AppState>): Promise<void> {
  // Optimistic local update so controls feel instant.
  appState.update((s) => (s ? { ...s, ...patch } : s));
  try {
    appState.set(await putState(patch));
  } catch {
    // On failure, re-sync from the server's truth.
    await loadState();
  }
}
