import asyncio
from datetime import datetime, timedelta

from app.core.config import settings
from app.services.utils import utcnow


class RateLimitManager:
    def __init__(self) -> None:
        self.pause_until: datetime | None = None
        self.last_used_weight_1m: int | None = None
        self._lock = asyncio.Lock()

    async def before_request(self) -> None:
        async with self._lock:
            if self.pause_until and utcnow() < self.pause_until:
                await asyncio.sleep((self.pause_until - utcnow()).total_seconds())
            if (
                self.last_used_weight_1m is not None
                and self.last_used_weight_1m >= settings.binance_safe_used_weight_per_minute
            ):
                await asyncio.sleep(1.0)

    def record_used_weight(self, used_weight: int | None) -> None:
        if used_weight is not None:
            self.last_used_weight_1m = used_weight

    def pause_for_seconds(self, seconds: int) -> None:
        self.pause_until = utcnow() + timedelta(seconds=max(seconds, 1))
