import { describe, expect, it } from 'vitest';
import { GLYPH_DND_TYPE, reorderIds, rowsForGlyphId } from '../lib/dnd';
import type { LibraryGlyph } from '../lib/types';

const G = (id: string, rows: number[] = [0, 0, 0, 0, 0, 0, 0]): LibraryGlyph => ({
  id,
  name: id,
  rows,
});

describe('library drag-and-drop helpers', () => {
  it('exposes a stable DnD payload type', () => {
    expect(GLYPH_DND_TYPE).toBe('application/x-checkout-glyph');
  });

  it('reorderIds moves the dragged id to the target position', () => {
    expect(reorderIds(['a', 'b', 'c'], 'c', 'a')).toEqual(['c', 'a', 'b']);
    expect(reorderIds(['a', 'b', 'c'], 'a', 'c')).toEqual(['b', 'c', 'a']);
    expect(reorderIds(['a', 'b', 'c'], 'b', 'b')).toEqual(['a', 'b', 'c']); // no-op
  });

  it('reorderIds is a no-op for unknown ids (never drops items)', () => {
    expect(reorderIds(['a', 'b'], 'x', 'a')).toEqual(['a', 'b']);
    expect(reorderIds(['a', 'b'], 'a', 'x')).toEqual(['a', 'b']);
  });

  it('rowsForGlyphId looks up the dropped glyph (slot load handler)', () => {
    const glyphs = [G('a', [1, 0, 0, 0, 0, 0, 0]), G('b', [0, 31, 0, 0, 0, 0, 0])];
    expect(rowsForGlyphId(glyphs, 'b')).toEqual([0, 31, 0, 0, 0, 0, 0]);
    expect(rowsForGlyphId(glyphs, 'missing')).toBeNull();
  });
});
