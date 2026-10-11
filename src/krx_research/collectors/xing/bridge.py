from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

from .worker_runtime import Xing32Environment


class XingBridgeError(RuntimeError):
    pass


class XingBridgeClient:
    """64bit facade. Every TR is executed by one persistent 32bit DLL worker."""

    def __init__(self, project_root: str | Path, *, delay: float = .08, timeout: float = 30.0) -> None:
        self.root = Path(project_root).expanduser().resolve()
        self.delay = max(0.0, float(delay))
        self.timeout = max(1.0, float(timeout))
        self.runtime = Xing32Environment(self.root)
        self.process: subprocess.Popen[str] | None = None

    def connect(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        python = self.runtime.require()
        worker = self.root / "scripts" / "xing32_worker.py"
        self.process = subprocess.Popen(
            [str(python), str(worker), "--serve", "--delay", str(self.delay), "--timeout", str(self.timeout)],
            cwd=self.root,
            env=self.runtime.process_environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        ready = self._read()
        if not ready.get("ready"):
            raise XingBridgeError(str(ready.get("error") or "xingAPI DLL worker 시작 실패"))

    def _read(self) -> dict[str, Any]:
        if self.process is None or self.process.stdout is None:
            raise XingBridgeError("xingAPI DLL worker가 시작되지 않았습니다.")
        line = self.process.stdout.readline()
        if not line:
            detail = self.process.stderr.read().strip() if self.process.stderr else ""
            raise XingBridgeError(detail or "xingAPI DLL worker가 응답 없이 종료되었습니다.")
        response = json.loads(line)
        if not response.get("ok", False):
            raise XingBridgeError(str(response.get("error") or "xingAPI DLL worker 오류"))
        return response

    def raw_tr(self, tr: str, values: dict[str, str]) -> dict[str, Any]:
        self.connect()
        assert self.process and self.process.stdin
        self.process.stdin.write(json.dumps(
            {"operation": "raw_tr", "tr": tr, "values": {k: str(v) for k, v in values.items()}},
            ensure_ascii=False,
        ) + "\n")
        self.process.stdin.flush()
        return self._read()["result"]

    def close(self) -> None:
        p, self.process = self.process, None
        if p is None:
            return
        try:
            if p.poll() is None and p.stdin:
                p.stdin.write('{"operation":"shutdown"}\n')
                p.stdin.flush()
                p.wait(timeout=3)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()
