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
          <a href="#/" aria-current={route === 'board' ? 'page' : undefined}>board</a>
          <span class="nav__dot">·</span>
          <a href="#/bumpbar" aria-current={route === 'bumpbar' ? 'page' : undefined}>bump bar</a>
        </nav>
      {/if}
      <span class="masthead__sub">phosphor status board · v{version}</span>
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

  .masthead__meta {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    align-items: baseline;
    gap: 6px 18px;
  }

  /* Two screens: board and bump bar. Same small-caps voice as the sub line. */
  .nav {
    display: flex;
    gap: 8px;
    font-size: 11px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
  }

  .nav a {
    color: var(--text-mute);
    text-decoration: none;
  }

  .nav a:hover {
    color: var(--phosphor-ink);
  }

  .nav a[aria-current='page'] {
    color: var(--phosphor);
    text-shadow: 0 0 8px var(--phosphor-deep);
  }

  .nav__dot {
    color: var(--text-faint);
  }

  /* Phone width: the nav + version line drop under the logo instead of
     squeezing into a column beside it. */
  @media (max-width: 600px) {
    .masthead {
      flex-wrap: wrap;
      gap: 10px;
    }

    .masthead__meta {
      justify-content: flex-start;
    }
  }

  .footnote {
    margin-top: 26px;
    text-align: center;
    font-size: 11px;
    letter-spacing: 0.1em;
    color: var(--text-faint);
  }

</style>
