"""Build bench/cases/<id> for the given bench/parts ids only (forge.cases.build_bench does all)."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from forge.backends import get_backend
from forge.facts import facts_from_measure
from forge.geometry import load_mesh
from forge.render import render_views

backend = get_backend("cadquery")
for stem in sys.argv[1:]:
    src = ROOT / "bench/parts" / f"{stem}.py"
    out = ROOT / "bench/cases" / stem
    code = src.read_text()
    ns = {}
    exec(code.split("import ", 1)[0], ns)
    res = backend.execute(code, out / "_build")
    if not res.ok or res.error:
        raise RuntimeError(f"{stem}: {res.error}")
    res.step_path.replace(out / "answer.step")
    (out / "description.md").write_text(ns["PROMPT"].strip() + "\n")
    (out / "facts.json").write_text(json.dumps(facts_from_measure(res.measure), indent=1))
    render_views(load_mesh(out / "answer.step"), out / "images", size=512)
    for f in (out / "_build").iterdir():
        f.unlink()
    (out / "_build").rmdir()
    m = res.measure
    print(stem, [round(s, 1) for s in m["bbox_size"]], "vol", round(m["volume"]), "area", round(m.get("area", 0)), "genus", m["genus"])
