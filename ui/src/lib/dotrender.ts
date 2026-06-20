// Shared phosphor dot rendering. ONE square-dot look used by both the main
// VfdPreview and the glyph editor (slot thumbnails + draw grid), so they match
// dot-for-dot. Geometry (pitch/gaps) is the caller's job; this only paints one
// dot in the panel's blue-green phosphor with the bloom + faint-unlit treatment.

export const PHOSPHOR = '#3df0c8';
export const GLASS_BG = '#03090a';

const LIT_MAIN_BRIGHT = '#8ffbe4';
const LIT_MAIN_DIM = '#36d8b4';
const LIT_CORE_BRIGHT = '#d8fff4';
const LIT_CORE_DIM = '#9af0dc';
const UNLIT = 'rgba(61, 240, 200, 0.055)';
const CORNER = 1.2; // dots are square but very slightly rounded, like the glass

export interface CellStyle {
  /** Edge length of the (square) dot, in the ctx's current units. */
  dotSize: number;
  /** Bright vs dim phosphor (mirrors the display's two brightness levels). */
  bright?: boolean;
  /** Bloom radius (shadowBlur); defaults scale with brightness. */
  blur?: number;
}

function square(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  size: number,
  color: string,
): void {
  if (size <= 0) return;
  const h = size / 2;
  ctx.beginPath();
  ctx.roundRect(x - h, y - h, size, size, Math.min(CORNER, h));
  ctx.fillStyle = color;
  ctx.fill();
}

/** Paint one cell centered at (x, y): a glowing square if lit, a faint one if not. */
export function paintCell(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  lit: boolean,
  style: CellStyle,
): void {
  const bright = style.bright ?? true;
  if (lit) {
    ctx.save();
    ctx.shadowColor = PHOSPHOR;
    ctx.shadowBlur = style.blur ?? (bright ? 10 : 6);
    square(ctx, x, y, style.dotSize, bright ? LIT_MAIN_BRIGHT : LIT_MAIN_DIM);
    // brighter inner core for the bloom
    ctx.shadowBlur = 0;
    square(ctx, x, y, style.dotSize - 2.4, bright ? LIT_CORE_BRIGHT : LIT_CORE_DIM);
    ctx.restore();
  } else {
    // Unlit phosphor — a faint resting dot.
    square(ctx, x, y, style.dotSize - 0.6, UNLIT);
  }
}
