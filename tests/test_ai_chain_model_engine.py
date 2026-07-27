# -*- coding: utf-8 -*-
"""Pure-function scoring and allocation tests for the AI-chain model."""

from datetime import date, timedelta

import pandas as pd

from src.core.ai_chain_model_engine import score_ai_chain_universe
from src.schemas.ai_chain_model import (
    AIChainIndustryProfile,
    AIChainModelAction,
    AIChainModelProfile,
    AIChainUniverseConfig,
    MarketGate,
)


def _bars(start: date, closes: list[float], *, amount: bool = True) -> pd.DataFrame:
    dates = [start + timedelta(days=index) for index in range(len(closes))]
    return pd.DataFrame(
        {
            "date": dates,
            "open": [value * 0.995 for value in closes],
            "high": [value * 1.01 for value in closes],
            "low": [value * 0.99 for value in closes],
            "close": closes,
            "volume": [1000 + index * 20 for index in range(len(closes))],
            "amount": [10000 + index * 300 if amount else None for index in range(len(closes))],
        }
    )


def _universe() -> AIChainUniverseConfig:
    groups = [
        ("000001", "硬件一", "hardware", "core", "semiconductor_equipment"),
        ("000002", "硬件二", "hardware", "core", "semiconductor_equipment"),
        ("000003", "硬件三", "hardware", "core", "ai_chips_storage"),
        ("000004", "端侧一", "edge", "core", None),
        ("000005", "应用一", "application", "core", None),
        ("000006", "观察一", "application", "observation", None),
    ]
    return AIChainUniverseConfig.model_validate(
        {
            "schema_version": "1.0",
            "historical_membership_assumption": "test",
            "members": [
                {
                    "code": code,
                    "name": name,
                    "group": group,
                    "tier": tier,
                    "hardware_subgroup": subgroup,
                    "effective_from": "2023-01-01",
                    "evidence_summary": "test",
                }
                for code, name, group, tier, subgroup in groups
            ],
        }
    )


def _profiles() -> list[AIChainIndustryProfile]:
    return [
        AIChainIndustryProfile.model_validate(
            {
                "version": "v1",
                "hardware_subgroup": subgroup,
                "effective_from": "2026-07-01",
                "barrier_score": 5,
                "scarcity_score": 4,
                "ai_demand_transmission_score": 5,
                "expansion_cycle": "medium",
                "evidence_date": "2026-07-01",
                "evidence_summary": "test",
            }
        )
        for subgroup in ("semiconductor_equipment", "ai_chips_storage")
    ]


def _frames(end_jump: float = 0.0, *, amount: bool = True) -> dict[str, pd.DataFrame]:
    start = date(2026, 5, 1)
    result = {}
    for index, code in enumerate(["000001", "000002", "000003", "000004", "000005", "000006"]):
        closes = [10 + day * (0.03 + index * 0.002) for day in range(80)]
        closes[-1] += index * 0.08
        if code == "000001":
            closes[-1] += end_jump
        result[code] = _bars(start, closes, amount=amount or code != "000001")
    return result


def test_scores_ignore_future_bars_after_as_of_date():
    frames = _frames(end_jump=0)
    as_of = frames["000001"].iloc[69]["date"]
    baseline = score_ai_chain_universe(
        daily_bars_by_code=frames,
        universe=_universe(),
        industry_profiles=_profiles(),
        as_of_date=as_of,
        wide_market_bars=_bars(date(2026, 5, 1), [100 + day * 0.1 for day in range(80)]),
    )
    mutated = _frames(end_jump=1000)
    replay = score_ai_chain_universe(
        daily_bars_by_code=mutated,
        universe=_universe(),
        industry_profiles=_profiles(),
        as_of_date=as_of,
        wide_market_bars=_bars(date(2026, 5, 1), [100 + day * 0.1 for day in range(80)]),
    )

    assert [item.score for item in replay.scores] == [item.score for item in baseline.scores]
    assert replay.market_gate == baseline.market_gate


def test_slow_profile_is_invisible_before_its_effective_date():
    frames = _frames()
    as_of = frames["000001"].iloc[-1]["date"]
    before = score_ai_chain_universe(
        daily_bars_by_code=frames,
        universe=_universe(),
        industry_profiles=_profiles(),
        as_of_date=date(2026, 6, 30),
    )
    after = score_ai_chain_universe(
        daily_bars_by_code=frames,
        universe=_universe(),
        industry_profiles=_profiles(),
        as_of_date=as_of,
    )

    before_item = next(item for item in before.scores if item.code == "000001")
    after_item = next(item for item in after.scores if item.code == "000001")
    assert before_item.factor_snapshot["slow_profile_adjustment"] == 0
    assert after_item.factor_snapshot["slow_profile_adjustment"] > 0


def test_missing_amount_uses_volume_fallback_and_degrades_quality():
    frames = _frames(amount=False)
    result = score_ai_chain_universe(
        daily_bars_by_code=frames,
        universe=_universe(),
        industry_profiles=_profiles(),
        as_of_date=frames["000001"].iloc[-1]["date"],
    )
    item = next(item for item in result.scores if item.code == "000001")

    assert item.quality_snapshot["status"] == "degraded"
    assert item.factor_snapshot["volume_factor_source"] == "volume"


def test_portfolio_respects_total_single_subgroup_and_observation_caps():
    frames = _frames()
    profile = AIChainModelProfile(
        core_buy_threshold=0,
        observation_buy_threshold=0,
        max_holdings=8,
        min_holdings=1,
    )
    result = score_ai_chain_universe(
        daily_bars_by_code=frames,
        universe=_universe(),
        industry_profiles=_profiles(),
        as_of_date=frames["000001"].iloc[-1]["date"],
        model_profile=profile,
    )

    selected = [item for item in result.scores if item.suggested_weight > 0]
    hardware_equipment = sum(
        item.suggested_weight for item in selected if item.hardware_subgroup == "semiconductor_equipment"
    )
    observation = sum(item.suggested_weight for item in selected if item.tier.value == "observation")
    assert result.market_gate in {MarketGate.NORMAL, MarketGate.CAUTION, MarketGate.RISK_OFF}
    assert sum(item.suggested_weight for item in selected) <= 0.60 + 1e-9
    assert all(item.suggested_weight <= 0.15 for item in selected)
    assert hardware_equipment <= 0.20 + 1e-9
    assert observation <= 0.15 + 1e-9
    assert [item.overall_rank for item in result.scores] == list(range(1, len(result.scores) + 1))
    assert [item.score for item in result.scores] == sorted(
        (item.score for item in result.scores), reverse=True
    )


def test_calibration_excludes_observations_not_completed_as_of_date():
    frames = _frames()
    as_of = frames["000001"].iloc[-1]["date"]
    profile = AIChainModelProfile(core_buy_threshold=0, observation_buy_threshold=0, min_calibration_sample=1)
    result = score_ai_chain_universe(
        daily_bars_by_code=frames,
        universe=_universe(),
        industry_profiles=_profiles(),
        as_of_date=as_of,
        model_profile=profile,
        calibration_observations=[
            {
                "completed_date": as_of - timedelta(days=1),
                "score": 80,
                "market_gate": "normal",
                "realized_return": 0.1,
                "relative_return": 0.05,
            },
            {
                "completed_date": as_of + timedelta(days=1),
                "score": 80,
                "market_gate": "normal",
                "realized_return": -0.9,
                "relative_return": -0.9,
            },
        ],
    )

    calibrated = next(item for item in result.scores if item.action == AIChainModelAction.BUY)
    assert calibrated.probability_up == 1.0
    assert calibrated.expected_return == 0.1
