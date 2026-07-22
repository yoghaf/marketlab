from __future__ import annotations

import json
import os
import time

from app.services.run_lock import JsonRunLock


def test_old_empty_lock_is_recovered(tmp_path) -> None:
    path = tmp_path / "old-empty.lock"
    path.write_text("", encoding="utf-8")
    old = time.time() - 30
    os.utime(path, (old, old))

    lock = JsonRunLock(path, "test", stale_seconds=3600, malformed_grace_seconds=5)

    assert lock.acquire() is True
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["pid"] == os.getpid()
    lock.release()
    assert not path.exists()


def test_fresh_empty_lock_is_not_removed(tmp_path) -> None:
    path = tmp_path / "fresh-empty.lock"
    path.write_text("", encoding="utf-8")
    lock = JsonRunLock(path, "test", stale_seconds=3600, malformed_grace_seconds=60)

    assert lock.acquire() is False
    assert path.exists()


def test_live_process_lock_is_not_removed(tmp_path) -> None:
    path = tmp_path / "live.lock"
    path.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    lock = JsonRunLock(path, "test", stale_seconds=0)

    assert lock.acquire() is False
    assert path.exists()


def test_release_does_not_remove_another_owner(tmp_path) -> None:
    path = tmp_path / "owner.lock"
    lock = JsonRunLock(path, "test")
    assert lock.acquire() is True
    path.write_text(json.dumps({"pid": os.getpid() + 100000}), encoding="utf-8")

    lock.release()

    assert path.exists()
