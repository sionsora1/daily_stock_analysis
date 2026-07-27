# -*- coding: utf-8 -*-
"""Persistence contracts for independent AI-chain model runs."""

from datetime import date

import pytest

from src.config import Config
from src.repositories.ai_chain_model_repo import AIChainModelRepository
from src.storage import DatabaseManager


@pytest.fixture
def model_repo():
    Config.reset_instance()
    DatabaseManager.reset_instance()
    database = DatabaseManager(db_url="sqlite:///:memory:")
    try:
        yield AIChainModelRepository(database)
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()


def _score(code="000977", rank=1):
    return {
        "code": code,
        "name": "浪潮信息",
        "group_name": "hardware",
        "hardware_subgroup": "ai_servers_odm_racks",
        "tier": "core",
        "factor_snapshot": {"relative_strength": 0.8},
        "quality_snapshot": {"status": "ready"},
        "probability_up": 0.61,
        "probability_outperform": 0.58,
        "expected_return": 0.06,
        "return_low": -0.05,
        "return_high": 0.14,
        "drawdown_risk": 0.11,
        "action": "hold",
        "rank": rank,
        "suggested_weight": 0.12,
    }


def test_same_day_same_version_successfully_upserts_run_and_scores(model_repo):
    first = model_repo.upsert_successful_run(
        as_of_date=date(2026, 7, 24),
        model_version="v1",
        market_gate="normal",
        data_coverage=0.96,
        warnings=["first"],
        model_profile={"holding_days": 20},
        scores=[_score()],
    )
    replaced = model_repo.upsert_successful_run(
        as_of_date=date(2026, 7, 24),
        model_version="v1",
        market_gate="risk_off",
        data_coverage=0.94,
        warnings=["replaced"],
        model_profile={"holding_days": 20},
        scores=[_score("603019")],
    )

    assert replaced.id == first.id
    assert replaced.market_gate == "risk_off"
    assert model_repo.get_scores_for_run(replaced.id)[0].code == "603019"


def test_failed_run_does_not_replace_latest_successful_snapshot(model_repo):
    successful = model_repo.upsert_successful_run(
        as_of_date=date(2026, 7, 24),
        model_version="v1",
        market_gate="normal",
        data_coverage=0.96,
        warnings=[],
        model_profile={},
        scores=[_score()],
    )
    model_repo.save_failed_run(
        as_of_date=date(2026, 7, 25),
        model_version="v1",
        failure_reason="coverage below threshold",
        data_coverage=0.72,
    )

    latest = model_repo.get_latest_successful_run()

    assert latest is not None
    assert latest.id == successful.id
    assert latest.as_of_date == date(2026, 7, 24)


def test_backtest_points_are_paginated_in_rebalance_order(model_repo):
    backtest = model_repo.create_backtest_run(
        model_version="v1",
        start_date=date(2023, 7, 1),
        end_date=date(2026, 7, 24),
        parameters={"holding_days": 20},
        cost_model={"commission": 0.0003},
        benchmarks={"ai_equal_weight": "constructed"},
    )
    model_repo.replace_backtest_points(
        backtest.id,
        [
            {"sequence": 1, "rebalance_date": date(2023, 7, 7), "portfolio_value": 1.01},
            {"sequence": 2, "rebalance_date": date(2023, 7, 14), "portfolio_value": 1.02},
            {"sequence": 3, "rebalance_date": date(2023, 7, 21), "portfolio_value": 1.03},
        ],
    )

    page, total = model_repo.list_backtest_points(backtest.id, page=2, page_size=1)

    assert total == 3
    assert [point.sequence for point in page] == [2]


def test_backtest_run_persists_completion_metrics_and_failure_reason(model_repo):
    backtest = model_repo.create_backtest_run(
        model_version="v1",
        start_date=date(2023, 7, 1),
        end_date=date(2026, 7, 24),
        parameters={"holding_days": 20},
        cost_model={"commission": 0.0003},
        benchmarks={"ai_equal_weight": "constructed"},
    )

    finished = model_repo.finish_backtest_run(
        backtest.id,
        metrics={"final_portfolio_value": 1.12},
        status="failed",
        failure_reason="missing benchmark bars",
    )
    loaded = model_repo.get_backtest_run(backtest.id)

    assert finished.status == "failed"
    assert loaded is not None
    assert loaded.metrics_json == '{"final_portfolio_value": 1.12}'
    assert loaded.failure_reason == "missing benchmark bars"
