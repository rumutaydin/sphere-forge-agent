"""Loading tasks, and building our own reference cases in the organisers' format.

Organiser layout (artifacts/inputs/):
    test_case_<n>/description.md, facts.json, images/view_*.png, [context.png]
The hidden parts have no facts.json: their facts are rebuilt from the brief (forge/brief.py).
FORGE_IGNORE_FACTS=1 does the same on parts that have one.

Our reference cases (bench/cases/, built from bench/parts/*.py) use the same
layout plus answer.step, which is what lets us compute a full score locally.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .types import Task

BENCH = Path(__file__).resolve().parent.parent / "bench"


def _order(path: Path):
    tail = path.name.rsplit("_", 1)[-1]
    return (0, int(tail), "") if tail.isdigit() else (1, 0, path.name)


def ignore_facts() -> bool:
    """FORGE_IGNORE_FACTS=1: never read facts.json, as on the hidden parts, which have none."""
    return os.environ.get("FORGE_IGNORE_FACTS", "0").strip().lower() in ("1", "on", "yes", "true")


def load_facts(task_dir: str | Path, description: str | None = None, views: list[Path] | None = None) -> dict:
    """The facts of one task folder: facts.json if it is there (and not ignored), else rebuilt
    from the brief (forge/brief.py). A run keeps the rebuilt facts of each task in
    $FORGE_FACTS_DIR/<task>.json, so that every subprocess of the run sees the same ones.
    Always returns a bounding box."""
    d = Path(task_dir)
    if not ignore_facts():
        try:
            facts = json.loads((d / "facts.json").read_text())
            box = facts.get("bounding_box_mm") or {}
            if all(float(box.get(k, 0)) > 0 for k in "xyz"):
                return facts
        except Exception:
            pass        # missing or unreadable: the brief has the numbers too
    cache = os.environ.get("FORGE_FACTS_DIR")
    if cache:
        try:
            kept = json.loads((Path(cache) / f"{d.name}.json").read_text())
            if kept.get("_dir") == str(d.resolve()):      # the same task folder, not one of the same name
                return kept
        except Exception:
            pass
    from .brief import facts_from_brief

    if description is None:
        try:
            description = (d / "description.md").read_text()
        except Exception:
            description = ""
    if views is None:
        views = sorted((d / "images").glob("view_*.png"))
    return facts_from_brief(description, views)


def settle_brief_facts(tasks: list[Task], cache_dir: str | Path, llm=None) -> None:
    """Once per run, for tasks whose facts come from the brief: optionally let the model add
    bores the rules missed (FORGE_BRIEF_LLM=1, one text call per task, FORGE_BRIEF_LLM_S each),
    then write the facts to `cache_dir` and point FORGE_FACTS_DIR at it. Never raises."""
    from concurrent.futures import ThreadPoolExecutor

    todo = [t for t in tasks if t.facts.get("_source") == "brief"]
    if not todo:
        return
    cache_dir = Path(cache_dir)
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        use_model = (llm is not None and type(llm).__name__ != "LLM"
                     and os.environ.get("FORGE_BRIEF_LLM", "0").strip().lower() in ("1", "on", "yes", "true")
                     and _endpoint_up())
        if use_model:
            from .brief import refine_with_model

            limit = float(os.environ.get("FORGE_BRIEF_LLM_S", "60"))
            with ThreadPoolExecutor(min(len(todo), 9)) as pool:
                for task, facts in zip(todo, pool.map(lambda t: refine_with_model(llm, t.description, t.facts, limit), todo)):
                    task.facts = facts
        for task in todo:
            if task.dir is not None:
                task.facts["_dir"] = str(Path(task.dir).resolve())
            (cache_dir / f"{task.name}.json").write_text(json.dumps(task.facts, indent=1))
        os.environ["FORGE_FACTS_DIR"] = str(cache_dir)
        n = sum(len(g["centres"]) for t in todo for g in t.facts.get("cylindrical_holes_and_bores", []))
        print(f"facts from the brief for {len(todo)} task(s): {n} bores placed"
              + (", model asked" if use_model else ""), flush=True)
        for task in todo:
            for w in task.facts.get("_warnings", []):
                print(f"{task.name}: {w}", flush=True)
    except Exception as exc:
        print(f"NOTE: brief facts not cached ({type(exc).__name__}: {exc})", flush=True)


def _endpoint_up(timeout: float = 3.0) -> bool:
    """Whether something listens at OPENAI_BASE_URL (a plain connect; no request is sent)."""
    import socket
    from urllib.parse import urlparse

    try:
        url = urlparse(os.environ.get("OPENAI_BASE_URL", ""))
        if not url.hostname:
            return False
        with socket.create_connection((url.hostname, url.port or (443 if url.scheme == "https" else 80)), timeout=timeout):
            return True
    except Exception:
        return False


def load_tasks(input_dir: str | Path, only: list[str] | None = None) -> list[Task]:
    tasks = []
    for d in sorted(Path(input_dir).iterdir(), key=_order):
        if not d.is_dir() or not ((d / "description.md").is_file() or (d / "images").is_dir()):
            continue        # a task folder has a brief or views; one without the brief still gets a solid
        if only and not any(d.name == o[:-1] if o.endswith("$") else o in d.name for o in only):
            continue
        context, answer = d / "context.png", d / "answer.step"
        try:
            description = (d / "description.md").read_text(errors="replace")
        except OSError:
            description = ""
        views = sorted((d / "images").glob("view_*.png"))
        tasks.append(Task(
            name=d.name,
            description=description,
            views=views,
            context=context if context.is_file() else None,
            facts=load_facts(d, description, views),
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
