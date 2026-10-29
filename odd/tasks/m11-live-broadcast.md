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

## Tasks

| Task | Specs | Route | Branch | Commit |
| :--- | :--- | :--- | :--- | :--- |
| T0 Record the decisions | S0 | inline | `docs/m11-decisions` | in progress |
| T1 Ingest URL and stream key storage (`stream key set/clear`, `stream url`, `stream show`) | S2, S5 | inline | `feat/stream-key` | pending |
| T2 RTMP(S) publisher (handshake, connect, publish, FLV tags as messages) and a fake local server | S2, S3 | inline | `feat/rtmp-publish` | pending |
| T3 Broadcast view: 1280x720 frames with Pillow from the player snapshot | S5 | inline | `feat/broadcast-view` | pending |
| T4 Encoder pipeline: ffmpeg (raw video + PCM in, FLV out), bounded queues fed from the callback | S1, S3 | inline | `feat/broadcast-encoder` | pending |
| T5 Player/daemon/ctl: `ctl stream start/stop`, status keys, safe sources while broadcasting | S1-S5 | inline | `feat/broadcast-ctl` | pending |
| T6 TUI action, parity map, README, sentinel-key leak test over every surface | S2, S3, S5 | inline | `feat/broadcast-tui` | pending |

## Log

- L1: User (verbatim): "suena bien, no importa que haya que reiniciar tras añadir un pack de voces. Sigue con la
  implementación". Next in the roadmap: M11 (PM-045), whose open decisions were asked first (S0).
- L2: Environment: ffmpeg 9.0.2 (rtmp, rtmps), espeak-ng installed, Pillow not installed. `-/rtmp_playpath FILE` is
  rejected by ffmpeg 9.0.2, so the key cannot reach ffmpeg off its command line; hence the in-process publisher (S0).
- L3: High-risk items: (2) security (the stream key), (4) concurrency (callback feed, encoder and network threads),
  (5) a new optional dependency (Pillow) and a system tool (ffmpeg). Secrets work (T1, T2) gets its own commits.
