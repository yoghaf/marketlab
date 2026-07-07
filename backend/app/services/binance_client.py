import asyncio
import logging
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.market import CollectorError, RateLimitUsage
from app.services.rate_limit import RateLimitManager
from app.services.utils import utcnow

logger = logging.getLogger(__name__)


class BinanceClientError(Exception):
    def __init__(self, message: str, status_code: int | None = None, payload: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class BinanceClient:
    FUTURES_BASE_URL = "https://fapi.binance.com"
    SPOT_BASE_URL = "https://api.binance.com"

    def __init__(
        self,
        db: Session,
        collector_name: str,
        collector_run_id: int | None = None,
        rate_limit_manager: RateLimitManager | None = None,
    ) -> None:
        self.db = db
        self.collector_name = collector_name
        self.collector_run_id = collector_run_id
        self.rate_limit_manager = rate_limit_manager or RateLimitManager()

    async def __aenter__(self) -> "BinanceClient":
        self._client = httpx.AsyncClient(timeout=settings.binance_timeout_seconds)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._client.aclose()

    async def _get(self, market: str, path: str, params: dict[str, Any] | None = None) -> Any:
        base_url = self.FUTURES_BASE_URL if market == "futures" else self.SPOT_BASE_URL
        url = f"{base_url}{path}"
        last_error: BinanceClientError | None = None

        for attempt in range(settings.binance_max_retries + 1):
            await self.rate_limit_manager.before_request()
            try:
                response = await self._client.get(url, params=params)
            except httpx.HTTPError as exc:
                last_error = BinanceClientError(str(exc))
                self._record_error(path, None, type(exc).__name__, str(exc))
                if attempt >= settings.binance_max_retries:
                    raise last_error from exc
                await asyncio.sleep(0.5 * (attempt + 1))
                continue

            used_weight = self._header_int(response, "X-MBX-USED-WEIGHT-1M")
            if used_weight is None:
                used_weight = self._header_int(response, "X-MBX-USED-WEIGHT")
            retry_after = self._header_int(response, "Retry-After")
            self.rate_limit_manager.record_used_weight(used_weight)
            self._record_usage(path, "GET", response.status_code, used_weight, retry_after, response.headers)

            if response.status_code == 418:
                pause = retry_after or 60
                self.rate_limit_manager.pause_for_seconds(pause)
                message = f"Binance REST collector paused after 418 for {pause}s"
                self._record_error(path, 418, "BinanceIpBanned", message, self._safe_json(response))
                raise BinanceClientError(message, 418, self._safe_json(response))

            if response.status_code == 429:
                pause = retry_after or min(2 ** attempt, 30)
                self.rate_limit_manager.pause_for_seconds(pause)
                message = f"Binance rate limit 429, retry after {pause}s"
                self._record_error(path, 429, "BinanceRateLimited", message, self._safe_json(response))
                if attempt >= settings.binance_max_retries:
                    raise BinanceClientError(message, 429, self._safe_json(response))
                await asyncio.sleep(pause)
                continue

            if response.status_code >= 400:
                payload = self._safe_json(response)
                message = f"Binance request failed {response.status_code}: {payload}"
                self._record_error(path, response.status_code, "BinanceHttpError", message, payload)
                raise BinanceClientError(message, response.status_code, payload)

            return response.json()

        raise last_error or BinanceClientError(f"Binance request failed after retries: {path}")

    async def futures_exchange_info(self) -> dict[str, Any]:
        return await self._get("futures", "/fapi/v1/exchangeInfo")

    async def spot_exchange_info(self) -> dict[str, Any]:
        return await self._get("spot", "/api/v3/exchangeInfo")

    async def futures_ticker_24h(self) -> list[dict[str, Any]]:
        return await self._get("futures", "/fapi/v1/ticker/24hr")

    async def spot_ticker_24h(self) -> list[dict[str, Any]]:
        return await self._get("spot", "/api/v3/ticker/24hr")

    async def futures_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
    ) -> list[list[Any]]:
        params: dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time_ms is not None:
            params["startTime"] = start_time_ms
        if end_time_ms is not None:
            params["endTime"] = end_time_ms
        return await self._get("futures", "/fapi/v1/klines", params)

    async def spot_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
    ) -> list[list[Any]]:
        params: dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time_ms is not None:
            params["startTime"] = start_time_ms
        if end_time_ms is not None:
            params["endTime"] = end_time_ms
        return await self._get("spot", "/api/v3/klines", params)

    async def futures_klines_1m(
        self,
        symbol: str,
        limit: int = 500,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
    ) -> list[list[Any]]:
        return await self.futures_klines(symbol, "1m", limit, start_time_ms, end_time_ms)

    async def spot_klines_1m(
        self,
        symbol: str,
        limit: int = 500,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
    ) -> list[list[Any]]:
        return await self.spot_klines(symbol, "1m", limit, start_time_ms, end_time_ms)

    async def futures_open_interest(self, symbol: str) -> dict[str, Any]:
        return await self._get("futures", "/fapi/v1/openInterest", {"symbol": symbol})

    async def futures_mark_funding(self, symbol: str) -> dict[str, Any]:
        return await self._get("futures", "/fapi/v1/premiumIndex", {"symbol": symbol})

    async def futures_book_ticker(self, symbol: str) -> dict[str, Any]:
        return await self._get("futures", "/fapi/v1/ticker/bookTicker", {"symbol": symbol})

    async def spot_book_ticker(self, symbol: str) -> dict[str, Any]:
        return await self._get("spot", "/api/v3/ticker/bookTicker", {"symbol": symbol})

    async def futures_taker_buy_sell_volume(
        self,
        symbol: str,
        period: str,
        limit: int = 100,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"symbol": symbol, "period": period, "limit": limit}
        if start_time_ms is not None:
            params["startTime"] = start_time_ms
        if end_time_ms is not None:
            params["endTime"] = end_time_ms
        return await self._get(
            "futures",
            "/futures/data/takerlongshortRatio",
            params,
        )

    async def futures_global_long_short_account_ratio(
        self,
        symbol: str,
        period: str,
        limit: int = 100,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"symbol": symbol, "period": period, "limit": limit}
        if start_time_ms is not None:
            params["startTime"] = start_time_ms
        if end_time_ms is not None:
            params["endTime"] = end_time_ms
        return await self._get(
            "futures",
            "/futures/data/globalLongShortAccountRatio",
            params,
        )

    async def futures_top_trader_position_ratio(
        self,
        symbol: str,
        period: str,
        limit: int = 100,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"symbol": symbol, "period": period, "limit": limit}
        if start_time_ms is not None:
            params["startTime"] = start_time_ms
        if end_time_ms is not None:
            params["endTime"] = end_time_ms
        return await self._get(
            "futures",
            "/futures/data/topLongShortPositionRatio",
            params,
        )

    async def futures_top_trader_account_ratio(
        self,
        symbol: str,
        period: str,
        limit: int = 100,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"symbol": symbol, "period": period, "limit": limit}
        if start_time_ms is not None:
            params["startTime"] = start_time_ms
        if end_time_ms is not None:
            params["endTime"] = end_time_ms
        return await self._get(
            "futures",
            "/futures/data/topLongShortAccountRatio",
            params,
        )

    async def futures_open_interest_history(
        self,
        symbol: str,
        period: str,
        limit: int = 100,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"symbol": symbol, "period": period, "limit": limit}
        if start_time_ms is not None:
            params["startTime"] = start_time_ms
        if end_time_ms is not None:
            params["endTime"] = end_time_ms
        return await self._get(
            "futures",
            "/futures/data/openInterestHist",
            params,
        )

    async def futures_funding_history(
        self,
        symbol: str,
        limit: int = 1000,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"symbol": symbol, "limit": limit}
        if start_time_ms is not None:
            params["startTime"] = start_time_ms
        if end_time_ms is not None:
            params["endTime"] = end_time_ms
        return await self._get("futures", "/fapi/v1/fundingRate", params)

    def _record_usage(
        self,
        endpoint: str,
        method: str,
        status_code: int | None,
        used_weight: int | None,
        retry_after: int | None,
        headers: httpx.Headers,
    ) -> None:
        raw_headers = {
            key: value
            for key, value in headers.items()
            if key.lower().startswith("x-mbx") or key.lower() == "retry-after"
        }
        self.db.add(
            RateLimitUsage(
                collector_run_id=self.collector_run_id,
                collector_name=self.collector_name,
                endpoint=endpoint,
                method=method,
                status_code=status_code,
                used_weight_1m=used_weight,
                retry_after_seconds=retry_after,
                created_at=utcnow(),
                raw_headers=raw_headers,
            )
        )
        self.db.commit()

    def _record_error(
        self,
        endpoint: str | None,
        status_code: int | None,
        error_type: str,
        message: str,
        payload: Any = None,
        symbol: str | None = None,
    ) -> None:
        logger.warning("%s: %s", error_type, message)
        self.db.add(
            CollectorError(
                collector_run_id=self.collector_run_id,
                collector_name=self.collector_name,
                symbol=symbol,
                endpoint=endpoint,
                status_code=status_code,
                error_type=error_type,
                message=message,
                raw_json=payload if isinstance(payload, dict) else {"payload": str(payload)} if payload else None,
                created_at=utcnow(),
            )
        )
        self.db.commit()

    @staticmethod
    def _header_int(response: httpx.Response, name: str) -> int | None:
        value = response.headers.get(name)
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    @staticmethod
    def _safe_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return {"text": response.text[:1000]}
