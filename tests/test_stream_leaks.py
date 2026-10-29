"""PM-045 S2: "The stream key never appears in any process's arguments, in logs, in `ctl status`, in the TUI or in
errors (a test searches all of them for a sentinel key)." The TUI is searched in tests/test_tui_broadcast.py; this
test runs a real broadcast through the background player and searches everything else."""
import io
import json
import shutil
import subprocess

import pytest

from gentle_stream import main, streamconf
from tests.rtmp_fake import FakeIngest
from tests.test_daemon import runtime  # noqa: F401  (fixture: a private runtime dir and a fake audio device)

SENTINEL = "SENTINEL-KEY-leak-3c3c-9x9x"


def everything_shown(capsys) -> str:
    out, err = capsys.readouterr()
    return out + err


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is needed for a real broadcast")
def test_the_key_is_nowhere_but_inside_the_connection(runtime, capsys, monkeypatch):  # noqa: F811
    monkeypatch.delenv(streamconf.KEY_ENV, raising=False)
    shown = []
    ingest = FakeIngest()
    assert main(["stream", "url", ingest.url]) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO(SENTINEL + "\n"))
    assert main(["stream", "key", "set"]) == 0
    assert main(["stream", "show"]) == 0
    shown.append(everything_shown(capsys))
    from gentle_stream import client

    client.ensure().detach()
    assert main(["ctl", "stream", "start"]) == 0
    assert main(["ctl", "status"]) == 0
    shown.append(everything_shown(capsys))
    status = json.loads(shown[-1].splitlines()[-1])
    assert status["stream"]["running"]
    shown.append(subprocess.run(["ps", "-axo", "command="], capture_output=True, text=True, check=False).stdout)
    assert "ffmpeg" in shown[-1]                                  # the encoder was there to be searched
    assert main(["ctl", "stream", "stop"]) == 0
    ingest.wait()
    assert ingest.stream_name == SENTINEL                         # the key did reach the ingest, and only it

    refusing = FakeIngest(refuse=True)                            # an error that holds the stream name
    assert main(["stream", "url", refusing.url]) == 0
    assert main(["ctl", "stream", "start"]) == 1
    shown.append(everything_shown(capsys))
    assert "NetStream.Publish.BadName" in shown[-1]
    assert main(["ctl", "status"]) == 0
    shown.append(everything_shown(capsys))
    log = runtime / "player.log"
    shown.append(log.read_text(errors="replace") if log.exists() else "")
    for i, text in enumerate(shown):
        assert SENTINEL not in text, f"the key leaked in output #{i}"
