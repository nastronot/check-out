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

/** A single-row LINE cell: only the peak row at `height` (1..7) lit, full width;
 *  every other row dark. Mirrors the daemon's `line_glyph` (lit row = CELL_ROWS -
 *  height). height 0 → fully dark. */
export function lineCell(height: number): Cell {
  const h = Math.max(0, Math.min(CELL_ROWS, height));
  const lit = CELL_ROWS - h; // the single peak row (height 1 → bottom row)
  const rows: Cell = [];
  for (let r = 0; r < CELL_ROWS; r++) {
    rows.push(new Array(CELL_COLS).fill(h > 0 && r === lit));
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

/** Map 20 heights to (top, bottom) cells for the LINE style: only ONE row lit at
 *  the peak. Mirrors the daemon's `line_to_cells` — once the peak enters the top
 *  cell (height 8..14) the BOTTOM cell goes EMPTY (nothing lit below the line). */
export function linesToCells(bars: number[]): { top: Cell[]; bottom: Cell[] } {
  const top: Cell[] = [];
  const bottom: Cell[] = [];
  for (let i = 0; i < LINE_LEN; i++) {
    const h = Math.max(0, Math.min(MAX_BAR, Math.round(bars?.[i] ?? 0)));
    if (h <= CELL_ROWS) {
      bottom.push(lineCell(h));                          // 1..7: line in bottom
      top.push(lineCell(0));                             // top empty
    } else {
      bottom.push(lineCell(0));                          // 8..14: bottom EMPTY
      top.push(lineCell(h - CELL_ROWS));                 // line up in the top
    }
  }
  return { top, bottom };
}

/** Pick the cell mapping for a spectrum style ("line" → single-row, else bars). */
export function spectrumCells(
  bars: number[],
  style?: string,
): { top: Cell[]; bottom: Cell[] } {
  return style === 'line' ? linesToCells(bars) : barsToCells(bars);
}
