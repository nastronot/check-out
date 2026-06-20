<script lang="ts">
  import { createEventDispatcher, onMount } from 'svelte';
  import { CELL_COLS, CELL_ROWS } from '../font5x7';
  import { GLASS_BG, paintCell } from '../dotrender';
  import { bitOf } from '../glyphedit';

  /** 7 row ints (low-5-bit). */
  export let rows: number[] = [0, 0, 0, 0, 0, 0, 0];
  /** Square dot edge length (logical px). */
  export let dotSize = 6;
  /** Center-to-center dot pitch (logical px). */
  export let pitch = 8;
  export let bright = true;
  /** When true, pointer-drag paints cells and emits `paint` events. */
  export let interactive = false;

  const dispatch = createEventDispatcher<{
    paint: { row: number; col: number; on: boolean };
  }>();

  // Logical geometry — same shape formula as the main preview.
  $: PAD = Math.max(3, dotSize * 0.5);
  $: ORIGIN = PAD + dotSize / 2;
  $: W = 2 * PAD + dotSize + (CELL_COLS - 1) * pitch;
  $: H = 2 * PAD + dotSize + (CELL_ROWS - 1) * pitch;

  let canvas: HTMLCanvasElement;
  let ctx: CanvasRenderingContext2D | null = null;
  let ro: ResizeObserver | undefined;
  let lastCssW = -1;

  onMount(() => {
    ctx = canvas.getContext('2d');
    sizeAndDraw();
    ro = new ResizeObserver(() => sizeAndDraw());
    ro.observe(canvas);
    return () => ro?.disconnect();
  });

  // Redraw on data change (explicit deps so it survives minification).
  $: if (ctx) draw(rows, bright);

  function sizeAndDraw(): void {
    if (!canvas || !ctx) return;
    const cssW = canvas.clientWidth || W;
    if (cssW !== lastCssW) {
      lastCssW = cssW;
      const dpr = window.devicePixelRatio || 1;
      const cssH = (cssW * H) / W;
      canvas.style.height = `${cssH}px`;
      canvas.width = Math.max(1, Math.round(cssW * dpr));
      canvas.height = Math.max(1, Math.round(cssH * dpr));
      const s = (cssW / W) * dpr;
      ctx.setTransform(s, 0, 0, s, 0, 0);
    }
    draw(rows, bright);
  }

  function draw(g: number[], isBright: boolean): void {
    if (!ctx) return;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = GLASS_BG;
    ctx.fillRect(0, 0, W, H);
    for (let r = 0; r < CELL_ROWS; r++) {
      for (let c = 0; c < CELL_COLS; c++) {
        const x = ORIGIN + c * pitch;
        const y = ORIGIN + r * pitch;
        paintCell(ctx, x, y, bitOf(g, r, c), { dotSize, bright: isBright });
      }
    }
  }

  // --- interaction (click + click-drag paint) ---
  let painting = false;
  let paintVal = true;
  let lastKey = '';

  function cellAt(ev: PointerEvent): { row: number; col: number } | null {
    const rect = canvas.getBoundingClientRect();
    const lx = ((ev.clientX - rect.left) / rect.width) * W;
    const ly = ((ev.clientY - rect.top) / rect.height) * H;
    const col = Math.round((lx - ORIGIN) / pitch);
    const row = Math.round((ly - ORIGIN) / pitch);
    if (col < 0 || col >= CELL_COLS || row < 0 || row >= CELL_ROWS) return null;
    return { row, col };
  }

  function onDown(ev: PointerEvent): void {
    if (!interactive) return;
    const cell = cellAt(ev);
    if (!cell) return;
    ev.preventDefault();
    try {
      canvas.setPointerCapture(ev.pointerId);
    } catch {
      /* not all environments support capture */
    }
    painting = true;
    // Paint value comes from the FIRST cell: lit -> erase, empty -> paint.
    paintVal = !bitOf(rows, cell.row, cell.col);
    lastKey = `${cell.row},${cell.col}`;
    dispatch('paint', { row: cell.row, col: cell.col, on: paintVal });
  }

  function onMove(ev: PointerEvent): void {
    if (!interactive || !painting) return;
    const cell = cellAt(ev);
    if (!cell) return;
    const key = `${cell.row},${cell.col}`;
    if (key === lastKey) return; // don't re-emit for the same cell
    lastKey = key;
    dispatch('paint', { row: cell.row, col: cell.col, on: paintVal });
  }

  function onUp(ev: PointerEvent): void {
    if (!painting) return;
    painting = false;
    lastKey = '';
    try {
      canvas.releasePointerCapture(ev.pointerId);
    } catch {
      /* ignore */
    }
  }
</script>

<!-- svelte-ignore a11y-no-static-element-interactions -->
<canvas
  bind:this={canvas}
  class:interactive
  style="aspect-ratio: {W} / {H};"
  aria-hidden="true"
  on:pointerdown={onDown}
  on:pointermove={onMove}
  on:pointerup={onUp}
  on:pointercancel={onUp}
></canvas>

<style>
  canvas {
    display: block;
    width: 100%;
    border-radius: 3px;
  }
  canvas.interactive {
    cursor: crosshair;
    touch-action: none; /* let us handle drag without the page scrolling */
  }
</style>
