"""TRACK C. Stage 4: compare what was built with the task, and correct it.

The critic gets the numeric check against facts.json (exact bounding box, hole
count, volume, area), kernel measurements, the target's eight views and our
part rendered in the same eight views. A revision is kept only if the numeric
self-score does not get worse.
"""
from __future__ import annotations

from ..backends import CadBackend, describe
from ..facts import report
from ..geometry import load_mesh
from ..llm import LLM, image_block, text_block
from ..render import contact_sheet, render_sheet
from ..types import Candidate, Task
from .build import extract_code, run_with_repair, system_prompt
from .understand import task_content

CRITIC_SYSTEM = """\
You are reviewing a CAD model against its task. You get the design brief and facts, the
current program, a numeric check of the built part against the facts, kernel
measurements, the TARGET's eight views on one sheet and the BUILT part's eight views on
a second sheet in the same order.

Fix in this order:
1. every line of the numeric check (bounding box, through-hole count, volume, area)
2. main masses: compare silhouettes view by view, target against built
3. features: count, size, position (use the cylindrical-face list for holes and bosses)
4. edge treatments, only if everything above is right

The numeric check is exact; trust it over the pictures. A volume that is too high means
material that should have been removed; too low means a missing mass.
If the numeric check passes and the views agree, reply with the single word APPROVED on
the first line. Otherwise list the concrete mismatches, then give the full corrected
program in one ```{language} code block. Change only what is wrong.

{guide}

READY-MADE HELPERS:
{catalogue}"""


def critique(llm: LLM, backend: CadBackend, cand: Candidate, task: Task, rounds: int = 2, repairs: int = 3) -> None:
    text_only = task_content(task, with_views=False)
    target_sheet = None
    if task.views:
        target_sheet = contact_sheet(task.views, [v.stem.split("_", 2)[2] for v in task.views],
                                     cand.dir / "target_views.png")
    for _ in range(rounds):
        if not cand.usable:
            return
        built_sheet = render_sheet(load_mesh(cand.result.step_path), cand.result.step_path.with_name("views.png"))
        ask = text_only + [text_block(
            f"CURRENT PROGRAM:\n```{backend.language}\n{cand.code}\n```\n\n"
            f"NUMERIC CHECK AGAINST FACTS:\n{report(cand.check) if cand.check else '(no facts for this task)'}\n\n"
            f"KERNEL MEASUREMENTS:\n{describe(cand.result.measure)}")]
        if target_sheet:
            ask += [text_block("TARGET VIEWS:"), image_block(target_sheet, max_side=1536)]
        ask += [text_block("BUILT VIEWS:"), image_block(built_sheet, max_side=1536)]
        reply = llm.complete(system_prompt(CRITIC_SYSTEM, backend), ask)
        new_code = extract_code(reply)
        if reply.strip().upper().startswith("APPROVED") or not new_code:
            cand.approved = True
            cand.log.append("approved")
            return
        previous = (cand.code, cand.result, cand.check)
        cand.code = new_code
        run_with_repair(llm, backend, cand, task, text_only, repairs)
        if not cand.usable or (previous[2] and cand.self_score < previous[2]["self_score"] - 1e-6):
            cand.code, cand.result, cand.check = previous
            cand.log.append("revision was worse or failed, reverted")
            return
        cand.log.append("revised")
