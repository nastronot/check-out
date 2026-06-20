<script lang="ts">
  // PLACEHOLDER (Phase 2c). Reserves layout space for the 9-slot 5x7 editor so
  // the grid doesn't reflow when it lands. No editing here yet.
  import { GLYPH_CODES } from '../font5x7';

  const slots = GLYPH_CODES.map((code, i) => ({ i, code }));
</script>

<section class="panel panel--disabled glyphs">
  <div class="panel__title">
    Glyph editor <span class="tag">coming next</span>
  </div>
  <div class="glyphs__grid">
    {#each slots as s}
      <div class="slot" title={`slot ${s.i} → code 0x${s.code.toString(16)}`}>
        <div class="slot__cell">
          {#each Array(7) as _, r}
            <div class="slot__row">
              {#each Array(5) as _, c}
                <span class="slot__dot"></span>
              {/each}
            </div>
          {/each}
        </div>
        <span class="slot__label">g{s.i}</span>
      </div>
    {/each}
  </div>
  <p class="field__hint">
    Draw 9 custom 5×7 glyphs, push them to the daemon, and reference them in
    messages with <code>{'{g0}'}</code>…<code>{'{g8}'}</code>.
  </p>
</section>

<style>
  .glyphs__grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(58px, 1fr));
    gap: 12px;
  }

  .slot {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
  }

  .slot__cell {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 5px;
    background: #03090a;
    border: 1px solid var(--rule);
    border-radius: 4px;
  }

  .slot__row {
    display: flex;
    gap: 2px;
  }

  .slot__dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: rgba(61, 240, 200, 0.06);
  }

  .slot__label {
    font-size: 10px;
    letter-spacing: 0.1em;
    color: var(--text-faint);
  }

  code {
    color: var(--phosphor);
    font-size: 11px;
  }
</style>
