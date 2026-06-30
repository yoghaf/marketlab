from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any


def utcnow() -> datetime:
    return datetime.now(UTC)


def ms_to_utc(value: Any) -> datetime | None:
    if value in (None, "", 0, "0"):
        return None
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)


def decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def current_minute_start_ms() -> int:
    now = utcnow()
    return int(now.replace(second=0, microsecond=0).timestamp() * 1000)


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    return value


def duration_seconds(start: datetime, end: datetime) -> int:
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    return max(0, int((end - start).total_seconds()))


def model_to_dict(row: Any) -> dict[str, Any]:
    return {
        column.name: json_safe(getattr(row, column.name))
        for column in row.__table__.columns
    }
