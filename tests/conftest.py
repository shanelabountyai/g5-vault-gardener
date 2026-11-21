from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from vault_gardener.clock import SimClock
from vault_gardener.config import Limits
from vault_gardener.simulate import copy_fixture
from vault_gardener.worker import Worker

BIG = Limits(daily_cap_usd=100.0, daily_token_budget=10**9, error_burst=1000, error_window_s=3600)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("G0_DB_PATH", "ANTHROPIC_API_KEY", "G5_DAILY_CAP_USD", "G5_DAILY_TOKEN_BUDGET", "G5_ERROR_BURST", "G5_ERROR_WINDOW_S"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    return copy_fixture(tmp_path / "vault")


@pytest.fixture
def make_worker(tmp_path: Path, vault: Path) -> Iterator:  # type: ignore[type-arg]
    made: list[Worker] = []

    def _make(**kw):  # type: ignore[no-untyped-def]
        kw.setdefault("clock", SimClock())
        kw.setdefault("limits", BIG)
        w = Worker(kw.pop("vault", vault), kw.pop("state_dir", tmp_path / "state"), **kw)
        made.append(w)
        return w

    yield _make
    for w in made:
        try:
            w.close()
        except Exception:
            pass
