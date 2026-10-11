from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CodeExecution:
    run_id: str
    code_hash: str
    created_at: str
    result: object
    origin: str


class OneOffWorkspace:
    """Runs calculation-only AI code outside the application import tree."""

    _FORBIDDEN = {
        "open", "compile", "eval", "exec", "globals", "locals", "getattr", "setattr",
        "delattr", "__import__", "breakpoint", "help", "input", "memoryview",
        "vars", "dir", "exit", "quit",
    }

    def __init__(self, root: Path, *, timeout_seconds: int = 20):
        self.root, self.timeout_seconds = Path(root), int(timeout_seconds)

    def execute(self, code: str, input_data) -> object:
        return self.execute_record(code, input_data).result

    def execute_record(self, code: str, input_data, *, origin: str = "one_off") -> CodeExecution:
        code = str(code).rstrip()
        self._validate(code)
        created_at, run_id = datetime.now().astimezone().isoformat(timespec="seconds"), uuid.uuid4().hex[:12]
        digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
        job = self.root / "runs" / created_at[:10].replace("-", "") / run_id
        job.mkdir(parents=True, exist_ok=False)
        (job / "code.py").write_text(code.rstrip() + "\n", encoding="utf-8")
        (job / "input.json").write_text(
            json.dumps(input_data, ensure_ascii=False, default=str), encoding="utf-8"
        )
        self._write_json(job / "metadata.json", {
            "run_id": run_id, "created_at": created_at, "code_hash": digest,
            "origin": origin, "status": "running",
        })
        wrapper = (
            "import json\n"
            "with open('input.json',encoding='utf-8') as f: input_data=json.load(f)\n"
            f"{code.rstrip()}\n"
            "print(json.dumps(result,ensure_ascii=False,default=str))\n"
        )
        script = job / "job.py"
        script.write_text(wrapper, encoding="utf-8")
        env = {
            key: os.environ[key]
            for key in ("SystemRoot", "WINDIR", "TEMP", "TMP")
            if key in os.environ
        }
        try:
            completed = subprocess.run(
                [sys.executable, "-I", str(script)], cwd=job, env=env, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            self._write_json(job / "metadata.json", {
                "run_id": run_id, "created_at": created_at, "code_hash": digest,
                "origin": origin, "status": "failed", "failure": "timeout",
            })
            raise RuntimeError("1회용 계산 코드가 제한시간을 초과했습니다.") from error
        (job / "stderr.log").write_text(completed.stderr, encoding="utf-8")
        if completed.returncode:
            self._write_json(job / "metadata.json", {
                "run_id": run_id, "created_at": created_at, "code_hash": digest,
                "origin": origin, "status": "failed", "failure": "nonzero_exit",
            })
            raise RuntimeError(f"1회용 계산 코드 실패: {completed.stderr[-1000:]}")
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            self._write_json(job / "metadata.json", {
                "run_id": run_id, "created_at": created_at, "code_hash": digest,
                "origin": origin, "status": "failed", "failure": "invalid_json_result",
            })
            raise RuntimeError("1회용 코드는 JSON 결과를 반환해야 합니다.") from exc
        self._write_json(job / "result.json", result)
        self._write_json(job / "metadata.json", {
            "run_id": run_id, "created_at": created_at, "code_hash": digest,
            "origin": origin, "status": "completed",
        })
        return CodeExecution(run_id, digest, created_at, result, origin)

    def list_runs(self) -> list[dict]:
        rows = []
        for path in (self.root / "runs").glob("*/*/metadata.json"):
            try: rows.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError): continue
        return sorted(rows, key=lambda row: row.get("created_at", ""), reverse=True)

    def load_code(self, run_id: str) -> str:
        folder = self._run_folder(run_id); code = (folder / "code.py").read_text(encoding="utf-8")
        metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        if hashlib.sha256(code.rstrip().encode("utf-8")).hexdigest() != metadata.get("code_hash"):
            raise RuntimeError("1회용 코드 원본의 무결성 검증에 실패했습니다.")
        return code

    def run_metadata(self, run_id: str) -> dict:
        return json.loads((self._run_folder(run_id) / "metadata.json").read_text(encoding="utf-8"))

    def _run_folder(self, run_id: str) -> Path:
        if not _is_hex(run_id, 12): raise ValueError("실행 ID 형식이 잘못되었습니다.")
        matches = list((self.root / "runs").glob(f"*/{run_id}"))
        if len(matches) != 1: raise FileNotFoundError(f"1회용 코드 실행 이력을 찾지 못했습니다: {run_id}")
        return matches[0]

    @staticmethod
    def _write_json(path: Path, value) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    @classmethod
    def _validate(cls, code: str) -> None:
        if len(code) > 12_000:
            raise ValueError("1회용 코드가 허용 길이를 초과했습니다.")
        tree = ast.parse(code, mode="exec")
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)):
                raise ValueError("1회용 계산 코드에서는 import와 전역 상태를 허용하지 않습니다.")
            if isinstance(node, ast.Name) and node.id in cls._FORBIDDEN:
                raise ValueError(f"허용하지 않는 함수입니다: {node.id}")
            if isinstance(node, ast.Name) and node.id.startswith("_"):
                raise ValueError("내부 이름 접근은 허용하지 않습니다.")
            if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
                raise ValueError("내부 속성 접근은 허용하지 않습니다.")
        if not any(isinstance(node, (ast.Assign, ast.AnnAssign)) and any(
            isinstance(target, ast.Name) and target.id == "result"
            for target in ([node.target] if isinstance(node, ast.AnnAssign) else node.targets)
        ) for node in ast.walk(tree)):
            raise ValueError("1회용 코드는 result 변수에 JSON 호환 결과를 저장해야 합니다.")


def _is_hex(value: str, length: int) -> bool:
    return len(str(value)) == length and all(character in "0123456789abcdef" for character in str(value).lower())


class ReusableCodeLibrary:
    """Immutable, human-approved versions of calculation-only one-off code."""

    def __init__(self, workspace: OneOffWorkspace):
        self.workspace, self.root = workspace, workspace.root / "library"

    def register(self, run_id: str, name: str, description: str, *, code: str | None = None) -> dict:
        title, note = str(name).strip(), str(description).strip()
        if not title or len(title) > 80: raise ValueError("등록 이름은 1~80자로 입력하십시오.")
        if len(note) > 500: raise ValueError("설명은 500자 이하여야 합니다.")
        if self.workspace.run_metadata(run_id).get("status") != "completed":
            raise ValueError("성공적으로 완료된 1회용 코드만 정식 등록할 수 있습니다.")
        source = (code if code is not None else self.workspace.load_code(run_id)).rstrip()
        self.workspace._validate(source)
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        library_id, version = hashlib.sha256(title.encode("utf-8")).hexdigest()[:16], digest[:12]
        folder, now = self.root / library_id, datetime.now().astimezone().isoformat(timespec="seconds")
        folder.mkdir(parents=True, exist_ok=True)
        code_path = folder / f"{version}.py"
        stored = source.rstrip() + "\n"
        if code_path.exists() and hashlib.sha256(code_path.read_text(encoding="utf-8").rstrip().encode("utf-8")).hexdigest() != digest:
            raise RuntimeError("기존 등록 코드의 무결성 검증에 실패했습니다.")
        if not code_path.exists(): code_path.write_text(stored, encoding="utf-8")
        manifest_path = folder / "manifest.json"
        manifest = self._read(manifest_path, {"library_id": library_id, "name": title, "versions": []})
        if not any(item["version"] == version for item in manifest["versions"]):
            manifest["versions"].append({"version": version, "code_hash": digest, "source_run_id": run_id,
                                         "registered_at": now, "description": note,
                                         "use_count": 0, "last_used_at": None})
        manifest.update({"name": title, "description": note, "active_version": version})
        self.workspace._write_json(manifest_path, manifest)
        return self._summary(manifest)

    def list(self) -> list[dict]:
        rows = [self._summary(self._read(path, {})) for path in self.root.glob("*/manifest.json")]
        return sorted((row for row in rows if row.get("library_id")), key=lambda row: row["name"])

    def execute(self, library_id: str, input_data) -> CodeExecution:
        if not _is_hex(library_id, 16): raise ValueError("등록 코드 ID 형식이 잘못되었습니다.")
        manifest_path = self.root / str(library_id) / "manifest.json"
        manifest = self._read(manifest_path, None)
        if not manifest: raise FileNotFoundError("등록 코드를 찾지 못했습니다.")
        version = manifest["active_version"]
        code = (manifest_path.parent / f"{version}.py").read_text(encoding="utf-8")
        item = next((entry for entry in manifest["versions"] if entry["version"] == version), None)
        if not item or hashlib.sha256(code.rstrip().encode("utf-8")).hexdigest() != item.get("code_hash"):
            raise RuntimeError("등록 코드의 무결성 검증에 실패했습니다.")
        record = self.workspace.execute_record(code, input_data, origin=f"library:{library_id}:{version}")
        item["use_count"], item["last_used_at"] = int(item.get("use_count", 0)) + 1, record.created_at
        self.workspace._write_json(manifest_path, manifest)
        return record

    def code(self, library_id: str) -> str:
        if not _is_hex(library_id, 16): raise ValueError("등록 코드 ID 형식이 잘못되었습니다.")
        manifest = self._read(self.root / str(library_id) / "manifest.json", None)
        if not manifest: raise FileNotFoundError("등록 코드를 찾지 못했습니다.")
        code = (self.root / str(library_id) / f"{manifest['active_version']}.py").read_text(encoding="utf-8")
        item = next((row for row in manifest["versions"] if row["version"] == manifest["active_version"]), None)
        if not item or hashlib.sha256(code.rstrip().encode("utf-8")).hexdigest() != item.get("code_hash"):
            raise RuntimeError("등록 코드의 무결성 검증에 실패했습니다.")
        return code

    @staticmethod
    def _read(path: Path, default):
        try: return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): return default

    @staticmethod
    def _summary(manifest: dict) -> dict:
        versions, active = manifest.get("versions", []), manifest.get("active_version")
        item = next((row for row in versions if row.get("version") == active), {})
        return {"library_id": manifest.get("library_id"), "name": manifest.get("name"),
                "description": manifest.get("description", ""), "active_version": active,
                "code_hash": item.get("code_hash"), "source_run_id": item.get("source_run_id"),
                "registered_at": item.get("registered_at"), "use_count": item.get("use_count", 0),
                "last_used_at": item.get("last_used_at"), "version_count": len(versions)}
