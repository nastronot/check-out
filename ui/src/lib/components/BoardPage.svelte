<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import VfdPreview from './VfdPreview.svelte';
  import ControlPanel from './ControlPanel.svelte';
  import DisplayPanel from './DisplayPanel.svelte';
  import GlyphEditorPanel from './GlyphEditorPanel.svelte';
  import SavedMessages from './SavedMessages.svelte';
  import GlyphLibrary from './GlyphLibrary.svelte';
  import {
    appState,
    health,
    loadState,
    patchState,
    refreshLibrary,
    startPolling,
    status,
    stopPolling,
  } from '../stores';

  onMount(() => {
    void loadState();
    void refreshLibrary();
    startPolling(500);
  });
  onDestroy(stopPolling);

  // Preview mirrors /api/status. Glyph bitmaps: a mode's own set when one is
  // loaded (weather), else the user's glyphs from the desired state (immediate
  // while editing).
  $: glyphs = $status?.mode_glyphs ?? $appState?.glyphs ?? {};
</script>

<main class="layout">
  <!-- LEFT column: one flex stack so the two columns size INDEPENDENTLY. A
       previous 2-row grid let the tall right column (controls) span both rows
       and distribute its excess height into the left rows, leaving a big empty
       gap under the fixed-size preview. One column = one stack = no inflation. -->
  <div class="layout__left">
    <div class="layout__preview">
      <VfdPreview status={$status} {glyphs} />
    </div>
    <div class="layout__glyphs">
      <GlyphEditorPanel />
      <GlyphLibrary />
    </div>
  </div>

  <div class="layout__controls">
    <ControlPanel state={$appState} status={$status} patch={patchState} />
    <SavedMessages />
    <!-- Display = device settings + commands + daemon readout, in one panel -->
    <DisplayPanel state={$appState} status={$status} health={$health} patch={patchState} />
  </div>
</main>

<style>
  .layout {
    display: grid;
    grid-template-columns: 1.25fr 1fr;
    gap: 20px;
    /* Each column is its OWN flex stack and aligns to the top; the taller column
       sets the container height and the shorter one is NOT stretched, so neither
       column gets dead space injected between its panels. */
    align-items: start;
  }

  .layout__left,
  .layout__controls,
  .layout__glyphs {
    display: flex;
    flex-direction: column;
    gap: 20px;
    min-width: 0; /* let the column shrink instead of overflowing on narrow widths */
  }

  /* The preview keeps a fixed 2×20 aspect (set on the canvas); this wrapper adds
     no extra height, so the preview box stays a constant size across mode/status
     changes — no layout jump. */
  .layout__preview {
    display: flex;
    flex-direction: column;
  }

  @media (max-width: 860px) {
    .layout {
      grid-template-columns: 1fr;
    }
    /* Flatten the left column into the grid so its children can interleave with
       controls, then order them: preview → controls → glyph editor+library
       (controls are the primary interaction, so they sit right under preview). */
    .layout__left {
      display: contents;
    }
    .layout__preview {
      order: 1;
    }
    .layout__controls {
      order: 2;
    }
    .layout__glyphs {
      order: 3;
    }
  }
</style>
