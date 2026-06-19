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
