# -*- coding: utf-8 -*-
"""Persistence access for the deterministic AI-chain model only.

This repository deliberately does not reuse LLM-analysis or legacy backtest
records.  It keeps successful snapshots stable when a later run fails, which
lets the API safely show the latest known-good result as non-current.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy import and_, delete, desc, func, select

from src.schemas.ai_chain_model import AIChainUniverseMember
from src.storage import (
    AiChainModelRun,
    AiChainModelScore,
    AiChainPortfolioBacktestPoint,
    AiChainPortfolioBacktestRun,
    AiChainUniverseMember as AiChainUniverseMemberRecord,
    DatabaseManager,
    utc_naive_now,
)


def _json(value: Any) -> str:
    """Stable JSON representation suitable for audit snapshots."""
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True, default=str)


class AIChainModelRepository:
    """Transactional query and write boundary for AI-chain model artifacts."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None) -> None:
        self.db = db_manager or DatabaseManager.get_instance()

    def sync_universe_members(
        self,
        *,
        universe_version: str,
        members: Iterable[AIChainUniverseMember],
    ) -> int:
        """Insert or update declared members without deleting historical versions."""
        member_list = list(members)
        with self.db.session_scope() as session:
            for member in member_list:
                existing = session.execute(
                    select(AiChainUniverseMemberRecord).where(
                        and_(
                            AiChainUniverseMemberRecord.universe_version == universe_version,
                            AiChainUniverseMemberRecord.code == member.code,
                            AiChainUniverseMemberRecord.effective_from == member.effective_from,
                        )
                    )
                ).scalar_one_or_none()
                values = {
                    "name": member.name,
                    "group_name": member.group.value,
                    "tier": member.tier.value,
                    "hardware_subgroup": (
                        member.hardware_subgroup.value if member.hardware_subgroup else None
                    ),
                    "effective_to": member.effective_to,
                    "evidence_summary": member.evidence_summary,
                }
                if existing is None:
                    session.add(
                        AiChainUniverseMemberRecord(
                            universe_version=universe_version,
                            code=member.code,
                            effective_from=member.effective_from,
                            **values,
                        )
                    )
                else:
                    for key, value in values.items():
                        setattr(existing, key, value)
            session.flush()
        return len(member_list)

    def upsert_successful_run(
        self,
        *,
        as_of_date: date,
        model_version: str,
        market_gate: str,
        data_coverage: float,
        warnings: Sequence[str],
        model_profile: Mapping[str, Any],
        scores: Sequence[Mapping[str, Any]],
        data_quality: Optional[Mapping[str, Any]] = None,
    ) -> AiChainModelRun:
        """Replace the successful snapshot for the same date and model version."""
        now = utc_naive_now()
        with self.db.session_scope() as session:
            run = session.execute(
                select(AiChainModelRun)
                .where(
                    and_(
                        AiChainModelRun.as_of_date == as_of_date,
                        AiChainModelRun.model_version == model_version,
                        AiChainModelRun.status == "succeeded",
                    )
                )
                .order_by(desc(AiChainModelRun.id))
                .limit(1)
            ).scalar_one_or_none()
            if run is None:
                run = AiChainModelRun(
                    as_of_date=as_of_date,
                    model_version=model_version,
                    status="succeeded",
                )
                session.add(run)

            run.market_gate = market_gate
            run.data_coverage = data_coverage
            run.warnings_json = _json(list(warnings))
            run.model_profile_json = _json(dict(model_profile))
            run.data_quality_json = _json(dict(data_quality or {}))
            run.failure_reason = None
            run.completed_at = now
            session.flush()

            session.execute(delete(AiChainModelScore).where(AiChainModelScore.run_id == run.id))
            for score in scores:
                session.add(self._score_row(run.id, score))
            session.flush()
            session.expunge(run)
        return run

    def save_failed_run(
        self,
        *,
        as_of_date: date,
        model_version: str,
        failure_reason: str,
        data_coverage: Optional[float] = None,
        data_quality: Optional[Mapping[str, Any]] = None,
    ) -> AiChainModelRun:
        """Record a failed attempt without modifying any successful snapshot."""
        with self.db.session_scope() as session:
            run = AiChainModelRun(
                as_of_date=as_of_date,
                model_version=model_version,
                status="failed",
                data_coverage=data_coverage,
                data_quality_json=_json(dict(data_quality or {})),
                failure_reason=failure_reason,
                completed_at=utc_naive_now(),
            )
            session.add(run)
            session.flush()
            session.expunge(run)
        return run

    def get_latest_successful_run(
        self, *, as_of_date: Optional[date] = None
    ) -> Optional[AiChainModelRun]:
        """Return the latest success; failed/running rows are intentionally ignored."""
        with self.db.session_scope() as session:
            statement = select(AiChainModelRun).where(AiChainModelRun.status == "succeeded")
            if as_of_date is not None:
                statement = statement.where(AiChainModelRun.as_of_date == as_of_date)
            run = session.execute(
                statement.order_by(desc(AiChainModelRun.as_of_date), desc(AiChainModelRun.id)).limit(1)
            ).scalar_one_or_none()
            if run is not None:
                session.expunge(run)
            return run

    def get_scores_for_run(self, run_id: int) -> List[AiChainModelScore]:
        """Return scores in their published rank order."""
        with self.db.session_scope() as session:
            rows = session.execute(
                select(AiChainModelScore)
                .where(AiChainModelScore.run_id == run_id)
                .order_by(AiChainModelScore.rank, AiChainModelScore.code)
            ).scalars().all()
            for row in rows:
                session.expunge(row)
            return list(rows)

    def list_successful_runs(
        self, *, page: int = 1, page_size: int = 30
    ) -> Tuple[List[AiChainModelRun], int]:
        """Return successful daily snapshots, newest first, for API history."""
        if page < 1:
            raise ValueError("page must be at least 1")
        if not 1 <= page_size <= 200:
            raise ValueError("page_size must be within [1, 200]")
        with self.db.session_scope() as session:
            total = int(
                session.execute(
                    select(func.count(AiChainModelRun.id)).where(
                        AiChainModelRun.status == "succeeded"
                    )
                ).scalar_one()
            )
            rows = session.execute(
                select(AiChainModelRun)
                .where(AiChainModelRun.status == "succeeded")
                .order_by(desc(AiChainModelRun.as_of_date), desc(AiChainModelRun.id))
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).scalars().all()
            for row in rows:
                session.expunge(row)
            return list(rows), total

    def create_backtest_run(
        self,
        *,
        model_version: str,
        start_date: date,
        end_date: date,
        parameters: Mapping[str, Any],
        cost_model: Mapping[str, Any],
        benchmarks: Mapping[str, Any],
    ) -> AiChainPortfolioBacktestRun:
        """Create an isolated backtest run before its walk-forward points exist."""
        if end_date < start_date:
            raise ValueError("end_date cannot be before start_date")
        with self.db.session_scope() as session:
            run = AiChainPortfolioBacktestRun(
                model_version=model_version,
                status="running",
                start_date=start_date,
                end_date=end_date,
                parameters_json=_json(dict(parameters)),
                cost_model_json=_json(dict(cost_model)),
                benchmarks_json=_json(dict(benchmarks)),
            )
            session.add(run)
            session.flush()
            session.expunge(run)
        return run

    def replace_backtest_points(
        self, backtest_run_id: int, points: Sequence[Mapping[str, Any]]
    ) -> int:
        """Atomically replace a backtest's detail points in sequence order."""
        with self.db.session_scope() as session:
            if session.get(AiChainPortfolioBacktestRun, backtest_run_id) is None:
                raise ValueError(f"backtest run does not exist: {backtest_run_id}")
            session.execute(
                delete(AiChainPortfolioBacktestPoint).where(
                    AiChainPortfolioBacktestPoint.backtest_run_id == backtest_run_id
                )
            )
            for point in points:
                session.add(self._backtest_point_row(backtest_run_id, point))
            session.flush()
        return len(points)

    def finish_backtest_run(
        self,
        backtest_run_id: int,
        *,
        metrics: Mapping[str, Any],
        status: str = "succeeded",
        failure_reason: Optional[str] = None,
    ) -> AiChainPortfolioBacktestRun:
        """Persist final metrics after all walk-forward points were written."""
        with self.db.session_scope() as session:
            run = session.get(AiChainPortfolioBacktestRun, backtest_run_id)
            if run is None:
                raise ValueError(f"backtest run does not exist: {backtest_run_id}")
            run.status = status
            run.metrics_json = _json(dict(metrics))
            run.failure_reason = failure_reason
            run.completed_at = utc_naive_now()
            session.flush()
            session.expunge(run)
            return run

    def get_backtest_run(self, backtest_run_id: int) -> Optional[AiChainPortfolioBacktestRun]:
        """Load one durable backtest header without loading its detail page."""
        with self.db.session_scope() as session:
            row = session.get(AiChainPortfolioBacktestRun, backtest_run_id)
            if row is not None:
                session.expunge(row)
            return row

    def list_backtest_points(
        self, backtest_run_id: int, *, page: int = 1, page_size: int = 50
    ) -> Tuple[List[AiChainPortfolioBacktestPoint], int]:
        """Return one page of durable backtest evidence and its total size."""
        if page < 1:
            raise ValueError("page must be at least 1")
        if not 1 <= page_size <= 200:
            raise ValueError("page_size must be within [1, 200]")
        with self.db.session_scope() as session:
            total = int(
                session.execute(
                    select(func.count(AiChainPortfolioBacktestPoint.id)).where(
                        AiChainPortfolioBacktestPoint.backtest_run_id == backtest_run_id
                    )
                ).scalar_one()
            )
            rows = session.execute(
                select(AiChainPortfolioBacktestPoint)
                .where(AiChainPortfolioBacktestPoint.backtest_run_id == backtest_run_id)
                .order_by(AiChainPortfolioBacktestPoint.sequence)
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).scalars().all()
            for row in rows:
                session.expunge(row)
            return list(rows), total

    @staticmethod
    def _score_row(run_id: int, score: Mapping[str, Any]) -> AiChainModelScore:
        required = ("code", "name", "group_name", "tier", "action", "rank")
        missing = [key for key in required if score.get(key) is None]
        if missing:
            raise ValueError(f"score is missing required fields: {', '.join(missing)}")
        return AiChainModelScore(
            run_id=run_id,
            code=str(score["code"]),
            name=str(score["name"]),
            group_name=str(score["group_name"]),
            hardware_subgroup=score.get("hardware_subgroup"),
            tier=str(score["tier"]),
            factor_snapshot_json=_json(score.get("factor_snapshot", {})),
            quality_snapshot_json=_json(score.get("quality_snapshot", {})),
            probability_up=score.get("probability_up"),
            probability_outperform=score.get("probability_outperform"),
            expected_return=score.get("expected_return"),
            return_low=score.get("return_low"),
            return_high=score.get("return_high"),
            drawdown_risk=score.get("drawdown_risk"),
            action=str(score["action"]),
            rank=int(score["rank"]),
            suggested_weight=score.get("suggested_weight"),
        )

    @staticmethod
    def _backtest_point_row(
        backtest_run_id: int, point: Mapping[str, Any]
    ) -> AiChainPortfolioBacktestPoint:
        if point.get("sequence") is None or point.get("rebalance_date") is None:
            raise ValueError("backtest point requires sequence and rebalance_date")
        return AiChainPortfolioBacktestPoint(
            backtest_run_id=backtest_run_id,
            sequence=int(point["sequence"]),
            rebalance_date=point["rebalance_date"],
            code=point.get("code"),
            event_type=str(point.get("event_type", "rebalance")),
            suggested_weight=point.get("suggested_weight"),
            realized_weight=point.get("realized_weight"),
            trade_cost=point.get("trade_cost"),
            portfolio_value=point.get("portfolio_value"),
            ai_benchmark_value=point.get("ai_benchmark_value"),
            broad_benchmark_value=point.get("broad_benchmark_value"),
            rejection_reason=point.get("rejection_reason"),
            detail_json=_json(point.get("detail", {})),
        )
