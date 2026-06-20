<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import VfdPreview from './lib/components/VfdPreview.svelte';
  import ControlPanel from './lib/components/ControlPanel.svelte';
  import CommandBar from './lib/components/CommandBar.svelte';
  import StatusReadout from './lib/components/StatusReadout.svelte';
  import GlyphEditorPanel from './lib/components/GlyphEditorPanel.svelte';
  import {
    appState,
    health,
    loadState,
    patchState,
    startPolling,
    status,
    stopPolling,
  } from './lib/stores';

  onMount(() => {
    void loadState();
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
      <img class="masthead__logo" src="/logo.png" alt="check-out" />
    </div>
    <span class="masthead__sub">phosphor status board · v{version}</span>
  </header>

  <main class="layout">
    <div class="layout__preview">
      <VfdPreview status={$status} {glyphs} />
      <StatusReadout status={$status} health={$health} />
    </div>

    <div class="layout__controls">
      <ControlPanel state={$appState} patch={patchState} />
      <CommandBar />
    </div>

    <div class="layout__glyphs">
      <GlyphEditorPanel />
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
    align-items: flex-end;
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
    width: auto;
    /* crisp scaling for the dot-matrix wordmark */
    image-rendering: -webkit-optimize-contrast;
    image-rendering: crisp-edges;
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
