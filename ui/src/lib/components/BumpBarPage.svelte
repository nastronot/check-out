<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { getBumpbar, putBumpbarMap, resetBumpbarMap } from '../api';
  import {
    actionLabel,
    groupActions,
    isFlashing,
    isNewPress,
    type BumpBar,
    type BumpButton,
    type BumpMap,
    type Layer,
  } from '../bumpbar';

  // The bump bar page: the real pad drawn as it looks (legends only), one panel
  // to remap the selected key, and a one-line status under the pad.
  // The web only WRITES bumpbar.json; the service picks it up on the next press.
  let data: BumpBar | null = null;
  let loadError = '';
  let saveError = '';
  let selected = 'next';
  let now = Date.now();

  // Map generation: bumped by every save. A poll SENT before a save must not
  // put the old map back when it lands after the save finished.
  let mapGen = 0;
  // Key flash: starts when the page first sees a new press (see isFlashing).
  let seenPress: string | null = null;
  let flashStart: number | null = null;
  let flashKey = '';
  let firstPoll = true;

  async function poll(): Promise<void> {
    const gen = mapGen;
    try {
      const fresh = await getBumpbar();
      data = gen !== mapGen && data ? { ...fresh, map: data.map } : fresh;
      const p = fresh.status?.last_press ?? null;
      if (p && isNewPress(seenPress, p.at)) {
        // The first poll only records the press already there: no stale flash.
        if (!firstPoll) {
          flashStart = Date.now();
          flashKey = p.button;
        }
        seenPress = p.at;
      }
      firstPoll = false;
      loadError = '';
    } catch (e) {
      loadError = String(e);
    }
  }

  let pollTimer: ReturnType<typeof setInterval>;
  let clockTimer: ReturnType<typeof setInterval>;
  onMount(() => {
    void poll();
    pollTimer = setInterval(() => void poll(), 500);
    clockTimer = setInterval(() => (now = Date.now()), 100);
  });
  onDestroy(() => {
    clearInterval(pollTimer);
    clearInterval(clockTimer);
  });

  async function store(write: () => Promise<BumpMap>): Promise<void> {
    mapGen += 1;
    try {
      const stored = await write();
      mapGen += 1;
      if (data) data = { ...data, map: stored };
      saveError = '';
    } catch (e) {
      saveError = String(e);
      await poll();
    }
  }

  function setAction(layer: Layer, button: string, e: Event): void {
    if (!data) return;
    const value = (e.currentTarget as HTMLSelectElement).value;
    const next = { ...data.map, [layer]: { ...data.map[layer], [button]: value } };
    data = { ...data, map: next };
    void store(() => putBumpbarMap(next));
  }

  const resetMap = () => void store(resetBumpbarMap);

  function legendOf(b: BumpButton | undefined | null): string {
    if (!b) return '';
    return b.legend || 'SHIFT';
  }

  function hintOf(id: string): string {
    return data?.actions.find((a) => a.id === id)?.hint ?? '';
  }

  // The key's two actions, shown on hover (the drawing itself stays clean).
  function tipOf(b: BumpButton): string {
    if (!data) return '';
    if (b.id === data.shift) return 'Shift: tap it, then a key';
    return `${actionLabel(data.actions, data.map.tap[b.id])}  ·  shift: ${actionLabel(
      data.actions,
      data.map.shift[b.id],
    )}`;
  }

  function ago(at: string, t: number): string {
    const s = Math.max(0, Math.round((t - Date.parse(at)) / 1000));
    if (Number.isNaN(s)) return '';
    if (s < 60) return `${s}s ago`;
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    return `${Math.floor(s / 3600)}h ago`;
  }

  $: status = data?.status ?? null;
  $: press = status?.last_press ?? null;
  $: hit = isFlashing(flashStart, now) ? flashKey : '';
  // The grey key glows while the one-shot shift is armed (3 s, or until used).
  $: shiftArmed = !!status?.connected && status?.layer === 'shift';
  $: groups = groupActions(data?.actions ?? []);
  $: current = data?.buttons.find((b) => b.id === selected) ?? null;
  $: isShift = !!data && selected === data.shift;
  $: connected = !!data?.alive && !!status?.connected;
  $: errorText = saveError || data?.map_error || status?.error || '';
  $: barState = !data
    ? ''
    : !data.installed
      ? 'no bump bar service on this machine'
      : !data.alive
        ? 'service stopped'
        : connected
          ? 'connected'
          : 'unplugged';
</script>

<main class="bb">
  <section class="pad">
    {#if !data}
      <p class="muted">{loadError ? `web API: ${loadError}` : 'loading…'}</p>
    {:else}
      <!-- The real bar: a brushed stainless plate, ten keys in their cap
           colours with printed legends, and the status LED hole below. -->
      <div class="plate">
        <div class="keys">
          {#each data.buttons as b (b.id)}
            <button
              class="key key--{b.color}"
              class:key--hit={hit === b.id || (b.id === data.shift && shiftArmed)}
              aria-pressed={selected === b.id}
              aria-label={legendOf(b)}
              title={tipOf(b)}
              on:click={() => (selected = b.id)}
            >
              {#each b.legend.split(' ').filter(Boolean) as word}
                <span>{word}</span>
              {/each}
            </button>
          {/each}
        </div>
        <span
          class="plate__led"
          class:plate__led--idle={connected && !hit}
          class:plate__led--hit={connected && !!hit}
          title={barState}
        ></span>
      </div>

      <!-- One line of status, not a panel. -->
      <p class="status">
        <span class="led" class:led--on={connected} class:led--dead={!connected}></span>
        <span>{barState}</span>
        {#if press && connected}
          <span class="status__sep">·</span>
          <span>
            {press.layer === 'shift' ? 'shift ' : ''}{legendOf(
              data.buttons.find((x) => x.id === press?.button),
            )} → <span class="readout">{actionLabel(data.actions, press.action)}</span>
          </span>
          <span class="status__ago">{ago(press.at, now)}</span>
        {/if}
      </p>
      {#if errorText}
        <p class="err">{errorText}</p>
      {/if}
    {/if}
  </section>

  <section class="panel">
    <div class="panel__title">
      {current ? legendOf(current) : 'Key'}
      <button class="btn" on:click={resetMap} disabled={!data} title="Put every key back to its default">Reset all</button>
    </div>
    {#if data && current}
      {#if isShift}
        <p class="note">
          The grey key is a one-shot shift. Tap it, then tap another key within
          3 seconds, and that key does its shift action. Volume and brightness
          steps keep it armed. Tap grey twice to cancel.
        </p>
      {:else}
        {#each data.layers as layer (layer)}
          <div class="field">
            <label class="field__label" for="act-{layer}">
              {layer === 'tap' ? 'Tap' : 'Shift mod'}
            </label>
            <select
              id="act-{layer}"
              value={data.map[layer][current.id]}
              on:change={(e) => current && setAction(layer, current.id, e)}
            >
              <optgroup label="check-out">
                {#each groups.checkout as a (a.id)}
                  <option value={a.id}>{a.label}</option>
                {/each}
              </optgroup>
              <optgroup label="system">
                {#each groups.system as a (a.id)}
                  <option value={a.id}>{a.label}</option>
                {/each}
              </optgroup>
            </select>
            <span class="field__hint">{hintOf(data.map[layer][current.id])}</span>
          </div>
        {/each}
      {/if}
      <p class="field__hint pick">Click a key on the pad to change it.</p>
    {:else}
      <p class="muted">loading…</p>
    {/if}
  </section>
</main>

<style>
  .bb {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 28px;
    align-items: start;
  }

  .muted {
    color: var(--text-faint);
    font-size: 12px;
  }

  /* --- the pad ----------------------------------------------------------- */
  .pad {
    display: flex;
    flex-direction: column;
    align-items: center;
    min-width: 0;
  }

  /* Brushed stainless: fine horizontal grain over a soft top-lit sheen. */
  .plate {
    position: relative;
    width: min(100%, 400px);
    padding: 26px 22px 44px;
    border-radius: 10px;
    background:
      repeating-linear-gradient(0deg, rgba(255, 255, 255, 0.05) 0 1px, rgba(0, 0, 0, 0.03) 1px 2px),
      linear-gradient(180deg, #c9cccd 0%, #a9adaf 38%, #b8bbbc 62%, #9a9ea0 100%);
    box-shadow:
      inset 0 1px 0 rgba(255, 255, 255, 0.7),
      inset 0 -1px 0 rgba(0, 0, 0, 0.25),
      0 1px 0 #6d7173,
      0 14px 34px rgba(0, 0, 0, 0.65);
  }

  .keys {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 14px 12px;
  }

  /* A key cap: glossy plastic in a dark recess, legend printed in black. */
  .key {
    --cap: #d6d6d2;
    appearance: none;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    aspect-ratio: 2.05 / 1;
    padding: 4px 6px;
    border: none;
    border-radius: 5px;
    cursor: pointer;
    font-family: Arial, 'Helvetica Neue', 'Liberation Sans', sans-serif;
    font-weight: 700;
    font-size: clamp(11px, 3.1vw, 14px);
    line-height: 1.12;
    letter-spacing: 0.01em;
    color: #151617;
    background:
      linear-gradient(180deg, rgba(255, 255, 255, 0.34), rgba(255, 255, 255, 0) 42%),
      linear-gradient(180deg, var(--cap), color-mix(in srgb, var(--cap) 82%, black));
    box-shadow:
      0 0 0 2px rgba(40, 42, 44, 0.55),
      inset 0 1px 0 rgba(255, 255, 255, 0.55),
      inset 0 -3px 0 color-mix(in srgb, var(--cap) 70%, black),
      0 3px 5px rgba(0, 0, 0, 0.35);
    transition: transform 0.06s, filter 0.12s, box-shadow 0.12s;
  }

  .key--red { --cap: #d8413a; }
  .key--green { --cap: #2fae57; }
  .key--grey { --cap: #dcdcd8; }
  .key--blue { --cap: #4a8ee0; }
  .key--dark { --cap: #55585b; }

  .key:hover {
    filter: brightness(1.05);
  }

  .key[aria-pressed='true'] {
    outline: 2px solid var(--phosphor);
    outline-offset: 4px;
  }

  /* A press on the REAL bar pushes the drawn key in for FLASH_MS. */
  .key--hit {
    transform: translateY(2px);
    filter: brightness(1.15);
    box-shadow:
      0 0 0 2px rgba(40, 42, 44, 0.55),
      inset 0 1px 0 rgba(255, 255, 255, 0.55),
      inset 0 -1px 0 color-mix(in srgb, var(--cap) 70%, black),
      0 0 18px var(--phosphor);
  }

  /* The bar's status LED behind a small drilled hole. */
  .plate__led {
    position: absolute;
    left: 50%;
    bottom: 17px;
    width: 7px;
    height: 7px;
    margin-left: -3.5px;
    border-radius: 50%;
    background: #3a3d3f;
    box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.8), 0 1px 0 rgba(255, 255, 255, 0.5);
  }

  .plate__led--idle {
    background: #44e36d;
    box-shadow: 0 0 7px #44e36d, 0 1px 0 rgba(255, 255, 255, 0.5);
  }

  .plate__led--hit {
    background: #ff4b3a;
    box-shadow: 0 0 7px #ff4b3a, 0 1px 0 rgba(255, 255, 255, 0.5);
  }

  .status {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: center;
    gap: 6px 8px;
    margin: 18px 0 0;
    font-size: 12px;
    color: var(--text-mute);
  }

  .status__sep,
  .status__ago {
    color: var(--text-faint);
  }

  .err {
    margin: 8px 0 0;
    font-size: 11px;
    color: var(--amber-warn);
    text-align: center;
  }

  /* --- the key panel ------------------------------------------------------ */
  .note {
    margin: 0;
    font-size: 12px;
    line-height: 1.6;
    color: var(--text-mute);
  }

  .pick {
    display: block;
    margin-top: 6px;
  }

  select {
    width: 100%;
  }

  @media (max-width: 860px) {
    .bb {
      grid-template-columns: minmax(0, 1fr);
    }
  }

  @media (max-width: 600px) {
    .plate {
      padding: 18px 14px 36px;
    }

    .keys {
      gap: 11px 10px;
    }
  }
</style>
