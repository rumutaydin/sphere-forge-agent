"""The exact-program path (forge/stages/exact.py), without a model: a scripted LLM hands in
hand-written programs for one of our reference parts and the whole loop runs:
program -> subprocess -> report -> revised program -> gate -> offer -> published file."""
import json
from pathlib import Path

import pytest

from forge.backends import get_backend
from forge.cases import BENCH, load_tasks
from forge.llm import ScriptedLLM
from forge.pipeline import Agent
from forge.stages import exact

FENCE = "```"
# The flange of bench/cases/03_flange, written in the frame of the brief (bbox minimum corner at the origin).
FLANGE = """import cadquery as cq
from forge.library import cylinder
DISC_D, DISC_H, HUB_D, HUB_H, BORE_D = 100.0, 10.0, 40.0, {hub_h}, 20.0   # brief
N_BOLTS, BOLT_D, PITCH_D = 6, 9.0, 75.0                                    # brief
CX = CY = DISC_D / 2
body = cylinder((CX, CY, 0), (CX, CY, DISC_H), DISC_D).union(cylinder((CX, CY, 0), (CX, CY, HUB_H), HUB_D))
body = body.cut(cylinder((CX, CY, -1), (CX, CY, HUB_H + 1), BORE_D))
bolts = cq.Workplane("XY").center(CX, CY).polarArray(PITCH_D / 2, 0, 360, N_BOLTS).circle(BOLT_D / 2).extrude(DISC_H)
result = body.cut(bolts)
"""
RIGHT, SHORT_HUB = FLANGE.format(hub_h="30.0"), FLANGE.format(hub_h="22.0")


def fenced(code: str) -> str:
    return f"A plan.\n{FENCE}python\n{code}\n{FENCE}"


@pytest.fixture(scope="module")
def flange(tmp_path_factory):
    """The flange as a hidden part would arrive: brief, eight organiser-style views, and only the
    facts a brief can give (no surface area, no faces)."""
    import cadquery as cq

    from forge.render import render_organiser_views
    from forge.vision import box_size

    src = BENCH / "cases" / "03_flange"
    root = tmp_path_factory.mktemp("exact_inputs")
    case = root / "test_case_1"
    case.mkdir()
    facts = json.loads((src / "facts.json").read_text())
    facts = {k: facts[k] for k in ("bounding_box_mm", "volume_mm3", "through_holes_genus")}
    (case / "facts.json").write_text(json.dumps(facts))
    (case / "description.md").write_text((src / "description.md").read_text())
    shape = cq.importers.importStep(str(src / "answer.step")).val()
    bb = shape.BoundingBox()
    render_organiser_views(shape.translate(cq.Vector(-bb.xmin, -bb.ymin, -bb.zmin)), case / "images", box_size(facts))
    return load_tasks(root)[0]


def test_cheat_sheet_runs(tmp_path):
    """Every line of the sheet in the prompt is real CadQuery and gives one valid solid."""
    res = get_backend().execute(exact.CHEAT_SHEET, tmp_path / "sheet")
    assert res.ok and not res.error, res.error
    assert res.measure["bbox_size"] == pytest.approx([90, 50, 50], abs=0.05)
    assert "{" not in exact.CHEAT_SHEET and exact.CHEAT_SHEET in exact.system_prompt()


def test_gate_is_strict():
    good = {"valid": True, "bbox_target": [10, 10, 10], "bbox_err": [0.0, 0.002, -0.004], "volume_ratio": 1.02,
            "genus": 3, "genus_target": 3, "iou": {"a": 0.99, "b": 0.98}, "iou_min": 0.98, "iou_mean": 0.985}
    assert exact.gate(good) == []
    for change in ({"bbox_err": [0.0, 0.0, 0.02]}, {"genus": 2}, {"volume_ratio": 1.06}, {"volume_ratio": 0.95},
                   {"volume_ratio": None}, {"iou": {"a": 0.99, "b": 0.93}, "iou_min": 0.93}, {"valid": False},
                   {"iou": {}, "iou_min": None}):
        assert exact.gate({**good, **change}), change
        assert exact.fidelity({**good, **change}) <= exact.fidelity(good)
    # surface area and faces are never needed
    assert "area_ratio" not in good and "surface" not in exact.report_text({**good, "bbox": [10, 10, 10], "volume": 1020.0, "diffs": {}})


def test_report_says_where(flange, tmp_path):
    res, rep = exact.execute(get_backend(), flange, SHORT_HUB, tmp_path / "short")
    assert res.ok and rep is not None
    assert rep["bbox_err"][2] == pytest.approx(-8 / 30, abs=0.01) and rep["genus"] == 7
    text = exact.report_text(rep)
    assert "size Z: 22.00 mm, target 30.00 mm  WRONG" in text and "MISSING" in text and "DIFFERS" in text
    assert "surface area" not in text                      # the facts of a hidden part have none
    assert any("Z size" in w for w in exact.gate(rep))


def test_whole_loop_publishes_the_exact_part(flange, tmp_path, monkeypatch):
    """Round 0 is wrong (short hub), the report goes back, round 1 is right, passes the gate and is published
    over a no-model part that is 20% too full."""
    monkeypatch.setenv("FORGE_EXACT_ROUNDS", "2")
    backend = get_backend()
    floor_res = backend.execute(backend.box_code(100, 100, 30), tmp_path / "floor")
    floor = {"name": "hull+holes", "step": str(floor_res.step_path),
             "check": {"estimate": 0.60, "self_score": 0.6, "dimensions": 1.0, "holes": 0.0, "volume_ratio": 3.3},
             "shape": {"iou_per_view": {"view_0_front": 0.7}}}
    out = tmp_path / "out" / "test_case_1.stp"
    out.parent.mkdir()
    llm = ScriptedLLM([fenced(SHORT_HUB), fenced(RIGHT)])
    summary = Agent(llm, backend, n_candidates=0, n_exact=1).solve(flange, tmp_path / "w", publish=out, floor=floor)
    assert summary["chosen"] == "exact program 0", summary["candidates"]
    assert len(llm.calls) == 2
    feedback = llm.calls[1][1][-1]["text"]
    assert "MEASURED BY CODE" in feedback and "WRONG" in feedback and "HUB_H" in feedback
    check = summary["self_check"]
    assert check["gate"] == [] and check["exact"]["genus"] == 7 and abs(check["exact"]["volume_ratio"] - 1) < 0.005
    assert check["exact"]["iou_min"] > 0.98
    assert out.read_bytes() == Path(summary["step"]).read_bytes() and b"ISO-10303-21" in out.read_bytes()[:20]
    assert exact.EXACT_MARK not in (tmp_path / "w" / "final.py").read_text()


def test_a_wrong_program_never_replaces_the_floor(flange, tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_EXACT_ROUNDS", "1")
    backend = get_backend()
    floor_res = backend.execute(backend.box_code(100, 100, 30), tmp_path / "floor")
    floor = {"name": "hull+holes", "step": str(floor_res.step_path),
             "check": {"estimate": 0.60, "dimensions": 1.0, "holes": 0.0, "volume_ratio": 3.3}, "shape": {}}
    out = tmp_path / "t.stp"
    no_bolts = RIGHT.replace("result = body.cut(bolts)", "result = body")
    llm = ScriptedLLM([fenced(SHORT_HUB), fenced(no_bolts)])
    summary = Agent(llm, backend, n_candidates=0, n_exact=1).solve(flange, tmp_path / "w", publish=out, floor=floor)
    assert summary["chosen"] == "hull+holes" and not out.exists()
    log = " ".join(summary["candidates"][0]["log"])
    assert "through-holes 1 against 7" in log and "fails" in log


def test_exact_is_off_by_default_and_thinking_is_per_call(monkeypatch):
    monkeypatch.delenv("FORGE_EXACT", raising=False)
    assert Agent(ScriptedLLM([""]), get_backend()).n_exact == 0
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("OPENAI_MODEL", "m")
    monkeypatch.setenv("FORGE_THINKING", "off")
    from forge.llm import OpenAICompatLLM

    llm = OpenAICompatLLM()
    assert llm._extra(None)["extra_body"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert llm._extra("medium") == {"reasoning_effort": "medium"}
    assert llm._extra("off") == llm._extra(None) and llm._extra("on") == {}


def test_relaxed_route_is_off_by_default_and_needs_a_better_volume(tmp_path, monkeypatch):
    from forge.backends.base import ExecResult
    from forge.types import Candidate

    rep = {"valid": True, "bbox_target": [10, 10, 10], "bbox_err": [0.0, 0.0, 0.0], "volume_ratio": 1.6,
           "genus": 0, "genus_target": 0, "iou": {"a": 0.99, "b": 0.985}, "iou_min": 0.985, "iou_mean": 0.9875}
    cand = Candidate(200, "code", tmp_path, result=ExecResult(True, "", tmp_path / "p.step"),
                     check={"exact": rep, "fidelity": exact.fidelity(rep), "gate": exact.gate(rep), "dimensions": 1.0})
    floor = {"name": "hull", "step": "x", "check": {"dimensions": 1.0, "holes": 1.0, "volume_ratio": 2.8},
             "shape": {"iou_per_view": {"a": 0.99, "b": 0.99}}}
    best = {"check": floor["check"]}
    assert cand.check["gate"] == ["volume x1.600"] and not exact.accept(cand, best, floor)
    monkeypatch.setenv("FORGE_EXACT_RELAX", "1")
    assert exact.accept(cand, best, floor)
    assert not exact.accept(cand, best, {**floor, "check": {**floor["check"], "volume_ratio": 1.5}})   # the floor is nearer
    cand.check["gate"] = ["volume x1.600", "through-holes 1 against 0"]
    assert not exact.accept(cand, best, floor)
