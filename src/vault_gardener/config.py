"""Configuration: paths, models, supervisor limits (D-4, D-10, D-15)."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_DIR / "fixtures"
FIXTURE_VAULT = FIXTURES_DIR / "vault"
TAXONOMY_FILE = FIXTURES_DIR / "taxonomy.json"
LABELS_FILE = FIXTURES_DIR / "labels.json"
RECORDED_FILE = FIXTURES_DIR / "recorded.json"
ARRIVALS_FILE = FIXTURES_DIR / "arrivals.json"
RUBRIC_FILE = REPO_DIR / "rubrics" / "g5_note_labels_v1.json"

TICK_SECONDS = 15 * 60
CLASSIFIER_MODEL = os.environ.get("G5_CLASSIFIER_MODEL", "claude-haiku-5-5")
LINKER_MODEL = os.environ.get("G5_LINKER_MODEL", "claude-haiku-5-5")
MAX_ATTEMPTS = 3  # D-21
MAX_LINKS = 5
LEASE_SECONDS = 120  # D-14

# D-4 (provisional): HEADROOM x the recorded 96-tick day, rounded up. The recorded day's tokens are an estimate
# (characters / 4, D-9); `test_default_limits_match_recorded_day` re-derives these from a fresh simulation.
HEADROOM = 3
RECORDED_DAY_COST_USD = 0.015636  # `gardener simulate --ticks 96`, 2026-11-21: 145 calls, estimated tokens
RECORDED_DAY_TOKENS = 144_796
DEFAULT_DAILY_CAP_USD = 0.05  # derive_cap_usd(RECORDED_DAY_COST_USD)
DEFAULT_DAILY_TOKEN_BUDGET = 440_000  # derive_token_budget(RECORDED_DAY_TOKENS)


def derive_cap_usd(day_cost_usd: float) -> float:
    """HEADROOM x the day's cost, rounded up to the cent."""
    return math.ceil(day_cost_usd * HEADROOM * 100 - 1e-9) / 100


def derive_token_budget(day_tokens: int) -> int:
    """HEADROOM x the day's tokens, rounded up to the next 10,000."""
    return int(math.ceil(day_tokens * HEADROOM / 10_000) * 10_000)


@dataclass(frozen=True)
class Limits:
    daily_cap_usd: float = DEFAULT_DAILY_CAP_USD
    daily_token_budget: int = DEFAULT_DAILY_TOKEN_BUDGET
    error_burst: int = 5
    error_window_s: int = 60 * 60
    failure_share: float = 0.8  # D-34: trip when this share of attempts in the window failed ...
    failure_min_attempts: int = 3  # ... and there were at least this many attempts

    @classmethod
    def from_env(cls, **overrides: float | int | None) -> Limits:
        vals: dict[str, float | int] = {
            "daily_cap_usd": float(os.environ.get("G5_DAILY_CAP_USD", DEFAULT_DAILY_CAP_USD)),
            "daily_token_budget": int(os.environ.get("G5_DAILY_TOKEN_BUDGET", DEFAULT_DAILY_TOKEN_BUDGET)),
            "error_burst": int(os.environ.get("G5_ERROR_BURST", 5)),
            "error_window_s": int(os.environ.get("G5_ERROR_WINDOW_S", 3600)),
            "failure_share": float(os.environ.get("G5_FAILURE_SHARE", 0.8)),
            "failure_min_attempts": int(os.environ.get("G5_FAILURE_MIN_ATTEMPTS", 3)),
        }
        vals.update({k: v for k, v in overrides.items() if v is not None})
        return cls(daily_cap_usd=float(vals["daily_cap_usd"]), daily_token_budget=int(vals["daily_token_budget"]),
                   error_burst=int(vals["error_burst"]), error_window_s=int(vals["error_window_s"]),
                   failure_share=float(vals["failure_share"]), failure_min_attempts=int(vals["failure_min_attempts"]))


def g0_db_path(state_dir: Path) -> str:
    """G0's SQLite file: `G0_DB_PATH` if set, else `<state>/g0.sqlite` (D-20)."""
    return os.environ.get("G0_DB_PATH") or str(state_dir / "g0.sqlite")
