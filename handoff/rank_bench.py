"""Compile every reference part once and true-score EVERY candidate row, so ranking rules can be
compared offline (handoff/rank_eval.py).   uv run python handoff/rank_bench.py out.json [case ...]"""
import json, os, sys, tempfile, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
ROOT = Path(os.environ.get("FORGE_REPO", ".")).resolve()
sys.path.insert(0, str(ROOT))

def one(case_dir):
    import cadquery as cq
    from forge.cases import load_tasks
    from forge.compile import compile_part
    from forge.geometry import shape_to_mesh
    from forge.render import render_organiser_views
    from forge.score import score
    from forge.vision import box_size
    t0 = time.time()
    case = Path(case_dir)
    task = load_tasks(case.parent, [case.name + "$"])[0]
    shape = cq.importers.importStep(str(task.answer)).val()
    bb = shape.BoundingBox()
    shape = shape.translate(cq.Vector(-bb.xmin, -bb.ymin, -bb.zmin))
    answer = shape_to_mesh(shape)
    tmp = Path(tempfile.mkdtemp(prefix="rankbench-"))
    task.views = render_organiser_views(shape, tmp / "views", box_size(task.facts))
    rows = compile_part(task, tmp / "out")
    out = []
    for r in rows:
        try:
            s = score(r["step"], answer)
        except Exception as exc:
            s = {"score": None, "error": str(exc)}
        out.append({"name": r["name"], "estimate": r["estimate"], "check": {k: r["check"].get(k) for k in
                    ("volume_ratio", "area_ratio", "dimensions", "holes", "silhouette_iou", "faces", "edge_all")},
                    "true": s})
    return case.name, {"facts_faces": task.facts.get("face_types"), "rows": out, "secs": round(time.time() - t0)}

if __name__ == "__main__":
    cases = sorted(p for p in (ROOT / "bench/cases").iterdir() if (p / "answer.step").exists())
    if sys.argv[2:]:
        cases = [c for c in cases if c.name in sys.argv[2:]]
    res = {}
    with ProcessPoolExecutor(int(os.environ.get("W", "6"))) as ex:
        for name, r in ex.map(one, map(str, cases)):
            res[name] = r
            best = max(r["rows"], key=lambda x: x["true"].get("score") or 0)
            print(name, len(r["rows"]), "rows; top-ranked", r["rows"][0]["name"], round(r["rows"][0]["true"].get("score") or 0, 3),
                  "| best possible", best["name"], round(best["true"]["score"], 3), flush=True)
            Path(sys.argv[1]).write_text(json.dumps(res, indent=1))
