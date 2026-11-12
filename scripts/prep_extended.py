"""Lay the organisers' extended practice set (20 parts) out as the hidden set will arrive.

    uv run python scripts/prep_extended.py                       # -> runs/extended/{inputs,scoring,map.json}
    uv run python scripts/prep_extended.py --out /data/ext --only 3 7

    <out>/inputs/test_case_<n>/    description.md, images/view_*.png, [context.png]   NO facts.json
    <out>/scoring/test_case_<n>/   the same plus the real facts.json: for scoring only, never an input
    <out>/map.json                 {"test_case_<n>": "<part id>"}, n in the alphabetical order of the ids

Source: bench/extended/ in the repo (parts/<id>/ holds brief and views, facts/<id>.json the real
facts, kept apart so that nothing reads them by accident). `--src` may also point at the unpacked
organiser zip (extended-practice/parts, facts.json inside each part). Needs nothing but Python.
"""
import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def find_facts(part: Path, src: Path) -> Path | None:
    for f in (src.parent / "facts" / f"{part.name}.json", src / "facts" / f"{part.name}.json", part / "facts.json"):
        if f.is_file():
            return f
    return None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(ROOT / "bench/extended/parts"), help="folder of <part id>/ folders")
    ap.add_argument("--out", default=str(ROOT / "runs/extended"))
    ap.add_argument("--only", nargs="*", help="numbers (as in map.json) or part-id substrings")
    a = ap.parse_args()
    src, out = Path(a.src), Path(a.out)
    parts = sorted(p for p in src.iterdir() if p.is_dir() and (p / "description.md").is_file())
    if not parts:
        raise SystemExit(f"no parts with a description.md under {src}")
    for sub in ("inputs", "scoring"):
        shutil.rmtree(out / sub, ignore_errors=True)
    mapping, no_facts = {}, []
    for n, part in enumerate(parts, 1):
        name = f"test_case_{n}"
        if a.only and not any(o == str(n) or (not o.isdigit() and o in part.name) for o in a.only):
            continue
        mapping[name] = part.name
        facts = find_facts(part, src)
        for sub in ("inputs", "scoring"):
            dst = out / sub / name
            (dst / "images").mkdir(parents=True)
            shutil.copyfile(part / "description.md", dst / "description.md")
            for img in sorted((part / "images").glob("view_*.png")):
                shutil.copyfile(img, dst / "images" / img.name)
            if (part / "context.png").is_file():
                shutil.copyfile(part / "context.png", dst / "context.png")
        if facts:
            shutil.copyfile(facts, out / "scoring" / name / "facts.json")
        else:
            no_facts.append(part.name)
    (out / "map.json").write_text(json.dumps(mapping, indent=1))
    leaked = sorted(str(p) for p in (out / "inputs").rglob("facts.json"))
    assert not leaked, f"facts.json in the inputs: {leaked}"
    print(f"{len(mapping)} parts -> {out / 'inputs'} (no facts.json), {out / 'scoring'} (with the real facts), {out / 'map.json'}")
    if no_facts:
        print(f"WARNING: no real facts found for {', '.join(no_facts)}: these cannot be scored")
