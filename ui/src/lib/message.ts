// Message helpers. The display is 2 lines x 20 chars; in message mode a '\n'
// splits top/bottom (the daemon's MessageFrame partitions on the first newline),
// so the real limit is 20 PER LINE, not 40 total.
//
// A {gN} placeholder (N=0..8) renders as ONE display cell (a custom glyph), so
// it must be COUNTED and fitted as a single cell — not its 4 literal characters.

export const LINE_WIDTH = 20;

// {g0}..{g8} — same tokens the daemon's apply_glyph_placeholders substitutes.
const GLYPH_TOKEN = /\{g[0-8]\}/g;

/** Collapse each {gN} placeholder to a single cell, for measuring/fitting. */
export function renderedText(message: string): string {
  return message.replace(GLYPH_TOKEN, '');
}

export interface LineBudget {
  /** Does the message contain a newline (i.e. an explicit top/bottom split)? */
  hasNewline: boolean;
  /** Char count of line 1 (everything before the first '\n', else the whole msg). */
  top: number;
  /** Char count of line 2 (everything after the first '\n'); 0 when no newline. */
  bottom: number;
  topOver: boolean;
  bottomOver: boolean;
}

/** Per-line RENDERED-cell budget, mirroring MessageFrame's split + {gN} cells. */
export function lineBudget(message: string): LineBudget {
  // Count rendered cells, not raw chars: each {gN} is one glyph cell, not 4.
  const m = renderedText(message);
  const nl = m.indexOf('\n');
  const hasNewline = nl >= 0;
  const top = hasNewline ? nl : m.length;
  const bottom = hasNewline ? m.length - nl - 1 : 0;
  return {
    hasNewline,
    top,
    bottom,
    topOver: top > LINE_WIDTH,
    bottomOver: bottom > LINE_WIDTH,
  };
}
