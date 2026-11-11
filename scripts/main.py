"""Entry point with the organisers' interface. Keep the name and the two arguments.

    python scripts/main.py --input_dir <inputs> --output_dir <outputs>
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from forge.run import run_all  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_dir", type=Path, default=REPO_ROOT / "artifacts/inputs")
    parser.add_argument("--output_dir", type=Path, default=REPO_ROOT / "artifacts/outputs")
    args = parser.parse_args()
    run_all(args.input_dir, args.output_dir)
