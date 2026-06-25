import { describe, expect, it } from 'vitest';
import {
  MAX_BAR,
  STEREO_H_MAX,
  barCell,
  barsToCells,
  colCell,
  labelCell,
  lineCell,
  linesToCells,
  spectrumCells,
  spectrumStatusCells,
  stereoHCells,
  stereoVCells,
  vlineCell,
} from '../lib/spectrumbars';

const litRows = (cell: boolean[][]) => cell.filter((row) => row.every(Boolean)).length;
const litCols = (cell: boolean[][]) => cell[0].filter(Boolean).length; // full-height cols
const anyLit = (cell: boolean[][]) => cell.some((row) => row.some(Boolean));

describe('spectrum preview bars', () => {
  it('barCell is bottom-anchored, full-width', () => {
    expect(litRows(barCell(0))).toBe(0);
    expect(litRows(barCell(3))).toBe(3);
    expect(litRows(barCell(7))).toBe(7);
    // the lit rows are the BOTTOM ones
    const c = barCell(2);
    expect(c[6].every(Boolean)).toBe(true); // bottom row lit
    expect(c[0].some(Boolean)).toBe(false); // top row dark
  });

  it('barsToCells maps double-height: bottom fills 1..7, top fills 8..14', () => {
    const { top, bottom } = barsToCells([0, 7, 14]);
    expect(top).toHaveLength(20);
    expect(bottom).toHaveLength(20);
    // bar 0: empty
    expect(litRows(top[0])).toBe(0);
    expect(litRows(bottom[0])).toBe(0);
    // bar 7: bottom full, top empty
    expect(litRows(bottom[1])).toBe(7);
    expect(litRows(top[1])).toBe(0);
    // bar 14: both full
    expect(litRows(bottom[2])).toBe(7);
    expect(litRows(top[2])).toBe(7);
  });

  it('clamps out-of-range / missing heights', () => {
    const { top, bottom } = barsToCells([99, -5]);
    expect(litRows(top[0])).toBe(7); // 99 -> MAX_BAR
    expect(litRows(bottom[0])).toBe(7);
    expect(litRows(bottom[1])).toBe(0); // -5 -> 0
    // missing entries (only 2 provided) render empty, never crash
    expect(litRows(bottom[19])).toBe(0);
  });

  it('MAX_BAR is 14 (two 7-row cells)', () => {
    expect(MAX_BAR).toBe(14);
  });
});

describe('spectrum preview line style', () => {
  it('lineCell lights exactly one peak row (or none at height 0)', () => {
    expect(litRows(lineCell(0))).toBe(0);
    expect(litRows(lineCell(3))).toBe(1);
    // height 1 -> bottom row only; height 7 -> top row only.
    expect(lineCell(1)[6].every(Boolean)).toBe(true);
    expect(lineCell(1)[0].some(Boolean)).toBe(false);
    expect(lineCell(7)[0].every(Boolean)).toBe(true);
    expect(lineCell(7)[6].some(Boolean)).toBe(false);
  });

  it('linesToCells: single row, bottom EMPTIES once the peak enters the top cell', () => {
    const { top, bottom } = linesToCells([0, 7, 8, 14]);
    // height 0: both empty
    expect(litRows(top[0]) + litRows(bottom[0])).toBe(0);
    // height 7: line in the bottom cell, top empty
    expect(litRows(bottom[1])).toBe(1);
    expect(litRows(top[1])).toBe(0);
    // height 8: line moves up to the TOP cell, bottom goes EMPTY (the contrast)
    expect(litRows(bottom[2])).toBe(0);
    expect(litRows(top[2])).toBe(1);
    // height 14: single line at the very top
    expect(litRows(top[3])).toBe(1);
    expect(litRows(bottom[3])).toBe(0);
  });

  it('spectrumCells picks line vs bars by style', () => {
    // At height 8, bars keep the bottom full; line empties it.
    expect(litRows(spectrumCells([8], 'bars').bottom[0])).toBe(7);
    expect(litRows(spectrumCells([8], 'line').bottom[0])).toBe(0);
    expect(litRows(spectrumCells([8], undefined).bottom[0])).toBe(7); // default bars
  });
});

describe('spectrum preview stereo cells', () => {
  it('labelCell inverts the letter (lit field, dark letter)', () => {
    const l = labelCell('L');
    // L's bottom row is full (lit) -> inverted it is dark; top-left was lit -> dark.
    expect(l[6].some(Boolean)).toBe(false); // bottom row (full in L) now dark
    expect(l[0][0]).toBe(false); // the L stroke column dark
    expect(l[0][4]).toBe(true); // the field (non-letter) lit
    expect(anyLit(l)).toBe(true);
  });

  it('colCell lights the leftmost n columns; vlineCell a single column', () => {
    expect(litCols(colCell(0))).toBe(0);
    expect(litCols(colCell(3))).toBe(3);
    expect(litCols(colCell(9))).toBe(5); // clamped
    expect(colCell(3)[0]).toEqual([true, true, true, false, false]);
    expect(vlineCell(3)[0]).toEqual([false, false, true, false, false]);
    expect(litCols(vlineCell(0))).toBe(0); // 0 = empty
  });

  it('stereoVCells: labels in cell 0; per-row single-cell bars/lines', () => {
    const { top, bottom } = stereoVCells([0, 7, 4], [7], 'bars');
    expect(top).toHaveLength(20);
    expect(anyLit(top[0])).toBe(true); // L label
    expect(anyLit(bottom[0])).toBe(true); // R label
    expect(litRows(top[1])).toBe(0); // height 0
    expect(litRows(top[2])).toBe(7); // height 7 full cell
    expect(litRows(top[3])).toBe(4); // height 4
    // line style: a single peak row per cell.
    const line = stereoVCells([4], [0], 'line');
    expect(litRows(line.top[1])).toBe(1);
  });

  it('stereoHCells BARS: fills with a partial leading cell at the 0..95 level', () => {
    // level 7: cell0 full (5 cols), cell1 partial (2 cols), rest empty.
    const { top } = stereoHCells(7, 0, 'bars');
    expect(top).toHaveLength(20);
    expect(anyLit(top[0])).toBe(true); // label
    expect(litCols(top[1])).toBe(5); // full
    expect(litCols(top[2])).toBe(2); // partial leading cell
    expect(anyLit(top[3])).toBe(false); // beyond level
  });

  it('stereoHCells LINE: a single lit column at the leading edge', () => {
    // level 7 line: the single lit column is global col 7 = cell1, in-cell col 2.
    const { top } = stereoHCells(7, 0, 'line');
    expect(anyLit(top[1])).toBe(false); // cell 0 empty
    expect(top[2][0]).toEqual([false, true, false, false, false]); // vline(2)
    expect(anyLit(top[3])).toBe(false);
  });

  it('STEREO_H_MAX is 95 (19 cells x 5 columns)', () => {
    expect(STEREO_H_MAX).toBe(95);
  });

  it('spectrumStatusCells dispatches by layout', () => {
    const v = spectrumStatusCells('stereo_v', null, [7], [0], null, null, 'bars');
    expect(litRows(v!.top[1])).toBe(7);
    const h = spectrumStatusCells('stereo_h', null, null, null, 7, 0, 'bars');
    expect(litCols(h!.top[1])).toBe(5);
    const f = spectrumStatusCells('full', [14], null, null, null, null, 'bars');
    expect(litRows(f!.bottom[0])).toBe(7);
    expect(spectrumStatusCells('full', null, null, null, null, null)).toBeNull();
  });
});
