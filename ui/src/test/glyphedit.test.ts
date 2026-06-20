import { describe, expect, it } from 'vitest';
import {
  EMPTY_GLYPH,
  bitOf,
  copyFromChar,
  normGlyph,
  withBit,
} from '../lib/glyphedit';
import { FONT5x7, GLYPH_CODES, cellDots } from '../lib/font5x7';

describe('glyph editing', () => {
  it('withBit sets the right low-5-bit (bit0 = leftmost column)', () => {
    let g = EMPTY_GLYPH.slice();
    g = withBit(g, 0, 0, true); // top-left dot
    expect(g[0]).toBe(0b00001);
    g = withBit(g, 0, 4, true); // top-right dot
    expect(g[0]).toBe(0b10001);
    g = withBit(g, 0, 0, false); // erase top-left
    expect(g[0]).toBe(0b10000);
  });

  it('encode (withBit) round-trips through the preview decode (cellDots)', () => {
    // Draw a known pattern...
    let g = EMPTY_GLYPH.slice();
    g = withBit(g, 1, 0, true);
    g = withBit(g, 1, 2, true);
    g = withBit(g, 1, 4, true);
    // ...then decode it the SAME way the canvas does (user-glyph slot 0).
    const cell = cellDots(GLYPH_CODES[0], { '0': g });
    expect(cell[1]).toEqual([true, false, true, false, true]);
    expect(bitOf(g, 1, 0)).toBe(true);
    expect(bitOf(g, 1, 1)).toBe(false);
  });

  it('copyFromChar loads the real font bitmap (as a copy)', () => {
    const a = copyFromChar('A');
    expect(a).toEqual(FONT5x7['A'.charCodeAt(0)]);
    expect(a).not.toBe(FONT5x7['A'.charCodeAt(0)]); // mutating the editor won't touch the font
    expect(copyFromChar('')).toBeNull();
  });

  it('clear / normGlyph yield a clean 7-row low-5-bit glyph', () => {
    expect(EMPTY_GLYPH).toEqual([0, 0, 0, 0, 0, 0, 0]);
    expect(normGlyph(undefined)).toEqual([0, 0, 0, 0, 0, 0, 0]);
    expect(normGlyph([1, 2, 3])).toEqual([0, 0, 0, 0, 0, 0, 0]); // wrong length -> empty
    expect(normGlyph([0xff, 0, 0, 0, 0, 0, 0])[0]).toBe(0x1f); // masked to 5 bits
  });
});
