"""How well the facts rebuilt from a brief match the real facts.json (forge/brief.py).

    uv run python scripts/brief_check.py [folders ...] [-v] [--model]

Each folder holds task folders with description.md and facts.json (default: artifacts/inputs).
Briefs that repeat are counted once. Per part: bounding box, volume and through-hole count
equal or not, and the bores: parsed, real, on a real bore's axis line (diameter, axis and the
two across-axis coordinates within 1 mm), midpoint within 1 mm, length within 1 mm, false,
missed. --model also asks the configured endpoint (OPENAI_*) and shows what it would add.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from forge.brief import compare_bores, facts_from_brief, refine_with_model  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("folders", nargs="*", default=[str(ROOT / "artifacts/inputs")])
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--model", action="store_true")
    a = ap.parse_args()
    llm = None
    if a.model:
        from forge.llm import OpenAICompatLLM

        llm = OpenAICompatLLM()
    keys = ("parsed", "real", "matched", "centre", "length", "false", "missed")
    total, total_m = dict.fromkeys(keys, 0), dict.fromkeys(keys, 0)
    exact = {"bbox": 0, "volume": 0, "genus": 0}
    seen: set[str] = set()
    for folder in a.folders:
        for d in sorted(p for p in Path(folder).iterdir() if (p / "description.md").is_file() and (p / "facts.json").is_file()):
            text = (d / "description.md").read_text()
            if text in seen:
                continue
            seen.add(text)
            real = json.loads((d / "facts.json").read_text())
            mine = facts_from_brief(text, sorted((d / "images").glob("view_*.png")))
            bb = all(abs(mine["bounding_box_mm"][k] - real["bounding_box_mm"][k]) < 0.011 for k in "xyz")
            vol = abs(mine.get("volume_mm3", 0) / real["volume_mm3"] - 1) < 0.002
            gen = mine["through_holes_genus"] == real["through_holes_genus"]
            exact["bbox"] += bb
            exact["volume"] += vol
            exact["genus"] += gen
            real_bores = real.get("cylindrical_holes_and_bores", [])
            c = compare_bores(mine["cylindrical_holes_and_bores"], real_bores)
            for k in keys:
                total[k] += c[k]
            line = (f"{d.name:34s} bbox {bb:d} vol {vol:d} genus {gen:d}  bores parsed {c['parsed']:2d} real {c['real']:2d} "
                    f"line {c['matched']:2d} centre {c['centre']:2d} length {c['length']:2d} false {c['false']:2d} missed {c['missed']:2d}")
            if llm is not None:
                both = refine_with_model(llm, text, mine)
                cm = compare_bores(both["cylindrical_holes_and_bores"], real_bores)
                for k in keys:
                    total_m[k] += cm[k]
                line += f"  | with model: line {cm['matched']:2d} false {cm['false']:2d} missed {cm['missed']:2d}"
            print(line, " ".join(mine.get("_warnings", [])))
            if a.verbose:
                for g in mine["cylindrical_holes_and_bores"]:
                    print("     brief", json.dumps(g))
                for g in real_bores:
                    print("     real ", json.dumps(g))
    print(f"{len(seen)} briefs; exact: {exact}")
    print(f"bores, rules only: {total}")
    if llm is not None:
        print(f"bores, rules + model: {total_m}")
