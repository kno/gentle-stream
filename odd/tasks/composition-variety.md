# Composition variety: themes, verses, choruses and answering counters

Branch `feat/composition-variety`, stacked on `chore/lint-cleanup`. Builds on the per-genre profiles.

## Specs

**S1** — Maintainer, verbatim: "vamos con más variedad musical", after the options "Pre-estribillos, puentes con
melodía propia, finales y riffs de bajo. Es lo que sigue acercando los géneros a lo que son."

**S2** — Themes and variations: each cycle develops the motif with its own fresh tail (never the same loop again),
and the tail is drawn from the genre's own bar rhythms (the profile's), not a shared set.

**S3** — A repeated section plays exactly what it played before within a cycle: pop's chorus comes back note for note
(the hook), the same chords and the same counter-melody.

**S4** — A chorus of its own: `Style.hook` (2-8 scale degrees, optional) gives the chorus its own progression; without
it the chorus takes section B's. The chorus melody lifts a step for its question and repeats it for its answer.
`pop` composes verse, chorus, verse, chorus, a breakdown and the chorus twice more; its form has no `A`/`B` stages.

**S5** — The counter-melody can answer instead of opposing: `Genre.counter_mode = "echo"` takes the lead's rhythm
from the bar before (pop, heavy); the default stays contrary motion. Both keep to the chord tones.

**S6** — Lo-fi renders sample-identical to the base; every other genre keeps its profile unless this feature changed
it (pop only).

## Tasks

| Task | Specs | Route | Commit |
| :--- | :--- | :--- | :--- |
| T1 Themes and variations per cycle, on the profile's rhythms | S2, S6 | inline | done |
| T2 A repeated section repeats: the chorus hook | S3 | inline | done |
| T3 `Style.hook`, the chorus section and melody | S4 | inline | done |
| T4 `counter_mode = "echo"`, pop and heavy; pop's verse/chorus form | S5 | inline | done |

## Log

**L1** — "vamos con más variedad musical".

**L2** — Chosen from the offered options: "Pre-estribillos, puentes con melodía propia, finales y riffs de bajo".

**L3** — Implementation notes: the tail is drawn from the profile's rhythms (already so) and each third cycle starts it
a step up or down, behind `Profile.tail_tilt` (False in the default profile: lo-fi keeps its exact golden hashes, as
S6 demands; every other genre opts in). A section that comes back within a cycle replays its bars verbatim unless
that cycle lifts the key on it. `Style.hook` is optional and round-trips; `variation` rotates it. `counter_mode` is a
Genre attribute; pop and heavy echo. Pop's form is now verse/chorus only. The 12 non-lo-fi golden hashes were
recaptured (their writing changed, as intended).
