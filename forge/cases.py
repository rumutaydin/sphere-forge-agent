"""Loading tasks, and building our own reference cases in the organisers' format.

Organiser layout (artifacts/inputs/):
    test_case_<n>/description.md, facts.json, images/view_*.png, [context.png]

Our reference cases (bench/cases/, built from bench/parts/*.py) use the same
layout plus answer.step, which is what lets us compute a full score locally.
"""
from __future__ import annotations

import json
from pathlib import Path

from .types import Task

BENCH = Path(__file__).resolve().parent.parent / "bench"


def _order(path: Path):
    tail = path.name.rsplit("_", 1)[-1]
    return (0, int(tail), "") if tail.isdigit() else (1, 0, path.name)


def load_tasks(input_dir: str | Path, only: list[str] | None = None) -> list[Task]:
    tasks = []
    for d in sorted(Path(input_dir).iterdir(), key=_order):
        if not (d / "description.md").is_file():
            continue
        if only and not any(d.name == o[:-1] if o.endswith("$") else o in d.name for o in only):
            continue
        facts_file, context, answer = d / "facts.json", d / "context.png", d / "answer.step"
        tasks.append(Task(
            name=d.name,
            description=(d / "description.md").read_text(),
            views=sorted((d / "images").glob("view_*.png")),
            context=context if context.is_file() else None,
            facts=json.loads(facts_file.read_text()) if facts_file.is_file() else {},
            answer=answer if answer.is_file() else None,
            dir=d,
        ))
    return tasks


def build_bench(verbose: bool = True) -> None:
    """Turn bench/parts/*.py into bench/cases/<id>/ in the organisers' input format."""
    from .backends import get_backend
    from .facts import facts_from_measure
    from .geometry import load_mesh
    from .render import render_views

    backend = get_backend("cadquery")
    for src in sorted((BENCH / "parts").glob("*.py")):
        out = BENCH / "cases" / src.stem
        code = src.read_text()
        ns: dict = {}
        exec(code.split("import cadquery", 1)[0], ns)  # only the PROMPT assignment
        res = backend.execute(code, out / "_build")
        if not res.ok or res.error:
            raise RuntimeError(f"{src.name}: {res.error}")
        res.step_path.replace(out / "answer.step")
        (out / "description.md").write_text(ns["PROMPT"].strip() + "\n")
        (out / "facts.json").write_text(json.dumps(facts_from_measure(res.measure), indent=1))
        render_views(load_mesh(out / "answer.step"), out / "images", size=512)
        for f in (out / "_build").iterdir():
            f.unlink()
        (out / "_build").rmdir()
        if verbose:
            size = ", ".join(f"{s:.1f}" for s in res.measure["bbox_size"])
            print(f"{src.stem:20s} bbox ({size})  holes {res.measure['genus']}")
