<script lang="ts">
  import { deleteGlyph, saveGlyph } from '../api';
  import {
    appState,
    commitGlyph,
    library,
    refreshLibrary,
    selectedGlyphSlot,
  } from '../stores';
  import { normGlyph } from '../glyphedit';
  import type { LibraryGlyph } from '../types';
  import GlyphCanvas from './GlyphCanvas.svelte';

  let busy = '';

  // Rows currently drawn in the selected editor slot (to save to the library).
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

  function loadIntoSelected(g: LibraryGlyph): void {
    // Goes through the shared optimistic + debounced push (same as drawing).
    commitGlyph($selectedGlyphSlot, normGlyph(g.rows));
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
        <div class="cell">
          <span class="cell__thumb"><GlyphCanvas rows={normGlyph(g.rows)} dotSize={5} pitch={6} /></span>
          <span class="cell__name" title={g.name}>{g.name}</span>
          <div class="cell__actions">
            <button
              class="btn btn--mini"
              disabled={busy !== ''}
              title={`load into g${$selectedGlyphSlot}`}
              on:click={() => loadIntoSelected(g)}
            >
              → g{$selectedGlyphSlot}
            </button>
            <button class="btn btn--mini btn--danger" disabled={busy !== ''} on:click={() => remove(g)}>
              ✕
            </button>
          </div>
        </div>
      {/each}
    </div>
    <p class="field__hint">
      9 <strong>slots</strong> are live hardware registers; the library is
      unlimited — load any saved glyph into the selected slot (g{$selectedGlyphSlot}).
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
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 5px;
    padding: 7px 5px;
    background: #04090a;
    border: 1px solid var(--bezel);
    border-radius: 5px;
  }

  .cell__thumb {
    display: block;
    width: 100%;
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

  .cell__actions {
    display: flex;
    gap: 4px;
  }

  .btn--mini {
    padding: 4px 7px;
    font-size: 10px;
  }

  strong {
    color: var(--phosphor);
    font-weight: 600;
  }
</style>
