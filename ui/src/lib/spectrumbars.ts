// Spectrum analyzer preview: turn the daemon's 20 bar heights (0..14) into the
// same 2×20 cell grid the dot-renderer paints, so the phosphor preview shows the
// analyzer. Mirrors the daemon's double-height mapping (bottom cell fills 1..7,
// top cell 8..14), but as lit-dot grids rather than glyph codes — the preview
// can't read the hardware's defined bar glyphs, so it draws the bars directly.

import { CELL_COLS, CELL_ROWS, LINE_LEN } from './font5x7';

/** A character cell as `cell[row][col]` (true = lit), matching `lineToCells`. */
export type Cell = boolean[][];

export const MAX_BAR = 2 * CELL_ROWS; // 14 (7 lit rows per cell, two cells)

/** A bottom-anchored bar cell with `litRows` (0..7) lit rows, full width. */
export function barCell(litRows: number): Cell {
  const n = Math.max(0, Math.min(CELL_ROWS, litRows));
  const rows: Cell = [];
  for (let r = 0; r < CELL_ROWS; r++) {
    rows.push(new Array(CELL_COLS).fill(r >= CELL_ROWS - n));
  }
  return rows;
}

/** Map 20 bar heights (0..14) to the (top, bottom) rows of 20 cells each. */
export function barsToCells(bars: number[]): { top: Cell[]; bottom: Cell[] } {
  const top: Cell[] = [];
  const bottom: Cell[] = [];
  for (let i = 0; i < LINE_LEN; i++) {
    const h = Math.max(0, Math.min(MAX_BAR, Math.round(bars?.[i] ?? 0)));
    bottom.push(barCell(Math.min(h, CELL_ROWS)));        // 1..7 fill the bottom
    top.push(barCell(Math.max(0, h - CELL_ROWS)));       // 8..14 fill the top
  }
  return { top, bottom };
}
