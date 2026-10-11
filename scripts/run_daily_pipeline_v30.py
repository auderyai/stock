"""Fast daily entry point: update facts only, calculate nothing ahead of demand."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from krx_research.data_engine.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["update", *sys.argv[1:]]))
