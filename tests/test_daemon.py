"""Daemon-level tests, focused on the graceful-shutdown path."""

import checkout.daemon as daemon
from checkout.driver import VFDDriver


def _last_tx_bytes(out: str) -> list[str]:
    tx_lines = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("TX")]
    return tx_lines[-1][2:].split()


def test_shutdown_blanks_with_cursor_hidden(monkeypatch, capsys):
    """The shutdown path must end in 0x14 (blank), not a bare clear."""
    drv = VFDDriver(dry_run=True)
    monkeypatch.setattr(daemon, "open_driver", lambda dry_run: drv)
    monkeypatch.setattr(daemon.time, "sleep", lambda s: None)
    monkeypatch.setattr(daemon, "BANNER_SECONDS", 0)
    # Request shutdown before the loop body runs.
    monkeypatch.setattr(daemon, "_stop", True)

    rc = daemon.run(dry_run=True)
    assert rc == 0

    last = _last_tx_bytes(capsys.readouterr().out)
    # blank() = 0x1F then 0x14, with 0x14 as the final emitted byte.
    assert last == ["1F", "14"]
    assert last[-1] == "14"
    # Port closed cleanly (dry-run driver has no open handle).
    assert drv._serial is None


class _CountingDriver:
    """Records show()/blank() calls without touching a port."""

    port = "fake"
    baud = 9600

    def __init__(self):
        self.shows = 0
        self.blanks = 0

    def clear(self):
        pass

    def show(self, top, bottom):
        self.shows += 1

    def blank(self):
        self.blanks += 1

    def close(self):
        pass


def test_exactly_one_show_per_tick_no_double_write(monkeypatch):
    """Each clock tick must emit exactly one show() — never zero, never two."""
    drv = _CountingDriver()
    monkeypatch.setattr(daemon, "open_driver", lambda dry_run: drv)
    monkeypatch.setattr(daemon, "show_banner", lambda d: None)
    monkeypatch.setattr(daemon, "_stop", False)

    # Count loop iterations (one load_state per tick) and stop after 3.
    ticks = {"n": 0}
    real_load = daemon.load_state

    def counting_load():
        ticks["n"] += 1
        return real_load()

    monkeypatch.setattr(daemon, "load_state", counting_load)

    def fake_sleep(_seconds):
        if ticks["n"] >= 3:
            daemon._stop = True

    monkeypatch.setattr(daemon.time, "sleep", fake_sleep)

    daemon.run(dry_run=True)

    # Exactly one show() per tick: not zero (diffed-away) and not two (scroll).
    assert drv.shows == ticks["n"] == 3
    assert drv.blanks == 1  # the single shutdown blank
