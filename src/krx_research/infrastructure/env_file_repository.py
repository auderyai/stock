from __future__ import annotations

import os
from pathlib import Path


class EnvFileRepository:
    """Preserve unrelated .env entries and atomically update selected keys."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()

    def save(self, values: dict[str, str]) -> None:
        lines = self.path.read_text(encoding="utf-8-sig").splitlines() if self.path.is_file() else []
        if any(any(c in str(value) for c in "\r\n\0") for value in values.values()):
            raise ValueError("환경 값에는 줄바꿈 또는 NUL을 넣을 수 없습니다.")
        pending, output = dict(values), []
        for line in lines:
            key = line.split("=", 1)[0].strip() if "=" in line else ""
            if key in values:
                output.append(f"{key}={values[key]}")
                pending.pop(key, None)
            else:
                output.append(line)
        if output and output[-1]: output.append("")
        output.extend(f"{key}={value}" for key, value in pending.items())
        temporary = self.path.with_name(f"{self.path.name}.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                if os.name == "nt":
                    self._restrict_access(temporary)
                stream.write("\n".join(output).rstrip() + "\n")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _restrict_access(path: Path) -> None:
        import ntsecuritycon
        import win32api
        import win32con
        import win32security

        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        try:
            user = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        finally:
            token.Close()
        acl = win32security.ACL()
        for sid in (user, win32security.ConvertStringSidToSid("S-1-5-18")):
            acl.AddAccessAllowedAce(win32security.ACL_REVISION, ntsecuritycon.FILE_ALL_ACCESS, sid)
        win32security.SetNamedSecurityInfo(
            str(path), win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
            None, None, acl, None,
        )
