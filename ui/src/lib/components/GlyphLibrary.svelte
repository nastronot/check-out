<script lang="ts">
  import { deleteGlyph, saveGlyph } from '../api';
  import {
    appState,
    library,
    loadGlyphFromLibrary,
    refreshLibrary,
    reorderLibraryGlyphs,
    selectedGlyphSlot,
  } from '../stores';
  import { normGlyph } from '../glyphedit';
  import { GLYPH_DND_TYPE, reorderIds } from '../dnd';
  import type { LibraryGlyph } from '../types';
  import GlyphCanvas from './GlyphCanvas.svelte';

  let busy = '';
  let dragId = '';      // glyph being dragged
  let dragOverId = '';  // card currently hovered as a reorder target

  $: selectedRows = normGlyph($appState?.glyphs?.[String($selectedGlyphSlot)]);

  async function saveCurrentSlot(): Promise<void> {
    const name = window
      .prompt(`Save g${$selectedGlyphSlot} to the glyph library as:`)
      ?.trim();
    if (!name) return;
    busy = 'save';
    try {
      await saveGlyph(name, selectedRows);
      await refreshLibrary();
    } finally {
      busy = '';
    }
  }

  // Click/tap fallback: load this glyph into the currently-selected slot.
  function loadIntoSelected(g: LibraryGlyph): void {
    loadGlyphFromLibrary($selectedGlyphSlot, g.id);
  }

  async function remove(g: LibraryGlyph): Promise<void> {
    if (!window.confirm(`Delete saved glyph "${g.name}"?`)) return;
    busy = g.id;
    try {
      await deleteGlyph(g.id);
      await refreshLibrary();
    } finally {
      busy = '';
    }
  }

  // --- drag to reorder (within the library) ---
  function onDragStart(e: DragEvent, g: LibraryGlyph): void {
    dragId = g.id;
    e.dataTransfer?.setData(GLYPH_DND_TYPE, g.id);
    e.dataTransfer?.setData('text/plain', g.id); // fallback type
    if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move';
  }

  function onDragOverCard(e: DragEvent, g: LibraryGlyph): void {
    if (!dragId || dragId === g.id) return;
    e.preventDefault(); // allow drop
    dragOverId = g.id;
  }

  async function onDropCard(e: DragEvent, g: LibraryGlyph): Promise<void> {
    e.preventDefault();
    const id = e.dataTransfer?.getData(GLYPH_DND_TYPE) || dragId;
    dragOverId = '';
    if (!id || id === g.id) return;
    const ids = reorderIds($library.glyphs.map((x) => x.id), id, g.id);
    await reorderLibraryGlyphs(ids);
  }

  function onDragEnd(): void {
    dragId = '';
    dragOverId = '';
  }
</script>

<section class="panel">
  <div class="panel__title">
    Glyph library
    <button class="btn btn--mini" disabled={busy !== ''} on:click={saveCurrentSlot}>
      Save g{$selectedGlyphSlot}
    </button>
  </div>

  {#if $library.glyphs.length === 0}
    <p class="field__hint">
      No saved glyphs yet. The 9 <strong>slots</strong> are the live hardware
      registers; this <strong>library</strong> is unlimited saved bitmaps you load
      into a slot.
    </p>
  {:else}
    <div class="grid">
      {#each $library.glyphs as g (g.id)}
        <div
          class="cell"
          class:dragging={dragId === g.id}
          class:dropover={dragOverId === g.id}
          draggable="true"
          role="button"
          tabindex="0"
          aria-label={`${g.name} — load into g${$selectedGlyphSlot}, or drag onto a slot`}
          title={`Click to load into g${$selectedGlyphSlot}; drag onto a slot to target it, or drag here to reorder`}
          on:click={() => loadIntoSelected(g)}
          on:keydown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), loadIntoSelected(g))}
          on:dragstart={(e) => onDragStart(e, g)}
          on:dragover={(e) => onDragOverCard(e, g)}
          on:drop={(e) => onDropCard(e, g)}
          on:dragend={onDragEnd}
        >
          <span class="cell__thumb"><GlyphCanvas rows={normGlyph(g.rows)} dotSize={5} pitch={6} /></span>
          <span class="cell__name" title={g.name}>{g.name}</span>
          <button
            class="cell__del btn btn--mini btn--danger"
            disabled={busy !== ''}
            title="delete"
            on:click|stopPropagation={() => remove(g)}
          >
            ✕
          </button>
        </div>
      {/each}
    </div>
    <p class="field__hint">
      <strong>Drag</strong> a glyph onto a slot (g0–g8) to load it there, or drag
      within the library to reorder. <strong>Click</strong> a glyph to load it into
      the selected slot (g{$selectedGlyphSlot}). 9 slots are live hardware registers;
      the library is unlimited.
    </p>
  {/if}
</section>

<style>
  .panel__title {
    justify-content: space-between;
  }

  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(76px, 1fr));
    gap: 10px;
  }

  .cell {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 5px;
    padding: 7px 5px;
    background: #04090a;
    border: 1px solid var(--bezel);
    border-radius: 5px;
    cursor: grab;
    transition: border-color 0.12s, box-shadow 0.12s, opacity 0.12s;
  }

  .cell:hover {
    border-color: var(--phosphor-dim);
  }

  .cell:focus-visible {
    outline: none;
    border-color: var(--phosphor);
    box-shadow: 0 0 0 1px var(--phosphor);
  }

  .cell.dragging {
    opacity: 0.4;
    cursor: grabbing;
  }

  /* reorder drop target */
  .cell.dropover {
    border-color: var(--phosphor);
    box-shadow: -3px 0 0 -1px var(--phosphor), 0 0 10px rgba(61, 240, 200, 0.25);
  }

  .cell__thumb {
    display: block;
    width: 100%;
    pointer-events: none; /* so the whole card is the drag handle */
  }

  .cell__name {
    font-size: 10px;
    letter-spacing: 0.04em;
    color: var(--text-mute);
    max-width: 100%;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .cell__del {
    position: absolute;
    top: 3px;
    right: 3px;
    padding: 1px 5px;
    font-size: 10px;
    line-height: 1.4;
    opacity: 0;
    transition: opacity 0.12s;
  }

  .cell:hover .cell__del,
  .cell:focus-within .cell__del {
    opacity: 1;
  }

  strong {
    color: var(--phosphor);
    font-weight: 600;
  }
</style>
