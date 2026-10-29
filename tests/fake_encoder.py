"""A stand-in for ffmpeg in the broadcast tests (PM-045): `fake_encoder.py MODE OUT VIDEO_FD`.

copy:  stores stdin (the PCM) in OUT, counts the video bytes into OUT.video, writes a small FLV stream to stdout.
stall: reads nothing, so the pipes fill up and stay full, until it is killed.
fail:  prints an error that holds $FAKE_KEY to stderr and exits 1, as an encoder that echoes its output URL would.
"""
import os
import sys
import threading
import time


def flv_tag(kind: int, ts: int, payload: bytes) -> bytes:
    head = bytes([kind]) + len(payload).to_bytes(3, "big") + ts.to_bytes(3, "big") + bytes(4)
    return head + payload + (len(head) + len(payload)).to_bytes(4, "big")


def main() -> int:
    mode, out, video_fd = sys.argv[1], sys.argv[2], int(sys.argv[3])
    if mode == "fail":
        sys.stderr.write(f"[flv] Error opening output rtmp://ingest/live2/{os.environ.get('FAKE_KEY', '')}: "
                         "connection refused\n")
        return 1
    if mode == "stall":
        time.sleep(120)
        return 0
    video_bytes = [0]

    def drain_video() -> None:
        with os.fdopen(video_fd, "rb") as f:
            while chunk := f.read(1 << 16):
                video_bytes[0] += len(chunk)

    reader = threading.Thread(target=drain_video)
    reader.start()
    sys.stdout.buffer.write(b"FLV\x01\x05\x00\x00\x00\x09" + bytes(4) + flv_tag(9, 0, b"\x17\x00" + bytes(3) + b"cfg")
                            + flv_tag(8, 0, b"\xaf\x00\x12\x10"))
    sys.stdout.buffer.flush()
    with open(out, "wb") as f:
        while chunk := sys.stdin.buffer.read(1 << 16):
            f.write(chunk)
    reader.join()
    with open(out + ".video", "w") as f:
        f.write(str(video_bytes[0]))
    sys.stdout.buffer.write(flv_tag(8, 20, b"\xaf\x01" + b"a" * 64))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
