"""Print the table of filed approaches (bench/approaches/*/scores.json) as markdown.

    uv run python scripts/approaches_table.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
rows = []
for d in sorted((ROOT / "bench/approaches").iterdir()):
    f = d / "scores.json"
    if f.is_file():
        rows.append((d.name, json.loads(f.read_text())))
names = [f"test_case_{i}" for i in range(1, 10)]
print("| Approach | Estimate | Leaderboard | " + " | ".join(str(i) for i in range(1, 10)) + " | Holes right |")
print("|---|---|---|" + "---|" * 9 + "---|")
for name, s in rows:
    lb = f"**{s['leaderboard']:.3f}**" if s.get("leaderboard") is not None else "not submitted"
    cells = " | ".join(f"{s['cases'][n]['estimate']:.2f}" if n in s["cases"] else "-" for n in names)
    print(f"| `{name}` | {s['mean_estimate']:.3f} | {lb} | {cells} | {s['holes_right']} of {s['n_cases']} |")
print()
for name, s in rows:
    print(f"- `{name}`: {s['what']}")
