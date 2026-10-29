# A natural voice for the phrases: Piper with carlfm

Spoken phrases use Piper (an external program, like espeak-ng) with the es_ES carlfm voice when it is installed, both
locally and while broadcasting. Branch `feat/piper-voice`, stacked on `feat/session-resume`.

## Specs

**S1** — Maintainer, verbatim: "vamos con las voces", then after the listening tests: "las mejores son la de piper"
and "las mejores con las de carlrm pero en masculino, las feminized quedan fatal". Chosen (verbatim answers):
"a-normal (recomendado)" and "En todas las frases (recomendado)": carlfm as Piper renders it, used for every phrase,
locally and while broadcasting; macOS `say` and espeak-ng stay as fallbacks when Piper is not installed (while
broadcasting, only espeak-ng).

**S2** — Licensing found before choosing (L2): Piper is GPL-3.0 since v1.3.0, so it is used as a separate program,
never imported. Almost every Spanish Piper voice derives from the lessac voice, whose data is research-only
(Blizzard 2013 licence); carlfm is public domain and trained from scratch, so it may be broadcast. The voice is
downloaded with a pinned revision and SHA-256, its licence kept beside it.

**S3** — The text never reaches a command line (stdin only); `--rate` maps to Piper's length scale; `--voice` and
`--list-voices` show the Piper voices too; the TUI offers the voice and its installation (parity).

## Tasks

| Task | Specs | Route | Commit |
| :--- | :--- | :--- | :--- |
| T1 `setup-speech`: download carlfm (pinned revision, SHA-256, LICENSES.txt) into the cache | S2 | inline | done (tests/test_piper_voice.py) |
| T2 speech.py: Piper backend first (local and broadcast), rate and voices, fallbacks | S1, S3 | inline | done |
| T3 TUI: the install in the voices dialog, the voice in the say dialog; parity; README | S3 | inline | done (tests/test_tui_voices.py) |
| T4 Piper kept open: a phrase well under a second, warm at player start (L5) | S1 | inline | done (tests/test_piper_voice.py) |

## Log

- L1: Listening tests in listen/voices (untracked): espeak-ng, Kokoro (ef_dora, em_alex, em_santa), Piper carlfm and
  davefx (reference); round 2 modulations of carlfm and em_alex; round 3 carlfm feminized with WORLD (pyworld),
  Kokoro ef_dora and two native female Piper voices as references. The maintainer chose carlfm, male, as rendered.
- L2: Sources checked: piper-tts 1.8.0 (GPL-3.0-or-later, OHF-Voice/piper1-gpl, `pip install piper-tts` gives a
  `piper` program); MODEL_CARDs of every es voice (davefx, sharvard, ald, daniela from lessac; mls from ryan, itself
  from lessac and CC BY-NC-SA; claude undeclared; carlfm public domain, from scratch); the Blizzard 2013 lessac licence
  ("exclusively for Research Purposes", any commercial purpose excluded). Kokoro-82M (Apache-2.0 weights) was the
  other clean option.
- L3: Pinned: rhasspy/piper-voices revision 5041a7a49ae5b3a0f30e6837769eb03fdbb231bd, es/es_ES/carlfm/x_low:
  es_ES-carlfm-x_low.onnx sha256 d69677323a907cd4963f42b29c20a98b5d6bfa7f3e64df339915e4650c00d125 (28,130,791
  bytes), .onnx.json sha256 d9bdfa9ff01eb2bc9e62e7d2593939d1e4c4d8eb7cf75f972731539d12399966, MODEL_CARD sha256
  a6e62a3d36c37c7702d877f784001208b952e2bf4d17c72a6b5da442fbefb4b3 (verified from that revision).
- L4: Contract change on purpose (S1): a broadcast with phrases is refused only when neither Piper (with a voice)
  nor espeak-ng is there; the message changed, and its pins in tests/test_broadcast_ctl.py were updated. `--rate` maps
  to Piper's length scale as 175 / rate. The say dialog's voice list comes from `speech.voices()`, so it lists
  carlfm with no change of its own. A phrase rendered before the install keeps its voice until the player restarts.
- L5: Maintainer, verbatim: "las frases con la nueva voz no se oyen", then "en la tui con t". Reproduced with a private
  player (FakeAudio): `ctl say` took 33 s against speech.TIMEOUT 30 s; Piper alone 9.5-11.4 s a phrase (a new Python,
  onnxruntime and the model every time; load 35). Fix (T4): one Piper per model and rate kept open with `-d`, a line
  per phrase, done on its "Wrote PATH" log line; started when the player starts (`speech.warm_up`), closed when it
  stops. Measured after: `ctl say` 0.8-1.2 s with the real Piper. conftest hides the user's Piper voice from tests.
