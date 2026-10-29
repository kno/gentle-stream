"""PM-045 T1: the ingest URL and the stream key, kept apart; the key only from stdin, in a 0600 file or the
environment, and never echoed anywhere."""
import io
import stat

import pytest

from gentle_stream import main, streamconf

KEY = "SENTINEL-KEY-t1-9f3a-xyzw"
URL = "rtmps://a.rtmps.youtube.com/live2"


@pytest.fixture(autouse=True)
def no_env(monkeypatch):
    monkeypatch.delenv(streamconf.KEY_ENV, raising=False)


def run(capsys, monkeypatch, *args, stdin: str | None = None):
    if stdin is not None:
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    try:
        code = main(list(args))
    except SystemExit as e:              # argparse usage errors
        code = e.code
    out, err = capsys.readouterr()
    assert KEY not in out and KEY not in err, "the key was echoed"
    return code, out, err


def mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


# ------------------------------------------------------------ the key
def test_key_set_reads_stdin_and_writes_a_file_only_the_user_can_read(capsys, monkeypatch):
    code, out, err = run(capsys, monkeypatch, "stream", "key", "set", stdin=KEY + "\n")
    path = streamconf.key_path()
    assert (code, err) == (0, "")
    assert out == f"Stream key saved in {path} (readable only by you)\n"
    assert path.read_text() == KEY and mode(path) == 0o600
    assert streamconf.load_key().reveal() == KEY
    assert [p.name for p in path.parent.iterdir()] == [path.name]          # no temporary file left


def test_setting_it_again_replaces_it_and_keeps_0600(capsys, monkeypatch):
    run(capsys, monkeypatch, "stream", "key", "set", stdin="old-key\n")
    run(capsys, monkeypatch, "stream", "key", "set", stdin=KEY)
    assert streamconf.key_path().read_text() == KEY and mode(streamconf.key_path()) == 0o600


def test_the_key_is_never_taken_from_the_command_line_nor_echoed(capsys, monkeypatch):
    code, out, err = run(capsys, monkeypatch, "stream", "key", "set", KEY, stdin="")
    assert code == 2 and out == ""
    assert "the stream key is read from stdin, never from the command line" in err
    assert not streamconf.key_path().exists()


@pytest.mark.parametrize("given", ["", "\n", "two words", "line\nline", "x" * 257, "tab\there", "bell\x07"])
def test_a_key_that_is_not_one_short_printable_line_is_refused_and_nothing_written(capsys, monkeypatch, given):
    code, out, err = run(capsys, monkeypatch, "stream", "key", "set", stdin=given)
    assert code == 1 and out == ""
    assert err in ("gentle-stream: no stream key read from stdin\n",
                   ("gentle-stream: a stream key is one line of printable characters without spaces, "
                    "at most 256\n"))
    assert not streamconf.key_path().exists()


def test_key_clear_removes_it(capsys, monkeypatch):
    run(capsys, monkeypatch, "stream", "key", "set", stdin=KEY)
    path = streamconf.key_path()
    assert run(capsys, monkeypatch, "stream", "key", "clear") == (0, f"Stream key removed from {path}\n", "")
    assert not path.exists()
    assert run(capsys, monkeypatch, "stream", "key", "clear") == (0, "No stream key saved\n", "")


def test_the_environment_variable_wins_over_the_file(capsys, monkeypatch):
    run(capsys, monkeypatch, "stream", "key", "set", stdin="file-key")
    monkeypatch.setenv(streamconf.KEY_ENV, KEY)
    assert streamconf.load_key().reveal() == KEY


def test_a_key_file_others_can_read_is_refused_like_ssh_does(capsys, monkeypatch):
    run(capsys, monkeypatch, "stream", "key", "set", stdin=KEY)
    path = streamconf.key_path()
    path.chmod(0o644)
    with pytest.raises(streamconf.StreamConfigError) as raised:
        streamconf.load_key()
    assert str(raised.value) == f"{path} can be read by others; run: chmod 600 {path}"
    assert KEY not in str(raised.value)


def test_without_a_key_loading_says_how_to_set_one():
    with pytest.raises(streamconf.StreamConfigError, match=r"no stream key: run `gentle-stream stream key set` "
                                                           r"and paste it, or set GENTLE_STREAM_KEY"):
        streamconf.load_key()


def test_the_key_object_never_shows_its_value():
    key = streamconf.StreamKey(KEY)
    for shown in (repr(key), str(key), f"{key}", f"{key!r}", repr([key]), repr({"key": key})):
        assert KEY not in shown


# ------------------------------------------------------------ the URL
def test_url_is_saved_apart_from_the_key(capsys, monkeypatch):
    assert run(capsys, monkeypatch, "stream", "url", URL) == (0, f"Ingest URL saved: {URL}\n", "")
    assert streamconf.load_url() == URL
    assert not streamconf.key_path().exists()


@pytest.mark.parametrize("url", ["https://a.rtmps.youtube.com/live2", "rtmp://", "rtmps:///live2", "live2",
                                 "rtmp://user:pass@host/app", "rtmp://host/app?key=1", "rtmp://host/app#x",
                                 "rtmp://host", "rtmp://host/", "rtmp://host/app?", "rtmp://host/app#",
                                 "rtmp://host:99999/app"])
def test_a_url_that_is_not_a_plain_rtmp_ingest_is_refused(capsys, monkeypatch, url):
    code, out, err = run(capsys, monkeypatch, "stream", "url", url)
    assert code == 1 and out == ""
    assert err == ("gentle-stream: the ingest URL must be rtmp:// or rtmps:// with a host and no credentials, "
                   "query or fragment, e.g. rtmps://a.rtmps.youtube.com/live2\n")
    assert streamconf.load_url() is None


# ------------------------------------------------------------ show
def test_show_says_what_is_set_and_never_the_key(capsys, monkeypatch, tmp_path):
    code, out, _ = run(capsys, monkeypatch, "stream", "show")
    assert code == 0 and out == ("ingest URL: not set (gentle-stream stream url URL)\n"
                                 "stream key: not set (gentle-stream stream key set, from stdin)\n")
    run(capsys, monkeypatch, "stream", "url", URL)
    run(capsys, monkeypatch, "stream", "key", "set", stdin=KEY)
    path = streamconf.key_path()
    assert run(capsys, monkeypatch, "stream", "show")[1] == (f"ingest URL: {URL}\n"
                                                             f"stream key: set (in {path})\n")
    monkeypatch.setenv(streamconf.KEY_ENV, KEY)
    assert run(capsys, monkeypatch, "stream", "show")[1].endswith(
        "stream key: set (environment variable GENTLE_STREAM_KEY)\n")
    monkeypatch.delenv(streamconf.KEY_ENV)
    path.chmod(0o640)
    assert run(capsys, monkeypatch, "stream", "show")[1].endswith(
        f"stream key: {path} can be read by others; run: chmod 600 {path}\n")


def test_help_lists_the_stream_command(capsys, monkeypatch):
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "stream" in capsys.readouterr().out


def test_in_a_terminal_the_key_is_asked_for_without_echo(capsys, monkeypatch):
    class Tty(io.StringIO):
        def isatty(self):
            return True

    prompts = []
    monkeypatch.setattr("sys.stdin", Tty("never read"))
    monkeypatch.setattr("getpass.getpass", lambda prompt: prompts.append(prompt) or KEY)
    code, _, err = run(capsys, monkeypatch, "stream", "key", "set")
    assert (code, err, prompts) == (0, "", ["Stream key (not shown): "])
    assert streamconf.key_path().read_text() == KEY
