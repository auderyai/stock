from __future__ import annotations

import re

_SQL_RE = re.compile(r"\b(select|insert|update|delete|from|where|join|psycopg|sqlstate|relation)\b", re.I)


def user_friendly_error(trace_text: str) -> str:
    """Return a short Korean message without exposing SQL statements/tracebacks."""
    text = str(trace_text)
    lower = text.lower()
    if "password authentication failed" in lower:
        return (
            "PostgreSQL 읽기 계정 인증에 실패했습니다.\n"
            "C:\\stock\\.env의 KRX_DB_READ_USER / KRX_DB_READ_PASSWORD가 "
            "실제 PostgreSQL 계정과 일치하는지 확인하십시오.\n"
            "필요하면 SETUP_DB_READ_CREDENTIALS_ONCE.cmd를 실행해 다시 등록하십시오."
        )
    if "connection refused" in lower or "could not connect" in lower:
        return "PostgreSQL 서버에 연결할 수 없습니다. PostgreSQL 서비스와 127.0.0.1:5432 상태를 확인하십시오."

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    tail = lines[-1] if lines else "알 수 없는 오류가 발생했습니다."
    if _SQL_RE.search(tail) or tail.startswith("Traceback"):
        return "데이터베이스 처리 중 오류가 발생했습니다. 자세한 내용은 C:\\stock\\logs 오류 로그를 확인하십시오."
    if ":" in tail:
        tail = tail.split(":", 1)[1].strip() or tail
    return tail[:500]
