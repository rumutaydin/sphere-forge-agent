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
    llm = ScriptedLLM([broken, fenced(NO_HOLES), "Holes missing.\n" + fenced(PLATE), "APPROVED"])
    summary = Agent(llm, get_backend(), n_candidates=1, rounds=2).solve(load_tasks(task)[0], tmp_path)
    log = summary["candidates"][0]["log"]
    assert log[0].startswith("error") and log[-2:] == ["revised", "approved"]
    assert score(summary["step"], plate.step_path)["score"] > 0.99


def test_worse_revision_is_reverted(task, tmp_path):
    llm = ScriptedLLM([fenced(PLATE), "I think the holes are wrong.\n" + fenced(NO_HOLES)])
    summary = Agent(llm, get_backend(), n_candidates=1, rounds=1).solve(load_tasks(task)[0], tmp_path)
    assert summary["candidates"][0]["log"][-1].startswith("revision was worse")
    assert summary["self_check"]["holes"] == 1.0


def test_run_writes_stp_and_keeps_the_no_model_part(task, tmp_path):
    agent = Agent(ScriptedLLM(["no code in this reply"]), get_backend(), n_candidates=1)
    summaries = run_all(task, tmp_path / "out", agent=agent, work_dir=tmp_path / "work")
    assert [p.name for p in (tmp_path / "out").iterdir()] == ["test_case_1.stp"]
    assert summaries[0]["chosen"] == "box"      # no views in this task, so pass 1 can only offer the box
    assert sorted(load_mesh(tmp_path / "out" / "test_case_1.stp").extents) == pytest.approx([8, 50, 80], abs=0.01)


class FailsOnSecondCall(ScriptedLLM):
    def complete(self, system, content, timeout=None):
        if len(self.calls) >= 1:
            self.calls.append((system, content))
            raise TimeoutError("model call timed out")
        return super().complete(system, content, timeout)


def test_a_failed_call_does_not_lose_the_part(plate, task, tmp_path):
    """Candidate 0 builds; the next model call raises. The built part must be what is handed in."""
    llm = FailsOnSecondCall([fenced(PLATE)])
    out = tmp_path / "out.stp"
    summary = Agent(llm, get_backend(), n_candidates=1, rounds=1).solve(load_tasks(task)[0], tmp_path / "w", publish=out)
    assert summary["chosen"] == "model body 0" and summary["self_check"]["holes"] == 1.0
    assert score(out, plate.step_path)["score"] > 0.99        # written when it was built, not at the end


def test_past_the_deadline_nothing_is_lost(task, tmp_path):
    import time

    agent = Agent(ScriptedLLM([fenced(PLATE)]), get_backend(), n_candidates=1)
    summary = agent.solve(load_tasks(task)[0], tmp_path, deadline=time.monotonic() - 1)
    assert summary["chosen"] == "fallback box" and summary["step"]


def test_no_model_part_from_views_and_facts(plate, tmp_path):
    """Pass 1 on its own: silhouettes of the plate + its bore list give the plate back, holes and all."""
    import numpy as np
    from PIL import Image

    from forge.compile import compile_part
    from forge.render import VIEWS
    from forge.vision import Camera, project_mask

    case = tmp_path / "in" / "test_case_1"
    (case / "images").mkdir(parents=True)
    mesh = load_mesh(plate.step_path)
    facts = facts_from_measure(plate.measure)
    facts["cylindrical_holes_and_bores"] = [{"diameter": 6.0, "axis": "Z", "count": 4, "lengths": [8.0],
                                             "centres": [[8, 8, 4], [72, 8, 4], [8, 42, 4], [72, 42, 4]]}]
    for stem in VIEWS:
        mask = project_mask(mesh, Camera(stem, [80, 50, 8], 512))
        rgb = np.full(mask.shape + (3,), 255, np.uint8)
        rgb[mask] = (186, 146, 95)
        Image.fromarray(rgb).save(case / "images" / f"{stem}.png")
    (case / "description.md").write_text("A plate.")
    (case / "facts.json").write_text(json.dumps(facts))
    out = tmp_path / "part.stp"
    rows = compile_part(load_tasks(tmp_path / "in")[0], tmp_path / "work", publish=out)
    assert rows[0]["check"]["holes"] == 1.0 and rows[0]["check"]["dimensions"] > 0.99
    assert score(out, plate.step_path)["score"] > 0.97


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


def test_cut_list_survives_a_truncated_reply():
    from forge.stages.carve import parse_cuts

    whole = '{"cuts": [{"shape": "box", "min": [0, 0, 0], "max": [1, 1, 1]}, {"shape": "cylinder", "centre": [1, 2, 3], "axis": "Z", "diameter": 4, "length": 5}]}'
    assert len(parse_cuts("Here you go:\n" + whole)) == 2
    assert len(parse_cuts(whole[:whole.index('{"shape": "cylinder"') + 30])) == 1
    assert parse_cuts("no json here") == []


def test_hole_count_from_topology_matches_the_mesh(plate, tmp_path):
    import cadquery as cq

    from forge.geometry import brep_genus, genus, shape_to_mesh

    gear = get_backend().execute("from forge.library import spur_gear\nresult = spur_gear(module=2, teeth=20, width=10, bore=8)", tmp_path / "g")
    ball = get_backend().execute("import cadquery as cq\nresult = cq.Workplane('XY').sphere(10).cut(cq.Workplane('XY').circle(3).extrude(40, both=True))", tmp_path / "b")
    for res, expected in ((plate, 4), (gear, 1), (ball, 1)):
        shape = cq.importers.importStep(str(res.step_path)).val()
        assert brep_genus(shape) == genus(shape_to_mesh(shape)) == expected
