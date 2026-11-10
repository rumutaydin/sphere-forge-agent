"""TRACK C. Stage 4: look at what was built and correct it.

The critic sees the task, the program, kernel measurements and four rendered
views. It either approves or returns a corrected program, which is re-run.
"""
from __future__ import annotations

from ..backends import CadBackend, describe
from ..geometry import load_mesh
from ..llm import LLM, image_block, text_block
from ..render import render_grid
from ..types import Candidate
from .build import extract_code, run_with_repair, system_prompt

CRITIC_SYSTEM = """\
You are reviewing a CAD model against its task. You get the task, the current program,
kernel measurements of what it actually built, and four rendered views.

Check in this order and stop caring about later items until earlier ones are right:
1. frame and placement (bbox min/max against the task's coordinates)
2. overall envelope (bbox size) and gross proportions
3. main masses present and connected
4. features: count, size, position (use the cylindrical-face list for holes and bosses)
5. edge treatments

Trust the measurements over the pictures for numbers; use the pictures for topology.
If everything matches the task, reply with the single word APPROVED on the first line.
Otherwise list the concrete mismatches, then give the full corrected program in one
```{language} code block. Change only what is wrong.

{guide}

READY-MADE HELPERS:
{catalogue}"""


def critique(llm: LLM, backend: CadBackend, cand: Candidate, task_blocks: list[dict],
             rounds: int = 2, repairs: int = 3, effort: str = "high") -> None:
    for _ in range(rounds):
        if not cand.usable:
            return
        sheet = render_grid(load_mesh(cand.result.stl_path), cand.result.stl_path.with_name("views.png"))
        ask = task_blocks + [
            text_block(f"CURRENT PROGRAM:\n```{backend.language}\n{cand.code}\n```\n\n"
                       f"KERNEL MEASUREMENTS:\n{describe(cand.result.measure)}\n\nRENDERED VIEWS:"),
            image_block(sheet),
        ]
        reply = llm.complete(system_prompt(CRITIC_SYSTEM, backend), ask, effort)
        new_code = extract_code(reply)
        if reply.strip().upper().startswith("APPROVED") or not new_code:
            cand.approved = True
            cand.log.append("approved")
            return
        previous = (cand.code, cand.result)
        cand.code = new_code
        run_with_repair(llm, backend, cand, task_blocks, repairs, effort)
        if not cand.usable:  # a revision that no longer runs is worse than what we had
            cand.code, cand.result = previous
            cand.log.append("revision failed, reverted")
            return
        cand.log.append("revised")
