"""TRACK C. Stages 2 and 3: plan -> program -> a part that actually builds.

generate() writes one program. run_with_repair() executes it and, on a crash or
an invalid solid, feeds the kernel's error back until it runs or we give up.
"""
from __future__ import annotations

import re

from ..backends import CadBackend
from ..facts import self_check
from ..library import catalogue
from ..llm import LLM, text_block
from ..types import Candidate, Task

CODE_SYSTEM = """\
You are an expert CAD programmer. Write one complete program that builds the part.
Reply with the reasoning you need, then exactly one ```{language} code block.

The part is scored against the real one on volume overlap, surface match, bounding-box
dimensions (2 % off already costs points) and the exact number of through-holes. Build
the envelope and the main masses exactly, then every hole, then smaller features. Skip
a cosmetic fillet or chamfer before you risk a program that fails.

Dimensions the brief does not state (a wall thickness, a rib depth, a plate size) must be
estimated from the views. Give each its own line at the top, marked with bounds:
    wall = 6.0  # FIT 3..12
At most four such lines. A search tunes them afterwards against the part's known volume
and surface area, so a marked estimate is better than a hidden guess. Never mark a
dimension the brief gives.

The bores listed in the facts under "cylindrical_holes_and_bores" are cut automatically
after your program, from the exact data. Spend your effort on the body, on features the
list does not cover, and on anything the brief says the list leaves out.

{guide}

READY-MADE HELPERS (import and call these rather than deriving the geometry):
{catalogue}"""


def system_prompt(template: str, backend: CadBackend) -> str:
    return template.format(language=backend.language, guide=backend.guide, catalogue=catalogue())


def extract_code(reply: str) -> str | None:
    blocks = re.findall(r"```[a-zA-Z0-9_+-]*\n(.*?)```", reply, flags=re.S)
    if blocks:
        return blocks[-1].strip()
    # A reply cut off by the token limit leaves the block open. A truncated program
    # still gives the repair loop something to work on; no program gives it nothing.
    opened = re.search(r"```[a-zA-Z0-9_+-]*\n(.*)\Z", reply, flags=re.S)
    if opened and "cadquery" in opened.group(1):
        return opened.group(1).strip()
    return None


def generate(llm: LLM, backend: CadBackend, task_blocks: list[dict], plan: str) -> str:
    content = task_blocks + [text_block("BUILD PLAN:\n" + plan)]
    for _ in range(2):  # an empty or code-less reply must not cost the candidate
        code = extract_code(llm.complete(system_prompt(CODE_SYSTEM, backend), content))
        if code:
            return code
        content = content + [text_block("Your previous reply contained no code block. Reply with the code block only.")]
    return ""


def run_with_repair(llm: LLM, backend: CadBackend, cand: Candidate, task: Task,
                    task_blocks: list[dict], repairs: int = 3) -> None:
    for attempt in range(repairs + 1):
        cand.result = backend.execute(cand.code, cand.dir / f"try{len(cand.log)}")
        if cand.result.ok and not cand.result.error:
            cand.check = self_check(cand.result.measure, task.facts) if task.facts else {}
            cand.log.append(f"ran (self-score {cand.self_score:.3f})")
            if task.facts:
                add_listed_holes(backend, cand, task)
                fit_parameters(backend, cand, task)
            return
        cand.log.append(f"error: {cand.result.error.splitlines()[-1] if cand.result.error else '?'}")
        if attempt == repairs:
            return
        ask = task_blocks + [text_block(
            f"This program failed.\n```{backend.language}\n{cand.code}\n```\n"
            f"Problem:\n{cand.result.error}\n\n"
            "Fix it while keeping the intended geometry. If one operation keeps failing "
            "(often a fillet, shell or sweep), build that feature a simpler way."
        )]
        fixed = extract_code(llm.complete(system_prompt(CODE_SYSTEM, backend), ask))
        if not fixed:
            return
        cand.code = fixed


# --- geometry from the facts, no model involved -------------------------------------

HOLES_MARK = "# --- bores from facts.json (added by forge) ---"
FIT_LINE = re.compile(r"^(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<value>-?\d+(?:\.\d+)?)\s*#\s*FIT\s+"
                      r"(?P<lo>-?\d+(?:\.\d+)?)\s*\.\.\s*(?P<hi>-?\d+(?:\.\d+)?)", re.M)


def _try(backend: CadBackend, cand: Candidate, task: Task, code: str, label: str, timeout: float = 90):
    """Run a variant of the candidate's program. Returns (self_score, code, result, check) or None."""
    res = backend.execute(code, cand.dir / label, timeout=timeout)
    if not (res.ok and not res.error):
        return None
    check = self_check(res.measure, task.facts)
    return check["self_score"], code, res, check


def _adopt(cand: Candidate, trial, note: str) -> bool:
    if trial and trial[0] > cand.self_score + 1e-6:
        before = cand.self_score
        _, cand.code, cand.result, cand.check = trial
        cand.log.append(f"{note}: self-score {before:.3f} -> {cand.self_score:.3f}")
        return True
    return False


def add_listed_holes(backend: CadBackend, cand: Candidate, task: Task) -> None:
    """Cut the bores listed in the facts into the model's body; keep the result only if it scores higher."""
    holes = task.facts.get("cylindrical_holes_and_bores") or []
    if not holes or HOLES_MARK in cand.code:
        return
    trials = []
    for extend in (False, True):
        code = (f"{cand.code}\n\n{HOLES_MARK}\n"
                "from forge.library.facts_tools import cut_listed_holes as _cut_listed_holes\n"
                f"result = _cut_listed_holes(result, {holes!r}, extend={extend})\n")
        trial = _try(backend, cand, task, code, f"holes{int(extend)}_{len(cand.log)}")
        if trial:
            trials.append(trial)
    if trials:
        _adopt(cand, max(trials, key=lambda t: t[0]), "bores cut from facts")


def fit_parameters(backend: CadBackend, cand: Candidate, task: Task, max_params: int = 4, timeout: float = 45) -> None:
    """Tune the lines the model marked `# FIT lo..hi` against the self-score (volume, area, box, holes).

    One parameter at a time: four values across its range, then two either side of the best.
    """
    if abs(cand.check.get("volume_ratio", 1) - 1) < 0.01 and abs(cand.check.get("area_ratio", 1) - 1) < 0.02:
        return
    names = [m.group("name") for m in FIT_LINE.finditer(cand.code)][:max_params]
    runs = 0

    def variant(name: str, value: float):
        nonlocal runs
        runs += 1

        def swap(m):
            if m.group("name") != name:
                return m.group(0)
            return f"{name} = {value:.4g}  # FIT {m.group('lo')}..{m.group('hi')}"

        return _try(backend, cand, task, FIT_LINE.sub(swap, cand.code), f"fit{len(cand.log)}_{runs}", timeout)

    for name in names:
        m = next(m for m in FIT_LINE.finditer(cand.code) if m.group("name") == name)
        lo, hi = sorted((float(m.group("lo")), float(m.group("hi"))))
        if hi - lo < 1e-9:
            continue
        step = (hi - lo) / 3
        scored = [(t[0], v, t) for v in (lo, lo + step, lo + 2 * step, hi) if (t := variant(name, v))]
        if not scored:
            continue
        best = max(scored, key=lambda s: s[0])
        for _ in range(2):  # narrow around the best value
            step /= 2
            near = [(t[0], v, t) for v in (best[1] - step, best[1] + step) if lo <= v <= hi and (t := variant(name, v))]
            best = max(near + [best], key=lambda s: s[0])
        _adopt(cand, best[2], f"fitted {name} = {best[1]:.4g}")
