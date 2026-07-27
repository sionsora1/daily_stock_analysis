# -*- coding: utf-8 -*-
"""Walk-forward, next-open AI-chain portfolio backtest service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from src.core.ai_chain_model_engine import score_ai_chain_universe
from src.schemas.ai_chain_model import (
    AIChainIndustryProfile,
    AIChainModelProfile,
    AIChainUniverseConfig,
)


@dataclass(frozen=True)
class BacktestCostModel:
    """Explicit stressable transaction-cost assumptions, not regulatory constants."""

    commission_rate: float = 0.0003
    sell_tax_rate: float = 0.0005
    slippage_rate: float = 0.0005

    def __post_init__(self) -> None:
        if min(self.commission_rate, self.sell_tax_rate, self.slippage_rate) < 0:
            raise ValueError("backtest costs cannot be negative")


@dataclass(frozen=True)
class AIChainBacktestPoint:
    """One weekly portfolio rebalance and realized holding-period return."""

    sequence: int
    signal_date: date
    execution_date: date
    exit_date: date
    execution_price_source: str
    market_gate: str
    weights: dict[str, float]
    rejected_codes: tuple[str, ...]
    period_return: float
    trade_cost: float
    portfolio_value: float
    ai_benchmark_value: float
    broad_benchmark_value: Optional[float]


@dataclass(frozen=True)
class AIChainBacktestResult:
    """Reproducible walk-forward output ready for persistence and API display."""

    model_profile: AIChainModelProfile
    cost_model: BacktestCostModel
    points: tuple[AIChainBacktestPoint, ...]
    metrics: dict[str, float]


class AIChainBacktestService:
    """Run weekly rebalances while keeping each signal strictly point-in-time."""

    def __init__(
        self,
        universe: AIChainUniverseConfig,
        industry_profiles: Sequence[AIChainIndustryProfile],
        model_profile: Optional[AIChainModelProfile] = None,
    ) -> None:
        self._universe = universe
        self._industry_profiles = list(industry_profiles)
        self._profile = model_profile or AIChainModelProfile()

    def run(
        self,
        *,
        daily_bars_by_code: Mapping[str, pd.DataFrame],
        wide_market_bars: Optional[pd.DataFrame] = None,
        rebalance_every_days: int = 5,
        cost_model: Optional[BacktestCostModel] = None,
    ) -> AIChainBacktestResult:
        """Execute close-signal/next-open trades using no future input for scoring."""
        if rebalance_every_days < 1:
            raise ValueError("rebalance_every_days must be positive")
        costs = cost_model or BacktestCostModel()
        normalized = {code: _normalize_bars(frame) for code, frame in daily_bars_by_code.items()}
        master_dates = _master_dates(normalized)
        if len(master_dates) < self._profile.min_history_bars + 2:
            return AIChainBacktestResult(
                model_profile=self._profile,
                cost_model=costs,
                points=(),
                metrics=_empty_metrics(),
            )

        portfolio_value = 1.0
        ai_benchmark_value = 1.0
        broad_benchmark_value: Optional[float] = 1.0 if wide_market_bars is not None else None
        points: list[AIChainBacktestPoint] = []
        calibration: list[dict[str, Any]] = []
        final_signal_index = len(master_dates) - rebalance_every_days - 1
        for signal_index in range(self._profile.min_history_bars - 1, final_signal_index + 1, rebalance_every_days):
            signal_date = master_dates[signal_index]
            execution_date = master_dates[signal_index + 1]
            exit_index = min(signal_index + rebalance_every_days, len(master_dates) - 1)
            exit_date = master_dates[exit_index]
            if exit_date <= execution_date:
                continue
            model_result = score_ai_chain_universe(
                daily_bars_by_code=normalized,
                universe=self._universe,
                industry_profiles=self._industry_profiles,
                as_of_date=signal_date,
                model_profile=self._profile,
                wide_market_bars=wide_market_bars,
                calibration_observations=calibration,
            )
            proposed_weights = {
                item.code: item.suggested_weight
                for item in model_result.scores
                if item.suggested_weight > 0
            }
            accepted_weights, rejected = _tradeable_weights(
                proposed_weights, normalized, execution_date, exit_date
            )
            gross_return = _weighted_return(accepted_weights, normalized, execution_date, exit_date)
            turnover = float(sum(accepted_weights.values()))
            trade_cost = turnover * (2 * costs.commission_rate + costs.sell_tax_rate + 2 * costs.slippage_rate)
            period_return = gross_return - trade_cost
            portfolio_value *= 1 + period_return
            ai_benchmark_value *= 1 + _equal_weight_return(normalized, execution_date, exit_date)
            if broad_benchmark_value is not None:
                broad_return = _single_frame_return(wide_market_bars, execution_date, exit_date)
                broad_benchmark_value *= 1 + broad_return
            point = AIChainBacktestPoint(
                sequence=len(points) + 1,
                signal_date=signal_date,
                execution_date=execution_date,
                exit_date=exit_date,
                execution_price_source="next_open",
                market_gate=model_result.market_gate.value,
                weights=accepted_weights,
                rejected_codes=tuple(sorted(rejected)),
                period_return=round(period_return, 10),
                trade_cost=round(trade_cost, 10),
                portfolio_value=round(portfolio_value, 10),
                ai_benchmark_value=round(ai_benchmark_value, 10),
                broad_benchmark_value=(round(broad_benchmark_value, 10) if broad_benchmark_value is not None else None),
            )
            points.append(point)
            calibration.extend(
                _completed_observations(
                    scores=model_result.scores,
                    weights=accepted_weights,
                    frames=normalized,
                    signal_date=signal_date,
                    execution_date=execution_date,
                    master_dates=master_dates,
                    signal_index=signal_index,
                    holding_days=self._profile.holding_days,
                    market_gate=model_result.market_gate.value,
                )
            )
        return AIChainBacktestResult(
            model_profile=self._profile,
            cost_model=costs,
            points=tuple(points),
            metrics=_metrics(points, rebalance_every_days),
        )


def _normalize_bars(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if "date" not in result.columns:
        return pd.DataFrame(columns=["date", "open", "close"])
    result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.date
    for column in ("open", "close", "high", "low", "volume", "amount"):
        if column in result.columns:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    return result.dropna(subset=["date"]).sort_values("date").drop_duplicates("date", keep="last")


def _master_dates(frames: Mapping[str, pd.DataFrame]) -> list[date]:
    date_sets = [set(frame["date"].tolist()) for frame in frames.values() if not frame.empty]
    if not date_sets:
        return []
    return sorted(set.intersection(*date_sets))


def _tradeable_weights(
    weights: Mapping[str, float],
    frames: Mapping[str, pd.DataFrame],
    execution_date: date,
    exit_date: date,
) -> tuple[dict[str, float], set[str]]:
    accepted: dict[str, float] = {}
    rejected: set[str] = set()
    for code, weight in weights.items():
        frame = frames.get(code)
        entry = _row_on(frame, execution_date)
        exit_row = _row_on(frame, exit_date)
        if entry is None or exit_row is None or not _positive(entry.get("open")) or not _positive(exit_row.get("close")):
            rejected.add(code)
            continue
        accepted[code] = float(weight)
    return accepted, rejected


def _weighted_return(
    weights: Mapping[str, float], frames: Mapping[str, pd.DataFrame], execution_date: date, exit_date: date
) -> float:
    return float(
        sum(
            weight * _single_frame_return(frames[code], execution_date, exit_date)
            for code, weight in weights.items()
        )
    )


def _equal_weight_return(frames: Mapping[str, pd.DataFrame], execution_date: date, exit_date: date) -> float:
    returns = [
        _single_frame_return(frame, execution_date, exit_date)
        for frame in frames.values()
        if _row_on(frame, execution_date) is not None and _row_on(frame, exit_date) is not None
    ]
    return float(np.mean(returns)) if returns else 0.0


def _single_frame_return(frame: Optional[pd.DataFrame], execution_date: date, exit_date: date) -> float:
    entry = _row_on(frame, execution_date)
    exit_row = _row_on(frame, exit_date)
    if entry is None or exit_row is None or not _positive(entry.get("open")) or not _positive(exit_row.get("close")):
        return 0.0
    return float(exit_row["close"] / entry["open"] - 1)


def _row_on(frame: Optional[pd.DataFrame], target_date: date) -> Optional[pd.Series]:
    if frame is None or frame.empty:
        return None
    rows = frame.loc[frame["date"] == target_date]
    return None if rows.empty else rows.iloc[-1]


def _positive(value: Any) -> bool:
    try:
        return bool(pd.notna(value) and float(value) > 0)
    except (TypeError, ValueError):
        return False


def _completed_observations(
    *,
    scores: Sequence[Any],
    weights: Mapping[str, float],
    frames: Mapping[str, pd.DataFrame],
    signal_date: date,
    execution_date: date,
    master_dates: Sequence[date],
    signal_index: int,
    holding_days: int,
    market_gate: str,
) -> list[dict[str, Any]]:
    completed_index = min(signal_index + holding_days, len(master_dates) - 1)
    completed_date = master_dates[completed_index]
    ai_return = _equal_weight_return(frames, execution_date, completed_date)
    observations: list[dict[str, Any]] = []
    for score in scores:
        if score.code not in weights:
            continue
        realized_return = _single_frame_return(frames.get(score.code), execution_date, completed_date)
        observations.append(
            {
                "signal_date": signal_date,
                "completed_date": completed_date,
                "score": score.score,
                "market_gate": market_gate,
                "realized_return": realized_return,
                "relative_return": realized_return - ai_return,
            }
        )
    return observations


def _metrics(points: Sequence[AIChainBacktestPoint], rebalance_every_days: int) -> dict[str, float]:
    if not points:
        return _empty_metrics()
    portfolio_values = np.array([1.0, *[point.portfolio_value for point in points]])
    period_returns = np.array([point.period_return for point in points])
    running_max = np.maximum.accumulate(portfolio_values)
    drawdown = portfolio_values / running_max - 1
    annualization_periods = max(1.0, 252 / rebalance_every_days)
    annualized_return = float(portfolio_values[-1] ** (annualization_periods / len(points)) - 1)
    volatility = float(period_returns.std(ddof=0) * np.sqrt(annualization_periods))
    sharpe = annualized_return / volatility if volatility > 0 else 0.0
    max_drawdown = float(drawdown.min())
    ai_final = points[-1].ai_benchmark_value
    rejected = sum(len(point.rejected_codes) for point in points)
    attempted = rejected + sum(len(point.weights) for point in points)
    return {
        "final_portfolio_value": round(float(portfolio_values[-1]), 10),
        "annualized_return": round(annualized_return, 10),
        "max_drawdown": round(max_drawdown, 10),
        "sharpe": round(sharpe, 10),
        "calmar": round(annualized_return / abs(max_drawdown), 10) if max_drawdown < 0 else 0.0,
        "turnover": round(float(sum(sum(point.weights.values()) for point in points)), 10),
        "win_rate": round(float((period_returns > 0).mean()), 10),
        "average_holding_days": float(rebalance_every_days),
        "ai_benchmark_final_value": round(float(ai_final), 10),
        "ai_excess_return": round(float(portfolio_values[-1] / ai_final - 1), 10) if ai_final > 0 else 0.0,
        "total_trade_cost": round(float(sum(point.trade_cost for point in points)), 10),
        "rejected_trade_count": float(rejected),
        "unfilled_trade_ratio": round(rejected / attempted, 10) if attempted else 0.0,
        "effective_rebalance_count": float(len(points)),
    }


def _empty_metrics() -> dict[str, float]:
    return {
        "final_portfolio_value": 1.0,
        "annualized_return": 0.0,
        "max_drawdown": 0.0,
        "sharpe": 0.0,
        "calmar": 0.0,
        "turnover": 0.0,
        "win_rate": 0.0,
        "average_holding_days": 0.0,
        "ai_benchmark_final_value": 1.0,
        "ai_excess_return": 0.0,
        "total_trade_cost": 0.0,
        "rejected_trade_count": 0.0,
        "unfilled_trade_ratio": 0.0,
        "effective_rebalance_count": 0.0,
    }
