# Composition profiles: each genre composes its own way

Today every genre shares one composer (form, motif rhythms, melodic steps, harmonic rhythm), so genres differ in
sound but not in writing. A per-genre composition profile fixes that; then pop, ballad and heavy join.
Branch `feat/composition-profiles`, stacked on `feat/sung-phrases` (the composer's lock lives there).

## Specs

**S1** — Maintainer, verbatim: "la música en general es siempre la misma o muy parecida ¿podemos hacer algo al
respecto? por ejemplo, si queremos hacer algo más pop, rock, heavy, baladas...", then "vale, ahora haz los cambios
que has dicho antes", choosing "Perfil de composición por género" ("El cambio grande: cada género con su propia forma,
progresiones, ritmo armónico y carácter melódico; después pop, ballad y heavy. Por fases y con commits separados").

**S2** — Profile mechanism, no audible change: a `Profile` owned by each genre names the form (first cycle and
loop), section energies, motif rhythms, melodic character (step weights, leap chance and size, range), harmonic
rhythm (one or two chords per bar) and the B-section progressions. The default profile is today's composer exactly:
every genre renders the same samples as before (differential check against the base commit).

**S3** — Genres stop hard-coding section lengths (`FIRST_FORM`): a bar plan names its section's length and the next
section, and the cycle clock (`cycle_position`, the TUI's cycle time) follows the playing genre's form.

**S4** — The existing genres get their own profiles (audible, requested): ambient, jazz, rock, synthwave, electro,
electrohouse, cumbia, dubstep and chiptune each compose differently from lo-fi, which keeps today's profile as the
default experience. Genre-specific fills, builds and drops still land on the last bars of their sections.

**S5** — New genres in 4/4 (said before: "Añadir después `pop` y `ballad` en 4/4, y separar `heavy` de `rock`"):
`pop` (verse, chorus, bridge; repeated chorus hook), `ballad` (piano and strings, two chords per bar, long notes,
expressive leaps, a final lift) and `heavy` (riff-based metal always on). `rock` keeps its metal mode as documented.
Each is registered, offered to the model, works on both backends and passes the genre contract.

**S6** — Out of scope (said before: "Dejar el 6/8 para el final, como un cambio aparte"): 6/8 or 12/8 meters.

## Tasks

| Task | Specs | Route | Commit |
| :--- | :--- | :--- | :--- |
| T1 `Profile` with today's values; `BarPlan.section_len`/`next_section`; genres off `FIRST_FORM`; per-profile cycle clock; byte-identical | S2, S3 | inline | done (04f2f90) |
| T2 Profile knobs that change writing: 16-bar sections, step/leap/range, rhythms, two chords per bar; tests | S2 | inline (worker unavailable: MODULE_NOT_FOUND) | done (66f0b19) |
| T3 Profiles for the nine non-default genres; genre tests updated; README | S4 | inline | done (2711210) |
| T4 `pop` genre, tests, README | S5 | inline | done (25d2c4b) |
| T5 `ballad` genre (and the profile's `lift_chance`/`lift_at`), tests, README | S5 | inline | done (1afc9f3) |
| T6 `heavy` genre, tests, README | S5 | inline | done (288ae7b) |

## Log

**L1** — "la música en general es siempre la misma o muy parecida ¿podemos hacer algo al respecto? por ejemplo, si
queremos hacer algo más pop, rock, heavy, baladas..."

**L2** — "vale, ahora haz los cambios que has dicho antes" → chose "Perfil de composición por género".

**L3** — T3 evidence: lo-fi renders sample-identical to the base (fingerprints and its golden hashes); the nine other
genres changed audio. Found and fixed: a release longer than 4 bars had no question transform (TypeError), now it
answers in every phrase; ambient's one-note bar rhythms made `next` reuse a motif head, replaced by two-note bars.
The live-glide golden hashes of the nine changed genres were recaptured; `test_next_still_starts_a_fresh_motif`
now checks five seeds (a carried head never changes; a fresh one may match by chance).

**L4** — Full suite after T4: 1752 passed, 1 failed: `test_vocals.py::test_the_sampled_choir_matches_the_procedural_level_within_3_db[ambient-melody]`
(3.07 dB > 3). Cause found: the sampled "ooh" choir in ambient's intro is ~5 dB under the procedural one in every mode,
already at the base commit (-5.18 dB); the 8-bar intro of ambient's T3 profile weighs it more in the test's 12-bar
window. A per-vowel reference does not explain it (procedural "o" is only 0.9 dB under "a"). Pending decision.

**L5** — Decision: "Arreglar el desajuste (recomendado)". Cause: Voice Oohs fades while it holds and was calibrated on the
first half second of a 1 s note (held notes 3-8 dB under, growing with length). Fix: `Program.reference` (a held
note measured whole), used by Voice Oohs at 4 s against the procedural "o"; every other program unchanged.

**L6** — Closed. Fix of the pre-existing Voice Oohs level: f1ef69e. Final full suite: 1858 passed. Lo-fi renders
sample-identical to the base throughout (fingerprints, golden hashes). Not done (S6): 6/8 and 12/8 meters.
