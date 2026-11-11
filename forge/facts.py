"""Checking a built part against facts.json, with no answer file needed.

Each task ships a facts.json with the target's bounding box, volume, surface
area, through-hole count and hole inventory. Two of the four score components
(dimensions, holes) can therefore be computed exactly at run time, and volume
and area give a strong hint about the other two. This is the signal the critic
and the final selection run on.
"""
from __future__ import annotations

from .score import WEIGHTS, dimension_score, hole_score


def facts_from_measure(measure: dict) -> dict:
    """A facts.json for one of our own reference parts (subset of the organisers' keys)."""
    x, y, z = measure["bbox_size"]
    return {
        "bounding_box_mm": {"x": round(x, 2), "y": round(y, 2), "z": round(z, 2)},
        "volume_mm3": round(measure["volume"], 1),
        "surface_area_mm2": round(measure["area"], 1),
        "solids": measure["solids"],
        "through_holes_genus": measure["genus"],
        "faces": sum(measure["faces"].values()),
        "face_types": measure["faces"],
        "_note": "positions in mm from the bounding-box min corner, in the frame of the 8 views",
    }


def _ratio(a: float, b: float) -> float:
    return min(a, b) / max(a, b) if a > 0 and b > 0 else 0.0


def self_check(measure: dict, facts: dict) -> dict:
    """Compare kernel measurements of a candidate with the task's facts.

    Returns {"self_score", "dimensions", "holes", "volume_ratio", "area_ratio", "issues"}.
    `dimensions` and `holes` follow the official rules. `self_score` substitutes the
    volume and area ratios for the two components we cannot compute without the
    target; it ranks candidates, it is not the leaderboard score.
    """
    box = facts["bounding_box_mm"]
    target = [box["x"], box["y"], box["z"]]
    built = measure["bbox_size"]
    issues = []

    for axis, b, t in zip("XYZ", built, target):
        err = (b - t) / t if t else 0.0
        if abs(err) > 0.005:
            issues.append(f"{axis} extent is {b:.2f} mm, target {t:.2f} mm ({err:+.1%})")
    # Pose does not matter for the score, so match axes by size; the per-axis lines
    # above are for the critic, who works in the frame of the views.
    dims = dimension_score(built, target)

    holes_target = int(facts.get("through_holes_genus", 0))
    holes_built = int(measure.get("genus", -1))
    holes = hole_score(holes_built, holes_target)
    if holes_built != holes_target:
        issues.append(f"through-holes: built {holes_built}, target {holes_target}")

    vol = measure["volume"] / facts["volume_mm3"] if facts.get("volume_mm3") else 1.0
    if abs(vol - 1) > 0.02:
        hint = "too much material: missing pocket, bore or cut-out?" if vol > 1 else "too little material: missing boss, rib or wall?"
        issues.append(f"volume is {vol - 1:+.1%} off target ({hint})")
    area = measure["area"] / facts["surface_area_mm2"] if facts.get("surface_area_mm2") else 1.0
    if abs(area - 1) > 0.05:
        issues.append(f"surface area is {area - 1:+.1%} off target (fewer or more features than the target)")

    built_diams = {round(2 * c["r"], 1) for c in measure.get("cylinders", [])}
    for group in facts.get("cylindrical_holes_and_bores", []) + facts.get("cylindrical_shafts_and_bosses", []):
        d = group.get("diameter")
        if d is not None and not any(abs(d - b) <= max(0.06, 0.005 * d) for b in built_diams):
            issues.append(f"no cylindrical face of diameter {d} mm (target has {group.get('count', '?')}, axis {group.get('axis', '?')})")

    if measure.get("solids", 1) != 1:
        issues.append(f"{measure['solids']} separate solids; exactly one is required")

    self_score = (WEIGHTS["volume"] * _ratio(vol, 1.0) + WEIGHTS["surface"] * _ratio(area, 1.0)
                  + WEIGHTS["dimensions"] * dims + WEIGHTS["holes"] * holes)
    return {"self_score": self_score, "dimensions": dims, "holes": holes,
            "volume_ratio": vol, "area_ratio": area, "issues": issues}


def report(check: dict) -> str:
    head = (f"dimensions {check['dimensions']:.2f}/1, holes {check['holes']:.2f}/1, "
            f"volume x{check['volume_ratio']:.3f}, surface area x{check['area_ratio']:.3f}")
    if not check["issues"]:
        return head + "\nAll numeric checks pass."
    return head + "\n" + "\n".join(f"- {i}" for i in check["issues"])
