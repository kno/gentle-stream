"""PM-045 T2: gentle-stream publishes FLV over RTMP(S) itself, so the stream key stays in this process."""
import io
import shutil
import ssl
import subprocess
import threading

import pytest

from gentle_stream.rtmp import (
    Publisher,
    PublishError,
    amf0_decode,
    amf0_encode,
    flv_tags,
)
from gentle_stream.streamconf import StreamKey
from tests.rtmp_fake import FakeIngest

KEY = "SENTINEL-KEY-t2-77aa-qq"
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is needed for this check")


def flv(*tags: tuple[int, int, bytes]) -> bytes:
    """An FLV stream: header, then each (type, timestamp ms, payload) tag with its back-pointer."""
    out = b"FLV\x01\x05\x00\x00\x00\x09" + bytes(4)
    for kind, ts, payload in tags:
        head = bytes([kind]) + len(payload).to_bytes(3, "big") + (ts & 0xFFFFFF).to_bytes(3, "big") \
            + bytes([ts >> 24]) + bytes(3)
        out += head + payload + (len(head) + len(payload)).to_bytes(4, "big")
    return out


TAGS = [(18, 0, amf0_encode("onMetaData", {"duration": 0.0, "width": 1280.0})),
        (9, 0, b"\x17\x00" + bytes(3) + b"avc-config"),
        (8, 0, b"\xaf\x00\x12\x10"),
        (9, 100, b"\x27\x01" + bytes(3) + b"x" * 10000),          # larger than one chunk
        (8, 23, b"\xaf\x01" + b"a" * 300),
        (9, 0x1000000 + 5, b"\x27\x01" + bytes(3) + b"late" * 3000)]   # extended timestamp, over several chunks


# ------------------------------------------------------------ FLV and AMF0
def test_flv_tags_reads_ffmpegs_output_format():
    assert list(flv_tags(io.BytesIO(flv(*TAGS)))) == TAGS


@pytest.mark.parametrize("data", [b"", b"NOT AN FLV STREAM", flv(*TAGS)[:-7]])
def test_a_stream_that_is_not_flv_or_ends_mid_tag_raises(data):
    with pytest.raises(PublishError):
        list(flv_tags(io.BytesIO(data)))


def test_amf0_round_trips_the_values_rtmp_commands_use():
    values = ["connect", 1.0, {"app": "live2", "n": 2.5, "ok": True, "nested": {"x": None}}, None, False, "é"]
    assert amf0_decode(amf0_encode(*values)) == values


# ------------------------------------------------------------ publishing
def publish(ingest, tags=TAGS, **kw):
    publisher = Publisher(ingest.url, StreamKey(KEY), **kw)
    publisher.open()
    for tag in tags:
        publisher.send(*tag)
    publisher.close()
    ingest.wait()
    return publisher


def test_connect_names_the_app_and_publish_names_the_key_only_inside_the_connection():
    ingest = FakeIngest()
    publish(ingest)
    assert ingest.error is None
    assert ingest.connect["app"] == "live2" and ingest.connect["tcUrl"] == ingest.url
    assert KEY not in repr(ingest.connect)
    assert ingest.peer_chunk_size == 4096                   # fewer chunk headers than the default 128
    assert [c[0] for c in ingest.commands] == ["connect", "releaseStream", "FCPublish", "createStream", "publish",
                                               "FCUnpublish", "deleteStream"]       # a clean end
    publish_command = next(c for c in ingest.commands if c[0] == "publish")
    assert ingest.stream_name == KEY and publish_command[4] == "live"


def test_the_tags_arrive_as_rtmp_messages_unchanged_and_in_order():
    ingest = FakeIngest()
    publish(ingest)
    metadata = ingest.media[0]
    assert metadata[0] == 18 and amf0_decode(metadata[2]) == ["@setDataFrame", "onMetaData",
                                                             {"duration": 0.0, "width": 1280.0}]
    assert ingest.media[1:] == TAGS[1:]


def test_publish_from_sends_an_flv_stream_until_it_ends():
    ingest = FakeIngest()
    publisher = Publisher(ingest.url, StreamKey(KEY))
    publisher.open()
    publisher.publish_from(io.BytesIO(flv(*TAGS)))
    publisher.close()
    ingest.wait()
    assert ingest.media[1:] == TAGS[1:]


def test_a_ping_from_the_ingest_is_answered_while_publishing():
    ingest = FakeIngest(ping=True)
    publisher = Publisher(ingest.url, StreamKey(KEY))
    publisher.open()
    for _ in range(100):                      # the reader thread answers on its own
        if ingest.pong is not None:
            break
        publisher.send(*TAGS[2])
        threading.Event().wait(0.02)
    publisher.close()
    ingest.wait()
    assert ingest.pong == b"\x00\x07" + (1234).to_bytes(4, "big")


def test_a_refused_publish_is_an_error_that_never_shows_the_key():
    ingest = FakeIngest(refuse=True)
    publisher = Publisher(ingest.url, StreamKey(KEY))
    with pytest.raises(PublishError) as raised:
        publisher.open()
    message = str(raised.value)
    assert "NetStream.Publish.BadName" in message and KEY not in message and "<stream key>" in message


def test_a_dropped_connection_is_an_error_on_send():
    ingest = FakeIngest(close_after=2)
    publisher = Publisher(ingest.url, StreamKey(KEY))
    publisher.open()
    with pytest.raises(PublishError, match="the ingest closed the connection|connection"):
        for _ in range(200):
            publisher.send(9, 0, b"\x27\x01" + bytes(3) + b"x" * 20000)
    assert KEY not in str(publisher.error or "")


def test_an_unreachable_ingest_is_an_error_without_the_key():
    with pytest.raises(PublishError) as raised:
        Publisher("rtmp://127.0.0.1:9/live2", StreamKey(KEY), timeout=2).open()
    assert "cannot reach 127.0.0.1:9" in str(raised.value) and KEY not in str(raised.value)


def test_rtmps_wraps_the_connection_in_tls(tmp_path):
    if shutil.which("openssl") is None:
        pytest.skip("openssl is needed to make a test certificate")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj",
                    "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1",
                    "-keyout", str(tmp_path / "k.pem"), "-out", str(tmp_path / "c.pem")],
                   check=True, capture_output=True)
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(tmp_path / "c.pem", tmp_path / "k.pem")
    client = ssl.create_default_context(cafile=str(tmp_path / "c.pem"))
    ingest = FakeIngest(tls=server)
    publish(ingest, ssl_context=client)
    assert ingest.error is None and ingest.media[1:] == TAGS[1:]


# ------------------------------------------------------------ against a real RTMP implementation
@needs_ffmpeg
def test_ffmpeg_as_the_ingest_receives_a_playable_stream(tmp_path):
    """ffmpeg listens as an RTMP server; what it receives from the publisher must decode as audio and video."""
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    out = tmp_path / "received.flv"
    server = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-listen", "1", "-timeout", "10",
                               "-i", f"rtmp://127.0.0.1:{port}/live2/{KEY}", "-c", "copy", "-y", str(out)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    source = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                             "testsrc=size=320x240:rate=10", "-f", "lavfi", "-i", "sine=frequency=440",
                             "-t", "2", "-c:v", "libx264", "-g", "10", "-c:a", "aac", "-f", "flv", "pipe:1"],
                            check=True, capture_output=True).stdout
    publisher = Publisher(f"rtmp://127.0.0.1:{port}/live2", StreamKey(KEY))
    for _ in range(50):                                   # until ffmpeg listens
        try:
            publisher.open()
            break
        except PublishError:
            threading.Event().wait(0.1)
    publisher.publish_from(io.BytesIO(source))
    publisher.close()
    assert server.wait(20) == 0, server.stderr.read().decode() if server.stderr else ""
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                            str(out)], check=True, capture_output=True, text=True).stdout.split()
    assert sorted(probe) == ["audio", "video"]
    duration = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                               str(out)], check=True, capture_output=True, text=True).stdout
    assert float(duration) > 1.8                              # the whole 2 s arrived
