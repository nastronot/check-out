<script lang="ts">
  import { onMount } from 'svelte';
  import { feedRows } from '../news';
  import { getNews } from '../api';
  import type { AppState, NewsCatalogue, Status } from '../types';

  // The News feeds panel: every topic's feeds (static, from /api/news) with each
  // ticked feed's current lead (status.news). Its own panel, beside Control, so
  // the headlines get the width they need. Ages refresh with each status poll.
  export let state: AppState | null = null;
  export let status: Status | null = null;

  let catalogue: NewsCatalogue | null = null;
  onMount(async () => {
    try {
      catalogue = (await getNews()).topics;
    } catch {
      catalogue = null; // older web process: no list, the rest still works
    }
  });
  $: groups = feedRows(catalogue, status?.news, state?.news_topics ?? [], status ? Date.now() : 0);
</script>

{#if groups.length}
  <section class="panel">
    <div class="panel__title">News feeds</div>
    {#each groups as group}
      <div class="group">
        <div class="group__head">
          <span class="group__title" class:off={!group.on}>{group.topic}</span>
          <span class="group__aside">{group.on ? `${group.feeds.length} feeds` : 'off'}</span>
        </div>
        <ul class="feeds">
          {#each group.feeds as f (f.key)}
            <li class="feed feed--{f.state}">
              <span class="feed__name">{f.name}</span>
              {#if f.state === 'ok'}
                {#if f.link}
                  <a class="feed__title" href={f.link} target="_blank" rel="noopener noreferrer"
                    title={f.title}>{f.title}</a
                  >
                {:else}
                  <span class="feed__title" title={f.title}>{f.title}</span>
                {/if}
                <span class="feed__age">{f.age}</span>
              {:else if f.state === 'error'}
                <span class="feed__title" title={f.error}>fetch failed</span>
              {:else if f.state === 'waiting'}
                <span class="feed__title">waiting…</span>
              {/if}
            </li>
          {/each}
        </ul>
      </div>
    {/each}
  </section>
{/if}

<style>
  .off {
    color: var(--text-faint);
  }

  .feeds {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  /* OUTLET | headline | age. Fixed outlet and age columns, so the headlines
     start and end on the same vertical line. */
  .feed {
    display: grid;
    grid-template-columns: 11ch minmax(0, 1fr) 4ch;
    gap: 12px;
    padding: 3px 0;
    font-size: 12px;
    line-height: 1.5;
    color: var(--text);
    border-bottom: 1px solid rgba(21, 32, 31, 0.6);
  }

  .feed:last-child {
    border-bottom: 0;
  }

  .feed__name {
    font-size: 10px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--text-mute);
    align-self: center;
  }

  .feed__title {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: inherit;
    text-decoration: none;
  }

  a.feed__title:hover {
    color: var(--phosphor-ink);
    text-decoration: underline;
  }

  .feed__age {
    text-align: right;
    color: var(--text-faint);
  }

  .feed--off,
  .feed--waiting {
    color: var(--text-faint);
  }

  .feed--off .feed__name {
    color: var(--text-faint);
  }

  .feed--error .feed__title {
    color: var(--red-dead);
  }
</style>
