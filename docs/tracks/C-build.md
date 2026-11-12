# Track C — Build

**In plain words:** you make the model write a program that builds the part, and fix it
when the checks say it is wrong. The brief gives exact numbers and Track B gives exact
checks, so your work is turning those into geometry that builds every time: first the
right size and every through-hole, then the masses, then detail.

```mermaid
flowchart LR
    PL["plan"] --> G["generate x N"]
    G --> R{"builds?"}
    R -- "no: traceback" --> FX["repair"] --> R
    R -- "yes" --> K["self-check vs facts"]
    K --> V{"critic"}
    V -- "corrected program" --> R
    V -- "approved" --> S["select: best self-score"]
    S --> OUT["test_case_n.stp"]
```

## You own

`forge/stages/build.py` `forge/stages/verify.py` `forge/stages/select.py`
`forge/backends/` `forge/library/`

## Numbers you move

| Number | How to read it | Now | Target |
|---|---|---|---|
| Build rate | parts where the agent, not the fallback, produced the file | unmeasured | 9 of 9 |
| Dimension score | `self_check.dimensions`, exact | unmeasured | 1.00 on every part |
| Hole score | `self_check.holes`, exact | unmeasured | 1.00 on every part |
| Self-score by tier | simple / medium / complex means | unmeasured | simple ≥ 0.95, medium ≥ 0.85, complex ≥ 0.70 |
| Critic gain | self-score after critique minus before | unmeasured | positive on average |

To test your stages alone: write the plan by hand for one part and feed it in.

## Backlog, in order

1. **Run the base agent on the nine practice parts** and sort the outcomes: crashed,
   wrong size, wrong hole count, wrong shape. Everything below is ordered by a guess;
   reorder it by what you see.
2. **Exact envelope, always.** The bounding box is given. After building, if an extent
   is off by a hair, find the feature that sets it. Never rescale the finished part to
   fit: that distorts every hole.
3. **Hole count is a hard target.** `through_holes_genus` is the exact number the scorer
   counts. Typical ways to get it wrong: a blind hole drilled too deep becomes a through
   hole; two crossing bores merge; a hole that misses the body does nothing. Make the
   repair prompt name the difference ("built 5, target 6") and list the facts' hole
   inventory (diameter, axis, centre) so the model can find the missing one.
4. **Use the hole inventory directly.** `cylindrical_holes_and_bores` gives diameter,
   axis, length and centres. Generate those cuts from the data in plain Python and hand
   the model a part that already has its listed holes; let it spend its effort on the
   body. Mind `more_not_listed` and tilted axes given as vectors.
5. **Build rate.** Group tracebacks from a run and remove the largest group with a line
   in the guide, a worked example or a fallback rule. Usual suspects: fillet radius too
   large, selectors that match nothing, sweeps and lofts, shells on filleted bodies.
6. **Degrade, do not fail.** If repair runs out, drop the failing feature and keep the
   body. Fillets and chamfers go first: the simple and medium parts carry dozens of
   torus and cone faces that are worth almost nothing in volume.
7. **Part-type recipes.** The practice set is engine parts, and so is the hidden set.
   Give the generator short worked examples for the recurring kinds: revolved parts
   (valve, bushing: sketch the half profile, revolve), prismatic blocks with hole
   patterns (cylinder head), shafts with offset journals (crankshaft), bores on tilted
   axes (V-block: build the tool cylinder along Z, rotate, translate, cut), radial fin
   patterns. Do not copy the practice parts' numbers.
8. **Critic that uses Track B's instruments.** Feed it the per-view silhouette scores
   and the difference sheet once they exist. Try a critic that never sees the program.
9. **Budget by tier.** `faces` in the facts gives the tier. One candidate and no critic
   may be enough for a 12-face part; spend the saved minutes on the 600-face one.
10. **Candidate diversity.** Vary the construction strategy across candidates (revolve
    vs extrude-and-cut vs union of blocks) so that selection has real alternatives.
11. **Parameter fitting (speculative).** When the structure is right and volume is off
    by a few percent, expose the unspecified dimensions as variables and search them
    against the self-score.
12. **build123d backend (optional).** Same kernel, different API. Worth an hour only if
    CadQuery's failure groups look API-specific.

## Search terms

CadQuery revolve / sweep / loft / shell, CadQuery polarArray and rarray, cut along
arbitrary axis, Workplane transformed rotate offset, counterbore and countersink
(cboreHole, cskHole), OpenCASCADE fillet failure, BRepCheck, shape healing, LLM program
synthesis for CAD, execution-guided generation, self-repair, critic model,
self-confirmation bias, best-of-N with a verifier, few-shot exemplar retrieval,
feature-based modelling, design intent, constructive solid geometry, derivative-free
optimisation (Nelder–Mead, CMA-ES), build123d.

Papers: CADSmith (numeric validator section), CADCodeVerify, ToolCAD (engine text
feedback beats visual feedback on multi-part models), Text2CAD-Bench (why sweep, loft
and shell crash).

## Traps

- Mirroring. The scorer does not mirror; a left-handed part scores like a different part.
  Check asymmetric features against the views.
- A critic round that lowers the self-score. `verify.py` reverts those; keep it that way.
- Spending the time budget on edge treatments while a hole is missing.
- Tuning prompts to the nine practice parts. The hidden parts are different parts of the
  same kind.

## Lab notes

Append one line per experiment: date, idea, number before → after, kept or dropped.

- 11 Nov (branch `c/facts-driven`): bores cut from facts + fitted `# FIT` dimensions + truncated-reply fix: parts built 3 → 4 as written, 7 with candidates on disk; hand-picked set scores 0.658 on the leaderboard. Kept, not merged.
- 11 Nov: fitting ran the kernel up to 64 times per candidate and can hide shape errors (part 5). Cap it and run it once, on the chosen candidate.
- 12 Nov: bores cut from the facts pattern by pattern until the through-hole count matches (`forge/compile.py: cut_holes_to_genus`): holes 1.00 on 9 of 9 with no model (before: 7 of 9 built at all). Kept.
- 12 Nov: hole count from B-rep topology (`brep_genus`) instead of meshing: same answer on 107 files, pass 1 from 19 min to 6 min. Kept.
- 12 Nov: model writes the body only, trimmed by the hull, bores by code: beats the no-model part on parts 4 and 6 only (thinking off), on 7 parts by small margins (thinking on). Kept as pass 2.
- 12 Nov: model lists empty regions as boxes and cylinders, code cuts and checks each (`forge/stages/carve.py`): most proposals rejected (silhouette changed, hole count changed, volume too low); part 4 0.825 → 0.851. Kept behind `FORGE_CARVE=1`; placement of an accepted cut is not verified.
- 12 Nov: today's tasks are C1–C5 in `docs/PLAN.md`.
- 12 Nov, leaderboard: model bodies help (part 4 0.851 → 0.915, part 1 +0.03, part 6 +0.01), model cut lists do not (part 9 0.784 → 0.733, part 8 −0.006, part 5 0, part 2 +0.014). Run with `FORGE_CARVE=0`.
- 12 Nov, review of 54 model-written bodies (runs `two-pass-1`, `-2`, `-4`): 12 ran at the first try (22%); of 80 errors 47 are CadQuery API misuse (methods that do not exist, wrong arguments to `center`, `rect`, `translate`, `transformed`), 21 kernel failures (fillet, loft, wire), 4 several solids. Of the 17 bodies that ran in the two thinking-on runs, 8 had the wrong envelope; the code shows why: `box()` is centred by default while features are placed in 0..X coordinates, and `Workplane("XZ").center()` is given world coordinates. The bodies that scored (parts 1, 2, 4) use only primitives placed by absolute coordinates and unioned. A body that runs with a wrong envelope is never sent back for repair. Next: a small helper API in absolute coordinates (box between corners, cylinder between two points, extruded polygon along an axis, revolved profile) so the model writes calls, not CadQuery; and envelope errors fed back as a repair.
- 12 Nov: model bodies written with helper solids in absolute coordinates + envelope repair (`c/helper-api`). Bodies that run at the first try: 22% → 90% (thinking off, 19 of 21) and 100% (thinking on, 14 of 14); errors 80 → 2; envelope right in the end 9 of 17 → 35 of 35 (12 of them after one repair). Model pass with thinking off takes about 70 s for nine parts. The bodies now build but are mostly worse than the hull on parts 5, 7, 8, 9 (estimate 0.1–0.6): what is left is spatial, not syntax. Leaderboard for `02` (old prompt, thinking off): part 4 0.913, so thinking is not needed for that gain.
