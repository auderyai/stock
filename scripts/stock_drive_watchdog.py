from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")
WORKFLOW = "stock-daily-google-drive.yml"


@dataclass(frozen=True)
class WorkflowRun:
    run_id: int
    created_at: datetime
    status: str
    conclusion: str | None
    url: str


class WatchdogPolicy:
    """Make one bounded recovery decision without touching completed work."""

    @staticmethod
    def target_day(now: datetime) -> date:
        local = now.astimezone(KST)
        return local.date() if local.time() >= time(20, 10) else local.date() - timedelta(days=1)

    @staticmethod
    def decide(runs: list[WorkflowRun], code_failure: bool = False) -> str:
        active = {"queued", "in_progress", "waiting", "requested", "pending"}
        if any(run.status in active for run in runs):
            return "wait"
        if any(run.conclusion == "success" for run in runs):
            return "complete"
        if not runs:
            return "dispatch"
        if code_failure:
            return "codex-repair"
        return "retry" if len(runs) == 1 else "exhausted"


class GitHubActionsClient:
    def __init__(self, repository: str, token: str) -> None:
        if not repository or not token:
            raise RuntimeError("GITHUB_REPOSITORY와 GITHUB_TOKEN이 필요합니다.")
        self.repository, self.token = repository, token
        self.base = f"https://api.github.com/repos/{repository}"

    def _request(self, method: str, path: str, body: dict | None = None):
        payload = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(
            f"{self.base}/{path}",
            data=payload,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "stock-drive-watchdog",
            },
        )
        with urlopen(request, timeout=30) as response:
            content = response.read()
        return None if not content else json.loads(content)

    def runs_since(self, cutoff: datetime) -> list[WorkflowRun]:
        data = self._request("GET", f"actions/workflows/{WORKFLOW}/runs?per_page=50")
        rows = []
        for item in data.get("workflow_runs", []):
            created = datetime.fromisoformat(str(item["created_at"]).replace("Z", "+00:00"))
            if created >= cutoff and item.get("head_branch") == "main":
                rows.append(
                    WorkflowRun(
                        int(item["id"]),
                        created,
                        str(item["status"]),
                        item.get("conclusion"),
                        str(item["html_url"]),
                    )
                )
        return sorted(rows, key=lambda row: row.created_at, reverse=True)

    def has_code_failure(self, run_id: int) -> bool:
        data = self._request("GET", f"actions/runs/{run_id}/artifacts?per_page=100")
        expected = f"stock-drive-code-failure-context-{run_id}"
        return any(item.get("name") == expected for item in data.get("artifacts", []))

    def dispatch(self, target: date) -> None:
        self._request(
            "POST",
            f"actions/workflows/{WORKFLOW}/dispatches",
            {"ref": "main", "inputs": {"target_date": target.isoformat(), "stage": "menu5"}},
        )

    def report_exhausted(self, target: date, runs: list[WorkflowRun]) -> None:
        title = f"Stock Drive 자동 재개 한도 도달: {target.isoformat()}"
        issues = self._request("GET", "issues?state=open&per_page=100")
        if any(item.get("title") == title for item in issues):
            return
        links = "\n".join(f"- {run.url}" for run in runs)
        body = (
            "클라우드 감시자가 예약 실행과 저장 지점 재개를 확인했지만 제한된 재시도 후에도 "
            "완료되지 않았습니다. 완료 데이터와 체크포인트는 보존했으며 추가 자동 실행은 "
            f"중단했습니다.\n\n{links}"
        )
        self._request("POST", "issues", {"title": title, "body": body})


def run(client: GitHubActionsClient, target: date) -> str:
    if target.weekday() >= 5:
        return "weekend"
    cutoff = datetime.combine(target, time(20), KST).astimezone(timezone.utc)
    runs = client.runs_since(cutoff)
    code_failure = bool(
        runs and runs[0].conclusion == "failure" and client.has_code_failure(runs[0].run_id)
    )
    decision = WatchdogPolicy.decide(runs, code_failure)
    if decision in {"dispatch", "retry"}:
        client.dispatch(target)
    elif decision == "exhausted":
        client.report_exhausted(target, runs)
    return decision


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stock Drive 클라우드 예약·복구 감시자")
    parser.add_argument("--date", type=date.fromisoformat)
    args = parser.parse_args(argv)
    target = args.date or WatchdogPolicy.target_day(datetime.now(KST))
    client = GitHubActionsClient(
        os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GITHUB_TOKEN", "")
    )
    decision = run(client, target)
    print(json.dumps({"target_date": target.isoformat(), "decision": decision}, ensure_ascii=False))
    return 1 if decision == "exhausted" else 0


if __name__ == "__main__":
    raise SystemExit(main())
