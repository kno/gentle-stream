# M11: Live broadcast (PM-045)

The background player sends what plays, with a picture of it, to an RTMP(S) ingest such as YouTube Live. One branch per
task, stacked on `feat/tui-render`. The spec is the PM-045 section of `docs/PROGRESSIVE_MUSIC_ROADMAP.md`
("### Milestone M11"), read verbatim before each task, with the maintainer's decisions below.

## Specs

**S0** — Maintainer decisions (2026-10-28/29, verbatim answers):
- Encoder: "El programa ffmpeg del sistema"; then, after the finding that ffmpeg 9.0.2 cannot read `rtmp_playpath`
  from a file ("Unrecognized option '/rtmp_playpath'"): "ffmpeg codifica, gentle-stream publica (recomendado)" —
  ffmpeg only encodes to FLV on a pipe (no network, no key); gentle-stream implements the RTMP/RTMPS publish.
- Frames: "Pillow, como extra opcional (recomendado)".
- Content: "utiliza otro tts con licencia que lo permita"; then "espeak-ng (recomendado para empezar)" — while a
  broadcast runs, phrases are spoken with espeak-ng, never `say`.
- Non-redistributable voice packs: "Voz integrada mientras se emite (recomendado)" — while a broadcast runs, the choir
  sings with the built-in voice; the pack comes back when it stops.

**S1** — "The audio sent equals the audio given to the device (fake encoder), and the audio callback never waits on the
encoder or the network: a stalled encoder drops broadcast frames, never local audio."

**S2** — "The stream key never appears in any process's arguments, in logs, in `ctl status`, in the TUI or in errors (a
test searches all of them for a sentinel key)."

**S3** — "A failing or disconnected encoder is reported (status and TUI) and leaves local playback untouched."

**S4** — "A broadcast with a non-redistributable voice pack or `say` phrases is refused with the reason, unless the
maintainer's chosen rule (decision 3) allows it." Decision 3 (S0): substitute, do not refuse: espeak-ng phrases and the
built-in choir while broadcasting; refuse with the reason only when espeak-ng is not installed and phrases are in use.

**S5** — Scope rules from the roadmap: frames about 10 fps at 1280x720 drawn by the player (style name, mood, genre and
key, journey line, spectrum, vocals and binaural lines); status in `ctl status` and the TUI: target (the URL without the
key), duration, dropped frames, the encoder's last error; stopping the player ends the broadcast; the key is set with
`gentle-stream stream key set` from stdin into a 0600 file in the config dir, or an environment variable; no health or
therapeutic claims in any overlay; tests with a fake encoder and a local sink, never a real service.

**S6** — First live test (2026-10-29), maintainer, verbatim: "no se ven los iconos, y en mobile no se ajusta bien"
(screenshot: "♪" and "→" drawn as empty boxes; the service's vertical auto-crop keeps only the centre, cutting the
left-aligned text; the health badge said "Mala"). Asked about the mobile fix: "no se puede hacer algún diseño que se
ajuste automáticamente?" — one video is sent and the service crops it, so the picture cannot know the screen: the
automatic answer is a layout whose text stays in the centre column a 9:16 crop keeps, the spectrum full width. Video:
"Bitrate fijo 2500k y 30 fps (recomendado)".

## Tasks

| Task | Specs | Route | Branch | Commit |
| :--- | :--- | :--- | :--- | :--- |
| T0 Record the decisions | S0 | inline | `docs/m11-decisions` | done (`f1a5ed8`) |
| T1 Ingest URL and stream key storage (`stream key set/clear`, `stream url`, `stream show`) | S2, S5 | inline | `feat/stream-key` | done (T1 commit; base `f1a5ed8`) |
| T2 RTMP(S) publisher (handshake, connect, publish, FLV tags as messages) and a fake local server | S2, S3 | inline | `feat/rtmp-publish` | done (`901bc99`; base `cfcba4f`) |
| T3 Broadcast view: 1280x720 frames with Pillow from the player snapshot | S5 | inline | `feat/broadcast-view` | done (T3 commit; base `901bc99`) |
| T4 Encoder pipeline: ffmpeg (raw video + PCM in, FLV out), bounded queues fed from the callback | S1, S3 | inline | `feat/broadcast-encoder` | done (T4 commit; base `9d523aa`) |
| T5 Player/daemon/ctl: `ctl stream start/stop`, status keys, safe sources while broadcasting | S1-S5 | inline | `feat/broadcast-ctl` | done (T5 commit; base `3d4bc5c`) |
| T5b Picture fixes from the first live test: missing glyphs, a layout that survives the mobile crop, constant 2500k at 30 fps | S6 | inline | `feat/broadcast-layout` | done (T5b commit; base `d911a42`) |
| T6 TUI action, parity map, README, sentinel-key leak test over every surface | S2, S3, S5 | inline | `feat/broadcast-tui` | pending |

## Log

- L1: User (verbatim): "suena bien, no importa que haya que reiniciar tras añadir un pack de voces. Sigue con la
  implementación". Next in the roadmap: M11 (PM-045), whose open decisions were asked first (S0).
- L2: Environment: ffmpeg 9.0.2 (rtmp, rtmps), espeak-ng installed, Pillow not installed. `-/rtmp_playpath FILE` is
  rejected by ffmpeg 9.0.2, so the key cannot reach ffmpeg off its command line; hence the in-process publisher (S0).
- L3: High-risk items: (2) security (the stream key), (4) concurrency (callback feed, encoder and network threads),
  (5) a new optional dependency (Pillow) and a system tool (ffmpeg). Secrets work (T1, T2) gets its own commits.
- L4: T1. New streamconf.py: StreamKey (repr/str masked; `reveal()` only for the publisher), key from stdin only
  (getpass without echo on a terminal), stream.key written atomically with mode 0600, refused when group/others can
  read it or another user owns it (ssh rule); GENTLE_STREAM_KEY wins; stream.json holds the URL (rtmp/rtmps, host, an
  app path, no credentials, query or fragment). CLI `stream key set|clear`, `stream url URL`, `stream show`; a key given
  as an argument is refused without echoing it. Every test asserts the sentinel key never reaches stdout or stderr.
  Parity: the three `stream` commands are listed in NOT_IN_TUI as "gap ... (PM-045 T6)" until the TUI action exists.
  Mutations: 9 of 9 caught after adding URL cases; __format__ removed (str() already masks). RED ImportError; GREEN 31.
- L5: T1 suite job-36: 1455 passed, 3 deselected, 0 test daemons. T1 verified.
- L6: T2. New rtmp.py: AMF0 encode/decode (object, ECMA array for ffmpeg's onMetaData), flv_tags (pipe-safe short
  reads), ChunkWriter/ChunkReader (type-0 headers, type-3 continuations with the extended timestamp, Set Chunk Size
  applied), Publisher: handshake, connect (app from the URL path, tcUrl = the URL, no key), releaseStream/FCPublish/
  createStream/publish (the key only as the stream name, inside the connection), FLV tags as messages (metadata as
  @setDataFrame), chunk size 4096, RTMPS through TLS, a reader thread answering pings and noting errors or a closed
  connection, a clean end (FCUnpublish, deleteStream). Server text passes through `_hide`, which masks the key.
  Tests: tests/rtmp_fake.py (a local ingest), TLS with a throwaway openssl certificate, and ffmpeg as a real RTMP
  server (`-listen 1`): what it receives decodes as audio + video lasting the whole 2 s. Mutations: 8 of 8 caught
  after making a continuation chunk carry an extended timestamp and recording the peer's chunk size.
- L7: T2 suite job-37: 1469 passed, 3 deselected, 0 test daemons. T2 verified.
- L8: T3. Pillow added as the optional extra `broadcast` (and to the dev group so the tests run); ImportError ->
  BroadcastUnavailable "a live broadcast needs Pillow: pip install 'gentle-stream[broadcast]'". New lines.py holds
  format_time, journey_line and binaural_line (app.py imports them, so the TUI and the picture share one wording).
  broadcast_view.py: ViewText (the TUI's lines, empty when the TUI hides them), view_text(player), BroadcastView.frame
  (raw RGB24 1280x720; text drawn with Pillow's default FreeType font once per change and cached; spectrum bars
  painted with numpy, rose-to-muted gradient; long lines cut with an ellipsis inside the margins). RED ImportError;
  a test compared absolute sums against a non-black background and was corrected to measure against the quiet frame.
  Mutations: 4 of 5 caught after adding the silent-vocals test; `if line:` -> True is equivalent (empty text draws
  nothing). 11 focused tests.
- L9: T3 suite job-38: 1480 passed, 3 deselected, 0 test daemons. T3 verified. (The session lost the record of the T2 push: feat/rtmp-publish was committed but not on fork; pushed with T3.)
- L10: T4. Delegated to gentle-ai-worker (context backstop); it returned partial: broadcast.py without tests, with
  defects found in review: `os.dup2(read_fd, 3)` in the parent (clobbers the daemon's own fd 3), the encoder left
  running when connect fails, stop() waiting on ffmpeg before closing the video pipe (always the 2 s kill), the exit
  code read with poll() right at stderr EOF (missed errors). Rewritten inline, tests first (RED against the worker's
  code). broadcast.py: encoder_command(sr) has no URL/key and reads video from `pipe:{video_fd}` (the pipe's own
  number, pass_fds); feed() = put_nowait or count a drop; threads write audio, draw 10 fps, write video, publish the
  FLV and watch ffmpeg (stderr kept masked, an exit while broadcasting is the error, preferred over the publisher's
  "no FLV" which it causes); stop() joins writers, kills a stuck encoder, closes its inputs, lets it finish, closes the
  publish; status() BroadcastStatus. tests/fake_encoder.py (copy/stall/fail), tests/test_broadcast.py (8): audio
  byte-for-byte, 500 feeds < 50 ms against a stalled encoder with drops counted, a failing encoder reported with the
  key masked, unreachable ingest leaves no encoder, command without URL/key, the caller's fds untouched, stop
  idempotent with no broadcast threads left, real ffmpeg to the local ingest (audio + video, key not in `ps`). One
  flaky run traced to counting all threads; the test now checks the broadcast's own threads. Mutations: 5 of 6 caught;
  "stderr not masked" is equivalent (stderr reaches the outside only through _fail, which masks again).
- L11: T4 suite job-39: 1488 passed, 3 deselected, 0 test daemons, 0 encoder processes left. T4 verified.
- L12: T5 (inline; delegation skipped after two partial worker results). Player.stream_start/stream_stop/streaming
  own a Broadcast fed from the audio callback next to the recorder (both branches of the callback); close() ends it.
  Start refuses, with the reason: no URL, no/unsafe key, no Pillow, already broadcasting, the journey's phrases
  without espeak-ng (checked on the running or queued journey: Engine.journey_phrases). Safe sources while it runs:
  speech.use_only("espeak-ng") (cache cleared; BROADCAST_NEEDS message when absent), a non-redistributable pack set
  aside (Engine.set_voices) and restored on stop, the journey's phrases forgotten and rendered again with the program
  in use. Daemon: stream_start/stream_stop commands, state key "stream" (last; test_daemon pin updated). Client:
  stream_start/stream_stop/streaming. CLI: `ctl stream start|stop` ("Broadcasting to URL"; "Broadcast to URL ended
  after m:ss (N frames dropped)"), `ctl status` gains "stream" (additive, last; two pins updated). Parity: `ctl stream`
  listed as a T6 gap. Tests (18): device audio == broadcast audio through the player, refusals, a failing encoder
  reported while the device keeps getting audio, double start, close ends it, pack swap both ways, say/espeak-ng
  order, phrases re-rendered, refusal without espeak-ng, ctl output and usage, and end to end: the background player
  broadcasting through the real ffmpeg to the local ingest, `ctl status` and `ps` without the key. Mutations: 8 of 8.
- L13: T5 suite job-40: 1506 passed, 3 deselected, 0 test daemons; the one encoder left belonged to the maintainer's real player (no test runtime dir), a live test broadcast. T5 verified.
- L14: T5b. The first live test showed "♪" and "→" as boxes; checking the font found "é" missing too (Pillow's
  default). broadcast_view: a system font with the glyphs (Arial Unicode on macOS, DejaVu/Noto on Linux, Menlo), else
  Pillow's with `drawable()` replacing what it lacks (stand-ins, the unaccented letter, or nothing; `missing()` detects
  a glyph by comparing its pixels with a lacking character's). Layout: every line centred and wrapped (between " · "
  parts, then words; at most N lines, "..." after) inside SAFE_WIDTH 400, the middle a 9:16 crop keeps (405 px of
  1280); the spectrum full width (y 300-470). Video: FPS 30, -b:v/-maxrate 2500k, -bufsize 5000k, nal-hrd=cbr,
  keyframes every 60 frames (2 s). Measured: 5.8 ms a frame; synthesis 45.1x real time alone, 43.8x while drawing 30
  fps (roadmap floor 4x). Sample frame and its mobile crop rendered to listen/broadcast-frame*.png (untracked). Tests:
  glyphs present (system font and forced Pillow font), text only inside the crop column, long lines wrap, spectrum
  spans the width, encoder 30 fps/2500k/keyframe 2 s. Mutations: 6 of 6.
- L15: T5b suite job-41: 1512 passed, 3 deselected, 0 test daemons. T5b verified.
