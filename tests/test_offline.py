"""Runs without any model or network. Must stay green on every PR."""
from pathlib import Path

import pytest

from forge.backends import get_backend
from forge.geometry import load_mesh
from forge.llm import ScriptedLLM
from forge.metrics import compare
from forge.pipeline import Agent
from forge.stages.select import select
from forge.types import Candidate, Task

PLATE = """import cadquery as cq
holes = cq.Workplane("XY").pushPoints([(32, 17), (-32, 17), (32, -17), (-32, -17)]).circle(3).extrude(8)
result = cq.Workplane("XY").box(80, 50, 8, centered=(True, True, False)).cut(holes)
"""
FENCE = "```"


def fenced(code: str) -> str:
    return f"{FENCE}python\n{code}\n{FENCE}"


@pytest.fixture(scope="module")
def plate(tmp_path_factory):
    res = get_backend().execute(PLATE, tmp_path_factory.mktemp("plate"))
    assert res.ok and not res.error
    return res


def test_identical_shapes_score_one(plate):
    rep = compare(plate.step_path, plate.stl_path, res=48, n_pts=2048)
    for mode in ("raw", "center", "unit", "rot24"):
        assert rep[mode]["iou"] > 0.99


def test_frame_error_costs_more_than_missing_holes(plate, tmp_path):
    shifted = "import cadquery as cq\nresult = cq.Workplane('XY').box(80, 50, 8)"  # centred in Z, no holes
    res = get_backend().execute(shifted, tmp_path)
    rep = compare(res.stl_path, plate.stl_path, res=48, n_pts=2048)
    assert rep["raw"]["iou"] < 0.5 < 0.9 < rep["center"]["iou"]


def test_pipeline_repairs_then_revises(plate, tmp_path):
    broken = fenced("import cadquery as cq\nresult = cq.Workplane('XY').box(80,50,8).edges('|Z').fillet(999)")
    draft = fenced("import cadquery as cq\nresult = cq.Workplane('XY').box(80,50,8)")
    llm = ScriptedLLM(["BRIEF", broken, draft, "Holes missing.\n" + fenced(PLATE), "APPROVED"])
    summary = Agent(llm, get_backend(), n_candidates=1).solve(Task(prompt="a plate"), tmp_path)
    log = summary["candidates"][0]["log"]
    assert log[0].startswith("error") and log[-2:] == ["revised", "approved"]
    assert compare(summary["stl"], plate.stl_path, res=48, n_pts=2048)["raw"]["iou"] > 0.99


def test_select_prefers_consensus(tmp_path):
    codes = [PLATE,
             "import cadquery as cq\nresult = cq.Workplane('XY').box(80,50,8,centered=(True,True,False))",
             "import cadquery as cq\nresult = cq.Workplane('XY').box(50,50,50)"]
    cands = []
    for i, code in enumerate(codes):
        c = Candidate(i, code, tmp_path / str(i))
        c.result = get_backend().execute(code, c.dir)
        cands.append(c)
    assert select(cands).idx in (0, 1)


def test_library_gear_is_callable_from_generated_code(tmp_path):
    code = "from forge.library import spur_gear\nresult = spur_gear(module=2, teeth=20, width=10, bore=8)"
    res = get_backend().execute(code, tmp_path)
    assert res.ok and not res.error
    assert max(load_mesh(res.stl_path).extents[:2]) == pytest.approx(44, abs=0.1)  # m * (z + 2)
