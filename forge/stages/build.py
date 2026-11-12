"""TRACK C. The model stage: the model writes the BODY only; code does the rest.

By the time this runs, forge.compile has already written a part made with no model (a
silhouette body with the facts' bores). The model is asked for the masses and pockets the
silhouettes cannot show. Its program is then finished by code: moved into the facts frame,
trimmed with the silhouette body, and given the facts' bores. A candidate replaces the
current part only if its estimate is higher.

    generate()         one body program from the brief, facts summary and views
    run_with_repair()  execute it (finished by code), feed kernel errors back
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from ..backends import CadBackend
from ..library import catalogue
from ..llm import LLM, text_block
from ..types import Candidate, Task

CODE_SYSTEM = """\
You model the BODY of a mechanical part by combining a few plain solids. Reply with at most
five lines of reasoning, then exactly one ```{language} code block of at most 60 lines.

Write the program ONLY with these functions. Do not import or call cadquery yourself: no
Workplane, no sketches, no selectors, no fillets, no chamfers.

    from forge.library import box, cylinder, cone, prism, revolve, polar, union, cut, common

{catalogue}

Every coordinate is a WORLD coordinate in the frame of the brief: millimetres, the minimum
corner of the bounding box at the origin. The finished body must span exactly 0..X, 0..Y and
0..Z of the envelope. Nothing is ever centred for you.

What happens after your program, automatically:
- every bore listed in the facts under "cylindrical_holes_and_bores" is cut from the exact
  data. Do NOT model those holes.
- the body is trimmed to the outline the eight views allow.
So model the masses: the main block or turned profile, bosses, ribs, webs, steps between
levels, and the pockets, recesses and hollow interiors that an outline cannot show. Use the
numbers of the brief and the facts; the target volume is in the facts, check against it.
Ten to thirty solids are enough. Leave out edge rounds and small detail.

Shape of a program:

```{language}
from forge.library import box, cylinder, prism, union, cut

base = box((0, 0, 0), (120, 80, 12))                     # plate, full envelope footprint
boss = cylinder((60, 40, 12), (60, 40, 45), 36)          # round boss standing on it
rib = prism('Y', [(20, 12), (42, 12), (42, 40)], 36, 44)  # triangular rib: (x, z) outline, y from 36 to 44
pocket = box((30, 20, 6), (50, 60, 13))                  # recess open to the top face
result = cut(union(base, boss, rib), pocket)
```

The last line must assign `result`."""


def helper_catalogue() -> str:
    from ..library import SOLIDS

    return "\n\n".join("    " + (fn.__doc__ or "").strip().replace("\n", "\n    ") for fn in SOLIDS)


FINISH_MARK = "# --- finished by forge: facts frame, silhouette trim, bores from facts.json ---"


def system_prompt(template: str, backend: CadBackend) -> str:
    if template is CODE_SYSTEM:      # bodies are written with the helper solids, not raw CadQuery
        return template.format(language=backend.language, catalogue=helper_catalogue())
    return template.format(language=backend.language, guide=backend.guide, catalogue=catalogue())


def extract_code(reply: str) -> str | None:
    blocks = re.findall(r"```[a-zA-Z0-9_+-]*\n(.*?)```", reply, flags=re.S)
    if blocks:
        return blocks[-1].strip()
    # A reply cut off by the token limit leaves the block open. A truncated program
    # still gives the repair loop something to work on; no program gives it nothing.
    opened = re.search(r"```[a-zA-Z0-9_+-]*\n(.*)\Z", reply, flags=re.S)
    if opened and ("cadquery" in opened.group(1) or "forge.library" in opened.group(1)):
        return opened.group(1).strip()
    return None


def _left(deadline: float | None) -> float | None:
    return None if deadline is None else deadline - time.monotonic()


def generate(llm: LLM, backend: CadBackend, task_blocks: list[dict], note: str = "",
             deadline: float | None = None) -> str:
    content = task_blocks + ([text_block(note)] if note else [])
    for _ in range(2):  # an empty or code-less reply must not cost the candidate
        left = _left(deadline)
        if left is not None and left < 20:
            return ""
        code = extract_code(llm.complete(system_prompt(CODE_SYSTEM, backend), content, timeout=left))
        if code:
            return code
        content = content + [text_block("Your previous reply contained no code block. Reply with the code block only.")]
    return ""


def finished(code: str, task: Task, hull: Path | None, holes: str) -> str:
    """The model's program plus the lines that finish it by code."""
    code = code.split(FINISH_MARK)[0].rstrip()
    if not task.facts or task.dir is None:
        return code
    return (f"{code}\n\n{FINISH_MARK}\n"
            "from forge.compile import finish_body as _finish_body\n"
            f"result = _finish_body(result, {str(Path(task.dir) / 'facts.json')!r}, "
            f"hull={str(hull) if hull else None!r}, holes={holes!r})\n")


def _execute(backend: CadBackend, cand: Candidate, task: Task, code: str, label: str, timeout: float = 150):
    env = {"FORGE_TASK_DIR": str(task.dir)} if task.dir and task.facts else None
    res = backend.execute(code, cand.dir / label, timeout=timeout, env=env)
    check = res.measure.get("check", {}) if res.ok and not res.error else {}
    return res, check


def envelope_problem(result, facts: dict) -> str:
    """Empty if the model's own body (before finishing) spans the envelope; else what to tell it."""
    raw = result.measure.get("raw_bbox") if result and result.measure else None
    box = facts.get("bounding_box_mm") if facts else None
    if not raw or not box:
        return ""
    lines = []
    for k, axis in enumerate("XYZ"):
        want = float(box[axis.lower()])
        lo, hi = raw["min"][k], raw["max"][k]
        if abs(lo) > 0.01 * want + 0.05 or abs(hi - want) > 0.01 * want + 0.05:
            lines.append(f"- {axis}: your body spans {lo:.2f} .. {hi:.2f}, it must span 0 .. {want:.2f}")
    return "\n".join(lines)


def volume_problem(check: dict, facts: dict, tol: float = 0.10) -> str:
    """Empty if the finished body's volume is within `tol` of the facts; else what to tell the model."""
    ratio, target = check.get("volume_ratio"), facts.get("volume_mm3") if facts else None
    if not ratio or not target or abs(ratio - 1) <= tol:
        return ""
    have = ratio * target
    if ratio > 1:
        return (f"This program runs and has the right envelope, but the part is too full. After trimming to the outline "
                f"and cutting the listed bores it has {have:.0f} mm^3; the real part has {target:.0f} mm^3. "
                f"{have - target:.0f} mm^3 more must be EMPTY ({(1 - 1 / ratio):.0%} of what you built). Surface area is "
                f"x{check.get('area_ratio', 1):.2f} of the real part's. Look at the views again, the isometric ones above "
                "all: where is the real part open that yours is solid? Deeper or more grooves, thinner fins or walls, "
                "a pocket, an open tray, a hollow. Remove that, with numbers that add up to the volume to remove.")
    return (f"This program runs and has the right envelope, but material is missing. After trimming to the outline and "
            f"cutting the listed bores it has {have:.0f} mm^3; the real part has {target:.0f} mm^3. "
            f"{target - have:.0f} mm^3 of material is missing: a mass you left out, a wall or web that is too thin, or a "
            "cut that is too deep. Add it, with numbers that add up.")


def run_with_repair(llm: LLM, backend: CadBackend, cand: Candidate, task: Task, task_blocks: list[dict],
                    repairs: int = 2, hull: Path | None = None, deadline: float | None = None) -> None:
    """Run the candidate's body program finished by code. On a crash, or on a body that does
    not span the envelope, ask for a fix. The best version that ran is the one kept."""
    has_bores = bool(task.facts.get("cylindrical_holes_and_bores")) if task.facts else False
    kept = None      # (code, result, check) of the best version so far
    for attempt in range(repairs + 1):
        best = None
        for holes in (("open", "listed") if has_bores else ("none",)):
            res, check = _execute(backend, cand, task, finished(cand.code, task, hull, holes), f"try{len(cand.log)}_{holes}")
            if best is None or check.get("estimate", -1) > best[1].get("estimate", -1):
                best = (res, check, holes)
            if not (res.ok and not res.error):
                break       # the body itself failed; the other hole variant will too
        if has_bores and best[0].ok and not best[0].error and best[1].get("holes", 1.0) < 1.0:
            # neither plain variant hits the through-hole count: run the search (20% of the score)
            res, check = _execute(backend, cand, task, finished(cand.code, task, hull, "fit"),
                                  f"try{len(cand.log)}_fit", timeout=300)
            if res.ok and not res.error and check.get("estimate", -1) > best[1].get("estimate", -1):
                best = (res, check, "fit")
        res, check = best[0], best[1]
        ran = res.ok and not res.error
        problem = ""
        if ran:
            rank = lambda c: (round(c.get("estimate", -1), 6), c.get("self_score", -1))   # self-score breaks ties (no views)
            if kept is None or rank(check) > rank(kept[2]):
                kept = (cand.code, res, check)
            problem = envelope_problem(res, task.facts)
            budget = "" if problem else volume_problem(check, task.facts)
            cand.log.append(f"ran (estimate {check.get('estimate', 0):.3f}, bores {best[2]}, volume x{check.get('volume_ratio', 0):.2f})"
                            + (", envelope wrong" if problem else ", volume off" if budget else ""))
            if not problem and not budget:
                break
        else:
            cand.log.append(f"error: {res.error.splitlines()[-1] if res.error else '?'}")
        left = _left(deadline)
        if attempt == repairs or (left is not None and left < 45):
            break
        if ran and not problem:
            what = budget
        elif ran:
            what = ("This program runs, but the body is not where it must be:\n" + problem + "\n\n"
                    "Usual causes: a coordinate measured from the part's centre instead of the minimum corner, "
                    "a mass that is missing at one end, or a solid that sticks out. Correct the coordinates.")
        else:
            what = (f"Problem:\n{res.error}\n\nFix it while keeping the intended geometry. Use only the "
                    "functions of forge.library listed above.")
        ask = task_blocks + [text_block(
            f"This program needs a correction.\n```{backend.language}\n{cand.code.split(FINISH_MARK)[0]}\n```\n{what}")]
        try:
            fixed = extract_code(llm.complete(system_prompt(CODE_SYSTEM, backend), ask, timeout=left))
        except Exception as exc:
            cand.log.append(f"repair call failed: {type(exc).__name__}")
            break
        if not fixed:
            break
        cand.code = fixed
    if kept:
        cand.code, cand.result, cand.check = kept
    else:
        cand.result, cand.check = res, {}


def floor_note(floor: dict | None, facts: dict) -> str:
    """The volume budget: what the outline of the views encloses against what the part really has,
    so the model has to reconcile the pictures with the numbers before it models anything."""
    if not floor or not floor.get("check") or not facts.get("volume_mm3"):
        return ""
    c = floor["check"]
    over, area, target = c.get("volume_ratio", 1.0), c.get("area_ratio", 1.0), float(facts["volume_mm3"])
    lines = ["VOLUME BUDGET (computed, exact):",
             f"- the real part: {target:.0f} mm^3, surface {facts.get('surface_area_mm2', 0):.0f} mm^2",
             f"- a solid that fills the outlines of all eight views, with the listed bores cut: {over * target:.0f} mm^3 "
             f"(x{over:.2f}), surface x{area:.2f} of the real part's"]
    if over > 1.05:
        lines.append(f"- so {(over - 1) * target:.0f} mm^3 inside the outline is EMPTY in the real part "
                     f"({1 - 1 / over:.0%} of the outline solid). No outline shows where; the shading and the lines inside "
                     "the views do, the two isometric views most of all.")
        if area < 0.8:
            lines.append("- the real surface is much larger than the outline solid's: expect thin fins or ribs with deep "
                         "gaps between them, an open tray, or a thin-walled shell, not a few shallow pockets.")
        lines.append("Before the code, state in one line where that empty volume is and which view shows it. "
                     "Your body's volume must come out near the real part's.")
    else:
        lines.append("- the outline solid is already close in volume: keep the masses where the outline has them.")
    return "\n".join(lines)
