"""A local RTMP ingest for the tests (PM-045): it answers the handshake, connect, createStream and publish, and
records what it receives. Never a real service."""
from __future__ import annotations

import os
import socket
import threading

from gentle_stream.rtmp import ChunkReader, ChunkWriter, amf0_decode, amf0_encode


class FakeIngest:
    """Serves one publisher on 127.0.0.1. `refuse` makes publish fail with a description holding the stream name (as
    some servers do); `close_after` drops the connection after that many media messages; `ping` sends a ping
    request once publishing starts and records the answer."""

    def __init__(self, refuse: bool = False, close_after: int | None = None, ping: bool = False, tls=None):
        self.refuse, self.close_after, self.ping, self.tls = refuse, close_after, ping, tls
        self.connect: dict = {}
        self.commands: list[list] = []        # every AMF command received, decoded
        self.stream_name: str | None = None
        self.media: list[tuple[int, int, bytes]] = []
        self.pong: bytes | None = None
        self.peer_chunk_size = 128
        self.done = threading.Event()
        self.error: BaseException | None = None
        self._server = socket.create_server(("127.0.0.1", 0))
        self.port = self._server.getsockname()[1]
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"{'rtmps' if self.tls else 'rtmp'}://127.0.0.1:{self.port}/live2"

    def _run(self) -> None:
        try:
            conn, _ = self._server.accept()
            conn.settimeout(10)
            if self.tls is not None:
                conn = self.tls.wrap_socket(conn, server_side=True)
            with conn:
                self._serve(conn)
        except BaseException as e:  # noqa: BLE001  (recorded for the test to assert on)
            self.error = e
        finally:
            self._server.close()
            self.done.set()

    def _read_exact(self, conn, n: int) -> bytes:
        data = b""
        while len(data) < n:
            part = conn.recv(n - len(data))
            if not part:
                raise ConnectionError("publisher closed")
            data += part
        return data

    def _serve(self, conn) -> None:
        c0c1 = self._read_exact(conn, 1 + 1536)
        assert c0c1[0] == 3
        s1 = bytes(8) + os.urandom(1528)
        conn.sendall(b"\x03" + s1 + c0c1[1:])      # S0, S1, S2 (= C1)
        assert self._read_exact(conn, 1536) == s1   # C2 echoes S1
        reader, writer = ChunkReader(lambda n: self._read_exact(conn, n)), ChunkWriter(conn.sendall)
        writer.set_chunk_size(4096)
        while True:
            try:
                kind, timestamp, stream, payload = reader.read_message()
            except ConnectionError:
                return
            self.peer_chunk_size = reader.chunk_size
            if kind in (8, 9, 18):
                self.media.append((kind, timestamp, payload))
                if self.close_after is not None and len(self.media) >= self.close_after:
                    return
                continue
            if kind == 4 and payload[:2] == b"\x00\x07":
                self.pong = payload
                continue
            if kind != 20:
                continue
            command = amf0_decode(payload)
            self.commands.append(command)
            name, txn = command[0], command[1]
            if name == "connect":
                self.connect = command[2]
                writer.send(5, 0, 0, (2_500_000).to_bytes(4, "big"), csid=2)
                writer.send(20, 0, 0, amf0_encode("_result", txn, {"fmsVer": "FMS/3,0,1,123"},
                                                  {"level": "status", "code": "NetConnection.Connect.Success"}))
            elif name == "createStream":
                writer.send(20, 0, 0, amf0_encode("_result", txn, None, 1.0))
            elif name == "publish":
                self.stream_name = command[3]
                if self.refuse:
                    writer.send(20, 0, stream, amf0_encode(
                        "onStatus", 0.0, None, {"level": "error", "code": "NetStream.Publish.BadName",
                                                "description": f"{self.stream_name} is already publishing"}))
                    return
                writer.send(20, 0, stream, amf0_encode("onStatus", 0.0, None, {
                    "level": "status", "code": "NetStream.Publish.Start", "description": "publishing"}))
                if self.ping:
                    writer.send(4, 0, 0, b"\x00\x06" + (1234).to_bytes(4, "big"), csid=2)

    def wait(self, timeout: float = 10.0) -> None:
        assert self.done.wait(timeout), "the fake ingest did not finish"
