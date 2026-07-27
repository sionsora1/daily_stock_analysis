# -*- coding: utf-8 -*-
"""Walk-forward backtest tests for the deterministic AI-chain model."""

from datetime import date, timedelta

import pandas as pd

from src.schemas.ai_chain_model import AIChainModelProfile, AIChainUniverseConfig
from src.services.ai_chain_backtest_service import AIChainBacktestService, BacktestCostModel


def _universe() -> AIChainUniverseConfig:
    return AIChainUniverseConfig.model_validate(
        {
            "schema_version": "1.0",
            "historical_membership_assumption": "test",
            "members": [
                {
                    "code": f"00000{index}",
                    "name": f"样本{index}",
                    "group": "application" if index > 3 else "edge",
                    "tier": "core",
                    "effective_from": "2023-01-01",
                    "evidence_summary": "test",
                }
                for index in range(1, 7)
            ],
        }
    )


def _bars(*, future_jump: float = 0, missing_open: bool = False) -> dict[str, pd.DataFrame]:
    start = date(2026, 1, 1)
    frames = {}
    for code_index in range(1, 7):
        closes = [10 + day * (0.05 + code_index * 0.004) for day in range(105)]
        closes[-1] += future_jump
        frame = pd.DataFrame(
            {
                "date": [start + timedelta(days=day) for day in range(105)],
                "open": [value * 0.99 for value in closes],
                "high": [value * 1.01 for value in closes],
                "low": [value * 0.98 for value in closes],
                "close": closes,
                "volume": [1000 + day * 5 for day in range(105)],
                "amount": [10000 + day * 50 for day in range(105)],
            }
        )
        if missing_open:
            frame.loc[60, "open"] = None
        frames[f"00000{code_index}"] = frame
    return frames


def _profile() -> AIChainModelProfile:
    return AIChainModelProfile(
        min_history_bars=60,
        core_buy_threshold=0,
        observation_buy_threshold=0,
        min_holdings=1,
        max_holdings=6,
        holding_days=10,
    )


def test_walk_forward_uses_next_open_and_is_reproducible():
    frames = _bars()
    service = AIChainBacktestService(_universe(), [], _profile())

    first = service.run(daily_bars_by_code=frames, rebalance_every_days=5)
    second = service.run(daily_bars_by_code=frames, rebalance_every_days=5)

    assert first.points
    assert first.points[0].execution_date > first.points[0].signal_date
    assert first.points[0].execution_price_source == "next_open"
    assert first.points == second.points
    assert first.metrics == second.metrics
    assert first.calibration_observations == second.calibration_observations
    assert first.calibration_observations
    assert all(
        observation["completed_date"] <= first.points[-1].exit_date
        for observation in first.calibration_observations
    )


def test_cost_model_reduces_walk_forward_portfolio_value():
    frames = _bars()
    service = AIChainBacktestService(_universe(), [], _profile())

    no_cost = service.run(
        daily_bars_by_code=frames,
        rebalance_every_days=5,
        cost_model=BacktestCostModel(commission_rate=0, sell_tax_rate=0, slippage_rate=0),
    )
    stressed = service.run(
        daily_bars_by_code=frames,
        rebalance_every_days=5,
        cost_model=BacktestCostModel(commission_rate=0.003, sell_tax_rate=0.002, slippage_rate=0.002),
    )

    assert stressed.metrics["final_portfolio_value"] < no_cost.metrics["final_portfolio_value"]
    assert stressed.metrics["total_trade_cost"] > 0


def test_untradeable_next_open_is_rejected_not_filled_with_close():
    frames = _bars(missing_open=True)
    service = AIChainBacktestService(_universe(), [], _profile())

    result = service.run(daily_bars_by_code=frames, rebalance_every_days=5)

    assert any(point.rejected_codes for point in result.points)
    assert result.metrics["rejected_trade_count"] > 0


def test_market_risk_off_produces_zero_new_risk_allocation():
    frames = _bars()
    wide = pd.DataFrame(
        {
            "date": [date(2026, 1, 1) + timedelta(days=day) for day in range(105)],
            "open": [100 - day for day in range(105)],
            "high": [100 - day for day in range(105)],
            "low": [100 - day for day in range(105)],
            "close": [100 - day for day in range(105)],
        }
    )
    service = AIChainBacktestService(_universe(), [], _profile())

    result = service.run(daily_bars_by_code=frames, wide_market_bars=wide, rebalance_every_days=5)

    assert result.points
    assert all(not point.weights for point in result.points)
