from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from src.services.intraday_monitor_service import (
    IntradayMonitorService,
    STATUS_CONFIRMED,
    STATUS_INSUFFICIENT,
    STATUS_CONTINUE,
    STATUS_PRELIMINARY,
    required_breadth,
)


class FakeQuote:
    def __init__(
        self,
        code: str,
        *,
        amount: float = 220.0,
        price: float = 11.0,
        is_stale: bool = False,
        provider_timestamp: str | None = "2026-07-27T10:31:00+08:00",
        fetched_at: str | None = None,
    ):
        self.code = code
        self.name = f"name-{code}"
        self.source = "direct"
        self.price = price
        self.open_price = 10.0
        self.change_pct = 10.0
        self.amount = amount
        self.volume = 1000
        self.turnover_rate = 5.0
        self.fetched_at = fetched_at or provider_timestamp
        self.provider_timestamp = provider_timestamp
        self.is_stale = is_stale


class FakeFetcher:
    def __init__(self, missing: set[str] | None = None, **quote_kwargs):
        self.missing = missing or set()
        self.quote_kwargs = quote_kwargs

    def get_realtime_quote(self, code: str, *, log_final_failure: bool = False):
        if code in self.missing:
            return None
        return FakeQuote(code, **self.quote_kwargs)


class FakeRepo:
    def __init__(self, plan):
        self.plans = plan if isinstance(plan, list) else [plan]
        self.plan = self.plans[0]
        self.history = []

    def list_active_plans(self):
        return self.plans

    def get_plan(self, plan_id):
        return next((item for item in self.plans if item.id == plan_id), None)

    def update_state(self, plan_id, *, status, snapshot_json, evaluated_at):
        plan = self.get_plan(plan_id)
        assert plan is not None
        plan.current_status = status
        plan.current_snapshot = snapshot_json
        plan.last_evaluated_at = evaluated_at
        return plan

    def create_history(self, fields):
        self.history.append(fields)

    def purge_old_history(self, *, days):
        return 0


def make_plan(
    snapshot: dict | None = None,
    *,
    symbols: list[str] | None = None,
    representative_groups: list[dict] | None = None,
):
    monitored_symbols = symbols or ["002371", "603690"]
    persisted_symbols = (
        json.dumps(
            {
                "symbols": monitored_symbols,
                "representative_groups": representative_groups,
            }
        )
        if representative_groups is not None
        else json.dumps(monitored_symbols)
    )
    return SimpleNamespace(
        id=1,
        name="test",
        event_symbol="688825",
        sector_symbol="159516",
        monitored_symbols=persisted_symbols,
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
        created_at=None,
        updated_at=None,
    )


class SplitStrengthFetcher:
    def __init__(self, strong_codes: set[str]):
        self.strong_codes = strong_codes

    def get_realtime_quote(self, code: str, *, log_final_failure: bool = False):
        return FakeQuote(code, price=11.0 if code in self.strong_codes else 9.0)


def warm_snapshot(
    codes: list[str],
    *,
    start: str = "2026-07-27T10:00:00+08:00",
    count: int = 12,
    interval_seconds: int = 60,
) -> dict:
    started_at = datetime.fromisoformat(start)
    return {
        "samples": [
            {
                "as_of": (started_at + timedelta(seconds=interval_seconds * index)).isoformat(),
                "quotes": {
                    code: {"price": 10 + index / 10, "open_price": 10.0, "amount": 100 + index * 10, "volume": 1000}
                    for code in codes
                },
            }
            for index in range(count)
        ],
        "streak": 0,
        "confirm_streak": 0,
    }


def test_required_breadth_uses_ceiling_without_fixed_signal_threshold():
    assert required_breadth(19, 0.6) == 12
    assert required_breadth(2, 0.6) == 2


def test_monitor_requires_two_consecutive_refreshes_for_confirmation():
    codes = ["688825", "159516", "002371", "603690"]
    repo = FakeRepo(make_plan(warm_snapshot(codes, start="2026-07-27T10:22:30+08:00", interval_seconds=30)))
    service = IntradayMonitorService(repository=repo, fetcher_manager=FakeFetcher())

    service.evaluate_plan(repo.plan, now=datetime.fromisoformat("2026-07-27T10:29:00+08:00"))
    before_confirm = service.evaluate_plan(repo.plan, now=datetime.fromisoformat("2026-07-27T10:29:30+08:00"))
    first_confirm = service.evaluate_plan(repo.plan, now=datetime.fromisoformat("2026-07-27T10:30:00+08:00"))
    second_confirm = service.evaluate_plan(repo.plan, now=datetime.fromisoformat("2026-07-27T10:30:30+08:00"))

    assert before_confirm["status"] == STATUS_PRELIMINARY
    assert first_confirm["status"] == STATUS_PRELIMINARY
    assert first_confirm["trigger_values"]["confirm_streak"] == 1
    assert second_confirm["status"] == STATUS_CONFIRMED
    assert second_confirm["trigger_values"]["confirm_streak"] == 2
    assert repo.history[-1]["status"] == STATUS_CONFIRMED


def test_pattern_uses_three_minute_timestamps_with_a_ten_second_poll_interval():
    codes = ["688825", "159516", "002371", "603690"]
    plan = make_plan(
        warm_snapshot(
            codes,
            start="2026-07-27T10:24:00+08:00",
            count=42,
            interval_seconds=10,
        )
    )
    plan.poll_interval_seconds = 10
    service = IntradayMonitorService(
        repository=FakeRepo(plan),
        fetcher_manager=FakeFetcher(amount=430.0, price=15.0),
    )

    snapshot = service.evaluate_plan(plan, now=datetime.fromisoformat("2026-07-27T10:31:00+08:00"))

    assert snapshot["event"]["pattern"] in {"attack_with_volume", "steady"}
    assert snapshot["event"]["recent_flow"] == 90.0
    assert snapshot["event"]["previous_flow"] == 180.0


def test_stale_quote_pauses_signal_without_counting_as_a_weakened_stock():
    codes = ["688825", "159516", "002371", "603690"]
    repo = FakeRepo(make_plan(warm_snapshot(codes, start="2026-07-27T10:22:30+08:00", interval_seconds=30)))
    service = IntradayMonitorService(
        repository=repo,
        fetcher_manager=FakeFetcher(is_stale=True),
    )

    snapshot = service.evaluate_plan(repo.plan, now=datetime.fromisoformat("2026-07-27T10:31:00+08:00"))

    assert snapshot["status"] == STATUS_INSUFFICIENT
    assert snapshot["event"]["is_fresh"] is False
    assert snapshot["event"]["freshness"] == "stale"


def test_expired_provider_timestamp_is_not_usable_even_without_source_stale_flag():
    codes = ["688825", "159516", "002371", "603690"]
    repo = FakeRepo(make_plan(warm_snapshot(codes, start="2026-07-27T10:22:30+08:00", interval_seconds=30)))
    service = IntradayMonitorService(
        repository=repo,
        fetcher_manager=FakeFetcher(provider_timestamp="2026-07-27T10:28:00+08:00"),
    )

    snapshot = service.evaluate_plan(repo.plan, now=datetime.fromisoformat("2026-07-27T10:31:00+08:00"))

    assert snapshot["status"] == STATUS_INSUFFICIENT
    assert snapshot["event"]["quote_age_seconds"] == 180
    assert snapshot["event"]["freshness_reason"] == "quote_age_exceeded"


def test_missing_provider_timestamp_remains_usable_but_is_visible_as_unknown():
    codes = ["688825", "159516", "002371", "603690"]
    repo = FakeRepo(make_plan(warm_snapshot(codes, start="2026-07-27T10:22:30+08:00", interval_seconds=30)))
    service = IntradayMonitorService(
        repository=repo,
        fetcher_manager=FakeFetcher(
            provider_timestamp=None,
            fetched_at="2026-07-27T10:31:00+08:00",
        ),
    )

    snapshot = service.evaluate_plan(repo.plan, now=datetime.fromisoformat("2026-07-27T10:31:00+08:00"))

    assert snapshot["event"]["is_fresh"] is True
    assert snapshot["event"]["freshness"] == "unknown"
    assert snapshot["event"]["freshness_reason"] == "provider_timestamp_unavailable"


def test_background_cycle_only_evaluates_plans_that_are_due():
    current = datetime.fromisoformat("2026-07-27T10:31:00+08:00")
    due = make_plan()
    due.id = 1
    due.last_evaluated_at = (current - timedelta(seconds=30)).replace(tzinfo=None)
    waiting = make_plan()
    waiting.id = 2
    waiting.last_evaluated_at = (current - timedelta(seconds=5)).replace(tzinfo=None)
    repo = FakeRepo([due, waiting])

    class RecordingService(IntradayMonitorService):
        def __init__(self):
            super().__init__(repository=repo, fetcher_manager=FakeFetcher())
            self.evaluated_ids: list[int] = []

        def evaluate_plan(self, row, *, now=None):
            self.evaluated_ids.append(row.id)
            return {"status": "observe"}

    service = RecordingService()

    assert service.run_cycle(now=current) == 1
    assert service.evaluated_ids == [1]
    assert service.run_cycle(now=current, force=True) == 2
    assert service.evaluated_ids == [1, 1, 2]


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


def test_default_representative_groups_are_applied_to_the_bundled_monitor_pool():
    symbols = [
        "002371", "603690", "603929", "603163", "603283", "688596", "688409", "300260",
        "603688", "002409", "603650", "600206", "688019", "300054", "300666", "688126",
        "688268", "688106", "605358",
    ]
    plan = make_plan(symbols=symbols)
    service = IntradayMonitorService(repository=FakeRepo(plan), fetcher_manager=FakeFetcher())

    result = service.plan_to_dict(plan)

    assert result["representative_groups_source"] == "default"
    assert [group["label"] for group in result["representative_groups"]] == ["设备", "关键零部件", "材料"]


def test_representative_gate_requires_strength_across_two_industry_directions():
    markers = ["002371", "603690", "688409", "300260", "603688", "002409"]
    codes = ["688825", "159516", *markers]
    groups = [
        {"key": "equipment", "label": "设备", "core_symbols": ["002371", "603690"], "backup_symbols": []},
        {"key": "components", "label": "关键零部件", "core_symbols": ["688409", "300260"], "backup_symbols": []},
        {"key": "materials", "label": "材料", "core_symbols": ["603688", "002409"], "backup_symbols": []},
    ]
    plan = make_plan(
        warm_snapshot(codes, start="2026-07-27T10:22:30+08:00", interval_seconds=30),
        symbols=markers,
        representative_groups=groups,
    )
    plan.majority_ratio = 0.3
    service = IntradayMonitorService(
        repository=FakeRepo(plan),
        fetcher_manager=SplitStrengthFetcher({"688825", "159516", "002371", "603690"}),
    )

    snapshot = service.evaluate_plan(plan, now=datetime.fromisoformat("2026-07-27T10:31:00+08:00"))

    assert snapshot["breadth"]["valid"] is True
    assert snapshot["representative_coverage"]["strong"] == 1
    assert snapshot["representative_coverage"]["required"] == 2
    assert snapshot["representative_coverage"]["valid"] is False
    assert snapshot["status"] == STATUS_CONTINUE
    assert "产业方向" in snapshot["reason"]


def test_backup_representative_does_not_replace_a_weak_core_stock():
    markers = ["002371", "603690", "688409", "603688"]
    codes = ["688825", "159516", *markers]
    groups = [
        {"key": "equipment", "label": "设备", "core_symbols": ["002371"], "backup_symbols": ["603690"]},
        {"key": "components", "label": "关键零部件", "core_symbols": ["688409"], "backup_symbols": []},
        {"key": "materials", "label": "材料", "core_symbols": ["603688"], "backup_symbols": []},
    ]
    plan = make_plan(
        warm_snapshot(codes, start="2026-07-27T10:22:30+08:00", interval_seconds=30),
        symbols=markers,
        representative_groups=groups,
    )
    service = IntradayMonitorService(
        repository=FakeRepo(plan),
        fetcher_manager=SplitStrengthFetcher({"688825", "159516", "603690", "688409", "603688"}),
    )

    snapshot = service.evaluate_plan(plan, now=datetime.fromisoformat("2026-07-27T10:31:00+08:00"))
    equipment = snapshot["representative_coverage"]["groups"][0]

    assert equipment["valid"] is False
    assert equipment["backup_valid_codes"] == ["603690"]
    assert equipment["used_role"] is None


def test_representative_groups_must_reference_monitored_symbols():
    with pytest.raises(ValueError, match="representative group symbols"):
        IntradayMonitorService.validate_plan_fields(
            {
                "name": "test",
                "event_symbol": "688825",
                "sector_symbol": "159516",
                "monitored_symbols": ["002371"],
                "representative_groups": [
                    {"key": "equipment", "label": "设备", "core_symbols": ["603690"]},
                ],
            }
        )


def test_representative_symbol_cannot_count_for_two_industry_groups():
    with pytest.raises(ValueError, match="only one industry group"):
        IntradayMonitorService.validate_plan_fields(
            {
                "name": "test",
                "event_symbol": "688825",
                "sector_symbol": "159516",
                "monitored_symbols": ["002371", "603690"],
                "representative_groups": [
                    {"key": "equipment", "label": "设备", "core_symbols": ["002371"]},
                    {"key": "materials", "label": "材料", "core_symbols": ["002371"], "backup_symbols": ["603690"]},
                ],
            }
        )


def test_deterministic_simulation_covers_confirm_invalidate_and_recover():
    repo = FakeRepo(
        make_plan(
            symbols=["002371", "603690"],
            representative_groups=[
                {"key": "equipment", "label": "设备", "core_symbols": ["002371"], "backup_symbols": ["603690"]},
            ],
        )
    )
    service = IntradayMonitorService(repository=repo, fetcher_manager=FakeFetcher())

    result = service.simulate_plan(1)

    assert result["passed"] is True
    assert result["transition_statuses"] == [
        "observe",
        "continue_observing",
        "preliminary",
        "confirmed",
        "invalidated",
        "continue_observing",
        "confirmed",
    ]
    assert result["steps"][-1]["representative_coverage"]["enabled"] is True
    assert repo.plan.current_status == "observe"
