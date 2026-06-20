// Pure helpers for editing a 5x7 user glyph. A glyph is 7 row ints whose LOW 5
// bits are columns 1..5 (bit0 = leftmost) — the exact convention state.glyphs /
// the daemon / the preview all share, so what you draw is what the VFD defines.

import { CELL_COLS, CELL_ROWS, FONT5x7 } from './font5x7';

export const EMPTY_GLYPH: number[] = [0, 0, 0, 0, 0, 0, 0];

/** Normalize anything into a valid 7-row, low-5-bit glyph (copy). */
export function normGlyph(g: unknown): number[] {
  if (Array.isArray(g) && g.length === CELL_ROWS) {
    return g.map((r) => (Number(r) | 0) & 0x1f);
  }
  return EMPTY_GLYPH.slice();
}

/** Return a NEW glyph with the dot at (row, col) turned on/off. */
export function withBit(
  rows: number[],
  row: number,
  col: number,
  on: boolean,
): number[] {
  const out = normGlyph(rows);
  if (row < 0 || row >= CELL_ROWS || col < 0 || col >= CELL_COLS) return out;
  const mask = 1 << col;
  out[row] = (on ? out[row] | mask : out[row] & ~mask) & 0x1f;
  return out;
}

/** Is the dot at (row, col) lit? */
export function bitOf(rows: number[], row: number, col: number): boolean {
  return (((rows[row] ?? 0) >> col) & 1) === 1;
}

/** Seed a glyph from a printable character's REAL font bitmap, or null if none. */
export function copyFromChar(ch: string): number[] | null {
  if (!ch) return null;
  const rows = FONT5x7[ch.charCodeAt(0)];
  return rows ? rows.slice() : null;
}
