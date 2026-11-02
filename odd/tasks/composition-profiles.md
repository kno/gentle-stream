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
| T1 `Profile` with today's values; `BarPlan.section_len`/`next_section`; genres off `FIRST_FORM`; per-profile cycle clock; byte-identical | S2, S3 | inline | done (ba1b6a9) |
| T2 Profile knobs that change writing: 16-bar sections, step/leap/range, rhythms, two chords per bar; tests | S2 | inline | pending |
| T3 Profiles for the nine non-default genres; genre tests updated; README | S4 | inline | pending |
| T4 `pop` genre, tests, README | S5 | inline | pending |
| T5 `ballad` genre, tests, README | S5 | inline | pending |
| T6 `heavy` genre, tests, README | S5 | inline | pending |

## Log

**L1** — "la música en general es siempre la misma o muy parecida ¿podemos hacer algo al respecto? por ejemplo, si
queremos hacer algo más pop, rock, heavy, baladas..."

**L2** — "vale, ahora haz los cambios que has dicho antes" → chose "Perfil de composición por género".
