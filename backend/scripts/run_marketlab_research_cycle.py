from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
ARTIFACT_DIR = BACKEND_DIR / "artifacts"
LOCK_PATH = REPO_ROOT / "data" / "marketlab_research_cycle.lock"

STEPS = [
    ("signal_factory", "run_multitimeframe_signal_factory_v1.py"),
    ("strategy_arena", "run_strategy_arena_v1_atr_r_all_labels.py"),
    ("phase6_readiness", "run_phase6_readiness_audit.py"),
    ("phase7_forward_test", "run_phase7_forward_test.py"),
    ("signal_forward_return_logger", "run_signal_forward_return_logger.py"),
]


def main() -> int:
    lock_acquired = acquire_lock()
    if not lock_acquired:
        print_json({"status": "SKIPPED_LOCK_EXISTS", "lock_path": str(LOCK_PATH), "generated_at_utc": iso_utc()})
        return 0

    step_results: list[dict[str, Any]] = []
    try:
        for name, script_name in STEPS:
            result = run_step(name, script_name)
            step_results.append(result)
            if result["returncode"] != 0:
                print_json(
                    {
                        "status": "FAILED",
                        "failed_step": name,
                        "steps": step_results,
                        "summary": research_summary(),
                        "generated_at_utc": iso_utc(),
                    }
                )
                return result["returncode"] or 1

        print_json(
            {
                "status": "SUCCESS",
                "steps": step_results,
                "summary": research_summary(),
                "generated_at_utc": iso_utc(),
            }
        )
        return 0
    finally:
        release_lock()


def acquire_lock() -> bool:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"pid": os.getpid(), "started_at_utc": iso_utc()}))
    return True


def release_lock() -> None:
    try:
        LOCK_PATH.unlink()
    except FileNotFoundError:
        pass


def run_step(name: str, script_name: str) -> dict[str, Any]:
    started = datetime.now(UTC)
    script_path = BACKEND_DIR / "scripts" / script_name
    print(f"[marketlab-research-cycle] step start {name} {iso_utc(started)}", flush=True)
    completed = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(BACKEND_DIR),
        text=True,
        capture_output=True,
    )
    ended = datetime.now(UTC)
    if completed.stdout:
        print(completed.stdout.rstrip(), flush=True)
    if completed.stderr:
        print(completed.stderr.rstrip(), file=sys.stderr, flush=True)
    print(f"[marketlab-research-cycle] step end {name} returncode={completed.returncode} {iso_utc(ended)}", flush=True)
    return {
        "name": name,
        "script": script_name,
        "returncode": completed.returncode,
        "started_at_utc": iso_utc(started),
        "ended_at_utc": iso_utc(ended),
        "duration_seconds": round((ended - started).total_seconds(), 3),
    }


def research_summary() -> dict[str, Any]:
    signal_summary = read_json(ARTIFACT_DIR / "signal_factory" / "v1" / "summary.json")
    phase6_decision = read_json(ARTIFACT_DIR / "phase6" / "phase7_candidate_decision.json")
    phase7_status = read_json(ARTIFACT_DIR / "phase7" / "forward_test_status.json")
    phase7_summary = read_json(ARTIFACT_DIR / "phase7" / "forward_test_summary.json")
    return {
        "signal_candidates": (signal_summary.get("candidate_status_counts") or {}).get("SIGNAL_CANDIDATE", 0),
        "phase6_approved": len(phase6_decision.get("approved_candidates") or []),
        "approved_shadow_events": phase7_status.get("approved_shadow_event_count", 0),
        "lab_shadow_events": phase7_status.get("lab_shadow_event_count", 0),
        "active_events": phase7_status.get("active_event_count", 0),
        "completed_events": phase7_status.get("completed_event_count", 0),
        "tp": phase7_summary.get("tp_hit", 0),
        "sl": phase7_summary.get("sl_hit", 0),
        "expired": phase7_summary.get("expired", 0),
        "avg_R": phase7_summary.get("avg_R") or phase7_summary.get("average_realized_R"),
        "phase7_mode": phase7_status.get("mode"),
        "last_run_at_utc": phase7_status.get("last_run_at_utc") or phase7_status.get("generated_at_utc"),
    }


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def iso_utc(value: datetime | None = None) -> str:
    return (value or datetime.now(UTC)).isoformat().replace("+00:00", "Z")


def print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
