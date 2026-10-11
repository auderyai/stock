from pathlib import Path

root = Path(__file__).resolve().parents[1]
git_tools = root / "tools" / "git"

required = [
    root / ".gitignore",
    root / "scripts" / "git_manager.py",
    git_tools / "GIT_SETUP_NEW_STOCK.cmd",
    git_tools / "GIT_STATUS.cmd",
    git_tools / "GIT_CHECKPOINT.cmd",
    git_tools / "GIT_COMMIT.cmd",
    git_tools / "GIT_LOG.cmd",
    git_tools / "GIT_REMOTE_SET.cmd",
    git_tools / "GIT_PUSH.cmd",
]

missing = [str(p.relative_to(root)) for p in required if not p.exists()]
if missing:
    raise SystemExit("Missing Git workflow files: " + ", ".join(missing))

ignore = (root / ".gitignore").read_text(encoding="utf-8")
for token in (".venv/", ".env", "*.db", "*.sqlite"):
    if token not in ignore:
        raise SystemExit(f".gitignore missing: {token}")

# Installed new_stock must preserve the real repository and keep Git helpers
# out of the root directory according to the project storage policy.
if not (root / ".git").exists():
    raise SystemExit(".git repository directory is missing")

legacy_root_tools = [
    root / "GIT_SETUP_NEW_STOCK.cmd",
    root / "GIT_STATUS.cmd",
    root / "GIT_CHECKPOINT.cmd",
    root / "GIT_COMMIT.cmd",
    root / "GIT_LOG.cmd",
    root / "GIT_REMOTE_SET.cmd",
    root / "GIT_PUSH.cmd",
]
legacy_present = [str(p.name) for p in legacy_root_tools if p.exists()]
if legacy_present:
    raise SystemExit(
        "Git helper files must be stored under tools/git, not project root: "
        + ", ".join(legacy_present)
    )

print("V10_GIT_WORKFLOW_CHECK: PASS")
