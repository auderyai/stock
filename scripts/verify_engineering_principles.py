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

from krx_research.policies import (  # noqa: E402
    DEFAULT_CHART_ANALYSIS_POLICY, DEFAULT_ENGINEERING_POLICY,
)


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    command: tuple[str, ...]


class EngineeringPrincipleVerifier:
    """Runs the repository guards that provide evidence for the policy catalog."""

    def __init__(self, python: str = sys.executable):
        self.checks = (
            Check("chart analysis settings", (python, "scripts/verify_chart_analysis_policy.py")),
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
    chart = DEFAULT_CHART_ANALYSIS_POLICY
    print(
        "[CHART-ANALYSIS] "
        f"RSI EMA{chart.rsi.periods}; MACD EMA{chart.macd_oscillator.periods}; "
        f"Slow Stochastic EMA{chart.stochastic_slow.periods}; "
        f"{chart.moving_average_kind}{chart.moving_average_periods}; "
        f"Bollinger {chart.bollinger.center}{chart.bollinger.period},{chart.bollinger.deviations:g}; "
        f"volume={chart.volume_source}; market=KOSPI+KOSDAQ/"
        f"returns={chart.market_context.return_horizons}/"
        f"volatility={chart.market_context.volatility_windows}/"
        f"regime={chart.market_context.regime_lookback_days}일"
    )
    if phase == "before":
        return subprocess.run(
            (sys.executable, "scripts/verify_chart_analysis_policy.py"), cwd=ROOT, check=False
        ).returncode
    return EngineeringPrincipleVerifier().run() if phase == "after" else 0


if __name__ == "__main__":
    raise SystemExit(main())

