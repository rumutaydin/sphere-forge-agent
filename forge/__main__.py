"""Command line.

  uv run python -m forge bench                       build benchmark targets
  uv run python -m forge sensitivity                 what does the metric punish?
  uv run python -m forge score PRED TARGET           compare two STEP/STL files
  uv run python -m forge solve "a 20mm cube" -o out  run the agent on one task
  uv run python -m forge eval [--image] [--only 03]  run the agent on the benchmark and score it
  uv run python -m forge eval --tag c-fewshot        ...and file the scores under results/
  uv run python -m forge board                       table of everything in results/
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from . import bench, sensitivity
from .metrics import MODES, compare
from .types import Task


RESULTS = Path(__file__).resolve().parent.parent / "results"


def _agent(args):
    from .pipeline import Agent
    from .backends import get_backend
    from .llm import AnthropicLLM

    return Agent(AnthropicLLM(args.model), get_backend(args.backend),
                 n_candidates=args.candidates, rounds=args.rounds, effort=args.effort)


def _print_report(rep: dict) -> None:
    print(f"{'mode':8s}{'iou':>8s}{'f1':>8s}{'chamfer':>10s}{'hd95':>8s}")
    for mode in MODES:
        r = rep[mode]
        print(f"{mode:8s}{r['iou']:8.3f}{r['f1']:8.3f}{r['chamfer']:10.4f}{r['hausdorff95']:8.3f}")
    print("volume ratio %.3f   sorted extent ratios %s" % (
        rep["ratios"]["volume"], [round(x, 3) for x in rep["ratios"]["extents_sorted"]]))


def main() -> None:
    ap = argparse.ArgumentParser(prog="forge")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("bench")
    sub.add_parser("board")
    s = sub.add_parser("sensitivity")
    s.add_argument("--only", nargs="*")
    s = sub.add_parser("score")
    s.add_argument("pred")
    s.add_argument("target")
    s.add_argument("--res", type=int, default=64)
    for name in ("solve", "eval"):
        s = sub.add_parser(name)
        s.add_argument("--backend", default="cadquery")
        s.add_argument("--model", default=None)
        s.add_argument("--candidates", type=int, default=3)
        s.add_argument("--rounds", type=int, default=2)
        s.add_argument("--effort", default="high")
        s.add_argument("-o", "--out", default=None)
        if name == "solve":
            s.add_argument("prompt", nargs="?")
            s.add_argument("--image")
        else:
            s.add_argument("--only", nargs="*")
            s.add_argument("--tag", help="save scores to results/<time>-<tag>.json (use <track>-<idea>)")
            s.add_argument("--image", action="store_true", help="give the agent the target render, not the text")
    args = ap.parse_args()

    if args.cmd == "bench":
        bench.build()
    elif args.cmd == "sensitivity":
        result = sensitivity.run(only=args.only)
        print(sensitivity.format_table(result))
        (bench.ROOT / "sensitivity.json").write_text(json.dumps(result, indent=1))
    elif args.cmd == "score":
        _print_report(compare(args.pred, args.target, res=args.res))
    elif args.cmd == "solve":
        out = Path(args.out or f"runs/solve-{time.strftime('%H%M%S')}")
        task = Task(args.prompt, Path(args.image) if args.image else None)
        print(json.dumps(_agent(args).solve(task, out), indent=1))
    elif args.cmd == "eval":
        agent = _agent(args)
        root = Path(args.out or f"runs/eval-{time.strftime('%m%d-%H%M%S')}")
        rows = {}
        for case in bench.cases(args.only):
            task = Task(image=case.image) if args.image else Task(prompt=case.prompt)
            summary = agent.solve(task, root / case.id)
            # A failed case scores zero. Dropping failures would flatter the average.
            rep = compare(summary["stl"], case.target) if summary["stl"] else None
            rows[case.id] = rep
            print(f"{case.id:20s}" + "".join(
                f"  {m} {rep[m]['iou']:.3f}" if rep else f"  {m} 0.000" for m in MODES), flush=True)
        mean = {m: sum(r[m]["iou"] if r else 0.0 for r in rows.values()) / max(len(rows), 1) for m in MODES}
        print(f"{'MEAN IoU':20s}" + "".join(f"  {m} {v:.3f}" for m, v in mean.items()))
        scores = {"mean_iou": mean, "input": "image" if args.image else "text", "n_cases": len(rows),
                  "settings": {k: getattr(args, k) for k in ("backend", "model", "candidates", "rounds", "effort")},
                  "cases": rows}
        (root / "scores.json").write_text(json.dumps(scores, indent=1))
        if args.tag:
            RESULTS.mkdir(exist_ok=True)
            (RESULTS / f"{time.strftime('%m%d-%H%M')}-{args.tag}.json").write_text(json.dumps(scores, indent=1))
    elif args.cmd == "board":
        print(f"{'run':40s}{'input':>7s}{'cases':>6s}" + "".join(f"{m:>8s}" for m in MODES))
        for f in sorted(RESULTS.glob("*.json")):
            r = json.loads(f.read_text())
            print(f"{f.stem:40s}{r.get('input', '?'):>7s}{r.get('n_cases', 0):6d}"
                  + "".join(f"{r['mean_iou'][m]:8.3f}" for m in MODES))


if __name__ == "__main__":
    main()
