# -*- coding: utf-8 -*-
"""Pure, deterministic end-of-day scoring for the A-share AI-chain model.

No network, database, clock, or mutable application state is used here.  The
caller supplies bars already known at the requested close, so the same input
always produces the same score and a backtest cannot accidentally see a later
trading session.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from src.schemas.ai_chain_model import (
    AIChainIndustryProfile,
    AIChainModelAction,
    AIChainModelProfile,
    AIChainModelResult,
    AIChainScoreResult,
    AIChainUniverseConfig,
    AIChainUniverseMember,
    MarketGate,
    UniverseTier,
)


def score_ai_chain_universe(
    *,
    daily_bars_by_code: Mapping[str, pd.DataFrame],
    universe: AIChainUniverseConfig,
    industry_profiles: Iterable[AIChainIndustryProfile],
    as_of_date: date,
    model_profile: Optional[AIChainModelProfile] = None,
    wide_market_bars: Optional[pd.DataFrame] = None,
    calibration_observations: Optional[Sequence[Mapping[str, Any]]] = None,
) -> AIChainModelResult:
    """Score active universe members using only bars available at ``as_of_date``."""
    profile = model_profile or AIChainModelProfile()
    as_of = _as_date(as_of_date)
    profiles = _active_profiles(industry_profiles, as_of)
    normalized_frames = {
        code: _bars_as_of(frame, as_of)
        for code, frame in daily_bars_by_code.items()
    }
    market_gate, market_gate_reason = _evaluate_market_gate(
        _bars_as_of(wide_market_bars, as_of) if wide_market_bars is not None else None
    )
    warnings: list[str] = []
    if wide_market_bars is None:
        warnings.append("宽基市场日线缺失，市场风险闸门按正常状态保守展示")

    active_members = universe.active_members(as_of)
    raw_features: dict[str, dict[str, Any]] = {}
    eligible_returns: list[float] = []
    for member in active_members:
        features = _fast_features(normalized_frames.get(member.code), profile)
        raw_features[member.code] = features
        if features["is_usable"]:
            eligible_returns.append(features["return_20"])
    ai_median_return = float(np.median(eligible_returns)) if eligible_returns else 0.0

    results: list[AIChainScoreResult] = []
    for member in active_members:
        features = raw_features[member.code]
        result = _score_member(
            member=member,
            features=features,
            ai_median_return=ai_median_return,
            active_profiles=profiles,
            as_of_date=as_of,
            profile=profile,
            market_gate=market_gate,
            calibration_observations=calibration_observations or [],
        )
        results.append(result)

    results = _rank_results(results)
    results = _allocate_portfolio(results, profile, market_gate)
    return AIChainModelResult(
        as_of_date=as_of,
        model_profile=profile,
        market_gate=market_gate,
        market_gate_reason=market_gate_reason,
        scores=results,
        warnings=warnings,
    )


def _as_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, pd.Timestamp):
        return value
    return pd.Timestamp(value).date()


def _bars_as_of(frame: Optional[pd.DataFrame], as_of_date: date) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "amount"])
    result = frame.copy()
    if "date" not in result.columns:
        return pd.DataFrame(columns=result.columns)
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result = result.dropna(subset=["date"])
    result = result.loc[result["date"].dt.date <= as_of_date].sort_values("date")
    return result.drop_duplicates("date", keep="last").reset_index(drop=True)


def _active_profiles(
    profiles: Iterable[AIChainIndustryProfile], as_of_date: date
) -> dict[str, AIChainIndustryProfile]:
    active: dict[str, AIChainIndustryProfile] = {}
    for item in profiles:
        if item.is_active_on(as_of_date):
            active[item.hardware_subgroup.value] = item
    return active


def _fast_features(frame: Optional[pd.DataFrame], profile: AIChainModelProfile) -> dict[str, Any]:
    if frame is None or "close" not in frame.columns:
        return _insufficient_features("缺少收盘价")
    close = pd.to_numeric(frame["close"], errors="coerce").dropna().reset_index(drop=True)
    if len(close) < profile.min_history_bars:
        return _insufficient_features(f"日线样本不足 {profile.min_history_bars} 根")
    if (close <= 0).any():
        return _insufficient_features("收盘价包含非正值")

    volume = pd.to_numeric(frame.get("volume", pd.Series(dtype=float)), errors="coerce")
    amount = pd.to_numeric(frame.get("amount", pd.Series(dtype=float)), errors="coerce")
    usable_length = min(len(close), len(frame))
    close = close.iloc[-usable_length:].reset_index(drop=True)
    amount = amount.iloc[-usable_length:].reset_index(drop=True)
    volume = volume.iloc[-usable_length:].reset_index(drop=True)
    ma5 = float(close.iloc[-5:].mean())
    ma20 = float(close.iloc[-20:].mean())
    return_5 = float(close.iloc[-1] / close.iloc[-6] - 1)
    return_20 = float(close.iloc[-1] / close.iloc[-21] - 1)
    returns = close.pct_change().dropna()
    volatility_20 = float(returns.iloc[-20:].std(ddof=0) * np.sqrt(20))
    high_20 = float(close.iloc[-20:].max())
    drawdown_20 = float(close.iloc[-1] / high_20 - 1)
    amount_coverage = float(amount.iloc[-20:].notna().mean()) if len(amount) >= 20 else 0.0
    if amount_coverage >= profile.min_coverage_ratio:
        activity = amount
        activity_source = "amount"
        quality_status = "ready"
    else:
        activity = volume
        activity_source = "volume"
        quality_status = "degraded"
    activity = pd.to_numeric(activity, errors="coerce")
    if len(activity.dropna()) < 20 or float(activity.iloc[-20:].mean() or 0) <= 0:
        return _insufficient_features("成交量或成交额样本不足")
    current_activity = float(activity.iloc[-1])
    activity_mean = float(activity.iloc[-20:].mean())
    activity_ratio = current_activity / activity_mean if activity_mean > 0 else 0.0
    return {
        "is_usable": True,
        "return_5": return_5,
        "return_20": return_20,
        "ma5": ma5,
        "ma20": ma20,
        "close": float(close.iloc[-1]),
        "volatility_20": volatility_20,
        "drawdown_20": drawdown_20,
        "activity_ratio": activity_ratio,
        "volume_factor_source": activity_source,
        "quality_status": quality_status,
        "amount_coverage": amount_coverage,
    }


def _insufficient_features(reason: str) -> dict[str, Any]:
    return {"is_usable": False, "reason": reason}


def _evaluate_market_gate(frame: Optional[pd.DataFrame]) -> tuple[MarketGate, str]:
    if frame is None or frame.empty or "close" not in frame.columns:
        return MarketGate.NORMAL, "宽基数据不可用，未触发风险闸门"
    close = pd.to_numeric(frame["close"], errors="coerce").dropna()
    if len(close) < 21:
        return MarketGate.CAUTION, "宽基样本不足 21 根，降低风险暴露"
    current = float(close.iloc[-1])
    return_20 = current / float(close.iloc[-21]) - 1
    drawdown_20 = current / float(close.iloc[-20:].max()) - 1
    ma20 = float(close.iloc[-20:].mean())
    if current < ma20 and (return_20 <= -0.08 or drawdown_20 <= -0.10):
        return MarketGate.RISK_OFF, "宽基跌破 20 日均线且中短期回撤扩大"
    if current < ma20 or return_20 <= -0.03:
        return MarketGate.CAUTION, "宽基趋势偏弱，组合风险预算减半"
    return MarketGate.NORMAL, "宽基趋势未触发风险闸门"


def _score_member(
    *,
    member: AIChainUniverseMember,
    features: Mapping[str, Any],
    ai_median_return: float,
    active_profiles: Mapping[str, AIChainIndustryProfile],
    as_of_date: date,
    profile: AIChainModelProfile,
    market_gate: MarketGate,
    calibration_observations: Sequence[Mapping[str, Any]],
) -> AIChainScoreResult:
    if not features["is_usable"]:
        return AIChainScoreResult(
            code=member.code,
            name=member.name,
            group=member.group,
            tier=member.tier,
            hardware_subgroup=member.hardware_subgroup,
            score=0,
            quality_snapshot={"status": "insufficient", "reason": features["reason"]},
            action=AIChainModelAction.DATA_INSUFFICIENT,
            reason=features["reason"],
        )

    trend_score = _trend_score(features["close"], features["ma5"], features["ma20"])
    relative_strength = _clamp(50 + (features["return_20"] - ai_median_return) * 400)
    momentum_score = _clamp(50 + features["return_5"] * 300 + features["return_20"] * 120)
    activity_score = _clamp(50 + (features["activity_ratio"] - 1) * 35)
    risk_score = _clamp(100 + features["drawdown_20"] * 400 - features["volatility_20"] * 100)
    fast_score = (
        0.32 * relative_strength
        + 0.25 * trend_score
        + 0.16 * momentum_score
        + 0.12 * activity_score
        + 0.15 * risk_score
    )
    slow_adjustment = 0.0
    if member.hardware_subgroup is not None:
        slow_profile = active_profiles.get(member.hardware_subgroup.value)
        if slow_profile is not None:
            slow_adjustment = _clamp(
                (slow_profile.barrier_score + slow_profile.scarcity_score + slow_profile.ai_demand_transmission_score - 9)
                * 1.25,
                lower=-7,
                upper=7,
            )
    score = fast_score + slow_adjustment
    if member.tier == UniverseTier.OBSERVATION:
        score -= profile.observation_score_penalty
    score = round(_clamp(score), 4)
    threshold = (
        profile.observation_buy_threshold
        if member.tier == UniverseTier.OBSERVATION
        else profile.core_buy_threshold
    )
    action = _action_for(score, threshold, market_gate)
    calibration = _calibrate(
        observations=calibration_observations,
        as_of_date=as_of_date,
        score=score,
        market_gate=market_gate,
        min_sample=profile.min_calibration_sample,
    )
    factor_snapshot = {
        "relative_strength": round(relative_strength, 4),
        "trend_score": round(trend_score, 4),
        "momentum_score": round(momentum_score, 4),
        "activity_score": round(activity_score, 4),
        "risk_score": round(risk_score, 4),
        "fast_score": round(fast_score, 4),
        "slow_profile_adjustment": round(slow_adjustment, 4),
        "return_5": round(features["return_5"], 6),
        "return_20": round(features["return_20"], 6),
        "volatility_20": round(features["volatility_20"], 6),
        "drawdown_20": round(features["drawdown_20"], 6),
        "activity_ratio": round(features["activity_ratio"], 6),
        "volume_factor_source": features["volume_factor_source"],
    }
    quality_snapshot = {
        "status": features["quality_status"],
        "amount_coverage_ratio": round(features["amount_coverage"], 4),
    }
    return AIChainScoreResult(
        code=member.code,
        name=member.name,
        group=member.group,
        tier=member.tier,
        hardware_subgroup=member.hardware_subgroup,
        score=score,
        factor_snapshot=factor_snapshot,
        quality_snapshot=quality_snapshot,
        probability_up=calibration["probability_up"],
        probability_outperform=calibration["probability_outperform"],
        expected_return=calibration["expected_return"],
        return_low=calibration["return_low"],
        return_high=calibration["return_high"],
        drawdown_risk=round(max(0.0, features["volatility_20"] - features["drawdown_20"]), 6),
        action=action,
        reason=(
            "观察池采用更高入选门槛" if member.tier == UniverseTier.OBSERVATION else "核心池量价与相对强弱评分"
        ),
    )


def _trend_score(close: float, ma5: float, ma20: float) -> float:
    if close > ma5 > ma20:
        return 100.0
    if close > ma20:
        return 72.0
    if close > ma5:
        return 55.0
    return 28.0


def _action_for(score: float, threshold: float, market_gate: MarketGate) -> AIChainModelAction:
    if market_gate == MarketGate.RISK_OFF:
        return AIChainModelAction.REDUCE if score >= threshold else AIChainModelAction.AVOID
    if score >= threshold:
        return AIChainModelAction.BUY
    if score >= threshold - 8:
        return AIChainModelAction.HOLD
    return AIChainModelAction.AVOID


def _calibrate(
    *,
    observations: Sequence[Mapping[str, Any]],
    as_of_date: date,
    score: float,
    market_gate: MarketGate,
    min_sample: int,
) -> dict[str, Optional[float]]:
    matching: list[Mapping[str, Any]] = []
    for item in observations:
        completed_date = item.get("completed_date")
        if completed_date is None or _as_date(completed_date) > as_of_date:
            continue
        if str(item.get("market_gate")) != market_gate.value:
            continue
        try:
            historical_score = float(item.get("score"))
            realized_return = float(item.get("realized_return"))
        except (TypeError, ValueError):
            continue
        if abs(historical_score - score) <= 15:
            matching.append(item)
    if len(matching) < min_sample:
        return {
            "probability_up": None,
            "probability_outperform": None,
            "expected_return": None,
            "return_low": None,
            "return_high": None,
        }
    returns = np.array([float(item["realized_return"]) for item in matching])
    relative_returns = np.array(
        [float(item.get("relative_return", 0.0)) for item in matching]
    )
    return {
        "probability_up": round(float((returns > 0).mean()), 6),
        "probability_outperform": round(float((relative_returns > 0).mean()), 6),
        "expected_return": round(float(returns.mean()), 6),
        "return_low": round(float(np.quantile(returns, 0.2)), 6),
        "return_high": round(float(np.quantile(returns, 0.8)), 6),
    }


def _rank_results(results: list[AIChainScoreResult]) -> list[AIChainScoreResult]:
    valid = [item for item in results if item.action != AIChainModelAction.DATA_INSUFFICIENT]
    overall_order = sorted(valid, key=lambda item: (-item.score, item.code))
    overall_rank = {item.code: index for index, item in enumerate(overall_order, start=1)}
    group_rank: dict[str, int] = {}
    for group in {item.group for item in valid}:
        group_items = sorted(
            (item for item in valid if item.group == group),
            key=lambda item: (-item.score, item.code),
        )
        group_rank.update({item.code: index for index, item in enumerate(group_items, start=1)})
    ranked = [
        item.model_copy(
            update={"overall_rank": overall_rank.get(item.code), "group_rank": group_rank.get(item.code)}
        )
        for item in results
    ]
    return sorted(ranked, key=lambda item: (item.overall_rank or 10_000, item.code))


def _allocate_portfolio(
    results: list[AIChainScoreResult], profile: AIChainModelProfile, market_gate: MarketGate
) -> list[AIChainScoreResult]:
    if market_gate == MarketGate.RISK_OFF:
        return results
    risk_multiplier = 0.5 if market_gate == MarketGate.CAUTION else 1.0
    target_total = profile.max_ai_allocation * risk_multiplier
    per_position = min(profile.max_single_position, target_total / profile.max_holdings)
    total = 0.0
    observation_total = 0.0
    hardware_totals: dict[str, float] = {}
    allocated: dict[str, float] = {}
    candidates = sorted(
        (item for item in results if item.action == AIChainModelAction.BUY),
        key=lambda item: (item.overall_rank or 10_000, item.code),
    )
    for item in candidates:
        if len(allocated) >= profile.max_holdings or total >= target_total - 1e-9:
            break
        cap = min(profile.max_single_position, target_total - total)
        if item.tier == UniverseTier.OBSERVATION:
            cap = min(cap, profile.max_observation_allocation - observation_total)
        if item.hardware_subgroup is not None:
            subgroup_key = item.hardware_subgroup.value
            cap = min(
                cap,
                profile.max_hardware_subgroup_allocation - hardware_totals.get(subgroup_key, 0.0),
            )
        weight = min(per_position, cap)
        if weight <= 1e-9:
            continue
        allocated[item.code] = round(weight, 6)
        total += weight
        if item.tier == UniverseTier.OBSERVATION:
            observation_total += weight
        if item.hardware_subgroup is not None:
            subgroup_key = item.hardware_subgroup.value
            hardware_totals[subgroup_key] = hardware_totals.get(subgroup_key, 0.0) + weight
    return [item.model_copy(update={"suggested_weight": allocated.get(item.code, 0.0)}) for item in results]


def _clamp(value: float, *, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, float(value)))
