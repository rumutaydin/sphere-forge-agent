"""Facts from the brief alone: the hidden parts come without facts.json. No model, no network."""
import json
import shutil
from pathlib import Path

import pytest

from forge.brief import bores_from_brief, compare_bores, facts_from_brief, parse_envelope, refine_with_model
from forge.cases import load_tasks
from forge.llm import LLM, ScriptedLLM
from forge.run import run_all

INPUTS = Path(__file__).resolve().parents[1] / "artifacts" / "inputs"
CASES = sorted(p for p in INPUTS.glob("test_case_*") if (p / "facts.json").is_file())


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.name)
def test_envelope_of_every_practice_brief(case):
    real = json.loads((case / "facts.json").read_text())
    mine = facts_from_brief((case / "description.md").read_text())
    for k in "xyz":
        assert mine["bounding_box_mm"][k] == pytest.approx(real["bounding_box_mm"][k], abs=0.011)
    assert mine["volume_mm3"] == pytest.approx(real["volume_mm3"], rel=0.002)
    assert mine["through_holes_genus"] == real["through_holes_genus"]
    assert mine["solids"] == 1 and mine["_source"] == "brief"
    assert not {"surface_area_mm2", "faces", "face_types"} & set(mine)       # not in the brief: never made up


def test_bores_of_the_practice_briefs_are_real_ones():
    parsed = matched = real_n = 0
    for case in CASES:
        real = json.loads((case / "facts.json").read_text())
        mine = facts_from_brief((case / "description.md").read_text())
        c = compare_bores(mine["cylindrical_holes_and_bores"], real.get("cylindrical_holes_and_bores", []))
        parsed, matched, real_n = parsed + c["parsed"], matched + c["matched"], real_n + c["real"]
        unlisted = sum(g.get("more_not_listed", 0) for g in real.get("cylindrical_holes_and_bores", []))
        assert c["false"] <= unlisted, f"{case.name}: a parsed bore is not on any real bore's axis"
    assert matched >= 0.8 * real_n and matched >= 0.95 * parsed


def test_envelope_spellings():
    e = parse_envelope("**Envelope:** 508 × 85.73 × 165.1 mm (X × Y × Z); volume 4246.4 cm³; 15 through‑passages.")
    assert e == {"bounding_box_mm": {"x": 508.0, "y": 85.73, "z": 165.1}, "volume_mm3": 4246400.0, "through_holes_genus": 15}
    e = parse_envelope("Envelope: 10 x 20 x 30 mm (Z x Y x X); volume 1500 mm^3; no through-holes")
    assert e == {"bounding_box_mm": {"x": 30.0, "y": 20.0, "z": 10.0}, "volume_mm3": 1500.0, "through_holes_genus": 0}
    assert parse_envelope("A bracket with one through‑passage.") == {}      # prose, not the envelope line


def test_bore_midpoints_and_patterns():
    text = ("- **Bolt holes (4):** Ø8.4 mm, axis Y, through the 9.4 mm‑thick rim. All centred at Y = 50.0 mm. Pattern:\n"
            "  - 2 on the top edge, Z = 30 mm, at X = 10 / 90 mm.\n"
            "  - 2 on the bottom edge, Z = 5 mm, at X = 10 / 90 mm.\n"
            "- **Blind bore:** one Ø30 mm bore, axis Z, on the bottom face, centred at (50, 30). Depth 12 mm (z = 0 to 12).\n"
            "- **Boss:** one Ø40 mm convex cylinder, axis Z, centred at (50, 30), length 5 mm.\n")
    got = {g["diameter"]: g for g in bores_from_brief(text, [100, 60, 40])}
    assert set(got) == {8.4, 30.0}                      # the boss is not a bore
    assert sorted(got[8.4]["centres"]) == [[10, 50, 5], [10, 50, 30], [90, 50, 5], [90, 50, 30]]
    assert got[8.4]["lengths"] == [9.4]
    assert got[30.0]["centres"] == [[50, 30, 6]] and got[30.0]["lengths"] == [12]


def _folder(tmp_path, brief):
    case = tmp_path / "inputs" / "test_case_1"
    (case / "images").mkdir(parents=True)
    (case / "description.md").write_text(brief)
    return case.parent


def test_load_tasks_without_facts_json(tmp_path, monkeypatch):
    brief = (CASES[0] / "description.md").read_text()
    task = load_tasks(_folder(tmp_path, brief))[0]
    assert task.facts["_source"] == "brief" and task.facts["bounding_box_mm"] == {"x": 19.0, "y": 19.0, "z": 50.8}
    assert task.facts["cylindrical_holes_and_bores"][0]["count"] == 2
    # with facts.json present it is used, unless FORGE_IGNORE_FACTS says to behave as on the hidden parts
    shutil.copy(CASES[0] / "facts.json", tmp_path / "inputs" / "test_case_1" / "facts.json")
    assert "surface_area_mm2" in load_tasks(tmp_path / "inputs")[0].facts
    monkeypatch.setenv("FORGE_IGNORE_FACTS", "1")
    assert load_tasks(tmp_path / "inputs")[0].facts["_source"] == "brief"
    monkeypatch.delenv("FORGE_IGNORE_FACTS")
    (tmp_path / "inputs" / "test_case_1" / "facts.json").write_text("{ not json")
    assert load_tasks(tmp_path / "inputs")[0].facts["_source"] == "brief"       # unreadable facts: the brief


def test_no_envelope_still_gives_a_box(tmp_path):
    from PIL import Image, ImageDraw

    root = _folder(tmp_path, "A plain block about 200 mm long.")
    for stem, (w, h) in {"view_0_front": (900, 300), "view_4_top": (900, 450)}.items():
        img = Image.new("RGB", (1024, 1024), "white")
        ImageDraw.Draw(img).rectangle([512 - w // 2, 512 - h // 2, 512 + w // 2, 512 + h // 2], fill=(200, 170, 120))
        img.save(root / "test_case_1" / "images" / f"{stem}.png")
    box = load_tasks(root)[0].facts["bounding_box_mm"]
    assert box["x"] == pytest.approx(200, abs=1) and box["y"] == pytest.approx(100, abs=3) and box["z"] == pytest.approx(66.7, abs=3)
    bare = facts_from_brief("", None)
    assert bare["bounding_box_mm"] == {"x": 100.0, "y": 100.0, "z": 100.0} and bare["_warnings"]


def test_run_writes_a_solid_for_a_task_without_facts(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_MODEL_PASS", "off")
    root = _folder(tmp_path, "**Envelope:** 40 x 30 x 10 mm (X x Y x Z); volume 12.0 cm^3; 0 through-passages.")
    out = run_all(root, tmp_path / "out", work_dir=tmp_path / "work")
    stp = tmp_path / "out" / "test_case_1.stp"
    assert stp.is_file() and out[0]["step"]
    from forge.geometry import load_mesh

    assert sorted(round(float(e), 1) for e in load_mesh(stp).extents) == [10.0, 30.0, 40.0]


def test_model_bores_are_checked_against_the_brief():
    brief = ("**Envelope:** 100 x 60 x 40 mm (X x Y x Z); volume 200 cm^3; 1 through-passage.\n"
             "- A 12 mm hole goes through the plate along Z at (25, 30). A boss of 20 mm stands at (70, 30).\n")
    facts = facts_from_brief(brief)
    reply = json.dumps({"bores": [
        {"diameter": 12, "axis": "Z", "length": 40, "through": True, "centres": [[25, 30, 20]]},
        {"diameter": 12, "axis": "Z", "length": 40, "through": True, "centres": [[33.3, 30, 20]]},    # 33.3 is not in the brief
        {"diameter": 17, "axis": "Z", "length": 40, "through": True, "centres": [[70, 30, 20]]},       # nor is a 17 mm diameter
        {"diameter": 12, "axis": "Z", "length": 400, "through": True, "centres": [[70, 30, 20]]},      # longer than the part
    ]})
    out = refine_with_model(ScriptedLLM(["Here you go:\n" + reply]), brief, {**facts, "cylindrical_holes_and_bores": []})
    assert [(g["diameter"], g["centres"]) for g in out["cylindrical_holes_and_bores"]] == [(12.0, [[25.0, 30.0, 20.0]])]
    assert refine_with_model(LLM(), brief, facts) == facts              # a dead endpoint changes nothing
    assert refine_with_model(ScriptedLLM(["no json here"]), brief, facts) == facts
