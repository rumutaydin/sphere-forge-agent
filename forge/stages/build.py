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

{guide}

READY-MADE HELPERS (import and call these rather than deriving the geometry):
{catalogue}"""


def system_prompt(template: str, backend: CadBackend) -> str:
    return template.format(language=backend.language, guide=backend.guide, catalogue=catalogue())


def extract_code(reply: str) -> str | None:
    blocks = re.findall(r"```[a-zA-Z0-9_+-]*\n(.*?)```", reply, flags=re.S)
    return blocks[-1].strip() if blocks else None


def generate(llm: LLM, backend: CadBackend, task_blocks: list[dict], plan: str) -> str:
    reply = llm.complete(system_prompt(CODE_SYSTEM, backend), task_blocks + [text_block("BUILD PLAN:\n" + plan)])
    return extract_code(reply) or ""


def run_with_repair(llm: LLM, backend: CadBackend, cand: Candidate, task: Task,
                    task_blocks: list[dict], repairs: int = 3) -> None:
    for attempt in range(repairs + 1):
        cand.result = backend.execute(cand.code, cand.dir / f"try{len(cand.log)}")
        if cand.result.ok and not cand.result.error:
            cand.check = self_check(cand.result.measure, task.facts) if task.facts else {}
            cand.log.append(f"ran (self-score {cand.self_score:.3f})")
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
