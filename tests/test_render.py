"""`gentle-stream render`: offline rendering to a 16-bit stereo WAV with the engine alone (no player, no daemon, no
audio device). Every test pins the procedural instruments: an empty cache and `--procedural`."""
import json

import numpy as np
import pytest
from scipy.io import wavfile

from gentle_stream import genres, main
from gentle_stream.engine import SR, Engine
from gentle_stream.style import Style


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    """Empty cache (no soundfont), and any attempt to reach a background player fails the test."""
    from gentle_stream import client

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    def no_player(*args, **kwargs):
        raise AssertionError("render must not use the background player")

    monkeypatch.setattr(client, "connect", no_player)
    monkeypatch.setattr(client, "ensure", no_player)


def render(capsys, *args):
    code = main(["render", "--procedural", *map(str, args)])
    out, err = capsys.readouterr()
    return code, out, err


def expected(style, seed, seconds):
    """What the engine renders for `style` and `seed`, trimmed and converted the way a WAV file stores it."""
    e = Engine(style, seed=seed, samples=False)
    n, bars = int(round(seconds * SR)), []
    while sum(map(len, bars)) < n:
        bars.append(e.render_bar())
    x = np.clip(np.concatenate(bars)[:n], -1, 1)
    return np.round(x * 32767).astype(np.int16)


# ------------------------------------------------------------ the file
def test_renders_exactly_the_requested_seconds_as_16_bit_stereo(tmp_path, capsys):
    out = tmp_path / "five.wav"
    code, stdout, err = render(capsys, "--seconds", 5, "--seed", 1, out)
    assert (code, err) == (0, "")
    assert stdout == f"wrote {out}: 5 s, lofi, seed 1\n"
    rate, data = wavfile.read(out)
    assert rate == SR and data.dtype == np.int16 and data.shape == (5 * SR, 2)
    peak = int(np.max(np.abs(data.astype(np.int32))))
    assert 0 < peak < 32767


def test_the_file_holds_what_the_engine_renders(tmp_path, capsys):
    out = tmp_path / "x.wav"
    assert render(capsys, "--seconds", 3.5, "--seed", 4, out)[0] == 0
    assert np.array_equal(wavfile.read(out)[1], expected(Style(), 4, 3.5))


def test_the_same_seed_writes_the_same_bytes(tmp_path, capsys):
    a, b, c = tmp_path / "a.wav", tmp_path / "b.wav", tmp_path / "c.wav"
    render(capsys, "--seconds", 4, "--seed", 7, a)
    render(capsys, "--seconds", 4, "--seed", 7, b)
    render(capsys, "--seconds", 4, "--seed", 8, c)
    assert a.read_bytes() == b.read_bytes()
    assert a.read_bytes() != c.read_bytes()


def test_without_a_seed_the_chosen_seed_is_printed_and_reproduces_the_file(tmp_path, capsys):
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    _, stdout, _ = render(capsys, "--seconds", 2, a)
    seed = int(stdout.rsplit("seed ", 1)[1])
    render(capsys, "--seconds", 2, "--seed", seed, b)
    assert a.read_bytes() == b.read_bytes()


def test_the_default_length_is_sixty_seconds(tmp_path, capsys, monkeypatch):
    out = tmp_path / "default.wav"
    _, stdout, _ = render(capsys, "--seed", 1, out)
    assert stdout == f"wrote {out}: 60 s, lofi, seed 1\n"
    assert wavfile.read(out)[1].shape == (60 * SR, 2)


# ------------------------------------------------------------ the style
def test_genre_reaches_the_engine(tmp_path, capsys):
    out = tmp_path / "synth.wav"
    _, stdout, _ = render(capsys, "--seconds", 3, "--seed", 2, "--genre", "synthwave", out)
    assert stdout == f"wrote {out}: 3 s, synthwave, seed 2\n"
    assert np.array_equal(wavfile.read(out)[1], expected(Style(genre="synthwave"), 2, 3))


def test_a_mood_file_is_read_as_a_style(tmp_path, capsys):
    mood = tmp_path / "style.json"
    data = {"name": "Fast", "genre": "jazz", "bpm": 120, "energy": 0.9, "unknown": 1}
    mood.write_text(json.dumps(data))
    out = tmp_path / "jazz.wav"
    _, stdout, _ = render(capsys, "--seconds", 4, "--seed", 3, "--mood-file", mood, out)
    assert stdout == f"wrote {out}: 4 s, jazz, seed 3\n"
    assert np.array_equal(wavfile.read(out)[1], expected(Style.from_dict(data), 3, 4))


def test_genre_overrides_the_mood_file(tmp_path, capsys):
    mood = tmp_path / "style.json"
    mood.write_text(json.dumps({"genre": "jazz", "bpm": 100}))
    out = tmp_path / "rock.wav"
    _, stdout, _ = render(capsys, "--seconds", 3, "--seed", 5, "--mood-file", mood, "--genre", "rock", out)
    assert stdout == f"wrote {out}: 3 s, rock, seed 5\n"
    assert np.array_equal(wavfile.read(out)[1], expected(Style(genre="rock", bpm=100), 5, 3))


# ------------------------------------------------------------ errors
def test_an_unwritable_output_path_is_one_error_line(tmp_path, capsys):
    out = tmp_path / "missing" / "x.wav"
    assert render(capsys, "--seconds", 1, out) == (1, "", f"gentle-stream: cannot write {out}: "
                                                         f"No such file or directory\n")


def test_a_missing_mood_file_is_one_error_line(tmp_path, capsys):
    mood = tmp_path / "nope.json"
    out = tmp_path / "x.wav"
    assert render(capsys, "--mood-file", mood, out) == (1, "", f"gentle-stream: cannot read {mood}: "
                                                               f"No such file or directory\n")
    assert not out.exists()


@pytest.mark.parametrize("text", ["not json", "[1, 2]", "42", "\udcff"], ids=["text", "list", "number", "binary"])
def test_a_mood_file_that_is_not_a_style_object_is_one_error_line(tmp_path, capsys, text):
    mood = tmp_path / "bad.json"
    mood.write_bytes(text.encode("utf-8", "surrogateescape"))
    out = tmp_path / "x.wav"
    assert render(capsys, "--mood-file", mood, out) == (1, "", f"gentle-stream: {mood}: not a JSON style object\n")
    assert not out.exists()


def test_an_unknown_genre_is_a_usage_error_listing_the_genres(tmp_path, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["render", "--genre", "polka", str(tmp_path / "x.wav")])
    err = capsys.readouterr().err
    assert exit_info.value.code == 2 and err.startswith("usage: ")
    assert "invalid genre 'polka'" in err and all(name in err for name in genres.NAMES)
    assert not (tmp_path / "x.wav").exists()


@pytest.mark.parametrize("seconds", ["0", "-1", "3600.5", "nan", "inf", "long"])
def test_seconds_must_be_above_zero_and_at_most_an_hour(tmp_path, capsys, seconds):
    with pytest.raises(SystemExit) as exit_info:
        main(["render", "--seconds", seconds, str(tmp_path / "x.wav")])
    assert exit_info.value.code == 2 and "--seconds" in capsys.readouterr().err


@pytest.mark.parametrize("seed", ["-1", "1.5", "x"])
def test_the_seed_must_be_a_non_negative_integer(tmp_path, capsys, seed):
    with pytest.raises(SystemExit) as exit_info:
        main(["render", "--seed", seed, str(tmp_path / "x.wav")])
    assert exit_info.value.code == 2 and "--seed" in capsys.readouterr().err
    assert not (tmp_path / "x.wav").exists()


def test_the_output_path_is_required(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["render"])
    assert exit_info.value.code == 2 and "OUT.wav" in capsys.readouterr().err


def test_render_help_documents_the_flags(capsys):
    with pytest.raises(SystemExit):
        main(["render", "--help"])
    out = capsys.readouterr().out
    for text in ("--seconds", "default: 60", "--seed", "--genre", "--mood-file", "--procedural", "OUT.wav"):
        assert text in out


def test_a_length_shorter_than_one_sample_still_writes_one_frame(tmp_path, capsys):
    out = tmp_path / "tiny.wav"
    code, _, err = render(capsys, "--seconds", "0.000001", "--seed", 1, out)
    assert (code, err) == (0, "")
    rate, data = wavfile.read(out)
    assert rate == SR and data.shape == (1, 2)


# ------------------------------------------------------------ journeys
def test_a_journey_is_rendered_offline_deterministically(tmp_path, capsys):
    from gentle_stream.journey import BUILTIN

    a, b, plain = tmp_path / "a.wav", tmp_path / "b.wav", tmp_path / "plain.wav"
    code, stdout, err = render(capsys, "--seconds", 6, "--seed", 9, "--journey", "warm-up", a)
    assert (code, err) == (0, "")
    assert stdout == f"wrote {a}: 6 s, lofi, seed 9, journey warm-up\n"
    render(capsys, "--seconds", 6, "--seed", 9, "--journey", "warm-up", b)
    render(capsys, "--seconds", 6, "--seed", 9, plain)
    assert a.read_bytes() == b.read_bytes()
    assert a.read_bytes() != plain.read_bytes()
    e = Engine(Style(), seed=9, samples=False)
    e.queue_journey(BUILTIN["warm-up"])
    n, bars = 6 * SR, []
    while sum(map(len, bars)) < n:
        bars.append(e.render_bar())
    want = np.round(np.clip(np.concatenate(bars)[:n], -1, 1) * 32767).astype(np.int16)
    assert np.array_equal(wavfile.read(a)[1], want)


def test_an_unknown_journey_is_a_usage_error_listing_the_journeys(tmp_path, capsys):
    from gentle_stream.journey import BUILTIN

    with pytest.raises(SystemExit) as exit_info:
        main(["render", "--journey", "nope", str(tmp_path / "x.wav")])
    err = capsys.readouterr().err
    assert exit_info.value.code == 2 and err.startswith("usage: ")
    assert "invalid journey 'nope'" in err and all(name in err for name in BUILTIN)
    assert not (tmp_path / "x.wav").exists()


def test_render_help_documents_the_journey_flag(capsys):
    with pytest.raises(SystemExit):
        main(["render", "--help"])
    assert "--journey" in capsys.readouterr().out
