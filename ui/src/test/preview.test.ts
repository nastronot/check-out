import { describe, expect, it } from 'vitest';
import {
  GLYPH_CODES,
  LINE_LEN,
  cellDots,
  lineToCells,
  litCount,
} from '../lib/font5x7';

describe('VfdPreview font mapping', () => {
  it('renders 40 cells across two 20-char lines', () => {
    const top = lineToCells('HELLO WORLD', {});
    const bottom = lineToCells('', {});
    expect(top.length).toBe(LINE_LEN);
    expect(bottom.length).toBe(LINE_LEN);
    expect(top.length + bottom.length).toBe(40);
    // Each cell is a 7x5 boolean matrix.
    expect(top[0].length).toBe(7);
    expect(top[0][0].length).toBe(5);
  });

  it('maps known characters to the real M202MD10C lit-dot counts', () => {
    // Counts decoded from the real charset photos (Eigenbaukombinat). These pin
    // the actual panel glyphs, not the old hand-drawn placeholder.
    const counts: Record<string, number> = {
      A: 16,
      G: 17,
      M: 18,
      Q: 17,
      '&': 15,
      '@': 21,
      '4': 14,
      '0': 16,
    };
    for (const [ch, n] of Object.entries(counts)) {
      expect(litCount(ch.charCodeAt(0))).toBe(n);
    }
    // Space lights nothing.
    expect(litCount(0x20)).toBe(0);
  });

  it('canvas decode path lights the same dots as litCount (one shared font)', () => {
    // draw() lights a dot exactly when lineToCells(line)[ci][r][c] is truthy.
    // Assert THAT path lights 16 dots for 'A' (real charset), matching litCount —
    // so a blank preview is never a font/decode bug, only a data/redraw one.
    const cells = lineToCells('A', {});
    const litInFirstCell = cells[0].reduce(
      (n, row) => n + row.filter(Boolean).length,
      0,
    );
    expect(litInFirstCell).toBe(16);
    expect(litInFirstCell).toBe(litCount('A'.charCodeAt(0)));
  });

  it('renders user glyphs from state.glyphs (low-5-bit rows)', () => {
    // Slot 0 (code 0x15): a single full top row -> 5 lit dots.
    const glyphs = { '0': [0x1f, 0, 0, 0, 0, 0, 0] };
    expect(litCount(GLYPH_CODES[0], glyphs)).toBe(5);
    // Same code with no definition renders blank.
    expect(litCount(GLYPH_CODES[0], {})).toBe(0);
  });

  it('places lit dots left-to-right per the bit0=leftmost convention', () => {
    // Row 0b00001 -> only column 0 (leftmost) lit.
    const glyphs = { '0': [0b00001, 0b10000, 0, 0, 0, 0, 0] };
    const cell = cellDots(GLYPH_CODES[0], glyphs);
    expect(cell[0]).toEqual([true, false, false, false, false]);
    expect(cell[1]).toEqual([false, false, false, false, true]);
  });
});
