"""Deterministic coverage of the daemon fixture's exit-during-cleanup race."""
import inspect
import signal

import pytest

from gentle_stream import client
from tests import test_daemon


@pytest.mark.parametrize("exited", [False, True])
def test_runtime_cleanup_handles_exit_between_probe_and_kill(monkeypatch, exited):
    fixture = inspect.unwrap(test_daemon.runtime)(monkeypatch)
    run = next(fixture)
    root = run.parent
    calls = []

    class Connection:
        def close(self):
            calls.append("close")

    def kill(pid, sig):
        calls.append((pid, sig))
        if sig == signal.SIGKILL and exited:
            raise ProcessLookupError("daemon exited after the liveness probe")

    monkeypatch.setattr(test_daemon, "daemon_pids", lambda path: [12345])
    monkeypatch.setattr(client, "connect", Connection)
    monkeypatch.setattr(test_daemon.os, "kill", kill)
    with pytest.raises(StopIteration):
        next(fixture)
    assert calls == ["close", (12345, 0), (12345, signal.SIGKILL)]
    assert not root.exists()
