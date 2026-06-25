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

// --- stereo layouts (v1.2.0) ------------------------------------------------
// Mirrors the daemon's spectrum.py stereo renderers + glyphs, but as lit-dot
// grids (the preview can't read the hardware's defined glyphs).

const STEREO_BANDS = 19; // data cells per row (cell 0 is the L/R label)
export const STEREO_H_MAX = STEREO_BANDS * CELL_COLS; // 95 fine horizontal steps

// The user's hand-designed INVERTED L/R label bitmaps (lit frame, dark letter) —
// must match spectrum.py's LABEL_L / LABEL_R exactly. 5x7, low 5 bits = columns
// 1..5 (bit0 = col 1). Already inverted, so labelCell renders them as-is.
const LABEL: Record<string, number[]> = {
  L: [31, 29, 29, 29, 29, 17, 31],
  R: [31, 17, 21, 25, 21, 21, 31],
};

/** An L/R label cell: the custom inverted design (lit field, dark letter). */
export function labelCell(letter: 'L' | 'R'): Cell {
  const rows = LABEL[letter];
  return rows.map((row) => {
    const out: boolean[] = [];
    for (let c = 0; c < CELL_COLS; c++) out.push((row & (1 << c)) !== 0);
    return out;
  });
}

/** A horizontal-fill cell: the leftmost `n` columns (0..5) lit, all rows. */
export function colCell(n: number): Cell {
  const lit = Math.max(0, Math.min(CELL_COLS, n));
  const rows: Cell = [];
  for (let r = 0; r < CELL_ROWS; r++) {
    const row: boolean[] = [];
    for (let c = 0; c < CELL_COLS; c++) row.push(c < lit);
    rows.push(row);
  }
  return rows;
}

/** A single-column cell: only column `col` (1..5) lit, all rows (0 = empty). */
export function vlineCell(col: number): Cell {
  const rows: Cell = [];
  for (let r = 0; r < CELL_ROWS; r++) {
    const row: boolean[] = [];
    for (let c = 0; c < CELL_COLS; c++) row.push(col >= 1 && c === col - 1);
    rows.push(row);
  }
  return rows;
}

/** One stereo_v row: [label] + 19 single-cell bars/lines (height 0..7). */
function stereoVRow(label: 'L' | 'R', heights: number[], style?: string): Cell[] {
  const cells: Cell[] = [labelCell(label)];
  const cell = style === 'line' ? lineCell : barCell;
  for (let i = 0; i < STEREO_BANDS; i++) {
    cells.push(cell(Math.max(0, Math.min(CELL_ROWS, Math.round(heights?.[i] ?? 0)))));
  }
  return cells;
}

/** stereo_v: top = LEFT spectrum, bottom = RIGHT, each with its label in cell 0. */
export function stereoVCells(
  left: number[],
  right: number[],
  style?: string,
): { top: Cell[]; bottom: Cell[] } {
  return { top: stereoVRow('L', left, style), bottom: stereoVRow('R', right, style) };
}

/** One stereo_h row: [label] + 19 cells encoding `level` (0..95) across 95 columns. */
function stereoHRow(label: 'L' | 'R', level: number, style?: string): Cell[] {
  const lvl = Math.max(0, Math.min(STEREO_H_MAX, Math.round(level)));
  const cells: Cell[] = [labelCell(label)];
  for (let i = 0; i < STEREO_BANDS; i++) {
    const lo = i * CELL_COLS;
    if (style === 'line') {
      // The single lit column is the `lvl`-th (1-based, global): in this cell iff
      // lo < lvl <= lo+5; the in-cell column is lvl-lo.
      cells.push(lvl > lo && lvl <= lo + CELL_COLS ? vlineCell(lvl - lo) : vlineCell(0));
    } else {
      cells.push(colCell(Math.max(0, Math.min(CELL_COLS, lvl - lo)))); // leftmost n cols
    }
  }
  return cells;
}

/** stereo_h: top = LEFT meter, bottom = RIGHT meter, each with its label in cell 0. */
export function stereoHCells(
  levelL: number,
  levelR: number,
  style?: string,
): { top: Cell[]; bottom: Cell[] } {
  return { top: stereoHRow('L', levelL, style), bottom: stereoHRow('R', levelR, style) };
}

/** Build the (top, bottom) preview cells for ANY spectrum layout from status. */
export function spectrumStatusCells(
  layout: string | undefined,
  bars: number[] | null,
  left: number[] | null | undefined,
  right: number[] | null | undefined,
  levelL: number | null | undefined,
  levelR: number | null | undefined,
  style?: string,
): { top: Cell[]; bottom: Cell[] } | null {
  if (layout === 'stereo_v' && left && right) return stereoVCells(left, right, style);
  if (layout === 'stereo_h') return stereoHCells(levelL ?? 0, levelR ?? 0, style);
  if (Array.isArray(bars)) return spectrumCells(bars, style);
  return null;
}
