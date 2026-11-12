"""Command line.

  uv run python -m forge bench                      build our reference cases (with answers)
  uv run python -m forge score PRED.step TARGET.step
  uv run python -m forge check PART.step FACTS.json check a STEP file against a task's facts
  uv run python -m forge eval --tag c-fewshot       agent on our reference cases, full score
  uv run python -m forge eval --inputs artifacts/inputs --tag c-fewshot
                                                    agent on the organisers' cases, self-score only
  uv run python -m forge board                      table of everything in results/
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .cases import BENCH, build_bench, load_tasks

RESULTS = Path(__file__).resolve().parent.parent / "results"
PARTS = ("volume", "surface", "dimensions", "holes")


def main() -> None:
    ap = argparse.ArgumentParser(prog="forge")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("bench")
    sub.add_parser("board")
    s = sub.add_parser("score")
    s.add_argument("pred")
    s.add_argument("target")
    s = sub.add_parser("check")
    s.add_argument("part")
    s.add_argument("facts")
    s = sub.add_parser("eval")
    s.add_argument("--inputs", default=str(BENCH / "cases"), help="folder of tasks in the organisers' layout")
    s.add_argument("--only", nargs="*")
    s.add_argument("--tag", help="save scores to results/<time>-<tag>.json (use <track>-<idea>)")
    s.add_argument("-o", "--out", default=None)
    args = ap.parse_args()

    if args.cmd == "bench":
        build_bench()
    elif args.cmd == "score":
        from .score import score

        rep = score(args.pred, args.target)
        print(f"score {rep['score']:.3f}   " + "   ".join(f"{k} {rep[k]:.3f}" for k in PARTS))
    elif args.cmd == "check":
        from .backends._cq_runner import measure
        from .facts import report, self_check
        from .geometry import genus, shape_to_mesh
        import cadquery as cq

        vals = cq.importers.importStep(args.part).vals()
        shape = vals[0] if len(vals) == 1 else cq.Compound.makeCompound(vals)
        info = measure(shape)
        info["genus"] = genus(shape_to_mesh(shape))
        check = self_check(info, json.loads(Path(args.facts).read_text()))
        print(f"self-score {check['self_score']:.3f}\n{report(check)}")
    elif args.cmd == "eval":
        from .run import run_all
        from .score import score

        root = Path(args.out or f"runs/eval-{time.strftime('%m%d-%H%M%S')}")
        tasks = {t.name: t for t in load_tasks(args.inputs, args.only)}
        t_start = time.time()
        summaries = run_all(Path(args.inputs), root / "outputs", only=args.only, work_dir=root / "work")
        rows = {}
        for s in summaries:
            task = tasks[s["task"]]
            chk = s["self_check"]
            row = {"self_score": chk.get("self_score", 0.0), "chosen": s["chosen"],
                   "estimate": chk.get("estimate", 0.0), "dimensions": chk.get("dimensions"), "holes": chk.get("holes"),
                   "volume_ratio": chk.get("volume_ratio"), "area_ratio": chk.get("area_ratio"),
                   "silhouette_iou": chk.get("silhouette_iou"),
                   "candidates": [(c["usable"], round(c["score"], 3)) for c in s.get("candidates", [])]}
            # A task with no part scores zero. Dropping failures would flatter the average.
            if task.answer:
                row.update(score(s["step"], task.answer) if s["step"] else {"score": 0.0, **dict.fromkeys(PARTS, 0.0)})
            rows[task.name] = row
            print(f"{task.name:20s} est {row['estimate']:.3f}  self {row['self_score']:.3f}  {row['chosen']}"
                  + (f"   score {row['score']:.3f}" if "score" in row else ""), flush=True)
        n = max(len(rows), 1)
        scored = [r for r in rows.values() if "score" in r]
        result = {
            "inputs": args.inputs, "n_cases": len(rows),
            "mean_self_score": sum(r["self_score"] for r in rows.values()) / n,
            "mean_estimate": sum(r["estimate"] for r in rows.values()) / n,
            "wall_clock_s": round(time.time() - t_start),
            "mean_score": sum(r["score"] for r in scored) / len(scored) if scored else None,
            "cases": rows,
        }
        print(f"MEAN estimate {result['mean_estimate']:.3f}  self {result['mean_self_score']:.3f}  wall {result['wall_clock_s']}s"
              + (f"   score {result['mean_score']:.3f}" if scored else "   (no answer files: self-score only)"))
        (root / "scores.json").write_text(json.dumps(result, indent=1))
        if args.tag:
            RESULTS.mkdir(exist_ok=True)
            (RESULTS / f"{time.strftime('%m%d-%H%M')}-{args.tag}.json").write_text(json.dumps(result, indent=1))
    elif args.cmd == "board":
        print(f"{'run':44s}{'cases':>6s}{'est':>8s}{'self':>8s}{'score':>8s}{'leaderboard':>13s}")
        for f in sorted(RESULTS.glob("*.json")):
            r = json.loads(f.read_text())
            score_txt = f"{r['mean_score']:8.3f}" if r.get("mean_score") is not None else f"{'-':>8s}"
            lb = r.get("leaderboard")
            est = f"{r['mean_estimate']:8.3f}" if r.get("mean_estimate") is not None else f"{'-':>8s}"
            print(f"{f.stem:44s}{r.get('n_cases', 0):6d}{est}{r.get('mean_self_score', 0):8.3f}{score_txt}"
                  + (f"{lb:13.3f}" if lb is not None else f"{'-':>13s}"))


if __name__ == "__main__":
    main()
