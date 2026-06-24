<script lang="ts">
  import { FONT5x7, GLYPH_CODES } from '../font5x7';
  import {
    appState,
    commitGlyph,
    draggedGlyph,
    glyphSync,
    loadGlyphFromLibrary,
    selectedGlyphSlot,
  } from '../stores';
  import { EMPTY_GLYPH, copyFromChar, normGlyph, withBit } from '../glyphedit';
  import { GLYPH_DND_TYPE } from '../dnd';
  import GlyphCanvas from './GlyphCanvas.svelte';

  // The slot currently hovered by a dragged library glyph (highlight).
  let dropSlot = -1;

  function onSlotDragOver(e: DragEvent, i: number): void {
    // Accept the drop iff a library glyph is being dragged. Gate on the SHARED
    // store (reliable across components) OR the dataTransfer type (custom-MIME
    // visibility during dragover is browser-dependent). preventDefault is
    // REQUIRED — without it the browser rejects the drop and never fires `drop`.
    const dragging =
      $draggedGlyph !== '' || !!e.dataTransfer?.types.includes(GLYPH_DND_TYPE);
    if (!dragging) return;
    e.preventDefault(); // mark as a valid drop target (load)
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
    dropSlot = i;
  }

  function onSlotDrop(e: DragEvent, i: number): void {
    e.preventDefault();
    dropSlot = -1;
    // dataTransfer first (works during `drop`), then the shared store fallback.
    const id = e.dataTransfer?.getData(GLYPH_DND_TYPE) || $draggedGlyph;
    draggedGlyph.set('');
    if (id) loadGlyphFromLibrary(i, id); // selects slot i + auto-pushes
  }

  const SLOTS = GLYPH_CODES.map((code, i) => ({
    i,
    code,
    token: `{g${i}}`,
  }));

  // Selected slot is shared (the glyph library loads into it).
  $: selected = $selectedGlyphSlot;

  // Live glyphs from the desired state. Derive reactively (NOT via a function
  // that hides $appState) so the strip + editor update when glyphs change.
  $: glyphMap = $appState?.glyphs ?? {};
  $: slotRows = SLOTS.map((s) => normGlyph(glyphMap[String(s.i)]));
  $: selectedRows = slotRows[selected];
  $: sync = $glyphSync;

  // --- editing (shared optimistic + debounced push) -----------------------
  function onPaint(
    e: CustomEvent<{ row: number; col: number; on: boolean }>,
  ): void {
    const { row, col, on } = e.detail;
    commitGlyph(selected, withBit(selectedRows, row, col, on));
  }

  function clearSlot(): void {
    commitGlyph(selected, EMPTY_GLYPH.slice());
  }

  let charInput = '';
  function loadChar(): void {
    const rows = copyFromChar(charInput.slice(0, 1));
    if (rows) commitGlyph(selected, rows);
  }
  $: charKnown =
    charInput.length > 0 && FONT5x7[charInput.charCodeAt(0)] !== undefined;

  // --- reference token ----------------------------------------------------
  let copied = false;
  async function copyToken(): Promise<void> {
    try {
      await navigator.clipboard.writeText(SLOTS[selected].token);
      copied = true;
      setTimeout(() => (copied = false), 1200);
    } catch {
      /* clipboard unavailable (insecure context) — token is shown anyway */
    }
  }
</script>

<section class="panel glyphs">
  <div class="panel__title">Glyph editor</div>

  <!-- slot strip -->
  <div class="strip" role="tablist" aria-label="glyph slots">
    {#each SLOTS as s}
      <button
        class="slot"
        class:selected={selected === s.i}
        class:dropping={dropSlot === s.i}
        role="tab"
        aria-selected={selected === s.i}
        title={`slot ${s.i} → code 0x${s.code.toString(16).toUpperCase()} (drop a library glyph here to load)`}
        on:click={() => selectedGlyphSlot.set(s.i)}
        on:dragover={(e) => onSlotDragOver(e, s.i)}
        on:dragleave={() => (dropSlot = dropSlot === s.i ? -1 : dropSlot)}
        on:drop={(e) => onSlotDrop(e, s.i)}
      >
        <span class="slot__thumb"><GlyphCanvas rows={slotRows[s.i]} dotSize={5} pitch={6} /></span>
        <span class="slot__label">
          g{s.i}
          <span
            class="syncdot"
            class:syncing={sync[s.i] === 'syncing'}
            class:synced={sync[s.i] === 'synced'}
            class:error={sync[s.i] === 'error'}
          ></span>
        </span>
      </button>
    {/each}
  </div>

  <!-- editor + tools -->
  <div class="editor">
    <div class="editor__grid">
      <GlyphCanvas
        rows={selectedRows}
        dotSize={22}
        pitch={32}
        interactive
        on:paint={onPaint}
      />
    </div>

    <div class="editor__tools">
      <div class="ref">
        <span>use <code>{SLOTS[selected].token}</code> in a message</span>
        <button class="btn btn--mini" on:click={copyToken}>
          {copied ? 'copied ✓' : 'copy'}
        </button>
      </div>

      <div class="tool">
        <span class="tool__label">seed from char</span>
        <div class="row">
          <input
            type="text"
            maxlength="1"
            bind:value={charInput}
            placeholder="A"
            spellcheck="false"
            on:keydown={(e) => e.key === 'Enter' && loadChar()}
          />
          <button class="btn btn--mini" on:click={loadChar} disabled={!charKnown}>
            load
          </button>
        </div>
      </div>

      <div class="tool">
        <button class="btn btn--mini" on:click={clearSlot}>Clear</button>
        <span class="sync-label">
          {#if sync[selected] === 'syncing'}syncing…
          {:else if sync[selected] === 'synced'}synced ✓
          {:else if sync[selected] === 'error'}sync failed
          {/if}
        </span>
      </div>
    </div>
  </div>

  <p class="field__hint">
    Click or drag to draw g{selected}. Edits auto-push to the daemon (~400 ms),
    which defines the glyph on the display; reference it in a message as
    <code>{SLOTS[selected].token}</code>.
  </p>
</section>

<style>
  /* slot strip */
  .strip {
    display: grid;
    grid-template-columns: repeat(9, 1fr);
    gap: 8px;
    margin-bottom: 16px;
  }

  .slot {
    appearance: none;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 5px;
    padding: 6px 4px;
    background: #04090a;
    border: 1px solid var(--bezel);
    border-radius: 5px;
    cursor: pointer;
    transition: border-color 0.12s, box-shadow 0.12s;
  }

  .slot:hover {
    border-color: var(--phosphor-dim);
  }

  .slot.selected {
    border-color: var(--phosphor);
    box-shadow: 0 0 0 1px var(--phosphor), 0 0 12px rgba(61, 240, 200, 0.18);
  }

  /* a dragged library glyph is hovering this slot — drop to load */
  .slot.dropping {
    border-color: var(--phosphor);
    box-shadow: 0 0 0 2px var(--phosphor), 0 0 16px rgba(61, 240, 200, 0.45);
  }

  .slot__thumb {
    display: block;
    width: 100%;
  }

  .slot__label {
    display: flex;
    align-items: center;
    gap: 5px;
    font-size: 10px;
    letter-spacing: 0.08em;
    color: var(--text-mute);
  }

  .syncdot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: transparent;
    transition: background 0.15s, box-shadow 0.15s;
  }
  .syncdot.syncing {
    background: var(--amber-warn);
    box-shadow: 0 0 6px var(--amber-warn);
  }
  .syncdot.synced {
    background: var(--phosphor);
    box-shadow: 0 0 6px var(--phosphor);
  }
  .syncdot.error {
    background: var(--red-dead);
    box-shadow: 0 0 6px var(--red-dead);
  }

  /* editor */
  .editor {
    display: grid;
    grid-template-columns: minmax(0, 1.1fr) 1fr;
    gap: 16px;
    align-items: start;
  }

  .editor__grid {
    background: #03090a;
    border: 1px solid var(--bezel);
    border-radius: 6px;
    padding: 8px;
    box-shadow: var(--shadow-inset);
  }

  .editor__tools {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  .ref {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    font-size: 12px;
    color: var(--text-mute);
  }

  .tool {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .tool__label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: var(--text-mute);
  }

  .tool .row {
    display: flex;
    gap: 8px;
    align-items: center;
  }

  .tool input[type='text'] {
    width: 48px;
    text-align: center;
  }

  .btn--mini {
    padding: 6px 12px;
    font-size: 11px;
  }

  .sync-label {
    font-size: 11px;
    letter-spacing: 0.06em;
    color: var(--text-faint);
    min-height: 14px;
  }

  code {
    color: var(--phosphor);
    background: #04090a;
    padding: 1px 5px;
    border-radius: 3px;
    border: 1px solid var(--rule);
    font-size: 11px;
  }

  @media (max-width: 560px) {
    .editor {
      grid-template-columns: 1fr;
    }
  }
</style>
