"""Runs without any model or network. Must stay green on every PR."""
import json
from pathlib import Path

import pytest

from forge.backends import get_backend
from forge.cases import load_tasks
from forge.facts import facts_from_measure, self_check
from forge.geometry import load_mesh
from forge.llm import ScriptedLLM
from forge.pipeline import Agent
from forge.run import run_all
from forge.score import score
from forge.stages.select import select
from forge.types import Candidate, Task

PLATE = """import cadquery as cq
holes = cq.Workplane("XY").pushPoints([(8, 8), (72, 8), (8, 42), (72, 42)]).circle(3).extrude(8)
result = cq.Workplane("XY").box(80, 50, 8, centered=False).cut(holes)
"""
NO_HOLES = "import cadquery as cq\nresult = cq.Workplane('XY').box(80, 50, 8, centered=False)"
FENCE = "```"


def fenced(code: str) -> str:
    return f"{FENCE}python\n{code}\n{FENCE}"


@pytest.fixture(scope="module")
def plate(tmp_path_factory):
    res = get_backend().execute(PLATE, tmp_path_factory.mktemp("plate"))
    assert res.ok and not res.error
    return res


@pytest.fixture(scope="module")
def task(plate, tmp_path_factory):
    """A task folder in the organisers' layout, with facts measured from the plate."""
    root = tmp_path_factory.mktemp("inputs")
    case = root / "test_case_1"
    (case / "images").mkdir(parents=True)
    (case / "description.md").write_text("A plate 80 x 50 x 8 mm with four 6 mm through holes.")
    (case / "facts.json").write_text(json.dumps(facts_from_measure(plate.measure)))
    return root


def test_backend_writes_step_only(plate):
    assert plate.step_path.suffix == ".step"
    assert {p.suffix for p in plate.step_path.parent.iterdir()} == {".step", ".json", ".py"}
    assert plate.measure["genus"] == 4


def test_score_ignores_pose_but_not_holes(plate, tmp_path):
    moved = PLATE + "result = result.rotate((0,0,0),(1,1,0),70).translate((30,-20,9))\n"
    res = get_backend().execute(moved, tmp_path / "moved")
    assert score(res.step_path, plate.step_path)["score"] > 0.97
    bare = get_backend().execute(NO_HOLES, tmp_path / "bare")
    rep = score(bare.step_path, plate.step_path)
    assert rep["holes"] == 0.0 and rep["dimensions"] == pytest.approx(1.0, abs=0.01)


def test_self_check_names_what_is_wrong(plate, task, tmp_path):
    facts = load_tasks(task)[0].facts
    assert self_check(plate.measure, facts)["issues"] == []
    bare = get_backend().execute(NO_HOLES, tmp_path)
    check = self_check(bare.measure, facts)
    assert check["holes"] == 0.0 and any("through-holes" in i for i in check["issues"])
    assert check["self_score"] < self_check(plate.measure, facts)["self_score"]


def test_pipeline_repairs_then_revises(plate, task, tmp_path):
    broken = fenced("import cadquery as cq\nresult = cq.Workplane('XY').box(80,50,8).edges('|Z').fillet(999)")
    llm = ScriptedLLM(["PLAN", broken, fenced(NO_HOLES), "Holes missing.\n" + fenced(PLATE), "APPROVED"])
    summary = Agent(llm, get_backend(), n_candidates=1).solve(load_tasks(task)[0], tmp_path)
    log = summary["candidates"][0]["log"]
    assert log[0].startswith("error") and log[-2:] == ["revised", "approved"]
    assert summary["step"].endswith("test_case_1.step")
    assert score(summary["step"], plate.step_path)["score"] > 0.99


def test_worse_revision_is_reverted(task, tmp_path):
    llm = ScriptedLLM(["PLAN", fenced(PLATE), "I think the holes are wrong.\n" + fenced(NO_HOLES)])
    summary = Agent(llm, get_backend(), n_candidates=1, rounds=1).solve(load_tasks(task)[0], tmp_path)
    assert summary["candidates"][0]["log"][-1].startswith("revision was worse")
    assert summary["self_check"]["holes"] == 1.0


def test_run_writes_stp_and_falls_back_to_box(task, tmp_path):
    agent = Agent(ScriptedLLM(["PLAN", "no code in this reply"]), get_backend(), n_candidates=1)
    summaries = run_all(task, tmp_path / "out", agent=agent, work_dir=tmp_path / "work")
    assert [p.name for p in (tmp_path / "out").iterdir()] == ["test_case_1.stp"]
    assert summaries[0]["chosen"] == "fallback box"
    assert sorted(load_mesh(tmp_path / "out" / "test_case_1.stp").extents) == pytest.approx([8, 50, 80], abs=0.01)


def test_select_prefers_best_self_score(plate, task, tmp_path):
    facts = load_tasks(task)[0].facts
    cands = []
    for i, code in enumerate([NO_HOLES, PLATE]):
        c = Candidate(i, code, tmp_path / str(i))
        c.result = get_backend().execute(code, c.dir)
        c.check = self_check(c.result.measure, facts)
        cands.append(c)
    assert select(cands).idx == 1


def test_library_gear_is_callable_from_generated_code(tmp_path):
    code = "from forge.library import spur_gear\nresult = spur_gear(module=2, teeth=20, width=10, bore=8)"
    res = get_backend().execute(code, tmp_path)
    assert res.ok and not res.error and res.measure["genus"] == 1
    assert max(res.measure["bbox_size"][:2]) == pytest.approx(44, abs=0.1)  # m * (z + 2)
