"""Injectable clock (D-19). The worker never calls `time` directly, so tests and the demo can compress a day."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...

    def sleep(self, seconds: float) -> None: ...


class RealClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class SimClock:
    """Starts at `start` (UTC) and advances only when `sleep` or `advance` is called."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 11, 21, 0, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def sleep(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)

    def advance(self, seconds: float) -> None:
        self.sleep(seconds)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def day_id(dt: datetime) -> str:
    """The G0 observability run id for a day (D-16): days roll over at 00:00 UTC."""
    return "g5-" + dt.astimezone(UTC).strftime("%Y-%m-%d")
