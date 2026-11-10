"""Local benchmark: reference parts with a text prompt and a rendered image each.

bench/parts/*.py     reference programs (PROMPT string + CadQuery code)
bench/targets/<id>/  generated: part.step, part.stl, measure.json, target.png, prompt.txt

Drop extra cases (from public datasets, or the organisers' examples) into
bench/targets/<id>/ with a part.step or part.stl and a prompt.txt and they are
picked up automatically.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .backends import get_backend
from .geometry import load_mesh
from .render import render_grid

ROOT = Path(__file__).resolve().parent.parent / "bench"


@dataclass
class Case:
    id: str
    prompt: str
    dir: Path

    @property
    def target(self) -> Path:
        step = self.dir / "part.step"
        return step if step.exists() else self.dir / "part.stl"

    @property
    def image(self) -> Path:
        return self.dir / "target.png"


def build(verbose: bool = True) -> None:
    backend = get_backend("cadquery")
    for src in sorted((ROOT / "parts").glob("*.py")):
        out = ROOT / "targets" / src.stem
        code = src.read_text()
        ns: dict = {}
        exec(code.split("import cadquery", 1)[0], ns)  # only the PROMPT assignment
        res = backend.execute(code, out)
        if not res.ok or res.error:
            raise RuntimeError(f"{src.name}: {res.error}")
        (out / "prompt.txt").write_text(ns["PROMPT"].strip() + "\n")
        render_grid(load_mesh(res.stl_path), out / "target.png")
        if verbose:
            size = ", ".join(f"{s:.1f}" for s in res.measure["bbox_size"])
            print(f"{src.stem:20s} bbox ({size})  volume {res.measure['volume']:.0f}")


def cases(only: list[str] | None = None) -> list[Case]:
    out = []
    for d in sorted((ROOT / "targets").iterdir()):
        if not d.is_dir() or not (d / "prompt.txt").exists():
            continue
        if only and not any(o in d.name for o in only):
            continue
        out.append(Case(d.name, (d / "prompt.txt").read_text().strip(), d))
    return out
