// The hardware cursor as the preview draws it: a fully lit cell. The daemon
// reports the cell in status.cursor (weather's colon tick); null = hidden.
import { CELL_COLS, CELL_ROWS, LINE_LEN } from './font5x7';
import type { Cell } from './spectrumbars';

const CURSOR_CELL: Cell = Array.from({ length: CELL_ROWS }, () =>
  Array<boolean>(CELL_COLS).fill(true),
);

/** Copies of the two lines with the cell at linear `cursor` (0..39) fully lit. */
export function withCursor(
  top: Cell[],
  bottom: Cell[],
  cursor: number | null | undefined,
): [Cell[], Cell[]] {
  if (cursor == null || cursor < 0 || cursor >= 2 * LINE_LEN) return [top, bottom];
  const lines = [top.slice(), bottom.slice()];
  lines[Math.floor(cursor / LINE_LEN)][cursor % LINE_LEN] = CURSOR_CELL;
  return [lines[0], lines[1]];
}
