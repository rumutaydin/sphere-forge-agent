"""Compare ranking rules on handoff/rank_bench.py output: mean true score of the row each rule picks.
    uv run python handoff/rank_eval.py runs/rankbench.json"""
import json, math, sys

TYPES = ("PLANE", "CYLINDER", "CONE", "TORUS", "BSPLINE", "SPHERE")

def fp_dist(faces, want):
    """Face-type fingerprint distance: mean |log(1+n) - log(1+n_facts)| over the types present in either."""
    if not want or faces is None:
        return 0.0
    ts = [t for t in TYPES if (faces.get(t, 0) or want.get(t, 0))]
    if not ts:
        return 0.0
    return sum(abs(math.log1p(faces.get(t, 0)) - math.log1p(want.get(t, 0))) for t in ts) / len(ts)

def two_num(c):
    vr, ar = c.get("volume_ratio") or 1, c.get("area_ratio") or 1
    return abs(math.log(vr)) + abs(math.log(ar))

def rules():
    yield "estimate (main)", lambda r, w: r["estimate"]
    for a in (0.1, 0.25, 0.5):
        yield f"est - {a}*|area-1|", lambda r, w, a=a: r["estimate"] - a * min(abs((r["check"]["area_ratio"] or 1) - 1), 1)
    for b in (0.02, 0.05, 0.1, 0.2):
        yield f"est - {b}*fingerprint", lambda r, w, b=b: r["estimate"] - b * fp_dist(r["check"]["faces"], w)
    for c in (0.1, 0.2, 0.4):
        yield f"est - {c}*(|log v|+|log a|)", lambda r, w, c=c: r["estimate"] - c * two_num(r["check"])
    for a, b in ((0.25, 0.05), (0.25, 0.1), (0.1, 0.05), (0.5, 0.1)):
        yield f"est - {a}*|area-1| - {b}*fp", lambda r, w, a=a, b=b: (r["estimate"] - a * min(abs((r["check"]["area_ratio"] or 1) - 1), 1)
                                                                      - b * fp_dist(r["check"]["faces"], w))

if __name__ == "__main__":
    data = json.load(open(sys.argv[1]))
    data = {k: v for k, v in data.items() if any(r["true"].get("score") is not None for r in v["rows"])}
    oracle = sum(max(r["true"]["score"] or 0 for r in v["rows"]) for v in data.values()) / len(data)
    print(f"{len(data)} parts; oracle (best row every time) {oracle:.4f}")
    res = []
    for name, f in rules():
        picks = {k: max((r for r in v["rows"] if r["true"].get("score") is not None), key=lambda r: f(r, v["facts_faces"]))
                 for k, v in data.items()}
        mean = sum(p["true"]["score"] for p in picks.values()) / len(picks)
        res.append((mean, name, picks))
    base = res[0][2]
    for mean, name, picks in sorted(res, key=lambda x: -x[0]):
        diff = [f"{k[:14]} {base[k]['true']['score']:.3f}->{p['true']['score']:.3f}" for k, p in picks.items()
                if abs(p["true"]["score"] - base[k]["true"]["score"]) > 0.002]
        print(f"{mean:.4f}  {name:34s} " + "; ".join(diff))
