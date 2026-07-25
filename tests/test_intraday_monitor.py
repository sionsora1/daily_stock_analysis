from __future__ import annotations

import json
from datetime import date, datetime
from types import SimpleNamespace

from src.services.intraday_monitor_service import (
    IntradayMonitorService,
    STATUS_CONFIRMED,
    STATUS_INSUFFICIENT,
    STATUS_CONTINUE,
    required_breadth,
)


class FakeQuote:
    def __init__(self, code: str, *, amount: float = 220.0, price: float = 11.0):
        self.code = code
        self.name = f"name-{code}"
        self.source = "direct"
        self.price = price
        self.open_price = 10.0
        self.change_pct = 10.0
        self.amount = amount
        self.volume = 1000
        self.turnover_rate = 5.0
        self.fetched_at = "2026-07-27T10:31:00+08:00"
        self.provider_timestamp = self.fetched_at
        self.is_stale = False


class FakeFetcher:
    def __init__(self, missing: set[str] | None = None):
        self.missing = missing or set()

    def get_realtime_quote(self, code: str, *, log_final_failure: bool = False):
        if code in self.missing:
            return None
        return FakeQuote(code)


class FakeRepo:
    def __init__(self, plan):
        self.plan = plan
        self.history = []

    def list_active_plans(self):
        return [self.plan]

    def get_plan(self, plan_id):
        return self.plan if plan_id == self.plan.id else None

    def update_state(self, plan_id, *, status, snapshot_json, evaluated_at):
        self.plan.current_status = status
        self.plan.current_snapshot = snapshot_json
        self.plan.last_evaluated_at = evaluated_at
        return self.plan

    def create_history(self, fields):
        self.history.append(fields)

    def purge_old_history(self, *, days):
        return 0


def make_plan(snapshot: dict | None = None):
    return SimpleNamespace(
        id=1,
        name="test",
        event_symbol="688825",
        sector_symbol="159516",
        monitored_symbols=json.dumps(["002371", "603690"]),
        majority_ratio=0.6,
        initial_time="10:00",
        confirm_time="10:30",
        poll_interval_seconds=30,
        listing_day_mode=True,
        start_date=date(2026, 7, 27),
        end_date=date(2026, 7, 27),
        enabled=True,
        paused=False,
        current_status="observe",
        current_snapshot=json.dumps(snapshot or {}),
        last_evaluated_at=None,
    )


def warm_snapshot(codes: list[str]) -> dict:
    return {
        "samples": [
            {
                "as_of": f"2026-07-27T10:{index:02d}:00+08:00",
                "quotes": {
                    code: {"price": 10 + index / 10, "open_price": 10.0, "amount": 100 + index * 10, "volume": 1000}
                    for code in codes
                },
            }
            for index in range(12)
        ],
        "streak": 0,
    }


def test_required_breadth_uses_ceiling_without_fixed_signal_threshold():
    assert required_breadth(19, 0.6) == 12
    assert required_breadth(2, 0.6) == 2


def test_monitor_requires_two_consecutive_refreshes_for_confirmation():
    codes = ["688825", "159516", "002371", "603690"]
    repo = FakeRepo(make_plan(warm_snapshot(codes)))
    service = IntradayMonitorService(repository=repo, fetcher_manager=FakeFetcher())

    first = service.evaluate_plan(repo.plan, now=datetime.fromisoformat("2026-07-27T10:31:00+08:00"))
    second = service.evaluate_plan(repo.plan, now=datetime.fromisoformat("2026-07-27T10:31:30+08:00"))

    assert first["status"] == STATUS_CONTINUE
    assert second["status"] == STATUS_CONFIRMED
    assert len(repo.history) == 2
    assert repo.history[-1]["status"] == STATUS_CONFIRMED


def test_missing_event_or_sector_data_does_not_shrink_breadth_denominator():
    codes = ["688825", "159516", "002371", "603690"]
    repo = FakeRepo(make_plan(warm_snapshot(codes)))
    service = IntradayMonitorService(
        repository=repo,
        fetcher_manager=FakeFetcher(missing={"688825"}),
    )

    snapshot = service.evaluate_plan(repo.plan, now=datetime.fromisoformat("2026-07-27T10:31:00+08:00"))

    assert snapshot["status"] == STATUS_INSUFFICIENT
    assert snapshot["breadth"]["total"] == 2
    assert snapshot["breadth"]["available"] == 2


def test_deterministic_simulation_covers_confirm_invalidate_and_recover():
    repo = FakeRepo(make_plan())
    service = IntradayMonitorService(repository=repo, fetcher_manager=FakeFetcher())

    result = service.simulate_plan(1)

    assert result["passed"] is True
    assert result["transition_statuses"] == [
        "observe",
        "preliminary",
        "confirmed",
        "invalidated",
        "continue_observing",
        "confirmed",
    ]
    assert repo.plan.current_status == "observe"
