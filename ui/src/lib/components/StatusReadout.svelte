<script lang="ts">
  import type { Health, Status } from '../types';

  export let status: Status | null = null;
  export let health: Health = { ok: false, daemon_alive: false };

  function ago(iso: string | null | undefined): string {
    if (!iso) return '—';
    const t = Date.parse(iso);
    if (Number.isNaN(t)) return '—';
    const secs = Math.max(0, Math.round((Date.now() - t) / 1000));
    if (secs < 2) return 'just now';
    if (secs < 60) return `${secs}s ago`;
    const mins = Math.round(secs / 60);
    return `${mins}m ago`;
  }
</script>

<section class="panel readout">
  <div class="panel__title">Daemon</div>
  <div class="readout__grid">
    <div class="cell">
      <span class="k">link</span>
      <span class="v">
        <span
          class="led"
          class:led--on={health.daemon_alive}
          class:led--dead={!health.daemon_alive}
        ></span>
        {health.daemon_alive ? 'ALIVE' : 'OFFLINE'}
      </span>
    </div>
    <div class="cell">
      <span class="k">mode</span>
      <span class="v">{status?.mode ?? '—'}</span>
    </div>
    <div class="cell">
      <span class="k">updated</span>
      <span class="v">{ago(status?.updated_at)}</span>
    </div>
    <div class="cell">
      <span class="k">last cmd</span>
      <span class="v mono-id">{status?.last_command_id?.slice(0, 8) ?? '—'}</span>
    </div>
  </div>
</section>

<style>
  .readout__grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }

  .cell {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .k {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: var(--text-faint);
  }

  .v {
    display: flex;
    align-items: center;
    gap: 7px;
    color: var(--text);
    font-size: 13px;
    letter-spacing: 0.06em;
  }

  .mono-id {
    color: var(--text-mute);
  }
</style>
