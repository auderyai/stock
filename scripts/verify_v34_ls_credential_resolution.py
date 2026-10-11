from __future__ import annotations

from pathlib import Path
from krx_research.collectors.ls_credentials import LSCredentialResolver


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    target = root / "src" / "krx_research" / "collectors" / "ls_openapi.py"
    text = target.read_text(encoding="utf-8")
    assert "V34_LS_CREDENTIAL_ALIAS_OVERRIDE" in text
    assert "load_ls_credentials" in text

    resolver = LSCredentialResolver(root)
    key, secret = resolver.load()
    assert key and secret

    print("V34_LS_CREDENTIAL_RESOLUTION_CHECK: PASS")
    print("LS credentials: FOUND (values hidden)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
