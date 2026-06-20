<script lang="ts">
  import { onMount } from 'svelte';
  import {
    CELL_COLS,
    CELL_ROWS,
    LINE_LEN,
    lineToCells,
  } from '../font5x7';
  import type { GlyphMap, Status } from '../types';

  export let status: Status | null = null;
  export let glyphs: GlyphMap = {};

  // --- Preview dot geometry (logical px; the canvas is dpr-scaled to fit) -----
  // All tunable in one place — nudge to match the real glass. The two spacings
  // are deliberately SEPARATE so the within-glyph dot pitch can be tightened
  // without changing the gap between characters.
  const DOT_SIZE = 5.4; // edge length of each (square) dot — real VFD dots are square
  const DOT_CORNER = 1.2; // corner radius; the panel's square dots are slightly rounded
  const DOT_PITCH_X = 5; // center-to-center of adjacent dots WITHIN a glyph (X) — tight
  const DOT_PITCH_Y = 7; // center-to-center of adjacent dots WITHIN a glyph (Y) — tight
  const CELL_GAP_X = 16; // center gap from a glyph's last col to the next glyph's first
  //                        col — the CHARACTER spacing (kept as before, looks right)
  const ROW_GAP_Y = 22; // center gap from the top line's bottom row to the bottom
  //                       line's top row — keeps the two text rows readable
  const MARGIN = 16; // dark border around the whole dot matrix

  // Cell-to-cell / line-to-line advances (col0->col0 of the next cell/row).
  const ADVANCE_X = (CELL_COLS - 1) * DOT_PITCH_X + CELL_GAP_X;
  const ADVANCE_Y = (CELL_ROWS - 1) * DOT_PITCH_Y + ROW_GAP_Y;
  const ORIGIN = MARGIN + DOT_SIZE / 2; // center of the top-left dot
  const W =
    2 * MARGIN + DOT_SIZE +
    (LINE_LEN - 1) * ADVANCE_X + (CELL_COLS - 1) * DOT_PITCH_X;
  const H =
    2 * MARGIN + DOT_SIZE + (2 - 1) * ADVANCE_Y + (CELL_ROWS - 1) * DOT_PITCH_Y;

  let canvas: HTMLCanvasElement;
  let ctx: CanvasRenderingContext2D | null = null;
  let ro: ResizeObserver | undefined;
  let lastCssW = -1;
  let logged = false;

  // Derived draw inputs as their OWN reactive statements, passed explicitly to
  // drawFrame() below. This makes the redraw's dependency on status/glyphs
  // UNAMBIGUOUS: the previous `$: { void status; draw(); }` relied on a no-op
  // expression that a minifier can strip, which left the canvas frozen on its
  // first (empty) frame in the production build.
  $: blank = !!status?.blank;
  $: top = blank ? '' : status?.top ?? '';
  $: bottom = blank ? '' : status?.bottom ?? '';
  $: bright = status?.brightness !== 'dim';

  onMount(() => {
    // Init order: get the 2D context, size the buffer, THEN draw. Drawing into
    // an unsized (0x0) canvas paints nothing — size first.
    ctx = canvas.getContext('2d');
    sizeAndDraw();
    // Re-size + redraw when the element's box changes (responsive + crisp).
    ro = new ResizeObserver(() => sizeAndDraw());
    ro.observe(canvas);
    return () => ro?.disconnect();
  });

  // Redraw whenever the mirrored data changes (every poll / glyph edit).
  $: if (ctx) drawFrame(top, bottom, bright, glyphs);

  /** Size the drawing buffer to the rendered width (×dpr), then draw. */
  function sizeAndDraw(): void {
    if (!canvas || !ctx) return;
    const cssW = canvas.clientWidth || W; // rendered CSS px (fallback pre-layout)
    if (cssW !== lastCssW) {
      lastCssW = cssW;
      const dpr = window.devicePixelRatio || 1;
      const cssH = (cssW * H) / W; // preserve the 2x20 aspect
      // Explicit CSS height so the element never collapses to 0; buffer dpr-scaled.
      canvas.style.height = `${cssH}px`;
      canvas.width = Math.max(1, Math.round(cssW * dpr));
      canvas.height = Math.max(1, Math.round(cssH * dpr));
      // Map logical (W x H) coords -> device pixels. Setting width above reset
      // the transform, so set it fresh — never accumulate.
      const s = (cssW / W) * dpr;
      ctx.setTransform(s, 0, 0, s, 0, 0);
    }
    drawFrame(top, bottom, bright, glyphs);
  }

  /** A square dot (slightly rounded), centered at (x, y) — matches the panel. */
  function dotSquare(x: number, y: number, size: number): void {
    if (size <= 0 || !ctx) return;
    const half = size / 2;
    ctx.beginPath();
    ctx.roundRect(x - half, y - half, size, size, Math.min(DOT_CORNER, half));
    ctx.fill();
  }

  function drawFrame(
    topLine: string,
    bottomLine: string,
    isBright: boolean,
    glyphMap: GlyphMap,
  ): void {
    if (!ctx) return;

    // Glass backdrop (logical coords; the transform maps them to the buffer).
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#03090a';
    ctx.fillRect(0, 0, W, H);

    const lines = [topLine, bottomLine].map((l) => lineToCells(l, glyphMap));
    const litFill = isBright ? '#8ffbe4' : '#36d8b4';
    // Bloom kept modest so tight square dots stay distinct, not merged.
    const litBlur = isBright ? 10 : 6;
    let litDots = 0;

    for (let li = 0; li < 2; li++) {
      const cells = lines[li];
      for (let ci = 0; ci < LINE_LEN; ci++) {
        const cell = cells[ci];
        const cx0 = ORIGIN + ci * ADVANCE_X;
        const cy0 = ORIGIN + li * ADVANCE_Y;
        for (let r = 0; r < CELL_ROWS; r++) {
          for (let c = 0; c < CELL_COLS; c++) {
            const x = cx0 + c * DOT_PITCH_X;
            const y = cy0 + r * DOT_PITCH_Y;
            if (cell[r][c]) {
              litDots++;
              ctx.save();
              ctx.shadowColor = '#3df0c8';
              ctx.shadowBlur = litBlur;
              ctx.fillStyle = litFill;
              dotSquare(x, y, DOT_SIZE);
              // a brighter inner core for bloom
              ctx.shadowBlur = 0;
              ctx.fillStyle = isBright ? '#d8fff4' : '#9af0dc';
              dotSquare(x, y, DOT_SIZE - 2.4);
              ctx.restore();
            } else {
              // Unlit phosphor — a faint resting dot.
              ctx.fillStyle = 'rgba(61, 240, 200, 0.055)';
              dotSquare(x, y, DOT_SIZE - 0.6);
            }
          }
        }
      }
    }

    // First-frame diagnostic — UN-GATED for v0.4.3 (runs in the prod build too,
    // so it reports whatever uvicorn serves). Re-gate to DEV once confirmed.
    if (!logged && (topLine + bottomLine).trim()) {
      logged = true;
      // eslint-disable-next-line no-console
      console.info(
        `[VfdPreview] first frame: top=${JSON.stringify(topLine)} ` +
          `bottom=${JSON.stringify(bottomLine)} lit=${litDots} ` +
          `buffer=${canvas.width}x${canvas.height}`,
      );
      if (litDots === 0) {
        // eslint-disable-next-line no-console
        console.warn(
          '[VfdPreview] non-empty status but 0 lit dots — check font/data',
        );
      }
    }
  }
</script>

<div class="vfd" class:vfd--blank={status?.blank}>
  <div class="vfd__glass">
    <canvas
      bind:this={canvas}
      style="aspect-ratio: {W} / {H};"
      aria-hidden="true"
    ></canvas>
    <div class="vfd__scan" aria-hidden="true"></div>
    <div class="vfd__bloom" aria-hidden="true"></div>
  </div>
  <div class="vfd__caption">
    <span class="tag">IBM SUREPOS 2×20 VFD</span>
    <span class="vfd__cap-right">
      {status?.blank ? 'BLANK' : (status?.brightness ?? '—').toUpperCase()}
    </span>
  </div>
</div>

<style>
  .vfd {
    --frame: #11191a;
    background: linear-gradient(180deg, #161f20, #0a1213);
    border: 1px solid var(--bezel-hi);
    border-radius: 12px;
    padding: 16px 16px 12px;
    box-shadow:
      var(--shadow-inset),
      0 8px 30px rgba(0, 0, 0, 0.6);
  }

  .vfd__glass {
    position: relative;
    border-radius: 7px;
    overflow: hidden;
    background: #03090a;
    border: 1px solid #000;
    box-shadow: inset 0 0 36px rgba(0, 0, 0, 0.9);
  }

  canvas {
    display: block;
    width: 100%;
    /* JS sets an explicit pixel height (and the dpr-scaled buffer) on mount /
       resize; the inline aspect-ratio is only a fallback for the first paint. */
  }

  /* faint scanlines — preview only */
  .vfd__scan {
    position: absolute;
    inset: 0;
    pointer-events: none;
    background: repeating-linear-gradient(
      to bottom,
      rgba(0, 0, 0, 0) 0px,
      rgba(0, 0, 0, 0) 2px,
      rgba(0, 0, 0, 0.22) 3px
    );
    mix-blend-mode: multiply;
  }

  /* soft phosphor bloom hugging the glass */
  .vfd__bloom {
    position: absolute;
    inset: 0;
    pointer-events: none;
    background: radial-gradient(
      120% 90% at 50% 40%,
      rgba(61, 240, 200, 0.08),
      rgba(61, 240, 200, 0) 70%
    );
  }

  .vfd--blank .vfd__bloom {
    opacity: 0.15;
  }

  .vfd__caption {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 10px;
  }

  .vfd__cap-right {
    font-size: 10px;
    letter-spacing: 0.18em;
    color: var(--text-mute);
  }
</style>
