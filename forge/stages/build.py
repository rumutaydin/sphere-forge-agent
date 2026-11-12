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
You are an expert CAD programmer. Write one complete program that builds the BODY of the part.
Reply with at most a few lines of reasoning, then exactly one ```{language} code block of at
most 120 lines.

What happens after your program, automatically:
- every bore listed in the facts under "cylindrical_holes_and_bores" is cut from the exact
  data. Do NOT model those holes.
- the body is trimmed to the outline the eight views allow, so its outer silhouette is
  corrected for you.
So spend your effort on what silhouettes cannot show: pockets, recesses, hollow interiors,
steps between levels, wall thicknesses, ribs, and the right mass in the right place.

The part is scored on volume overlap and surface match with the real part, bounding-box
dimensions and the number of through-holes. Use the frame of the brief: millimetres, the
minimum corner of the bounding box at the origin, so the body spans exactly
0..X, 0..Y, 0..Z of the envelope. The target volume is in the facts: check your arithmetic
against it. Skip cosmetic fillets and chamfers.

{guide}

READY-MADE HELPERS (import and call these rather than deriving the geometry):
{catalogue}"""

FINISH_MARK = "# --- finished by forge: facts frame, silhouette trim, bores from facts.json ---"


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


def run_with_repair(llm: LLM, backend: CadBackend, cand: Candidate, task: Task, task_blocks: list[dict],
                    repairs: int = 2, hull: Path | None = None, deadline: float | None = None) -> None:
    """Run the candidate's body program finished by code. On a crash, ask for a fix."""
    has_bores = bool(task.facts.get("cylindrical_holes_and_bores")) if task.facts else False
    for attempt in range(repairs + 1):
        best = None
        for holes in (("open", "listed") if has_bores else ("none",)):
            res, check = _execute(backend, cand, task, finished(cand.code, task, hull, holes), f"try{len(cand.log)}_{holes}")
            if best is None or check.get("estimate", -1) > best[1].get("estimate", -1):
                best = (res, check, holes)
            if not (res.ok and not res.error):
                break       # the body itself failed; the other hole variant will too
        cand.result, cand.check = best[0], best[1]
        if cand.result.ok and not cand.result.error:
            cand.log.append(f"ran (estimate {cand.check.get('estimate', 0):.3f}, bores {best[2]})")
            return
        cand.log.append(f"error: {cand.result.error.splitlines()[-1] if cand.result.error else '?'}")
        left = _left(deadline)
        if attempt == repairs or (left is not None and left < 45):
            return
        ask = task_blocks + [text_block(
            f"This program failed.\n```{backend.language}\n{cand.code.split(FINISH_MARK)[0]}\n```\n"
            f"Problem:\n{cand.result.error}\n\n"
            "Fix it while keeping the intended geometry. If one operation keeps failing "
            "(often a fillet, shell or sweep), build that feature a simpler way."
        )]
        try:
            fixed = extract_code(llm.complete(system_prompt(CODE_SYSTEM, backend), ask, timeout=left))
        except Exception as exc:
            cand.log.append(f"repair call failed: {type(exc).__name__}")
            return
        if not fixed:
            return
        cand.code = fixed


def floor_note(floor: dict | None, facts: dict) -> str:
    """What the no-model part already achieves, so the model knows what is left to fix."""
    if not floor or not floor.get("check"):
        return ""
    c = floor["check"]
    over = c.get("volume_ratio", 1.0)
    lines = [f"A part built from the silhouettes of the views and the facts' bores already exists: "
             f"volume x{over:.2f} of the target, surface area x{c.get('area_ratio', 1):.2f}."]
    if over > 1.03 and facts.get("volume_mm3"):
        lines.append(f"It is too full by about {(over - 1) * facts['volume_mm3']:.0f} mm^3: that much material sits "
                     "in pockets, recesses or hollows that no outline shows. Your body must leave those open.")
    return "\n".join(lines)
