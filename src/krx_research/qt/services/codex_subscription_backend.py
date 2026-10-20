from __future__ import annotations

import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from krx_research.research_archive.parsers import find_codex_executable


class CodexSubscriptionBackend:
    """Structured planner using the signed-in Codex subscription in isolation."""

    _SCHEMA = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": [
                "describe_database", "query_database", "search_stock_files",
                "search_research_archive", "run_one_off_python", "list_reusable_python",
                "run_one_off_query_python",
                "run_reusable_python", "run_numbered_screen", "get_last_screen_result",
                "search_similar_patterns", "request_chart", "finish",
            ]},
            "arguments": {"type": "string", "description": "선택한 도구 인수의 JSON 객체 문자열"},
            "answer": {"type": "string"},
            "citations": {"type": "array", "items": {"type": "object", "properties": {
                "title": {"type": "string"}, "url": {"type": "string"},
            }, "required": ["title", "url"], "additionalProperties": False}},
        },
        "required": ["action", "arguments", "answer", "citations"],
        "additionalProperties": False,
    }

    def __init__(self, root: Path, *, timeout: int = 180):
        self.root, self.timeout = Path(root).resolve(), int(timeout)
        self.work = self.root / "assistant_workspace" / "codex_subscription"
        self.work.mkdir(parents=True, exist_ok=True)
        self.schema = self.work / "assistant_action.schema.json"
        self.schema.write_text(json.dumps(self._SCHEMA, ensure_ascii=False), encoding="utf-8")

    def step(self, prompt: str) -> dict:
        executable = find_codex_executable()
        if not executable:
            raise RuntimeError("로그인된 Codex 실행 파일을 찾지 못했습니다. Codex 앱 설치 상태를 확인하십시오.")
        with TemporaryDirectory(dir=self.work) as directory:
            output = Path(directory) / "response.json"
            command = [
                executable, "exec", "--ephemeral", "--ignore-user-config", "--ignore-rules",
                "-c", 'model_reasoning_effort="low"', "--skip-git-repo-check",
                "--sandbox", "read-only", "--color", "never", "-C", directory,
                "--output-schema", str(self.schema), "--output-last-message", str(output), "-",
            ]
            try:
                completed = subprocess.run(command, input=prompt, capture_output=True, text=True,
                                           encoding="utf-8", errors="replace", timeout=self.timeout)
            except subprocess.TimeoutExpired as error:
                raise RuntimeError("Codex 구독 분석 제한시간을 초과했습니다.") from error
            if completed.returncode or not output.is_file():
                detail = " ".join((completed.stderr or completed.stdout).splitlines())[-1000:]
                raise RuntimeError(f"Codex 구독 분석에 실패했습니다. {detail or '실행 상태를 확인하십시오.'}")
            try:
                return json.loads(output.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                raise RuntimeError("Codex 구독 분석 결과를 해석하지 못했습니다.") from error
