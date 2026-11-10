"""TRACK B. Stage 1: task (text and/or image) -> Spec.

The hidden target is fixed; the prompt is all we get. This stage turns a vague
or visual description into an explicit modelling brief with a coordinate frame,
an envelope and a dimensioned feature list, so the code generator never has to
guess silently.
"""
from __future__ import annotations

from ..library import catalogue
from ..llm import LLM, image_block, text_block
from ..types import Spec, Task

SPEC_SYSTEM = """\
You are a mechanical engineer preparing a part for CAD modelling. Your model will be
scored by geometric overlap with a hidden reference part, so a wrong coordinate frame
or wrong overall proportion costs far more than a missing small feature.

From the task (text and/or image), write a modelling brief:
1. FRAME: units, which way is up, where the origin sits relative to the part. Use what
   the task states. Where it is silent, say so and pick the most conventional choice.
2. ENVELOPE: the overall bounding box size along X, Y, Z.
3. BUILD PLAN: the main body first, then features in order of volume, each with every
   dimension and its position in absolute coordinates.
4. STANDARD PARTS: if any feature is a catalogue item below, name the helper and its
   arguments instead of describing the geometry.
5. UNKNOWNS: anything you had to guess, with the value you chose and why.
Do the arithmetic explicitly. Do not write code.

CATALOGUE OF READY-MADE HELPERS:
{catalogue}"""


def task_content(task: Task) -> list[dict]:
    """The task as model input blocks. Every later stage shows the model this too."""
    content = []
    if task.image:
        content.append(image_block(task.image))
    content.append(text_block("TASK:\n" + (task.prompt or "Reproduce the part shown in the image.")))
    return content


def make_spec(llm: LLM, task: Task, effort: str = "high") -> Spec:
    text = llm.complete(SPEC_SYSTEM.format(catalogue=catalogue()), task_content(task), effort)
    return Spec(text=text)
