import json
import os
import time
from pathlib import Path

from app.services.utils import utcnow


class JsonRunLock:
    def __init__(
        self,
        path: Path,
        name: str,
        stale_seconds: int = 3600,
        malformed_grace_seconds: int = 5,
    ) -> None:
        self.path = path
        self.name = name
        self.stale_seconds = stale_seconds
        self.malformed_grace_seconds = malformed_grace_seconds
        self.owner_pid = os.getpid()
        self.acquired = False

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
        payload = json.dumps({"pid": self.owner_pid, "acquired_at": utcnow().isoformat()}).encode("utf-8")
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        self.acquired = True
        return True

    def release(self) -> None:
        if not self.acquired:
            return
        if self._lock_pid() not in {None, self.owner_pid}:
            self.acquired = False
            return
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        finally:
            self.acquired = False

    def _remove_stale_lock(self) -> bool:
        pid = self._lock_pid()
        try:
            age_seconds = max(0.0, time.time() - self.path.stat().st_mtime)
        except FileNotFoundError:
            return True
        if pid is not None and self._process_exists(pid):
            return False
        if pid is not None:
            reason = f"pid {pid} is not running"
        elif age_seconds >= self.malformed_grace_seconds:
            reason = f"malformed lock is older than {self.malformed_grace_seconds}s"
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
        if os.name == "nt":
            return _windows_process_exists(pid)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True


def _windows_process_exists(pid: int) -> bool:
    import ctypes

    process_query_limited_information = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_int
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if handle:
        kernel32.CloseHandle(handle)
        return True
    return ctypes.get_last_error() == 5
