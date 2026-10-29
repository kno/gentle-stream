"""Publish an FLV stream over RTMP or RTMPS (PM-045), so the stream key never leaves this process.

ffmpeg only encodes: it writes FLV to a pipe and never sees the network or the key (ffmpeg 9 cannot read the key from
a file, so publishing with it would put the key in its command line, where `ps` shows it). This module does the rest:
the RTMP handshake, `connect` to the app named by the URL, `releaseStream`/`FCPublish`/`createStream`, `publish` with
the key as the stream name, then every FLV tag as one RTMP message (audio 8, video 9, metadata 18 as @setDataFrame),
chunked at 4096 bytes. RTMPS is the same inside TLS. Errors are PublishError, with the key replaced by "<stream key>"
in anything the server says, since some servers echo the stream name back.
"""
from __future__ import annotations

import contextlib
import os
import socket
import ssl
import struct
import threading
from collections.abc import Callable, Iterator
from typing import Any, BinaryIO
from urllib.parse import urlsplit

from .streamconf import StreamKey

CHUNK = 4096
HIDDEN = "<stream key>"


class PublishError(Exception):
    """Publishing failed or stopped; the message never holds the key."""


# ---------------------------------------------------------------- AMF0, the command encoding
def _amf_value(v: Any) -> bytes:
    if v is None:
        return b"\x05"
    if isinstance(v, bool):
        return b"\x01" + bytes([v])
    if isinstance(v, (int, float)):
        return b"\x00" + struct.pack(">d", float(v))
    if isinstance(v, str):
        raw = v.encode("utf-8")
        return (b"\x02" + struct.pack(">H", len(raw)) if len(raw) < 0x10000 else b"\x0c" + struct.pack(">I", len(raw))) \
            + raw
    if isinstance(v, dict):
        out = b"\x03"
        for key, value in v.items():
            raw = str(key).encode("utf-8")
            out += struct.pack(">H", len(raw)) + raw + _amf_value(value)
        return out + b"\x00\x00\x09"
    raise TypeError(f"no AMF0 encoding for {type(v).__name__}")


def amf0_encode(*values: Any) -> bytes:
    return b"".join(_amf_value(v) for v in values)


def _amf_read(data: bytes, i: int) -> tuple[Any, int]:
    kind = data[i]
    i += 1
    if kind == 0x00:
        return struct.unpack_from(">d", data, i)[0], i + 8
    if kind == 0x01:
        return bool(data[i]), i + 1
    if kind in (0x02, 0x0C):
        width = 2 if kind == 0x02 else 4
        n = int.from_bytes(data[i:i + width], "big")
        return data[i + width:i + width + n].decode("utf-8"), i + width + n
    if kind in (0x03, 0x08):            # object, or ECMA array (ffmpeg's onMetaData): a count, then the same pairs
        if kind == 0x08:
            i += 4
        out: dict[str, Any] = {}
        while data[i:i + 3] != b"\x00\x00\x09":
            n = int.from_bytes(data[i:i + 2], "big")
            key = data[i + 2:i + 2 + n].decode("utf-8")
            out[key], i = _amf_read(data, i + 2 + n)
        return out, i + 3
    if kind == 0x0A:                    # strict array
        n, i = int.from_bytes(data[i:i + 4], "big"), i + 4
        items = []
        for _ in range(n):
            item, i = _amf_read(data, i)
            items.append(item)
        return items, i
    if kind in (0x05, 0x06):            # null, undefined
        return None, i
    if kind == 0x0B:                    # date: a double and a time zone
        return struct.unpack_from(">d", data, i)[0], i + 10
    raise ValueError(f"unsupported AMF0 type {kind}")


def amf0_decode(data: bytes) -> list[Any]:
    values, i = [], 0
    while i < len(data):
        value, i = _amf_read(data, i)
        values.append(value)
    return values


# ---------------------------------------------------------------- FLV, what ffmpeg writes
def _read_exact(stream: BinaryIO, n: int) -> bytes:
    """Up to `n` bytes: fewer only at the end of the stream (a pipe may return short reads)."""
    data = b""
    while len(data) < n:
        part = stream.read(n - len(data))
        if not part:
            break
        data += part
    return data


def flv_tags(stream: BinaryIO) -> Iterator[tuple[int, int, bytes]]:
    """(tag type, timestamp in ms, payload) for every tag of an FLV stream, until it ends."""
    header = _read_exact(stream, 9)
    if len(header) < 9 or header[:3] != b"FLV":
        raise PublishError("the encoder did not produce an FLV stream")
    _read_exact(stream, int.from_bytes(header[5:9], "big") - 9 + 4)   # the rest of the header, PreviousTagSize0
    while head := _read_exact(stream, 11):
        if len(head) < 11:
            raise PublishError("the encoder's FLV stream ended in the middle of a tag")
        size = int.from_bytes(head[1:4], "big")
        timestamp = int.from_bytes(head[4:7], "big") | head[7] << 24
        body = _read_exact(stream, size + 4)
        if len(body) < size + 4:
            raise PublishError("the encoder's FLV stream ended in the middle of a tag")
        yield head[0], timestamp, body[:size]


# ---------------------------------------------------------------- RTMP chunks
class ChunkWriter:
    """Writes RTMP messages as chunks (a full type-0 header, then type-3 continuations)."""

    def __init__(self, sendall: Callable[[bytes], Any]):
        self.sendall, self.chunk_size = sendall, 128

    def set_chunk_size(self, size: int) -> None:
        self.send(1, 0, 0, size.to_bytes(4, "big"), csid=2)
        self.chunk_size = size

    def send(self, kind: int, timestamp: int, stream: int, payload: bytes, csid: int = 3) -> None:
        extended = timestamp >= 0xFFFFFF
        ext = timestamp.to_bytes(4, "big") if extended else b""
        head = bytes([csid]) + min(timestamp, 0xFFFFFF).to_bytes(3, "big") + len(payload).to_bytes(3, "big") \
            + bytes([kind]) + stream.to_bytes(4, "little") + ext
        parts = [head + payload[:self.chunk_size]]
        for i in range(self.chunk_size, len(payload), self.chunk_size):
            parts.append(bytes([0xC0 | csid]) + ext + payload[i:i + self.chunk_size])
        self.sendall(b"".join(parts))


class ChunkReader:
    """Reads RTMP messages from chunks; applies Set Chunk Size messages itself."""

    def __init__(self, read_exact: Callable[[int], bytes]):
        self.read, self.chunk_size = read_exact, 128
        self.streams: dict[int, dict[str, Any]] = {}

    def read_message(self) -> tuple[int, int, int, bytes]:
        """(message type, timestamp, message stream id, payload) of the next complete message."""
        while True:
            first = self.read(1)[0]
            fmt, csid = first >> 6, first & 0x3F
            if csid == 0:
                csid = 64 + self.read(1)[0]
            elif csid == 1:
                b = self.read(2)
                csid = 64 + b[0] + b[1] * 256
            st = self.streams.setdefault(csid, {"ts": 0, "delta": 0, "length": 0, "type": 0, "stream": 0,
                                                "ext": False, "buf": b""})
            if fmt <= 2:
                field = int.from_bytes(self.read(3), "big")
                if fmt <= 1:
                    st["length"] = int.from_bytes(self.read(3), "big")
                    st["type"] = self.read(1)[0]
                if fmt == 0:
                    st["stream"] = int.from_bytes(self.read(4), "little")
                st["ext"] = field == 0xFFFFFF
                if st["ext"]:
                    field = int.from_bytes(self.read(4), "big")
                if fmt == 0:
                    st["ts"], st["delta"] = field, 0
                else:
                    st["delta"] = field
            elif st["ext"]:
                self.read(4)
            if not st["buf"] and fmt != 0:
                st["ts"] += st["delta"]
            st["buf"] += self.read(min(self.chunk_size, st["length"] - len(st["buf"])))
            if len(st["buf"]) < st["length"]:
                continue
            payload, st["buf"] = st["buf"], b""
            if st["type"] == 1:
                self.chunk_size = int.from_bytes(payload[:4], "big") & 0x7FFFFFFF
                continue
            return st["type"], st["ts"], st["stream"], payload


# ---------------------------------------------------------------- the publisher
class Publisher:
    """One live publish: `open()`, then `send()` tags (or `publish_from()` an FLV stream), then `close()`. A reader
    thread answers pings and notices errors or a closed connection, which the next `send()` raises."""

    def __init__(self, url: str, key: StreamKey, ssl_context: ssl.SSLContext | None = None, timeout: float = 10.0):
        parts = urlsplit(url)
        if parts.scheme not in ("rtmp", "rtmps") or not parts.hostname:
            raise PublishError(f"not an RTMP(S) URL: {url}")
        self.url, self.key, self.timeout = url, key, timeout
        self.host, self.tls = parts.hostname, parts.scheme == "rtmps"
        self.port = parts.port or (443 if self.tls else 1935)
        self.app = parts.path.strip("/")
        self.ssl_context = ssl_context
        self.error: str | None = None
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._stream = 0
        self._closing = False
        self._reader_thread: threading.Thread | None = None

    def _hide(self, text: str) -> str:
        return text.replace(self.key.reveal(), HIDDEN)

    # -------------------------------------------------------- connecting
    def _recv_exact(self, n: int) -> bytes:
        assert self._sock is not None
        data = b""
        while len(data) < n:
            try:
                part = self._sock.recv(n - len(data))
            except TimeoutError:
                if self._closing or self._reader_thread is None:
                    raise
                continue
            if not part:
                raise ConnectionError("the ingest closed the connection")
            data += part
        return data

    def open(self) -> None:
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as e:
            raise PublishError(f"cannot reach {self.host}:{self.port}: {e.strerror or e}") from None
        try:
            if self.tls:
                context = self.ssl_context or ssl.create_default_context()
                sock = context.wrap_socket(sock, server_hostname=self.host)
            self._sock = sock
            self._handshake()
            self._writer = ChunkWriter(sock.sendall)
            self._reader = ChunkReader(self._recv_exact)
            self._writer.set_chunk_size(CHUNK)
            self._command("connect", 1, {"app": self.app, "type": "nonprivate",
                                         "flashVer": "FMLE/3.0 (compatible; gentle-stream)", "tcUrl": self.url})
            self._await_result(1)
            key = self.key.reveal()
            self._command("releaseStream", 2, None, key)
            self._command("FCPublish", 3, None, key)
            self._command("createStream", 4, None)
            self._stream = int(self._await_result(4)[3])
            self._command("publish", 5, None, key, "live", stream=self._stream, csid=4)
            self._await_publish_start()
        except PublishError:
            self._shut()
            raise
        except (OSError, ConnectionError, ssl.SSLError, ValueError, IndexError) as e:
            self._shut()
            raise PublishError(self._hide(f"the ingest at {self.host}:{self.port} failed: {e}")) from None
        self._reader_thread = threading.Thread(target=self._read_loop, name="rtmp-reader", daemon=True)
        self._reader_thread.start()

    def _handshake(self) -> None:
        assert self._sock is not None
        c1 = bytes(8) + os.urandom(1528)
        self._sock.sendall(b"\x03" + c1)
        s0s1 = self._recv_exact(1 + 1536)
        if s0s1[0] != 3:
            raise PublishError(f"the ingest at {self.host}:{self.port} does not speak RTMP")
        self._recv_exact(1536)                     # S2
        self._sock.sendall(s0s1[1:])               # C2 echoes S1

    def _command(self, name: str, txn: int, *args: Any, stream: int = 0, csid: int = 3) -> None:
        with self._lock:
            self._writer.send(20, 0, stream, amf0_encode(name, float(txn), *args), csid=csid)

    def _handle_control(self, kind: int, payload: bytes) -> None:
        if kind == 4 and payload[:2] == b"\x00\x06":            # ping request: answer with the same time
            with self._lock:
                self._writer.send(4, 0, 0, b"\x00\x07" + payload[2:6], csid=2)

    def _await_result(self, txn: int) -> list[Any]:
        while True:
            kind, _, _, payload = self._reader.read_message()
            if kind != 20:
                self._handle_control(kind, payload)
                continue
            command = amf0_decode(payload)
            if command[0] == "_error" and command[1] == txn:
                raise PublishError(self._hide(f"the ingest refused: {_describe(command)}"))
            if command[0] == "_result" and command[1] == txn:
                return command

    def _await_publish_start(self) -> None:
        while True:
            kind, _, _, payload = self._reader.read_message()
            if kind != 20:
                self._handle_control(kind, payload)
                continue
            command = amf0_decode(payload)
            if command[0] == "onStatus":
                info = command[3] if len(command) > 3 and isinstance(command[3], dict) else {}
                if info.get("code") == "NetStream.Publish.Start":
                    return
                if info.get("level") == "error":
                    raise PublishError(self._hide(f"the ingest refused to publish: {_describe(command)}"))
            elif command[0] == "_error":
                raise PublishError(self._hide(f"the ingest refused to publish: {_describe(command)}"))

    def _read_loop(self) -> None:
        """While publishing: answer pings, remember errors and a closed connection."""
        try:
            while not self._closing:
                kind, _, _, payload = self._reader.read_message()
                if kind != 20:
                    self._handle_control(kind, payload)
                    continue
                command = amf0_decode(payload)
                info = command[3] if len(command) > 3 and isinstance(command[3], dict) else {}
                if command[0] == "onStatus" and info.get("level") == "error":
                    self.error = self._hide(f"the ingest stopped the stream: {_describe(command)}")
        except (OSError, ConnectionError, ValueError, IndexError):
            if not self._closing and self.error is None:
                self.error = "the ingest closed the connection"

    # -------------------------------------------------------- publishing
    def send(self, kind: int, timestamp: int, payload: bytes) -> None:
        """One FLV tag as an RTMP message."""
        if self.error is not None:
            raise PublishError(self.error)
        if kind == 18:
            payload = amf0_encode("@setDataFrame") + payload
        try:
            with self._lock:
                self._writer.send(kind, timestamp, self._stream, payload, csid={8: 4, 9: 6}.get(kind, 5))
        except (OSError, ssl.SSLError):
            self.error = self.error or "the ingest closed the connection"
            raise PublishError(self.error) from None

    def publish_from(self, stream: BinaryIO) -> None:
        """Send every tag of an FLV stream until it ends (or an error)."""
        for tag in flv_tags(stream):
            self.send(*tag)

    def close(self) -> None:
        """End the publish cleanly (FCUnpublish, deleteStream) when the connection still works, then close it."""
        if self._sock is None:
            return
        if self.error is None:
            with contextlib.suppress(OSError, ssl.SSLError):
                self._command("FCUnpublish", 6, None, self.key.reveal())
                self._command("deleteStream", 7, None, float(self._stream))
        self._shut()

    def _shut(self) -> None:
        self._closing = True
        sock, self._sock = self._sock, None
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
            sock.close()
        if self._reader_thread is not None and self._reader_thread is not threading.current_thread():
            self._reader_thread.join(2)


def _describe(command: list[Any]) -> str:
    """The code and description of a server's error or status, for an error message."""
    info = next((v for v in command[2:] if isinstance(v, dict)), {})
    return " ".join(str(info[k]) for k in ("code", "description") if info.get(k)) or "no reason given"
