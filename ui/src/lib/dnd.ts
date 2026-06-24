// Drag-and-drop helpers for the glyph library. Pure logic so the reorder and
// the "what did we drop" decoding are unit-testable without real DnD events.

import type { LibraryGlyph } from './types';

/** dataTransfer key carrying a dragged library glyph's id. */
export const GLYPH_DND_TYPE = 'application/x-checkout-glyph';

/** Return a NEW id list with `dragId` moved to `targetId`'s position. */
export function reorderIds(
  ids: string[],
  dragId: string,
  targetId: string,
): string[] {
  if (dragId === targetId) return ids.slice();
  const from = ids.indexOf(dragId);
  const to = ids.indexOf(targetId);
  if (from < 0 || to < 0) return ids.slice();
  const out = ids.slice();
  out.splice(from, 1);
  out.splice(to, 0, dragId);
  return out;
}

/** Find a glyph's rows by id (for the slot drop handler). */
export function rowsForGlyphId(
  glyphs: LibraryGlyph[],
  id: string,
): number[] | null {
  const g = glyphs.find((x) => x.id === id);
  return g ? g.rows : null;
}

/** Resolve a library→slot drop: the rows to load into `slot`, or null if the
 *  dragged id isn't in the library. Pure logic behind the slot drop handler, so
 *  the cross-component drop can be unit-tested without real DnD events. */
export function resolveGlyphDrop(
  glyphs: LibraryGlyph[],
  draggedId: string,
  slot: number,
): { slot: number; rows: number[] } | null {
  const rows = rowsForGlyphId(glyphs, draggedId);
  return rows ? { slot, rows } : null;
}
