from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def clean_env() -> None:
    path = ROOT / ".env"
    if not path.is_file():
        return
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    kept = [line for line in lines if not line.strip().startswith("LS_XING_RES_DIR=")]
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")
    tmp.replace(path)

def main() -> int:
    clean_env()
    print("RES_CONFIG_REMOVAL: PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
