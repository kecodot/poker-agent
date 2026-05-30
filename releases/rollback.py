"""Rollback system — restore any prior release immediately.

Usage:
    python3 releases/rollback.py baseline_v1
    python3 releases/rollback.py adaptive_router_v2
    python3 releases/rollback.py continuous_mixer_v3
    python3 releases/rollback.py --list
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RELEASES_DIR = PROJECT_ROOT / "releases"

RELEASES = {
    "baseline_v1": {
        "tag": "arena-baseline-v1",
        "commit": "4158d71",
        "description": "Single-strategy Monte Carlo equity agent",
        "bb_per_100": 152.61,
        "config_version": "v1",
    },
    "adaptive_router_v2": {
        "tag": "arena-adaptive-v2",
        "commit": "8d069c7",
        "description": "Multi-strategy pool classification + adaptive routing",
        "bb_per_100": 176.78,
        "config_version": "v1",
    },
    "continuous_mixer_v3": {
        "tag": "arena-mixer-v3",
        "commit": "d128e2f",
        "description": "Continuous strategy blending with EMA smoothing (CURRENT)",
        "bb_per_100": 176.78,
        "config_version": "v1",
    },
}

ROLLBACK_LOG = PROJECT_ROOT / "logs" / "rollbacks.jsonl"


def _log_rollback(from_version: str, to_version: str, success: bool, error: Optional[str] = None) -> None:
    """Record rollback event to persistent log."""
    ROLLBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "from": from_version,
        "to": to_version,
        "success": success,
    }
    if error:
        entry["error"] = error
    with open(ROLLBACK_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _current_version() -> str:
    """Detect current release version from git HEAD."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT),
        )
        commit = result.stdout.strip()
        for rel_id, info in RELEASES.items():
            if info["commit"].startswith(commit) or commit.startswith(info["commit"]):
                return rel_id
        return f"unknown ({commit})"
    except Exception:
        return "unknown (no git)"


def _git_checkout(tag_or_commit: str) -> bool:
    """Check out a git ref. Returns True on success."""
    try:
        subprocess.run(
            ["git", "checkout", tag_or_commit],
            check=True, capture_output=True, text=True, cwd=str(PROJECT_ROOT),
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"[rollback] git checkout failed: {e.stderr.strip()}", file=sys.stderr)
        return False


def _restore_config(release_id: str) -> bool:
    """Restore config snapshot from release directory."""
    config_src = RELEASES_DIR / release_id / "strategy-config.json"
    config_dst = PROJECT_ROOT / "config" / "strategy-config.json"
    if not config_src.exists():
        print(f"[rollback] No config snapshot found for {release_id}, skipping config restore",
              file=sys.stderr)
        return True
    try:
        shutil.copy2(str(config_src), str(config_dst))
        print(f"[rollback] Restored config from {release_id} snapshot")
        return True
    except OSError as e:
        print(f"[rollback] Config restore failed: {e}", file=sys.stderr)
        return False


def rollback_to_release(release_id: str) -> bool:
    """Rollback to a prior release immediately.

    Performs:
      1. Inventory current state
      2. Git checkout to the release tag/commit
      3. Restore config snapshot
      4. Log the rollback event

    Returns True on success, False on failure.
    """
    if release_id not in RELEASES:
        print(f"[rollback] Unknown release: {release_id!r}", file=sys.stderr)
        print(f"[rollback] Available: {list(RELEASES.keys())}", file=sys.stderr)
        return False

    info = RELEASES[release_id]
    current = _current_version()

    print(f"[rollback] Rolling back from {current} → {release_id}")
    print(f"[rollback] Target: {info['description']}")
    print(f"[rollback] Tag: {info['tag']}, Commit: {info['commit']}")

    # Check for uncommitted changes
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT),
        )
        if result.stdout.strip():
            print("[rollback] WARNING: Uncommitted changes detected. "
                  "These will be preserved in working tree.", file=sys.stderr)
    except Exception:
        pass

    # Execute rollback
    success = _git_checkout(info["tag"])
    if success:
        _restore_config(release_id)

    _log_rollback(current, release_id, success)
    if success:
        print(f"[rollback] Successfully rolled back to {release_id}")
    return success


def list_releases() -> None:
    """Print all available releases."""
    current = _current_version()
    print(f"{'Release ID':<25} {'Tag':<25} {'BB/100':<10} Status")
    print("-" * 80)
    for rel_id, info in RELEASES.items():
        status = "← CURRENT" if rel_id == current else ""
        print(f"{rel_id:<25} {info['tag']:<25} +{info['bb_per_100']:<9.2f} {status}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("--list", "-l"):
        list_releases()
    elif sys.argv[1] in ("--help", "-h"):
        print(__doc__)
    else:
        release_id = sys.argv[1]
        if not rollback_to_release(release_id):
            sys.exit(1)
