# -*- coding: utf-8 -*-
"""Persistence helpers for reusable intraday monitor plans."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, desc, select

from src.storage import (
    DatabaseManager,
    IntradayMonitorHistoryRecord,
    IntradayMonitorPlanRecord,
)


class IntradayMonitorRepository:
    """Small repository kept separate from the legacy alert-rule tables."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def create_plan(self, fields: Dict[str, Any]) -> IntradayMonitorPlanRecord:
        with self.db.get_session() as session:
            row = IntradayMonitorPlanRecord(**fields)
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def get_plan(self, plan_id: int) -> Optional[IntradayMonitorPlanRecord]:
        with self.db.get_session() as session:
            return session.execute(
                select(IntradayMonitorPlanRecord)
                .where(IntradayMonitorPlanRecord.id == plan_id)
                .limit(1)
            ).scalar_one_or_none()

    def list_plans(self, *, enabled: Optional[bool] = None) -> List[IntradayMonitorPlanRecord]:
        conditions = []
        if enabled is not None:
            conditions.append(IntradayMonitorPlanRecord.enabled.is_(enabled))
        with self.db.get_session() as session:
            query = select(IntradayMonitorPlanRecord)
            if conditions:
                query = query.where(*conditions)
            return list(
                session.execute(
                    query.order_by(
                        desc(IntradayMonitorPlanRecord.updated_at),
                        desc(IntradayMonitorPlanRecord.id),
                    )
                ).scalars().all()
            )

    def list_active_plans(self) -> List[IntradayMonitorPlanRecord]:
        with self.db.get_session() as session:
            return list(
                session.execute(
                    select(IntradayMonitorPlanRecord)
                    .where(
                        IntradayMonitorPlanRecord.enabled.is_(True),
                        IntradayMonitorPlanRecord.paused.is_(False),
                    )
                    .order_by(IntradayMonitorPlanRecord.id.asc())
                ).scalars().all()
            )

    def update_plan(self, plan_id: int, fields: Dict[str, Any]) -> Optional[IntradayMonitorPlanRecord]:
        with self.db.get_session() as session:
            row = session.execute(
                select(IntradayMonitorPlanRecord)
                .where(IntradayMonitorPlanRecord.id == plan_id)
                .limit(1)
            ).scalar_one_or_none()
            if row is None:
                return None
            for key, value in fields.items():
                setattr(row, key, value)
            row.updated_at = datetime.now()
            session.commit()
            session.refresh(row)
            return row

    def delete_plan(self, plan_id: int) -> bool:
        with self.db.get_session() as session:
            session.execute(
                delete(IntradayMonitorHistoryRecord).where(
                    IntradayMonitorHistoryRecord.plan_id == plan_id
                )
            )
            result = session.execute(
                delete(IntradayMonitorPlanRecord).where(IntradayMonitorPlanRecord.id == plan_id)
            )
            session.commit()
            return bool(result.rowcount)

    def update_state(
        self,
        plan_id: int,
        *,
        status: str,
        snapshot_json: str,
        evaluated_at: datetime,
    ) -> Optional[IntradayMonitorPlanRecord]:
        return self.update_plan(
            plan_id,
            {
                "current_status": status,
                "current_snapshot": snapshot_json,
                "last_evaluated_at": evaluated_at,
            },
        )

    def create_history(self, fields: Dict[str, Any]) -> IntradayMonitorHistoryRecord:
        with self.db.get_session() as session:
            row = IntradayMonitorHistoryRecord(**fields)
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def list_history(self, plan_id: int, *, days: int = 30, limit: int = 200) -> List[IntradayMonitorHistoryRecord]:
        since = datetime.now() - timedelta(days=max(1, min(days, 30)))
        with self.db.get_session() as session:
            return list(
                session.execute(
                    select(IntradayMonitorHistoryRecord)
                    .where(
                        IntradayMonitorHistoryRecord.plan_id == plan_id,
                        IntradayMonitorHistoryRecord.created_at >= since,
                    )
                    .order_by(
                        desc(IntradayMonitorHistoryRecord.created_at),
                        desc(IntradayMonitorHistoryRecord.id),
                    )
                    .limit(max(1, min(limit, 500)))
                ).scalars().all()
            )

    def purge_old_history(self, *, days: int = 30) -> int:
        cutoff = datetime.now() - timedelta(days=max(1, min(days, 30)))
        with self.db.get_session() as session:
            result = session.execute(
                delete(IntradayMonitorHistoryRecord).where(
                    IntradayMonitorHistoryRecord.created_at < cutoff
                )
            )
            session.commit()
            return int(result.rowcount or 0)
