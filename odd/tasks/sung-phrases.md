# Sung phrases: the voice sings the melody

A phrase can be sung: the spoken voice (Piper carlfm, or the system's) re-pitched with WORLD so each syllable lands on
a note of the melody, with vibrato, as a lead vocal. Branch `feat/sung-phrases`, stacked on `feat/piper-voice`.

## Specs

**S1** — Maintainer, verbatim: "la voz puede "cantar" con los tonos de la melodía?", then "prueba las 2", then after
the listening test (listen/canto): "2 y 3 son las mejores". Chosen technique: WORLD (pyworld), each voiced stretch
(syllable) on its own note and stretched to the note's length, the consonant before it ending on the note's start,
a 40 ms glide between notes, the melody moved by octaves into the voice's register.

**S2** — Answers, verbatim: "Say y journeys (recomendado)": `ctl say --sing` and a "Sing" switch in the TUI's say
dialog (t); in a journey, `"sing": true` per stage sings that stage's phrases.

**S3** — "Con vibrato (3)": vibrato from 0.25 s into a note (5.5 Hz, up to ±0.3 semitone, growing over 0.3 s).

**S4** — "Canta la melodía planeada (recomendado)": the voice sings the composer's planned melody even when the lead
layer does not play it; where no melody is planned (an intro), the chord's tones stand in.

**S5** — "Como voz principal (recomendado)": a sung phrase sits at the music's level with the music 6 dB under it
(spoken phrases keep their level and 3 dB duck).

**S6** — Constraints carried from earlier work: singing needs pyworld (`pyworld-prebuilt`, MIT, WORLD modified-BSD;
an optional extra, the install hint named when missing); rendering never runs in the render thread; while
broadcasting only Piper or espeak-ng voices are used (unchanged); the parity guard holds (CLI ↔ TUI); a journey edited
in words can ask for singing (bridge schema).

## Tasks

| Task | Specs | Route | Commit |
| :--- | :--- | :--- | :--- |
| T1 `sing.py`: syllables on notes, vibrato, lead level; the `sing` extra | S1, S3, S5, S6 | inline | done (aff09d9) |
| T2 Engine: the planned melody of coming bars (chord tones where none); a clip queued for an exact bar, its duck | S4, S5 | inline | done (aff09d9) |
| T3 `ctl say --sing`, the say dialog's Sing switch, daemon, client, parity, README | S2, S6 | inline | done (1db5bd0) |
| T4 Journeys: `"sing": true` per stage, sung on its phrase boundaries; bridge schema; README | S2, S6 | inline | done (3289a2e) |

## Log

- L1: Listening test (listen/canto, untracked; script /tmp/gs-tts/scripts/sing.py): WORLD pitch-only, WORLD syllables
  on notes, the same with vibrato, a channel vocoder on the speech's timing and on the notes. First mix inaudible
  ("no se oye ninguno con la múscia"): the voice was normalised as a spoken phrase, 6-12 dB under the music; redone as
  a lead vocal (the music's RMS, music 6 dB under). Verdict: "2 y 3 son las mejores".
- L2: pyworld 0.3.5 imports pkg_resources (needs setuptools<81 at runtime) and pyworld 0.3.6 ships no wheels;
  pyworld-prebuilt 0.3.6.post1 has wheels (macOS arm64/x86_64, manylinux, Windows), imports cleanly on 3.13, MIT.
- L3: T1: harvest also calls a consonant's noise voiced, so a syllable is a run of voiced *and* periodic frames
  (aperiodicity under 0.5 below 1 kHz); a consonant that does not fit before its note shortens the vowel before it
  (at most by half). Tests measure pitch with autocorrelation: harvest lags ~30 ms and misreads re-pitched synthetic
  voices. T2: Composer.plan/pivot now hold an RLock (a sung phrase asks for coming bars from a connection thread).
  T3: the daemon's say goes through Player.say for both paths. Ear check (listen/canto/6-integrado-player-say-sing.wav,
  real Piper): first phrase ready in 2.2 s (pyworld import, Piper start), the next in 0.26 s.
- L4: Fix found before committing T3: sing.voice_for's cache survived use_only, so a phrase analysed with macOS
  `say` could be reused on air; speech.clear_cache now clears it too (test first). T4: the engine decides a sung
  phrase one phrase boundary ahead (_sung_phrase, its own state) and hands (text, bar) to Engine.sing_requests,
  set by the Player only when pyworld is there; the Player's singer thread sings it on that bar's notes and queues
  it for that exact bar. Without pyworld the stage speaks and the log says why. Ear file:
  listen/canto/7-journey-etapa-cantada.wav.
- L5: Mutation checks: 19 mutants, 7 survived at first; tests strengthened (glide measured inside it, a long
  consonant that must shorten the vowel before it, exact silence between syllables, a key-lifted chord bar, a clip
  one bar late, a sung phrase asked for 4 bars ahead); the pyworld check in Player.say was redundant with
  voice_for and was removed. All 19 killed. Full suite: 1663 passed; 2 broadcast timing tests failed at load 13-16
  and passed alone (10/10 at load 64).
