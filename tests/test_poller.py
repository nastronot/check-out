"""The shared background Poller (weather and news both build on it)."""

import threading

from checkout.poller import Poller


class _Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class _Counter(Poller):
    """A toy poller: fetches the key's value, next fetch 100 s later."""

    def __init__(self, replies, **kw):
        super().__init__(**kw)
        self.replies = list(replies)
        self.value = None

    def _fetch(self, key, now):
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    def _next_at(self, key, now):
        return now + 100

    def _accept(self, key, result, now):
        self.value = result

    def _has_result(self):
        return self.value is not None

    def _reset(self):
        self.value = None


def _poller(replies, clock=None):
    return _Counter(replies, clock=clock or _Clock(), autostart=False)


def test_idle_without_a_key():
    p = _poller([])
    assert p.due_in(0) is None
    p.fetch_once()                      # nothing to fetch, nothing raised


def test_due_at_once_then_on_its_schedule():
    clock = _Clock()
    p = _poller(["a"], clock)
    p.set_key("k")
    assert p.due_in(clock()) == 0
    p.fetch_once()
    assert p.value == "a"
    assert p.due_in(clock()) == 100


def test_failure_backs_off_and_caps():
    clock = _Clock()
    p = _poller([OSError("x")] * 6, clock)
    p.set_key("k")
    seen = []
    for _ in range(6):
        p.fetch_once()
        seen.append(p.due_in(clock()))
    assert seen == [60, 120, 240, 480, 900, 900]
    assert "x" in p.error


def test_success_clears_the_error():
    clock = _Clock()
    p = _poller([OSError("x"), "ok"], clock)
    p.set_key("k")
    p.fetch_once()
    p.fetch_once()
    assert p.error is None and p.value == "ok"


def test_a_new_key_resets_and_a_result_for_an_old_key_is_dropped():
    p = _poller([])

    def fetch(key, now):
        p.set_key("other")              # the key changed while the request was out
        return "stale"

    p._fetch = fetch
    p.set_key("k")
    p.fetch_once()
    assert p.value is None


def test_the_thread_survives_an_unexpected_error():
    got, logged = threading.Event(), []
    calls = []

    class Flaky(_Counter):
        def _fetch(self, key, now):
            calls.append(key)
            if len(calls) == 1:
                raise RuntimeError("bug")
            got.set()
            return "ok"

    p = Flaky([], log=logged.append)
    p.set_key("a")
    for _ in range(200):                # wait for the first (failing) fetch to finish
        if logged:
            break
        threading.Event().wait(0.01)
    p.set_key("b")                      # new key -> due now -> fetched again
    assert got.wait(2)
    p.stop()
    assert any("bug" in m for m in logged)
