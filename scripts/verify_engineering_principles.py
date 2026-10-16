from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from krx_research.policies import DEFAULT_ENGINEERING_POLICY  # noqa: E402


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    command: tuple[str, ...]


class EngineeringPrincipleVerifier:
    """Runs the repository guards that provide evidence for the policy catalog."""

    def __init__(self, python: str = sys.executable):
        self.checks = (
            Check("architecture", (python, "scripts/verify_architecture.py")),
            Check("import boundaries", (python, "scripts/verify_import_boundaries.py")),
            Check("chart policy", (python, "scripts/verify_v6_chart_navigation.py")),
            Check("table policy", (python, "scripts/verify_v15_global_table_alignment.py")),
            Check("Git safety", (python, "scripts/verify_v10_git_workflow.py")),
            Check("diff integrity", ("git", "diff", "--check")),
        )

    def run(self) -> int:
        failed = []
        for check in self.checks:
            result = subprocess.run(check.command, cwd=ROOT, check=False)
            if result.returncode:
                failed.append(check.name)
        print("ENGINEERING_PRINCIPLES:", "PASS" if not failed else "FAIL")
        if failed:
            print(" - " + "\n - ".join(failed))
        return int(bool(failed))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("before", "after", "list"))
    phase = parser.parse_args().phase
    print(DEFAULT_ENGINEERING_POLICY.text())
    return EngineeringPrincipleVerifier().run() if phase == "after" else 0


if __name__ == "__main__":
    raise SystemExit(main())

