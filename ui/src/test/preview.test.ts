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

  it('maps a known character to the right lit-dot count', () => {
    // 'A' in the built-in 5x7 font lights exactly 18 dots.
    expect(litCount('A'.charCodeAt(0))).toBe(18);
    // Space lights nothing.
    expect(litCount(0x20)).toBe(0);
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
