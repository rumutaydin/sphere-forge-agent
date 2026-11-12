"""Runs one generated CadQuery program in its own process.

usage: python _cq_runner.py <code.py> <out_dir>
Writes part.step and measure.json into out_dir. Exit code 0 on success;
on failure the traceback goes to stderr.
"""
import json
import os
import sys
import traceback
from pathlib import Path

# Let generated programs `from forge.library import ...`.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def find_result(ns: dict):
    import cadquery as cq

    kinds = (cq.Workplane, cq.Shape, cq.Assembly)
    if isinstance(ns.get("result"), kinds):
        return ns["result"]
    shown = ns.get("_shown")
    if shown:
        return shown[-1]
    found = [v for k, v in ns.items() if isinstance(v, kinds) and not k.startswith("_")]
    if not found:
        raise RuntimeError("program did not define `result` (a cq.Workplane or cq.Shape)")
    return found[-1]


def to_shape(obj):
    import cadquery as cq

    if isinstance(obj, cq.Assembly):
        return obj.toCompound()
    if isinstance(obj, cq.Workplane):
        vals = [v for v in obj.vals() if isinstance(v, cq.Shape)]
        if not vals:
            raise RuntimeError("`result` workplane holds no shapes")
        return vals[0] if len(vals) == 1 else cq.Compound.makeCompound(vals)
    return obj


def measure(shape) -> dict:
    from OCP.BRepAdaptor import BRepAdaptor_Surface

    bb = shape.BoundingBox()
    com = shape.Center()
    faces: dict[str, int] = {}
    cylinders = []
    for face in shape.Faces():
        kind = face.geomType()
        faces[kind] = faces.get(kind, 0) + 1
        if kind == "CYLINDER":
            cyl = BRepAdaptor_Surface(face.wrapped).Cylinder()
            ax = cyl.Axis()
            d, p = ax.Direction(), ax.Location()
            cylinders.append(
                {"r": cyl.Radius(), "dir": [d.X(), d.Y(), d.Z()], "at": [p.X(), p.Y(), p.Z()]}
            )
    return {
        "valid": bool(shape.isValid()),
        "solids": len(shape.Solids()),
        "bbox_min": [bb.xmin, bb.ymin, bb.zmin],
        "bbox_max": [bb.xmax, bb.ymax, bb.zmax],
        "bbox_size": [bb.xlen, bb.ylen, bb.zlen],
        "volume": float(shape.Volume()),
        "area": float(shape.Area()),
        "com": [com.x, com.y, com.z],
        "faces": faces,
        "cylinders": cylinders,
    }


def main() -> int:
    code_path, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        import cadquery as cq

        shown: list = []
        ns = {"__name__": "__main__", "_shown": shown, "show_object": lambda o, *a, **k: shown.append(o)}
        exec(compile(code_path.read_text(), str(code_path), "exec"), ns)
        shape = to_shape(find_result(ns))
        info = measure(shape)
        bbox_volume = info["bbox_size"][0] * info["bbox_size"][1] * info["bbox_size"][2]
        if info["solids"] == 0 or info["volume"] <= 1e-6 * bbox_volume:
            raise RuntimeError("result has no solid volume (did you forget to extrude/close a sketch?)")
        cq.exporters.export(shape, str(out_dir / "part.step"))
        from forge.geometry import genus, shape_to_mesh

        mesh = shape_to_mesh(shape)
        info["genus"] = genus(mesh)  # through-hole count, as the scorer counts it
        info["bbox_size"] = [float(e) for e in mesh.extents]   # the kernel's own box can be loose on curved faces
        task_dir = os.environ.get("FORGE_TASK_DIR")
        if task_dir and info["valid"] and info["solids"] == 1:
            # score against the task's facts and views here, in the subprocess
            from forge.cases import load_tasks
            from forge.compile import estimate
            from forge.facts import self_check
            from forge.vision import shape_score

            task = load_tasks(Path(task_dir).parent, [Path(task_dir).name + "$"])[0]
            info["check"] = self_check(info, task.facts)
            info["shape"] = shape_score(mesh, task) if task.views else {"mean": 0.0, "iou_per_view": {}}
            info["check"]["silhouette_iou"] = info["shape"]["mean"]
            info["check"]["estimate"] = estimate(info["check"], info["shape"])
        (out_dir / "measure.json").write_text(json.dumps(info))
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
