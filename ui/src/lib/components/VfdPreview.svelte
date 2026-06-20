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

  // Logical geometry (px) — a true 2x20 of 5x7 cells.
  const DOT = 6;
  const DGAP = 3;
  const CGAP_X = 10;
  const CGAP_Y = 18;
  const MARGIN = 22;
  const cellW = CELL_COLS * DOT + (CELL_COLS - 1) * DGAP;
  const cellH = CELL_ROWS * DOT + (CELL_ROWS - 1) * DGAP;
  const W = MARGIN * 2 + LINE_LEN * cellW + (LINE_LEN - 1) * CGAP_X;
  const H = MARGIN * 2 + 2 * cellH + CGAP_Y;

  let canvas: HTMLCanvasElement;
  let ctx: CanvasRenderingContext2D | null = null;
  let ro: ResizeObserver | undefined;
  let lastCssW = -1;
  let selfChecked = false;

  onMount(() => {
    // Init order: get the 2D context, size the buffer, THEN draw. Drawing into
    // an unsized (0x0) canvas paints nothing — size first.
    ctx = canvas.getContext('2d');
    resize();
    // Re-size + redraw when the element's box changes (responsive + crisp).
    ro = new ResizeObserver(() => resize());
    ro.observe(canvas);
    return () => ro?.disconnect();
  });

  /** Size the drawing buffer to the rendered width (×dpr) and redraw. */
  function resize(): void {
    if (!canvas || !ctx) return;
    const cssW = canvas.clientWidth || W; // rendered CSS px (fallback pre-layout)
    if (cssW === lastCssW) {
      draw();
      return;
    }
    lastCssW = cssW;
    const dpr = window.devicePixelRatio || 1;
    const cssH = (cssW * H) / W; // preserve the 2x20 aspect
    // Explicit CSS height so the element never collapses to 0; buffer is dpr-scaled.
    canvas.style.height = `${cssH}px`;
    canvas.width = Math.max(1, Math.round(cssW * dpr));
    canvas.height = Math.max(1, Math.round(cssH * dpr));
    // Map logical (W x H) coords -> device pixels (setting width above reset the
    // transform, so set it fresh — never accumulate).
    const s = (cssW / W) * dpr;
    ctx.setTransform(s, 0, 0, s, 0, 0);
    draw();
  }

  // Redraw whenever the mirrored status or glyph bitmaps change (every poll).
  $: if (ctx) {
    void status;
    void glyphs;
    draw();
  }

  function dot(x: number, y: number, r: number): void {
    if (r <= 0) return;
    ctx!.beginPath();
    ctx!.arc(x, y, r, 0, Math.PI * 2);
    ctx!.fill();
  }

  function draw(): void {
    if (!ctx) return;
    const blank = !!status?.blank;
    const top = blank ? '' : status?.top ?? '';
    const bottom = blank ? '' : status?.bottom ?? '';
    const bright = status?.brightness !== 'dim';

    // Glass backdrop (logical coords; the transform maps them to the buffer).
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#03090a';
    ctx.fillRect(0, 0, W, H);

    const lines = [top, bottom].map((l) => lineToCells(l, glyphs));
    const litFill = bright ? '#8ffbe4' : '#36d8b4';
    const litBlur = bright ? 13 : 7;
    let litDots = 0;

    for (let li = 0; li < 2; li++) {
      const cells = lines[li];
      for (let ci = 0; ci < LINE_LEN; ci++) {
        const cell = cells[ci];
        const cx0 = MARGIN + ci * (cellW + CGAP_X);
        const cy0 = MARGIN + li * (cellH + CGAP_Y);
        for (let r = 0; r < CELL_ROWS; r++) {
          for (let c = 0; c < CELL_COLS; c++) {
            const x = cx0 + c * (DOT + DGAP) + DOT / 2;
            const y = cy0 + r * (DOT + DGAP) + DOT / 2;
            if (cell[r][c]) {
              litDots++;
              ctx.save();
              ctx.shadowColor = '#3df0c8';
              ctx.shadowBlur = litBlur;
              ctx.fillStyle = litFill;
              dot(x, y, DOT / 2);
              // a brighter core for bloom
              ctx.shadowBlur = 0;
              ctx.fillStyle = bright ? '#d8fff4' : '#9af0dc';
              dot(x, y, DOT / 2 - 1.6);
              ctx.restore();
            } else {
              // Unlit phosphor — a faint resting dot.
              ctx.fillStyle = 'rgba(61, 240, 200, 0.055)';
              dot(x, y, DOT / 2 - 0.4);
            }
          }
        }
      }
    }

    // Dev self-check: confirm the first non-empty frame actually lit dots.
    if (import.meta.env.DEV && !selfChecked && (top + bottom).trim()) {
      selfChecked = true;
      // eslint-disable-next-line no-console
      console.info(
        `[VfdPreview] first frame rendered: ${litDots} lit dots, ` +
          `buffer ${canvas.width}x${canvas.height}`,
      );
      if (litDots === 0) {
        // eslint-disable-next-line no-console
        console.warn('[VfdPreview] non-empty status but 0 lit dots — check font/data');
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
