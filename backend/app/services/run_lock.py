import json
import os
import time
from pathlib import Path

from app.services.utils import utcnow


class JsonRunLock:
    def __init__(self, path: Path, name: str, stale_seconds: int = 3600) -> None:
        self.path = path
        self.name = name
        self.stale_seconds = stale_seconds

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if not self._remove_stale_lock():
                return False
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                return False
        os.write(fd, json.dumps({"pid": os.getpid(), "acquired_at": utcnow().isoformat()}).encode("utf-8"))
        os.close(fd)
        return True

    def release(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def _remove_stale_lock(self) -> bool:
        pid = self._lock_pid()
        age_seconds = max(0.0, time.time() - self.path.stat().st_mtime)
        if pid is not None and self._process_exists(pid):
            return False
        if pid is not None:
            reason = f"pid {pid} is not running"
        elif age_seconds >= self.stale_seconds:
            reason = f"age {age_seconds:.0f}s exceeds {self.stale_seconds}s"
        else:
            return False
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        print(f"{utcnow().isoformat()} {self.name} removed stale lock at {self.path}: {reason}")
        return True

    def _lock_pid(self) -> int | None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        try:
            pid = int(payload.get("pid"))
        except (TypeError, ValueError):
            return None
        return pid if pid > 0 else None

    @staticmethod
    def _process_exists(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
