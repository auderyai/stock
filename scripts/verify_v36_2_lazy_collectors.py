from __future__ import annotations
import ast
from pathlib import Path

def main() -> int:
    root = Path(__file__).resolve().parents[1]
    init_path = root / "src" / "krx_research" / "collectors" / "__init__.py"
    text = init_path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    assert "def __getattr__" in text
    assert "_EXPORTS" in text
    assert "from .history_coverage import" not in text
    assert "import pandas" not in text

    public = {
        "fetch_ohlcv", "fetch_index_membership", "normalize_ohlcv",
        "fetch_security_master", "fetch_realtime_krx_quotes"
    }
    namespace = {}
    exec(compile(tree, str(init_path), "exec"), namespace)
    assert public.issubset(set(namespace["__all__"]))

    worker = root / "scripts" / "xing32_worker.py"
    if worker.is_file():
        worker_text = worker.read_text(encoding="utf-8")
        assert "krx_research.collectors.xing.credentials" in worker_text
        assert "import pandas" not in worker_text

    print("V36_2_LAZY_COLLECTORS_CHECK: PASS")
    print("32bit xing worker no longer requires collectors eager pandas import: PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
