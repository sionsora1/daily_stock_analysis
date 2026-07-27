# -*- coding: utf-8 -*-
"""Manual asynchronous orchestration for the deterministic AI-chain model."""

from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, Mapping, Optional

import pandas as pd

from data_provider.base import DataFetcherManager
from src.core.ai_chain_model_engine import score_ai_chain_universe
from src.repositories.ai_chain_model_repo import AIChainModelRepository
from src.repositories.stock_repo import StockRepository
from src.schemas.ai_chain_model import AIChainModelProfile, DataQualityStatus
from src.services.ai_chain_backtest_service import AIChainBacktestService, BacktestCostModel
from src.services.ai_chain_market_data_service import AIChainMarketDataService
from src.services.ai_chain_universe import (
    load_ai_chain_industry_profiles,
    load_ai_chain_universe,
)


MODEL_HISTORY_START = date(2023, 7, 1)
WIDE_MARKET_CODE = "000300"


@dataclass
class AIChainModelTask:
    """In-memory status for a user-triggered long-running model operation."""

    task_id: str
    kind: str
    status: str = "pending"
    progress: int = 0
    message: str = "等待执行"
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "kind": self.kind,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class AIChainModelTaskError(RuntimeError):
    """Raised when an equivalent manual operation is already running."""


class AIChainModelService:
    """Coordinates data preparation, pure scoring/backtest and persistence."""

    def __init__(
        self,
        *,
        model_repository: Optional[AIChainModelRepository] = None,
        stock_repository: Optional[StockRepository] = None,
        fetcher_manager: Optional[DataFetcherManager] = None,
    ) -> None:
        self._model_repository = model_repository or AIChainModelRepository()
        stock_repo = stock_repository or StockRepository()
        fetcher = fetcher_manager or DataFetcherManager()
        self._market_data = AIChainMarketDataService(stock_repo, fetcher)
        self._tasks: Dict[str, AIChainModelTask] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ai-chain-model")

    def submit_daily_run(self, *, requested_as_of_date: Optional[date] = None) -> Dict[str, Any]:
        task = self._submit("daily_run")
        self._executor.submit(self._execute_daily_run, task.task_id, requested_as_of_date or date.today())
        return task.to_dict()

    def submit_backtest(
        self,
        *,
        start_date: date = MODEL_HISTORY_START,
        end_date: Optional[date] = None,
        holding_days: int = 20,
        rebalance_every_days: int = 5,
        cost_model: Optional[Mapping[str, float]] = None,
    ) -> Dict[str, Any]:
        if end_date is not None and end_date < start_date:
            raise ValueError("end_date cannot be before start_date")
        task = self._submit("backtest")
        self._executor.submit(
            self._execute_backtest,
            task.task_id,
            start_date,
            end_date or date.today(),
            holding_days,
            rebalance_every_days,
            dict(cost_model or {}),
        )
        return task.to_dict()

    def get_task(self, task_id: str) -> Dict[str, Any]:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(f"AI-chain model task not found: {task_id}")
            return task.to_dict()

    def get_latest(self) -> Optional[Dict[str, Any]]:
        run = self._model_repository.get_latest_successful_run()
        if run is None:
            return None
        scores = self._model_repository.get_scores_for_run(run.id)
        payload = self._run_payload(run, scores)
        payload["is_stale"] = run.as_of_date < date.today()
        return payload

    def get_history(self, *, page: int, page_size: int) -> Dict[str, Any]:
        runs, total = self._model_repository.list_successful_runs(page=page, page_size=page_size)
        return {
            "items": [self._run_payload(run, []) for run in runs],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def get_backtest(self, backtest_run_id: int, *, page: int = 1, page_size: int = 100) -> Optional[Dict[str, Any]]:
        run = self._model_repository.get_backtest_run(backtest_run_id)
        if run is None:
            return None
        points, total = self._model_repository.list_backtest_points(
            backtest_run_id, page=page, page_size=page_size
        )
        return {
            "id": run.id,
            "model_version": run.model_version,
            "status": run.status,
            "start_date": run.start_date.isoformat(),
            "end_date": run.end_date.isoformat(),
            "parameters": _loads(run.parameters_json, {}),
            "cost_model": _loads(run.cost_model_json, {}),
            "benchmarks": _loads(run.benchmarks_json, {}),
            "metrics": _loads(run.metrics_json, {}),
            "failure_reason": run.failure_reason,
            "points": [
                {
                    "sequence": point.sequence,
                    "rebalance_date": point.rebalance_date.isoformat(),
                    "code": point.code,
                    "event_type": point.event_type,
                    "suggested_weight": point.suggested_weight,
                    "realized_weight": point.realized_weight,
                    "trade_cost": point.trade_cost,
                    "portfolio_value": point.portfolio_value,
                    "ai_benchmark_value": point.ai_benchmark_value,
                    "broad_benchmark_value": point.broad_benchmark_value,
                    "rejection_reason": point.rejection_reason,
                    "detail": _loads(point.detail_json, {}),
                }
                for point in points
            ],
            "point_total": total,
        }

    def _submit(self, kind: str) -> AIChainModelTask:
        with self._lock:
            if any(task.kind == kind and task.status in {"pending", "processing"} for task in self._tasks.values()):
                raise AIChainModelTaskError(f"an AI-chain model {kind} task is already running")
            task = AIChainModelTask(task_id=str(uuid.uuid4()), kind=kind)
            self._tasks[task.task_id] = task
            self._trim_finished_tasks()
            return task

    def _execute_daily_run(self, task_id: str, requested_as_of_date: date) -> None:
        self._start(task_id, "加载分类池和日线数据")
        quality: Dict[str, Dict[str, Any]] = {}
        effective_as_of = requested_as_of_date
        try:
            universe, profiles, frames, quality, effective_as_of = self._collect_daily_bars(
                task_id, requested_as_of_date, MODEL_HISTORY_START
            )
            self._progress(task_id, 80, "计算市场闸门、相对强弱和仓位约束")
            wide_market_bars = frames.pop(WIDE_MARKET_CODE, None)
            result = score_ai_chain_universe(
                daily_bars_by_code=frames,
                universe=universe,
                industry_profiles=profiles,
                as_of_date=effective_as_of,
                model_profile=AIChainModelProfile(),
                wide_market_bars=wide_market_bars,
            )
            warnings = list(result.warnings) + [
                f"{code} 成交额覆盖不足，已退回成交量因子"
                for code, item in quality.items()
                if item.get("status") == DataQualityStatus.DEGRADED.value
            ]
            run = self._model_repository.upsert_successful_run(
                as_of_date=effective_as_of,
                model_version=result.model_profile.model_version,
                market_gate=result.market_gate.value,
                data_coverage=float(np_mean([item["coverage_ratio"] for item in quality.values()])),
                warnings=warnings,
                model_profile=result.model_profile.model_dump(mode="json"),
                data_quality=quality,
                scores=[
                    {
                        "code": item.code,
                        "name": item.name,
                        "group_name": item.group.value,
                        "hardware_subgroup": item.hardware_subgroup.value if item.hardware_subgroup else None,
                        "tier": item.tier.value,
                        "factor_snapshot": {**item.factor_snapshot, "model_score": item.score},
                        "quality_snapshot": item.quality_snapshot,
                        "probability_up": item.probability_up,
                        "probability_outperform": item.probability_outperform,
                        "expected_return": item.expected_return,
                        "return_low": item.return_low,
                        "return_high": item.return_high,
                        "drawdown_risk": item.drawdown_risk,
                        "action": item.action.value,
                        "rank": item.overall_rank or 9999,
                        "suggested_weight": item.suggested_weight,
                    }
                    for item in result.scores
                ],
            )
            self._complete(task_id, {"run_id": run.id, "as_of_date": effective_as_of.isoformat()})
        except Exception as exc:
            try:
                self._model_repository.save_failed_run(
                    as_of_date=effective_as_of,
                    model_version=AIChainModelProfile().model_version,
                    failure_reason=str(exc),
                    data_coverage=float(np_mean([item["coverage_ratio"] for item in quality.values()])),
                    data_quality=quality,
                )
            finally:
                self._fail(task_id, str(exc))

    def _execute_backtest(
        self,
        task_id: str,
        start_date: date,
        end_date: date,
        holding_days: int,
        rebalance_every_days: int,
        raw_cost_model: Mapping[str, float],
    ) -> None:
        backtest_run_id: Optional[int] = None
        try:
            self._start(task_id, "加载分类池和历史日线")
            universe, profiles, frames, _, effective_as_of = self._collect_daily_bars(task_id, end_date, start_date)
            profile = AIChainModelProfile(holding_days=holding_days)
            costs = BacktestCostModel(**raw_cost_model)
            backtest_run = self._model_repository.create_backtest_run(
                model_version=profile.model_version,
                start_date=start_date,
                end_date=effective_as_of,
                parameters=profile.model_dump(mode="json"),
                cost_model=costs.__dict__,
                benchmarks={"ai_equal_weight": "versioned_current_universe", "broad": WIDE_MARKET_CODE},
            )
            backtest_run_id = backtest_run.id
            self._progress(task_id, 80, "执行走步回测并扣除交易成本")
            result = AIChainBacktestService(universe, profiles, profile).run(
                daily_bars_by_code={code: bars for code, bars in frames.items() if code != WIDE_MARKET_CODE},
                wide_market_bars=frames.get(WIDE_MARKET_CODE),
                rebalance_every_days=rebalance_every_days,
                cost_model=costs,
            )
            self._model_repository.replace_backtest_points(
                backtest_run.id,
                [
                    {
                        "sequence": point.sequence,
                        "rebalance_date": point.signal_date,
                        "event_type": "weekly_rebalance",
                        "portfolio_value": point.portfolio_value,
                        "ai_benchmark_value": point.ai_benchmark_value,
                        "broad_benchmark_value": point.broad_benchmark_value,
                        "trade_cost": point.trade_cost,
                        "detail": {
                            "signal_date": point.signal_date,
                            "execution_date": point.execution_date,
                            "exit_date": point.exit_date,
                            "execution_price_source": point.execution_price_source,
                            "market_gate": point.market_gate,
                            "weights": point.weights,
                            "rejected_codes": point.rejected_codes,
                            "period_return": point.period_return,
                        },
                        "rejection_reason": ",".join(point.rejected_codes) or None,
                    }
                    for point in result.points
                ],
            )
            self._model_repository.finish_backtest_run(backtest_run.id, metrics=result.metrics)
            self._complete(task_id, {"backtest_run_id": backtest_run.id})
        except Exception as exc:
            if backtest_run_id is not None:
                self._model_repository.finish_backtest_run(
                    backtest_run_id, metrics={}, status="failed", failure_reason=str(exc)
                )
            self._fail(task_id, str(exc))

    def _collect_daily_bars(
        self, task_id: str, requested_end_date: date, start_date: date
    ) -> tuple[Any, Any, Dict[str, pd.DataFrame], Dict[str, Dict[str, Any]], date]:
        universe = load_ai_chain_universe()
        profiles = load_ai_chain_industry_profiles()
        universe.validate_industry_profiles(profiles)
        self._model_repository.sync_universe_members(
            universe_version=universe.schema_version, members=universe.members
        )
        active_members = universe.active_members(requested_end_date)
        frames: Dict[str, pd.DataFrame] = {}
        quality: Dict[str, Dict[str, Any]] = {}
        latest_dates: list[date] = []
        total = len(active_members) + 1
        for index, member in enumerate(active_members, start=1):
            self._progress(task_id, int(index * 70 / total), f"同步 {member.code} 日线 ({index}/{total})")
            prepared = self._market_data.prepare_stock(member.code, start_date, requested_end_date)
            report = prepared.quality.model_dump(mode="json")
            quality[member.code] = report
            if prepared.quality.status in {DataQualityStatus.INSUFFICIENT, DataQualityStatus.FAILED}:
                raise RuntimeError(f"{member.code} 数据质量不足: {'; '.join(prepared.quality.failure_reasons)}")
            if prepared.quality.last_trade_date is None:
                raise RuntimeError(f"{member.code} 缺少最后交易日")
            latest_dates.append(prepared.quality.last_trade_date)
            frames[member.code] = prepared.daily_bars
        self._progress(task_id, int((len(active_members) + 1) * 70 / total), "同步宽基日线")
        wide = self._market_data.prepare_stock(WIDE_MARKET_CODE, start_date, requested_end_date)
        if wide.quality.status not in {DataQualityStatus.INSUFFICIENT, DataQualityStatus.FAILED}:
            frames[WIDE_MARKET_CODE] = wide.daily_bars
        effective_as_of = min(latest_dates)
        return universe, profiles, frames, quality, effective_as_of

    def _start(self, task_id: str, message: str) -> None:
        with self._lock:
            task = self._tasks[task_id]
            task.status = "processing"
            task.progress = 1
            task.message = message
            task.started_at = datetime.now()

    def _progress(self, task_id: str, progress: int, message: str) -> None:
        with self._lock:
            task = self._tasks[task_id]
            task.progress = min(99, max(task.progress, progress))
            task.message = message

    def _complete(self, task_id: str, result: Dict[str, Any]) -> None:
        with self._lock:
            task = self._tasks[task_id]
            task.status = "completed"
            task.progress = 100
            task.message = "完成"
            task.result = result
            task.completed_at = datetime.now()

    def _fail(self, task_id: str, error: str) -> None:
        with self._lock:
            task = self._tasks[task_id]
            task.status = "failed"
            task.message = "失败"
            task.error = error
            task.completed_at = datetime.now()

    def _trim_finished_tasks(self) -> None:
        finished = [task for task in self._tasks.values() if task.status in {"completed", "failed"}]
        if len(finished) <= 100:
            return
        for task in sorted(finished, key=lambda item: item.completed_at or item.created_at)[:-100]:
            self._tasks.pop(task.task_id, None)

    @staticmethod
    def _run_payload(run: Any, scores: list[Any]) -> Dict[str, Any]:
        return {
            "id": run.id,
            "as_of_date": run.as_of_date.isoformat(),
            "model_version": run.model_version,
            "status": run.status,
            "market_gate": run.market_gate,
            "data_coverage": run.data_coverage,
            "warnings": _loads(run.warnings_json, []),
            "model_profile": _loads(run.model_profile_json, {}),
            "data_quality": _loads(run.data_quality_json, {}),
            "scores": [
                {
                    "code": item.code,
                    "name": item.name,
                    "group": item.group_name,
                    "hardware_subgroup": item.hardware_subgroup,
                    "tier": item.tier,
                    "score": item.factor_snapshot_json and _loads(item.factor_snapshot_json, {}).get("model_score"),
                    "factor_snapshot": _loads(item.factor_snapshot_json, {}),
                    "quality_snapshot": _loads(item.quality_snapshot_json, {}),
                    "probability_up": item.probability_up,
                    "probability_outperform": item.probability_outperform,
                    "expected_return": item.expected_return,
                    "return_low": item.return_low,
                    "return_high": item.return_high,
                    "drawdown_risk": item.drawdown_risk,
                    "action": item.action,
                    "rank": item.rank,
                    "suggested_weight": item.suggested_weight,
                }
                for item in scores
            ],
        }


def _loads(value: Optional[str], default: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return default


def np_mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


_service_instance: Optional[AIChainModelService] = None
_service_lock = threading.Lock()


def get_ai_chain_model_service() -> AIChainModelService:
    """Return the process-local manual task service without adding a scheduler job."""
    global _service_instance
    with _service_lock:
        if _service_instance is None:
            _service_instance = AIChainModelService()
        return _service_instance
