"""A background poller: fetch something on a schedule without blocking the caller.

Extracted from the weather fetcher so every "fetch from the network now and
then" feature shares one tested implementation (weather, news). The caller —
the daemon's fast loop — only ever sets a KEY (what to fetch: a location, a set
of sources; None = idle) and reads results; a daemon thread does the fetching:

- It sleeps on an Event until the next fetch is due — it never polls. Setting a
  new key wakes it (the Event is cleared BEFORE the schedule is read, so no
  wake-up is lost).
- A new key resets the stored results (they belong to the old key), and a reply
  for a key that changed while the request was out is dropped.
- A failed fetch keeps the last good result, records the error and retries
  after 60 s, doubling to 15 min. An unexpected exception is logged and backed
  off the same way — it never kills the thread.

Subclasses supply the fetch and what to do with its result (see the hooks).
"""

from __future__ import annotations

import http.client
import threading
import time


class Poller:
    RETRY_START_S = 60      # first retry after a failed fetch
    RETRY_MAX_S = 900       # retries double up to this

    # Errors a fetch is expected to raise (network, HTTP, a malformed reply).
    FETCH_ERRORS = (OSError, ValueError, http.client.HTTPException)

    def __init__(self, clock=time.time, log=None, autostart: bool = True,
                 name: str = "poller") -> None:
        self._clock = clock
        self._log = log or (lambda msg: None)
        self._autostart = autostart
        self._name = name
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._key = None            # wanted now (None = idle)
        self._result_key = None     # the key the stored results/backoff belong to
        self.error: str | None = None
        self._retry_at: float | None = None
        self._next: float | None = None
        self._backoff = 0.0
        self._thread: threading.Thread | None = None
        self._stopping = False

    # --- subclass hooks -----------------------------------------------------
    def _fetch(self, key, now):
        """Fetch for ``key`` (network; may block). Raise on failure."""
        raise NotImplementedError

    def _next_at(self, key, now) -> float:
        """When the next fetch is due after a successful one at ``now``."""
        raise NotImplementedError

    def _accept(self, key, result, now) -> None:
        """Store a successful result. Called with the lock held."""
        raise NotImplementedError

    def _has_result(self) -> bool:
        """Whether a result is stored (no result -> a fetch is due at once)."""
        raise NotImplementedError

    def _reset(self) -> None:
        """Forget stored results (a new key). Called with the lock held."""
        raise NotImplementedError

    # --- the caller's side ----------------------------------------------------
    def set_key(self, key) -> None:
        """What to fetch; None = idle. Cheap — call it every tick."""
        with self._lock:
            if key == self._key:
                return
            self._key = key
            if key is not None and key != self._result_key:
                self._result_key = key
                self._reset()
                self.error = None
                self._retry_at = None
                self._next = None
                self._backoff = 0.0
        if key is not None and self._autostart and self._thread is None:
            self._thread = threading.Thread(target=self._run, name=self._name, daemon=True)
            self._thread.start()
        self._wake.set()

    def due_in(self, now: float) -> float | None:
        """Seconds until the next fetch, or None when idle."""
        with self._lock:
            if self._key is None:
                return None
            if self._retry_at is not None:
                at = self._retry_at
            elif not self._has_result() or self._next is None:
                return 0.0
            else:
                at = self._next
        return max(0.0, at - now)

    def fetch_once(self) -> None:
        """One synchronous fetch (the thread's work; tests call it directly)."""
        with self._lock:
            key = self._key
        if key is None:
            return
        now = self._clock()
        try:
            result, error = self._fetch(key, now), None
        except self.FETCH_ERRORS as exc:
            result, error = None, f"{type(exc).__name__}: {exc}"
        with self._lock:
            if key != self._result_key:
                return  # the key changed while the request was out
            if error is None:
                self._accept(key, result, now)
                self.error = None
                self._retry_at, self._backoff = None, 0.0
                self._next = self._next_at(key, now)
            else:
                self._fail(error, now)
        if error:
            self._log(f"{self._name} failed ({error}); retrying in {self._backoff:.0f}s")

    def stop(self) -> None:
        self._stopping = True
        self._wake.set()

    # --- the thread -------------------------------------------------------------
    def _fail(self, error: str, now: float) -> None:
        """Record a failure and schedule the backed-off retry (lock held)."""
        self.error = error
        self._backoff = min(self.RETRY_MAX_S, max(self.RETRY_START_S, self._backoff * 2))
        self._retry_at = now + self._backoff

    def _run(self) -> None:
        while not self._stopping:
            self._wake.clear()  # before reading the schedule, so no wake-up is lost
            wait = self.due_in(self._clock())
            if wait is None:
                self._wake.wait()
            elif wait > 0:
                self._wake.wait(wait)
            else:
                try:
                    self.fetch_once()
                except Exception as exc:  # noqa: BLE001 — keep the thread alive
                    # fetch_once handles expected errors itself; anything else is
                    # a bug. Log it and back off instead of letting the thread die.
                    self._log(f"{self._name} error: {exc!r}")
                    with self._lock:
                        self._fail(repr(exc), self._clock())
