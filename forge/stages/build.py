"""TRACK C. Stages 2 and 3: Spec -> program -> a part that actually builds.

generate() writes one program. run_with_repair() executes it and, on a crash or
an invalid solid, feeds the kernel's error back until it runs or we give up.
"""
from __future__ import annotations

import re

from ..backends import CadBackend
from ..library import catalogue
from ..llm import LLM, text_block
from ..types import Candidate, Spec

CODE_SYSTEM = """\
You are an expert CAD programmer. Write one complete program that builds the part in
the brief. Reply with the reasoning you need, then exactly one ```{language} code block.

{guide}

READY-MADE HELPERS (import and call these rather than deriving the geometry):
{catalogue}"""


def system_prompt(template: str, backend: CadBackend) -> str:
    return template.format(language=backend.language, guide=backend.guide, catalogue=catalogue())


def extract_code(reply: str) -> str | None:
    blocks = re.findall(r"```[a-zA-Z0-9_+-]*\n(.*?)```", reply, flags=re.S)
    return blocks[-1].strip() if blocks else None


def generate(llm: LLM, backend: CadBackend, task_blocks: list[dict], spec: Spec, effort: str = "high") -> str:
    reply = llm.complete(system_prompt(CODE_SYSTEM, backend),
                         task_blocks + [text_block("BRIEF:\n" + spec.text)], effort)
    return extract_code(reply) or ""


def run_with_repair(llm: LLM, backend: CadBackend, cand: Candidate, task_blocks: list[dict],
                    repairs: int = 3, effort: str = "high") -> None:
    for attempt in range(repairs + 1):
        cand.result = backend.execute(cand.code, cand.dir / f"try{len(cand.log)}")
        if cand.result.ok and not cand.result.error:
            cand.log.append("ran")
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
        fixed = extract_code(llm.complete(system_prompt(CODE_SYSTEM, backend), ask, effort))
        if not fixed:
            return
        cand.code = fixed
