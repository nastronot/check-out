<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import BoardPage from './lib/components/BoardPage.svelte';
  import BumpBarPage from './lib/components/BumpBarPage.svelte';
  import { getBumpbar } from './lib/api';
  import { routeFromHash, showBumpbarNav, type Route } from './lib/bumpbar';

  // App version (Vite-injected from package.json, so it never goes stale).
  const version = __APP_VERSION__;

  // Two screens on hash routes: the board (#/) and the bump bar page (#/bumpbar).
  let route: Route = routeFromHash(location.hash);
  const onHash = () => (route = routeFromHash(location.hash));

  // Show the bump bar link only where its service has run (dad, not work).
  let bumpbarInstalled = false;
  onMount(async () => {
    window.addEventListener('hashchange', onHash);
    try {
      bumpbarInstalled = (await getBumpbar()).installed;
    } catch {
      /* older backend or web down: no link */
    }
  });
  onDestroy(() => window.removeEventListener('hashchange', onHash));
</script>

<div class="shell">
  <header class="masthead">
    <div class="masthead__brand">
      <span class="masthead__logo" role="img" aria-label="check-out"></span>
    </div>
    <div class="masthead__meta">
      {#if showBumpbarNav(bumpbarInstalled, route)}
        <nav class="nav">
          <a href="#/" aria-current={route === 'board' ? 'page' : undefined}>display</a>
          <a href="#/bumpbar" aria-current={route === 'bumpbar' ? 'page' : undefined}>bump bar</a>
        </nav>
      {/if}
      <span class="tag">v{version}</span>
    </div>
  </header>

  {#if route === 'bumpbar'}
    <BumpBarPage />
  {:else}
    <BoardPage />
  {/if}

  <footer class="footnote">
    {#if route === 'bumpbar'}
      the bump bar service owns the keypad · this page only writes bumpbar.json
    {:else}
      daemon owns the serial port · this UI only reads status.json &amp; writes
      state.json
    {/if}
  </footer>
</div>

<style>
  .shell {
    /* Sized for the real screens: a 2048-wide main monitor and 1024-1080-wide
       portrait side monitors. No phone layout. */
    max-width: 2200px;
    margin: 0 auto;
    padding: 16px 24px 16px;
  }

  .masthead {
    display: flex;
    justify-content: space-between;
    /* Sit the meta text on the logo's baseline (its bottom edge), not the top. */
    align-items: center;
    margin-bottom: 16px;
  }

  .masthead__brand {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .masthead__logo {
    display: block;
    height: 30px;
    aspect-ratio: 923 / 121; /* the logo PNG's intrinsic ratio */
    /* Tint the (white/transparent) wordmark to the app's phosphor accent: use
       the logo's alpha as a mask and fill with the accent color. The scanline
       gaps stay transparent, so the dot-matrix look is preserved. */
    background-color: var(--phosphor);
    -webkit-mask: url(/logo.png) no-repeat center / contain;
    mask: url(/logo.png) no-repeat center / contain;
  }

  .masthead__meta {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    align-items: center;
    gap: 18px;
  }

  /* Two screens, drawn as tabs: the current one is lit and underlined. */
  .nav {
    display: flex;
    gap: 4px;
    font-size: 11px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
  }

  .nav a {
    padding: 6px 10px;
    color: var(--text-mute);
    text-decoration: none;
    border-bottom: 2px solid transparent;
  }

  .nav a:hover {
    color: var(--phosphor-ink);
  }

  .nav a[aria-current='page'] {
    color: var(--phosphor);
    text-shadow: 0 0 8px var(--phosphor-deep);
    border-bottom-color: var(--phosphor);
  }

  .footnote {
    margin-top: 18px;
    text-align: center;
    font-size: 11px;
    letter-spacing: 0.1em;
    color: var(--text-faint);
  }

</style>
