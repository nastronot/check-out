// Svelte stores for live data.
//
// - `status` is POLLED (~500ms) so the preview is a true mirror of what the
//   daemon actually rendered (clock ticks, ticker motion, blank...). `health`
//   (daemon_alive) is DERIVED from that same status's freshness — no separate
//   /api/health hot poll (the endpoint still exists for external checks; the UI
//   just doesn't hammer it every cycle).
// - `appState` is the desired state: fetched once on load, then replaced by the
//   response of every PUT/command (optimistic edits reconcile against the API's
//   canonical, backfilled result).

import { get, writable } from 'svelte/store';
import {
  getDevices,
  getLibrary,
  getState,
  getStatus,
  putState,
  reorderGlyphs,
} from './api';
import { normGlyph } from './glyphedit';
import type { AppState, AudioDevice, Health, Library, Status } from './types';

// Mirror of the backend's STALE_SECONDS: a status older than this (or absent)
// means the daemon isn't writing, so it's treated as offline.
const STALE_MS = 5000;

export const status = writable<Status | null>(null);
export const health = writable<Health>({ ok: false, daemon_alive: false });
export const appState = writable<AppState | null>(null);
export const library = writable<Library>({ messages: [], glyphs: [] });

// Audio input devices for the spectrum SOURCE selector (from devices.json, which
// the audioviz process writes). Empty until that process has run.
export const audioDevices = writable<AudioDevice[]>([]);

/** Refresh the audio device list (cheap; called when spectrum controls show). */
export async function refreshDevices(): Promise<void> {
  try {
    audioDevices.set((await getDevices()).devices ?? []);
  } catch {
    /* audioviz hasn't written devices.json yet — keep mic/system only */
  }
}

// The glyph editor's active slot (0..8), shared so the glyph library can load
// a saved glyph into whichever slot is selected.
export const selectedGlyphSlot = writable<number>(0);

// Id of the library glyph currently being dragged, '' when none. Shared across
// components so the editor's slot strip can accept a cross-component drop without
// depending on dataTransfer being readable during dragover (custom-MIME-type
// visibility varies by browser; this store is the reliable signal).
export const draggedGlyph = writable<string>('');

export type GlyphSync = 'idle' | 'syncing' | 'synced' | 'error';
export const glyphSync = writable<Record<number, GlyphSync>>({});

let timer: ReturnType<typeof setInterval> | null = null;

/** Daemon liveness from the status mirror: it must be marked alive AND fresh
 *  (< STALE_MS old). Matches the backend's /api/health freshness check, so the
 *  UI needs no separate health poll. */
export function aliveFromStatus(s: Status | null, now = Date.now()): boolean {
  if (!s || !s.alive || !s.updated_at) return false;
  const t = Date.parse(s.updated_at);
  if (Number.isNaN(t)) return false;
  return now - t < STALE_MS;
}

async function pollOnce(): Promise<void> {
  try {
    const s = await getStatus();
    status.set(s);
    // Derive liveness from the same payload — no extra /api/health request.
    health.set({ ok: true, daemon_alive: aliveFromStatus(s) });
  } catch {
    // Web API unreachable: keep the last good status, but report offline.
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

/** Optimistically set ONE glyph slot locally, keeping the other slots intact. */
export function setGlyphLocal(slot: string, rows: number[]): void {
  appState.update((s) =>
    s ? { ...s, glyphs: { ...(s.glyphs ?? {}), [slot]: rows } } : s,
  );
}

/** Persist glyph slots to the daemon (backend deep-merges into state.glyphs).
 *  Does NOT overwrite local glyphs from the response — the editor's optimistic
 *  state is authoritative, so an in-flight push can't clobber a newer edit. */
export async function pushGlyphs(
  slots: Record<string, number[]>,
): Promise<boolean> {
  try {
    await putState({ glyphs: slots });
    return true;
  } catch {
    return false;
  }
}

// Debounced per-slot glyph push, shared by the editor AND the glyph library so
// "load saved glyph into slot" goes through the same optimistic + auto-push path.
let glyphPending = new Set<number>();
let glyphTimer: ReturnType<typeof setTimeout> | null = null;

/** Optimistically set a slot's glyph and debounce a single push to the daemon. */
export function commitGlyph(slot: number, rows: number[]): void {
  setGlyphLocal(String(slot), rows); // strip + main preview update now
  glyphPending.add(slot);
  glyphSync.update((s) => ({ ...s, [slot]: 'syncing' }));
  if (glyphTimer) clearTimeout(glyphTimer);
  glyphTimer = setTimeout(flushGlyphs, 400);
}

async function flushGlyphs(): Promise<void> {
  glyphTimer = null;
  const flushing = [...glyphPending];
  glyphPending = new Set();
  const live = get(appState)?.glyphs ?? {};
  const slots: Record<string, number[]> = {};
  for (const s of flushing) slots[String(s)] = normGlyph(live[String(s)]);
  const ok = await pushGlyphs(slots);
  glyphSync.update((sync) => {
    const next = { ...sync };
    for (const s of flushing) next[s] = ok ? 'synced' : 'error';
    return next;
  });
}

/** Refresh the saved library (messages + glyphs). */
export async function refreshLibrary(): Promise<void> {
  try {
    library.set(await getLibrary());
  } catch {
    /* keep last good value */
  }
}

/** Replace appState from a recall response (library -> live). */
export function applyState(next: AppState): void {
  appState.set(next);
}

/** Load a saved library glyph (by id) into an editor slot — shared push path. */
export function loadGlyphFromLibrary(slot: number, id: string): boolean {
  const g = get(library).glyphs.find((x) => x.id === id);
  if (!g) return false;
  selectedGlyphSlot.set(slot);
  commitGlyph(slot, normGlyph(g.rows));
  return true;
}

/** Optimistically reorder the library glyphs, then persist (revert on failure). */
export async function reorderLibraryGlyphs(ids: string[]): Promise<void> {
  const prev = get(library).glyphs;
  const byId = new Map(prev.map((g) => [g.id, g]));
  const next = ids.map((id) => byId.get(id)).filter((g): g is NonNullable<typeof g> => !!g);
  if (next.length !== prev.length) return; // ids drifted; skip
  library.update((lib) => ({ ...lib, glyphs: next })); // optimistic
  try {
    await reorderGlyphs(ids);
  } catch {
    library.update((lib) => ({ ...lib, glyphs: prev })); // revert
  }
}
