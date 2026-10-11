from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
import sys
from pathlib import Path

from krx_research.application.xing_db.e2e_models import CommandOutcome


class LocalMenuCommandRunner:
    """Runs the same script entry points used by menus 2, 5 and 7.

    All child Python processes are forced to UTF-8 so their pipe contract is
    deterministic on Windows. Console mirroring is encoded with replacement
    only at the display boundary; the logical output remains Unicode.
    """

    _AFFECTED = re.compile(r"V41_AFFECTED_ROWS=(\d+)")

    def __init__(self, project_root: Path) -> None:
        self._root = Path(project_root)

    def run_menu7_single_combined(
        self, stock_code: str, trade_date: dt.date, *, force_refresh: bool = False
    ) -> CommandOutcome:
        args = [
            "scripts/run_xing_db_menu.py", "--menu", "7",
            "--venues", "COMBINED", "--ticker", stock_code,
            "--start", trade_date.isoformat(), "--end", trade_date.isoformat(),
            "--verification-marker", "--no-investor",
        ]
        if force_refresh:
            args.append("--force-refresh")
        return self._run(args)

    def run_menu5_single_day(
        self, stock_code: str, trade_date: dt.date, *, force_refresh: bool = False
    ) -> CommandOutcome:
        args = [
            "scripts/update_ls_investor_date_range.py",
            "--ticker", stock_code, "--start", trade_date.isoformat(),
            "--end", trade_date.isoformat(), "--chunk-days", "1",
            "--verification-marker",
        ]
        if force_refresh:
            args.append("--force-refresh")
        return self._run(args)

    def run_menu2_full(self, as_of: dt.date) -> CommandOutcome:
        return self._run([
            "scripts/run_daily_pipeline.py", "--as-of", as_of.isoformat(),
            "--until-complete", "--no-investor", "--markets", "KOSPI", "KOSDAQ",
        ])

    @staticmethod
    def _console_safe(text: str, stream=None) -> str:
        """Return text representable by the selected console stream.

        This is intentionally a display-only conversion. It prevents Windows
        cp949 consoles from crashing on U+FFFD or other non-representable code
        points while keeping the child pipe itself UTF-8.
        """
        stream = stream or sys.stdout
        encoding = getattr(stream, "encoding", None) or "utf-8"
        try:
            return text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        except LookupError:
            return text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")

    @classmethod
    def _safe_print(cls, text: str, *, stream=None) -> None:
        stream = stream or sys.stdout
        print(cls._console_safe(text, stream), file=stream, flush=True)

    def _run(self, relative_args: list[str]) -> CommandOutcome:
        script = self._root / relative_args[0]
        if not script.is_file():
            self._safe_print(f"[V41.5] 실행 파일 없음: {script}", stream=sys.stderr)
            return CommandOutcome(97, 0)

        command = [sys.executable, str(script), *relative_args[1:]]
        self._safe_print("[V41.5 EXEC] " + " ".join(command))

        child_env = os.environ.copy()
        # Deterministic text protocol between Python parent/child on Windows.
        child_env["PYTHONUTF8"] = "1"
        child_env["PYTHONIOENCODING"] = "utf-8"
        child_env.setdefault("PYTHONDONTWRITEBYTECODE", "1")

        proc = subprocess.Popen(
            command,
            cwd=self._root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=child_env,
        )
        assert proc.stdout is not None

        affected = 0
        for line in proc.stdout:
            clean = line.rstrip("\r\n")
            self._safe_print(clean)
            match = self._AFFECTED.search(clean)
            if match:
                affected = int(match.group(1))

        return CommandOutcome(int(proc.wait()), affected)
