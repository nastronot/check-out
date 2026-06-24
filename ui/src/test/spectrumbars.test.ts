import { describe, expect, it } from 'vitest';
import { MAX_BAR, barCell, barsToCells } from '../lib/spectrumbars';

const litRows = (cell: boolean[][]) => cell.filter((row) => row.every(Boolean)).length;

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
