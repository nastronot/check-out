<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import VfdPreview from './VfdPreview.svelte';
  import ControlPanel from './ControlPanel.svelte';
  import CommandBar from './CommandBar.svelte';
  import DisplaySettings from './DisplaySettings.svelte';
  import GlyphEditorPanel from './GlyphEditorPanel.svelte';
  import SavedMessages from './SavedMessages.svelte';
  import GlyphLibrary from './GlyphLibrary.svelte';
  import NewsFeeds from './NewsFeeds.svelte';
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
  // The feeds list only matters while news alerts can play.
  $: showFeeds = $appState?.mode === 'dynamic' && $appState.news_enabled;
</script>

<!-- One grid, two shapes (see the style block): a wide monitor puts the glass
     and glyph tools, Control, and the side lists in three columns; a portrait
     monitor stacks the glass, then Control beside the lists, then the glyph
     tools. Each area is its own flex stack aligned to the top, so a tall area
     never stretches a short one. -->
<main class="layout">
  <div class="area area--preview">
    <VfdPreview status={$status} {glyphs} alive={$health.daemon_alive} />
  </div>

  <div class="area area--control">
    <!-- One Control panel: mode + its settings, then the device (brightness,
         blank); Self-test / Reset sit small in its header. -->
    <ControlPanel state={$appState} status={$status} patch={patchState}>
      <CommandBar slot="actions" />
      <DisplaySettings state={$appState} patch={patchState} />
    </ControlPanel>
  </div>

  <div class="area area--side">
    <SavedMessages />
    {#if showFeeds}
      <NewsFeeds state={$appState} status={$status} />
    {/if}
  </div>

  <div class="area area--editor"><GlyphEditorPanel /></div>
  <div class="area area--library"><GlyphLibrary /></div>
</main>

<style>
  /* Portrait side monitors (about 1024-1080 wide): two columns. */
  .layout {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    grid-template-areas:
      'preview preview'
      'control side'
      'editor  library';
    gap: 18px;
    align-items: start;
  }

  /* The main monitor (2048 wide): three columns, the whole page on one screen.
     Glass + glyph tools | Control | saved messages + news feeds. The last row
     takes any spare height, so the editor never gets stretched. */
  @media (min-width: 1600px) {
    .layout {
      grid-template-columns: minmax(0, 660px) minmax(0, 520px) minmax(0, 1fr);
      grid-template-rows: auto auto 1fr;
      grid-template-areas:
        'preview control side'
        'editor  control side'
        'library control side';
    }
  }

  .area {
    display: flex;
    flex-direction: column;
    gap: 18px;
    min-width: 0;
  }

  .area--preview { grid-area: preview; }
  .area--control { grid-area: control; }
  .area--side { grid-area: side; }
  .area--editor { grid-area: editor; }
  .area--library { grid-area: library; }
</style>
