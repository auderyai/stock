"""Run the fast PostgreSQL daily price update.

Investor flow is deliberately excluded from the market-wide scheduled job.
The workstation retrieves aggregate public Naver flow only for the ticker the
user opens, while existing detailed PostgreSQL investor facts remain preferred.
"""

from __future__ import annotations

import sys

from krx_research.data_engine.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["update", "--no-investor", *sys.argv[1:]]))
