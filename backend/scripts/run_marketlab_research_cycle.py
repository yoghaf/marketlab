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
LOCK_STALE_SECONDS = int(os.getenv("MARKETLAB_RESEARCH_LOCK_STALE_SECONDS", "7200"))

CORE_STEPS = [
    ("signal_factory", "run_multitimeframe_signal_factory_v1.py"),
    ("signal_forward_return_logger", "run_signal_forward_return_logger.py"),
    ("v3_shadow_forward_log", "run_v3_shadow_forward_log.py"),
]

OPTIMIZATION_STEPS = [
    ("strategy_optimization_artifacts", "run_strategy_optimization_artifacts.py"),
]

LEGACY_PHASE7_STEPS = [
    ("strategy_arena", "run_strategy_arena_v1_atr_r_all_labels.py"),
    ("phase6_readiness", "run_phase6_readiness_audit.py"),
    ("phase7_forward_test", "run_phase7_forward_test.py"),
]


def main() -> int:
    mode = parse_mode()
    steps = build_steps(mode)
    lock_acquired = acquire_lock()
    if not lock_acquired:
        print_json({"status": "SKIPPED_LOCK_EXISTS", "lock_path": str(LOCK_PATH), "generated_at_utc": iso_utc()})
        return 0

    step_results: list[dict[str, Any]] = []
    try:
        for name, script_name in steps:
            result = run_step(name, script_name)
            step_results.append(result)
            if result["returncode"] != 0:
                print_json(
                    {
                        "status": "FAILED",
                        "mode": mode,
                        "legacy_phase7_enabled": legacy_phase7_enabled(),
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
                "mode": mode,
                "legacy_phase7_enabled": legacy_phase7_enabled(),
                "steps": step_results,
                "summary": research_summary(),
                "generated_at_utc": iso_utc(),
            }
        )
        return 0
    finally:
        release_lock()


def build_steps(mode: str) -> list[tuple[str, str]]:
    steps = list(CORE_STEPS)
    if mode == "full":
        steps.extend(OPTIMIZATION_STEPS)
        if legacy_phase7_enabled():
            steps.extend(LEGACY_PHASE7_STEPS)
    elif legacy_phase7_enabled() and os.getenv("MARKETLAB_LEGACY_PHASE7_IN_LIGHT", "0").strip() == "1":
        steps.extend(LEGACY_PHASE7_STEPS)
    return steps


def legacy_phase7_enabled() -> bool:
    return os.getenv("MARKETLAB_ENABLE_LEGACY_PHASE7", "0").strip().lower() in {"1", "true", "yes", "on"}


def parse_mode() -> str:
    if "--mode" in sys.argv:
        index = sys.argv.index("--mode")
        try:
            mode = sys.argv[index + 1].strip().lower()
        except IndexError:
            raise SystemExit("--mode requires 'light' or 'full'")
        del sys.argv[index : index + 2]
    else:
        mode = os.getenv("MARKETLAB_RESEARCH_CYCLE_MODE", "full").strip().lower()
    if mode not in {"light", "full"}:
        raise SystemExit("--mode must be 'light' or 'full'")
    return mode


def acquire_lock() -> bool:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        if not remove_stale_lock(LOCK_PATH, LOCK_STALE_SECONDS):
            return False
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


def remove_stale_lock(path: Path, stale_seconds: int) -> bool:
    payload = read_json(path)
    pid = parse_pid(payload.get("pid"))
    if pid is not None and process_exists(pid):
        return False
    age_seconds = max(0.0, datetime.now(UTC).timestamp() - path.stat().st_mtime)
    if pid is not None:
        reason = f"pid {pid} is not running"
    elif age_seconds >= stale_seconds:
        reason = f"age {age_seconds:.0f}s exceeds {stale_seconds}s"
    else:
        return False
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    print(f"[marketlab-research-cycle] removed stale lock {path}: {reason}", flush=True)
    return True


def parse_pid(value: Any) -> int | None:
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


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
    v3_forward = read_json(ARTIFACT_DIR / "v3_shadow_forward" / "v1" / "summary.json")
    v3_summary = v3_forward.get("summary") or {}
    v3_lane = (v3_summary.get("v3_shadow_signal") or {}).get("performance") or {}
    return {
        "core_loop_profile": "lean",
        "legacy_phase7_enabled": legacy_phase7_enabled(),
        "legacy_phase7_note": (
            "Legacy Strategy Arena/Phase 6/Phase 7 runs are manual unless MARKETLAB_ENABLE_LEGACY_PHASE7=1."
            if not legacy_phase7_enabled()
            else "Legacy Strategy Arena/Phase 6/Phase 7 runs are enabled by environment flag."
        ),
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
        "v3_shadow_signals": v3_summary.get("v3_shadow_signal_count", 0),
        "v3_shadow_total_r": v3_lane.get("total_r_closed"),
        "v3_shadow_read": v3_summary.get("read"),
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
