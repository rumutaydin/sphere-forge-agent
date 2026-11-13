"""TRACK B. Stage 1: how a task is shown to the model, and the build plan.

The brief already carries exact dimensions, and facts.json carries the exact
bounding box, volume and hole inventory. So this stage no longer has to invent
missing numbers. Its job is to lay brief, facts and the eight views out so the
model can cross-reference them, and to get a build plan that says which
features come from the text and which have to be read off the views.
"""
from __future__ import annotations

import json

from ..llm import LLM, image_block, text_block
from ..types import Task

VIEW_NOTES = {
    "view_0_front": "front, looking along +Y: X to the right, Z up",
    "view_1_back": "back, looking along -Y: X to the left, Z up",
    "view_2_left": "left, looking along +X: Y to the left, Z up",
    "view_3_right": "right, looking along -X: Y to the right, Z up",
    "view_4_top": "top, looking along -Z: X to the right, Y up",
    "view_5_bottom": "bottom, looking along +Z: X to the right, Y down",
    "view_6_iso_front_right_top": "isometric from +X, -Y, +Z",
    "view_7_iso_back_left_bottom": "isometric from -X, +Y, -Z",
}

PLAN_SYSTEM = """\
You are a mechanical engineer planning how to model a part in CAD. You get a design
brief with exact dimensions, a facts file measured from the real part, and eight
orthographic views. All three use one frame: millimetres, origin at the minimum corner
of the part's bounding box.

The result is scored on volume overlap, surface match, bounding-box dimensions and the
number of through-holes. Pose does not matter. Size and handedness do: never mirror.

Write a build plan:
1. BASE BODY: the simplest solid that gives the right envelope and gross mass, and the
   operation that makes it (extrude a profile, revolve a profile, union of blocks).
2. FEATURES in order of volume: for each, the operation, every dimension, its position,
   and where the numbers come from (brief, facts, or read from a named view).
3. THROUGH-HOLES: list each one that passes fully through. The count must equal
   `through_holes_genus` in the facts. A blind hole is not a through-hole.
4. GAPS: what the brief leaves unspecified, and the value you will use, taken from the
   views or from the volume and surface area in the facts.
5. CHECKS: bounding box, volume and through-hole count your plan should produce.
Do the arithmetic explicitly. Do not write code."""


def task_content(task: Task, with_views: bool = True) -> list[dict]:
    """The task as model input blocks. Every stage shows the model this."""
    content = [text_block("DESIGN BRIEF:\n" + task.description.strip())]
    if task.facts:
        label = "FACTS (read from the brief by a parser; bores it could not place are missing)" \
            if task.facts.get("_source") == "brief" else "FACTS (measured from the target part)"
        shown = {k: v for k, v in task.facts.items() if k != "_dir"}
        content.append(text_block(label + ":\n" + json.dumps(shown, indent=1)))
    if with_views:
        for view in task.views:
            content.append(text_block("VIEW " + VIEW_NOTES.get(view.stem, view.stem) + ":"))
            content.append(image_block(view))
        if task.context:
            content.append(text_block("CONTEXT (the part in orange inside its assembly; for function only):"))
            content.append(image_block(task.context, max_side=512))
    return content


def make_plan(llm: LLM, task: Task) -> str:
    return llm.complete(PLAN_SYSTEM, task_content(task))
