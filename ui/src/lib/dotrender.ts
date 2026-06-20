// Shared phosphor dot rendering. ONE square-dot look used by both the main
// VfdPreview and the glyph editor (slot thumbnails + draw grid), so they match
// dot-for-dot. Geometry (pitch/gaps) is the caller's job; this only paints one
// dot in the panel's blue-green phosphor with the bloom + faint-unlit treatment.

export const PHOSPHOR = '#3df0c8';
export const GLASS_BG = '#03090a';

const UNLIT = 'rgba(61, 240, 200, 0.055)';
const CORNER = 1.2; // dots are square but very slightly rounded, like the glass

// FOUR phosphor intensities, indexed by the display's brightness level 0..3
// (0 Minimum .. 3 Maximum). Each step raises the dot/core lightness and bloom so
// the preview visibly tracks the chosen level — subtle but distinguishable.
export interface Intensity {
  main: string;
  core: string;
  blur: number;
}
const INTENSITIES: Intensity[] = [
  { main: '#2bbf9c', core: '#7fe6cf', blur: 4 }, // 0 Minimum
  { main: '#34d4ad', core: '#9af0dc', blur: 6 }, // 1 Medium
  { main: '#5fe9c6', core: '#bcf7e6', blur: 8 }, // 2 AboveMedium
  { main: '#8ffbe4', core: '#d8fff4', blur: 11 }, // 3 Maximum
];

/** Clamp/resolve a brightness level (0..3) to its phosphor intensity. */
export function intensityForLevel(level: number): Intensity {
  const i = Math.max(0, Math.min(INTENSITIES.length - 1, Math.round(level)));
  return INTENSITIES[i];
}

export interface CellStyle {
  /** Edge length of the (square) dot, in the ctx's current units. */
  dotSize: number;
  /** Display brightness level 0..3 (default 3 = Maximum). */
  level?: number;
  /** Bloom radius (shadowBlur) override; defaults to the level's bloom. */
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
  const ink = intensityForLevel(style.level ?? 3);
  if (lit) {
    ctx.save();
    ctx.shadowColor = PHOSPHOR;
    ctx.shadowBlur = style.blur ?? ink.blur;
    square(ctx, x, y, style.dotSize, ink.main);
    // brighter inner core for the bloom
    ctx.shadowBlur = 0;
    square(ctx, x, y, style.dotSize - 2.4, ink.core);
    ctx.restore();
  } else {
    // Unlit phosphor — a faint resting dot.
    square(ctx, x, y, style.dotSize - 0.6, UNLIT);
  }
}
