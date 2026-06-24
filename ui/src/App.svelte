<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import VfdPreview from './lib/components/VfdPreview.svelte';
  import ControlPanel from './lib/components/ControlPanel.svelte';
  import DisplayPanel from './lib/components/DisplayPanel.svelte';
  import CommandBar from './lib/components/CommandBar.svelte';
  import StatusReadout from './lib/components/StatusReadout.svelte';
  import GlyphEditorPanel from './lib/components/GlyphEditorPanel.svelte';
  import SavedMessages from './lib/components/SavedMessages.svelte';
  import GlyphLibrary from './lib/components/GlyphLibrary.svelte';
  import {
    appState,
    health,
    loadState,
    patchState,
    refreshLibrary,
    startPolling,
    status,
    stopPolling,
  } from './lib/stores';

  onMount(() => {
    void loadState();
    void refreshLibrary();
    startPolling(500);
  });
  onDestroy(stopPolling);

  // Preview mirrors /api/status; glyph bitmaps come from the desired state.
  $: glyphs = $appState?.glyphs ?? {};

  // App version (Vite-injected from package.json, so it never goes stale).
  const version = __APP_VERSION__;
</script>

<div class="shell">
  <header class="masthead">
    <div class="masthead__brand">
      <span class="masthead__logo" role="img" aria-label="check-out"></span>
    </div>
    <span class="masthead__sub">phosphor status board · v{version}</span>
  </header>

  <main class="layout">
    <div class="layout__preview">
      <VfdPreview status={$status} {glyphs} />
    </div>

    <div class="layout__controls">
      <ControlPanel state={$appState} patch={patchState} />
      <DisplayPanel state={$appState} patch={patchState} />
      <SavedMessages />
      <CommandBar />
      <StatusReadout status={$status} health={$health} />
    </div>

    <div class="layout__glyphs">
      <GlyphEditorPanel />
      <GlyphLibrary />
    </div>
  </main>

  <footer class="footnote">
    daemon owns the serial port · this UI only reads status.json &amp; writes
    state.json
  </footer>
</div>

<style>
  .shell {
    max-width: 1180px;
    margin: 0 auto;
    padding: 26px 22px 40px;
  }

  .masthead {
    display: flex;
    justify-content: space-between;
    /* Sit the meta text on the logo's baseline (its bottom edge), not the top. */
    align-items: baseline;
    padding-bottom: 14px;
    margin-bottom: 22px;
  }

  .masthead__brand {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .masthead__logo {
    display: block;
    height: 34px;
    aspect-ratio: 923 / 121; /* the logo PNG's intrinsic ratio */
    /* Tint the (white/transparent) wordmark to the app's phosphor accent: use
       the logo's alpha as a mask and fill with the accent color. The scanline
       gaps stay transparent, so the dot-matrix look is preserved. */
    background-color: var(--phosphor);
    -webkit-mask: url(/logo.png) no-repeat center / contain;
    mask: url(/logo.png) no-repeat center / contain;
  }

  .masthead__sub {
    font-size: 11px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--text-faint);
  }

  .layout {
    display: grid;
    grid-template-columns: 1.25fr 1fr;
    grid-template-areas:
      'preview controls'
      'glyphs  controls';
    gap: 20px;
    align-items: start;
  }

  .layout__preview {
    grid-area: preview;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  .layout__controls {
    grid-area: controls;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  .layout__glyphs {
    grid-area: glyphs;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  .footnote {
    margin-top: 26px;
    text-align: center;
    font-size: 11px;
    letter-spacing: 0.1em;
    color: var(--text-faint);
  }

  @media (max-width: 860px) {
    .layout {
      grid-template-columns: 1fr;
      grid-template-areas:
        'preview'
        'controls'
        'glyphs';
    }
  }
</style>
