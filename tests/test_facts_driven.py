"""Holes cut from facts.json and dimensions fitted to the known volume. No model needed."""
import json
from pathlib import Path

from forge.backends.cadquery_backend import CadQueryBackend
from forge.facts import self_check
from forge.library.facts_tools import hole_segments, parse_axis
from forge.stages.build import add_listed_holes, extract_code, fit_parameters
from forge.types import Candidate, Task

CASE1 = Path(__file__).resolve().parents[1] / "artifacts/inputs/test_case_1/facts.json"


def _candidate(tmp_path, code, facts):
    backend = CadQueryBackend()
    task = Task(name="t", description="", views=[], context=None, facts=facts, answer=None)
    cand = Candidate(0, code, tmp_path / "cand0")
    cand.result = backend.execute(code, cand.dir / "try0")
    assert cand.result.ok, cand.result.error
    cand.check = self_check(cand.result.measure, facts)
    return backend, task, cand


def test_axis_parsing():
    assert parse_axis("Y") == (0.0, 1.0, 0.0)
    x, y, z = parse_axis("(-0.00, 0.71, -0.71)")
    assert abs(x) < 1e-9 and abs(y - 0.5 ** 0.5) < 1e-9 and abs(z + 0.5 ** 0.5) < 1e-9
    assert parse_axis("sideways") is None


def test_segment_is_centred_on_the_listed_point():
    holes = [{"diameter": 6.75, "axis": "Y", "count": 2, "lengths": [14.0],
              "centres": [[9.5, 7.0, 6.35], [9.5, 7.0, 44.45]]}]
    segs = hole_segments(holes, (19.0, 19.0, 50.8))
    assert len(segs) == 2 and segs[0]["start"] == [9.5, 0.0, 6.35] and segs[0]["length"] == 14.0
    assert hole_segments(holes, (19.0, 19.0, 50.8), extend=True)[0]["length"] > 14.0


def test_listed_holes_are_cut_into_a_plain_body(tmp_path):
    facts = json.loads(CASE1.read_text())
    code = "import cadquery as cq\nresult = cq.Workplane('XY').box(19.0, 14.0, 50.8, centered=False)\n"
    backend, task, cand = _candidate(tmp_path, code, facts)
    assert cand.result.measure["genus"] == 0
    add_listed_holes(backend, cand, task)
    assert cand.result.measure["genus"] == 2 and cand.check["holes"] == 1.0
    assert "bores cut from facts" in cand.log[-1]
    add_listed_holes(backend, cand, task)  # second call is a no-op
    assert cand.code.count("added by forge") == 1


def test_marked_dimension_is_fitted_to_the_volume(tmp_path):
    facts = {"bounding_box_mm": {"x": 100.0, "y": 60.0, "z": 40.0}, "through_holes_genus": 0,
             "volume_mm3": 100 * 60 * 40 - 84 * 44 * 32, "surface_area_mm2": 0}
    code = ("import cadquery as cq\nwall = 3.0  # FIT 2..14\n"
            "result = cq.Workplane('XY').box(100, 60, 40, centered=False).cut(\n"
            "    cq.Workplane('XY').box(100 - 2 * wall, 60 - 2 * wall, 40 - wall, centered=False).translate((wall, wall, wall)))\n")
    backend, task, cand = _candidate(tmp_path, code, facts)
    before = abs(cand.check["volume_ratio"] - 1)
    fit_parameters(backend, cand, task)
    assert abs(cand.check["volume_ratio"] - 1) < min(before, 0.03)
    assert "wall = 8" in cand.code


def test_cut_off_reply_still_yields_a_program():
    assert extract_code("thinking...\n```python\nimport cadquery as cq\nresult = cq.Workplane('XY').box(1, 2, 3)") is not None
    assert extract_code("no code here") is None
