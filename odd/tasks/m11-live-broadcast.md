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

**S7** — Maintainer, verbatim (2026-10-29): "debes añadir cuanto antes la capacidad para mutear en local, pero seguir
emitiendo". Chosen meaning (stated to the maintainer): muting acts on the speakers only; the broadcast and the session
recording keep the sound at its volume; pause still stops the music for everyone.

**S8** — Maintainer, verbatim: "gentle-stream no puede elegir otra salida?" then "si" to the proposal: `ctl output`
lists the outputs and `ctl output NAME` switches to one live (short fade, no restart, the broadcast untouched); a
TUI key and palette entry with the list, the output in the state line; the choice remembered for the next start; a
one-channel output (headphones in hands-free mode: "Invalid number of channels [PaErrorCode -9998]") gets the two
channels mixed instead of failing.

**S9** — Maintainer, verbatim, while T8 started: "y un fallback para que la aplicación siempre arranque, aunque sea sin
sonido local, para poder hacer streaming". When no output opens (the chosen one, then the system default), the player
starts on a silent output paced by the clock, so the music, a broadcast and a recording go on; the state says why
there is no sound here. This replaces "a device error stops the player from starting".

**S10** — Maintainer, verbatim: "no se ven todas las opciones posible en el pie, añade una tecla ? para mostrarlas en
un popup".

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
| T5c Video paced by the clock (second live test still "Mala") | S1, S6 | inline | `feat/broadcast-tui` (own commit) | done (T5c commit; confirmed live, L19) |
| T6 TUI action, parity map, README, sentinel-key leak test over every surface | S2, S3, S5 | inline | `feat/broadcast-tui` | done (T6 commit) |
| T7 Mute here, keep broadcasting (`ctl mute`/`unmute`, `M`, status) | S7 | inline | `feat/local-mute` | done (T7 commit; base `1052db8`) |
| T8 Choose the audio output (`ctl output`, TUI, remembered, mono outputs) | S8 | inline | `feat/audio-output` | done (T8/T9 commit; base `7c235db`) |
| T9 `?` popup with every key and action | S10 | inline | `feat/audio-output` | done (T8/T9 commit; base `7c235db`) |

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
- L16: Second live test, maintainer verbatim: "sigue dando mensaje de calidad mala, analiza porqué". Evidence from the
  running player (new code: -r 30 -b:v 2500k): 5156 drops in 666 s, ffmpeg at 10.6% CPU, x264 720p30 at 39x real
  time here: not CPU. Cause: frames were counted, not clocked (wait 1/30 s, then draw ~6 ms: ~26 fps real) while
  ffmpeg stamps rawvideo by frame count, so the video fell behind the audio, ffmpeg stopped reading the audio to wait,
  the audio queue filled and broadcast blocks were dropped (gaps), and the ingest got less than real time. T5c:
  _draw_video sends frame n at n / FPS from the start and repeats a late picture for each frame time it missed. RED: a
  20 ms view sent 33 frames in 2 s; GREEN: 30 a second. With frames sent at once, a broken video pipe raced the
  watcher in the failing-encoder test; writers and the publisher now defer to the encoder's exit (_encoder_ended).
- L17: T6. BroadcastModal on `L` and in the palette: URL (saved with streamconf.save_url, its message), the key line
  of `stream show`, a password Input for the key (saved 0600, the field emptied whatever happens), clear, start/stop in
  a worker (connecting takes a moment), errors kept in the dialog. The state line shows "● LIVE m:ss" or "LIVE failed
  (L)" (S3 in the TUI). PARITY maps `ctl stream` and the `stream` commands to "broadcast"; NOT_IN_TUI holds only
  `ctl status` again. S2 sentinel searches: the TUI screen (export_screenshot) while typing, after saving, while live,
  after a failure; and tests/test_stream_leaks.py, a real broadcast through the background player: `stream show`,
  `ctl stream start`, `ctl status`, every process's arguments (`ps -axo command`), an ingest refusing with the stream
  name in its description, and player.log; the key reached the ingest as the stream name (so the sentinel was live).
  Mutations: 5 of 5 (key kept in the field, not masked, no LIVE, failure not shown, URL not saved).
- L18: Suite job-42: 2 failed, 1521 passed. (1) test_ctl_stream_without_a_player reached the maintainer's real player
  (no private XDG_RUNTIME_DIR) and sent it `stream start`; it refused ("already broadcasting"), nothing changed, its
  status was checked right after (playing, broadcasting, 0 drops in 190 s: the restarted player already ran the
  T5c working tree). Fix: tests/conftest.py gives every test a private short XDG_RUNTIME_DIR under /tmp (the daemon
  tests' own fixture still overrides it); with the real player running, the test now finds no player. (2) The
  thread-leak test looked for any `rtmp-reader` in the process, also those left by test_rtmp.py publishers never
  closed; it now checks only the threads of the broadcast it starts.
- L19: Maintainer, verbatim, after restarting the player on the T5c working tree: "si, ya no da error" (YouTube no longer reports bad health; the player showed 0 dropped frames in 190 s). S6 confirmed live.
- L20: Suite job-43: 1523 passed, 3 deselected, 0 test daemons. T5c and T6 verified; M11 implementation complete.
- L21: Slow tests job-44: 3 passed, 0 test daemons. M11 closed. PR order (stacked, each against the previous): docs/m11-decisions, feat/stream-key, feat/rtmp-publish, feat/broadcast-view, feat/broadcast-encoder, feat/broadcast-ctl, feat/broadcast-layout, feat/broadcast-tui.
- L22: T7 (S7). Player.muted / set_muted: a monitor gain applied last in the audio callback, after the recorder and
  the broadcast were fed and the level/spectrum measured, ramped over RAMP_SECONDS like the volume (no click); pause
  still stops everything. Daemon `mute` {"on": bool} (bad value refused, unchanged), state key "muted" (last); client
  mute()/muted; `ctl mute` / `ctl unmute` ("Muted here; a broadcast or a recording keeps the sound" / "Sound back
  here"; arguments refused, exit 2), `ctl status` "muted" (additive, last; pins updated). TUI `M`, palette "Mute
  here", state line "MUTED here"; PARITY maps both ctl actions. README: TUI key, ctl row, parity row, the broadcast
  section. Tests (11): speakers silent after a ramp and back, broadcast and recording keep the music while muted,
  pause, daemon, ctl, status, TUI, palette. Mutations: 3 of 3 (mute before feeding, no ramp, mute ignored); "no
  ramp" first survived (the click check looked inside one block only): the first muted block must now start with the
  music and go down (the 30 ms fade is longer than a 512-frame block). That stronger test was edited after job-45
  collected the file; it passed 3 times on its own.
- L23: T7 suite job-45: 1534 passed, 3 deselected, 0 test daemons. T7 verified.
- L24: T8 (S8, S9). outputs.py: the devices that play (index, name, channels, system default), find by name (exact,
  then any case), the choice in output.json. Player: start() opens the remembered output, else the system default,
  else a SilentStream that calls the callback by the clock (S9: the music, a broadcast and a recording go on); a
  one-channel output gets both channels mixed (the callback builds a stereo block, feeds the recorder and broadcast
  with it, then writes mono or stereo); set_output() fades the speakers (the monitor gain), swaps the stream live and
  remembers it; `output` = {name, channels, silent, error}. Daemon `outputs`/`set_output`, state "output" (last);
  client; `ctl output [NAME|default]`; `ctl status` "output"; TUI `o` (OutputModal), state line "out: NAME" or "no
  sound here (o)"; parity. Contract change by S9: a device error no longer stops the player; the two tests that
  pinned it now pin the new behaviour (daemon and TUI start silent, the reason in the status). tests/conftest.py gives
  every test one fake stereo output (the machine's devices vary: here the default was 1-channel headphones). A first
  run of the affected files hung 39 min: test_main's old "clean error" test now opened a real TUI; fixed by the new
  test, which replaces StreamApp.run. Mutations: 5 of 5.
- L25: T9 (S10). `?` (footer "Keys", palette "Keys") opens HelpModal: every visible binding (key label and
  description), ctrl+p, and every palette action with its help, from the app's own BINDINGS and palette_actions(), so
  new actions appear by themselves; it scrolls (tested at 80x24) and `?`/esc close it.
- L26: T8+T9 suite job-49: 1551 passed, 3 deselected, 0 test daemons. Verified.
